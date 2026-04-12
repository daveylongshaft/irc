from __future__ import annotations

import argparse
import os
import signal
import socket
import threading
import time

from csc_services import SERVER_NAME, Service
from csc_crypto import DHExchange, encrypt, decrypt, is_encrypted

from csc_server.exec.dispatcher import CommandDispatcher
from csc_server.irc.ingress import IRCIngress
from csc_server.queue.local_queue import LocalCommandQueue
from csc_server.queue.store import CommandStore
from csc_server.state.server_state import ServerState
from csc_server.sync.link_mixin import LinkMixin
from csc_server.sync.mesh import SyncMesh


class Server(Service, LinkMixin):
    """Queue-first server scaffold built on the CSC service inheritance chain.

    Link management is provided by LinkMixin: the Server owns the link
    table and anything that needs per-link data (SyncMesh, STATS L,
    netsplit handling, all-known-users aggregation) goes through
    self.iter_links() / self.get_link_by_id() / self.get_link_by_origin().

    The `peers` constructor arg accepts either:
        (host, port)                  -- origin bound on first SYNCLINE (bootstrap)
        (origin_server, host, port)   -- origin bound at startup (recommended)

    Routing is always by origin_server id (O(1) lookup) once bound.
    Address is used exactly once per link, and only to bootstrap-bind
    a 2-tuple-configured Link the first time we hear from it.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9525,
        debug: bool = False,
        peers: list[tuple] | None = None,
        name: str | None = None,
    ):
        super().__init__(self)
        self._init_links()
        self.name = name or SERVER_NAME
        self.debug_enabled = debug
        self.server_addr = (host, port)
        self._running = False
        self._stop_event = threading.Event()
        self._bound = False
        self._outbound_cursor = 0
        self._session_addresses: dict[str, tuple[str, int]] = {}
        self._addr_keys: dict[str, bytes] = {}
        self._addr_dh: dict[str, DHExchange] = {}
        self.state = ServerState(server_name=self.name, bind_host=host, bind_port=port)
        self.command_store = CommandStore(logger=self.log)
        self.queue = LocalCommandQueue(logger=self.log, store=self.command_store)
        # Register each configured peer as a Link on the server before
        # constructing SyncMesh. SyncMesh no longer owns link state --
        # it reads from self.iter_links() via the mixin.
        if peers:
            for peer in peers:
                self.add_link_from_peer_tuple(peer)
        self.sync_mesh = SyncMesh(server=self, logger=self.log)
        self.dispatcher = CommandDispatcher(
            server=self,
            state=self.state,
            logger=self.log,
            store=self.command_store,
        )
        self.ingress = IRCIngress(server=self, queue=self.queue, sync_mesh=self.sync_mesh, logger=self.log)
        self._restore_pending_queue()

    def enqueue_client_line(
        self,
        line: str,
        source_session: str = "local",
        metadata: dict | None = None,
    ) -> str:
        """Normalize a client line into a command envelope and queue it."""
        envelope = self.ingress.accept_client_line(
            line=line,
            source_session=source_session,
            metadata=metadata,
        )
        return envelope.command_id

    def update_session_context(
        self,
        source_session: str,
        *,
        source_nick: str | None = None,
        source_is_oper: bool | None = None,
        channel_ops: set[str] | None = None,
    ) -> dict:
        return self.state.set_session_context(
            source_session,
            source_nick=source_nick,
            source_is_oper=source_is_oper,
            channel_ops=channel_ops,
        )

    def run_once(self) -> bool:
        """Execute one queued command if available."""
        envelope = self.queue.pop_next()
        if envelope is None:
            return False
        self.debug(
            f"[DEBUG] dequeue id={envelope.command_id} kind={envelope.kind} "
            f"source={envelope.source_session} origin={envelope.origin_server}"
        )
        self.dispatcher.dispatch(envelope)
        self._flush_outbound_events()
        return True

    def run(self) -> None:
        """Run the queue-first UDP server loop until interrupted."""
        self._running = True
        self._bind_socket()
        self.start_listener()
        self.log(f"[STARTUP] Queue-first server listening on {self.server_addr}")
        self.sync_mesh.start()
        self._install_signal_handlers()

        while self._running and not self._stop_event.is_set():
            self._ingest_network_messages()
            handled = self.run_once()
            if not handled:
                time.sleep(0.05)

        self._flush_outbound_events()
        self.sync_mesh.stop()
        self.close()
        self.log("[SHUTDOWN] Server stopped.")

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()

    def debug(self, message: str) -> None:
        if self.debug_enabled:
            self.log(message)

    def _install_signal_handlers(self) -> None:
        def _handle_signal(sig, _frame):
            self.log(f"[SHUTDOWN] Signal {sig} received.")
            self.stop()

        try:
            signal.signal(signal.SIGTERM, _handle_signal)
            signal.signal(signal.SIGINT, _handle_signal)
        except ValueError:
            self.log("[WARN] Signal handlers unavailable in this thread.")

    def _restore_pending_queue(self) -> None:
        pending = self.command_store.load_pending()
        for envelope in pending:
            self.queue.append(envelope, persist=False)
        if pending:
            self.log(f"[QUEUE] restored {len(pending)} pending command(s) from {self.command_store.log_path}")
            for envelope in pending:
                self.debug(
                    f"[DEBUG] restored id={envelope.command_id} kind={envelope.kind} "
                    f"payload={envelope.payload}"
                )

    def _bind_socket(self) -> None:
        if self._bound:
            return
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(self.server_addr)
        bound_host, bound_port = self.sock.getsockname()[:2]
        self.server_addr = (bound_host, bound_port)
        self._bound = True

    def _ingest_network_messages(self) -> None:
        while True:
            message = self.get_message()
            if message is None:
                return
            data, addr = message
            session_id = self._session_id_for_addr(addr)

            if is_encrypted(data):
                key = self._addr_keys.get(session_id)
                if key:
                    try:
                        data = decrypt(key, data)
                    except Exception as e:
                        self.log(f"[CRYPTO] decrypt failed from {session_id}: {e}")
                        continue
                else:
                    self.log(f"[CRYPTO] encrypted data from {session_id} but no key -- dropping")
                    continue

            try:
                text = data.decode("utf-8", errors="ignore")
            except Exception as exc:
                self.log(f"[INGRESS] decode error from {addr}: {exc}")
                continue

            self._session_addresses[session_id] = addr
            for raw_line in text.splitlines():
                line = raw_line.rstrip()
                if not line:
                    continue
                if line.upper().startswith("SYNCLINE "):
                    self.sync_mesh.receive_command_line(line, peer=addr)
                    continue
                upper = line.upper()
                if upper.startswith("CRYPTOINIT DH "):
                    self._handle_cryptoinit_dh(line, addr, session_id)
                    continue
                if upper.startswith("SLINKDH "):
                    self._handle_slinkdh(line, addr, session_id)
                    continue
                if upper.startswith("SLINKDHREPLY "):
                    self._handle_slinkdhreply(line, addr, session_id)
                    continue
                self.enqueue_client_line(line, source_session=session_id)

    def _flush_outbound_events(self) -> None:
        while self._outbound_cursor < len(self.state.outbound_events):
            event = self.state.outbound_events[self._outbound_cursor]
            self._outbound_cursor += 1
            session_id = event["session_id"]
            addr = self._session_addresses.get(session_id)
            if addr is None:
                self.debug(f"[DEBUG] drop outbound for unknown session={session_id} line={event['line']!r}")
                continue
            data = (event["line"] + "\r\n").encode("utf-8")
            key = self._addr_keys.get(session_id)
            if key:
                data = encrypt(key, data)
            self.sock_send(data, addr)

    def _handle_cryptoinit_dh(self, line: str, addr: tuple, session_id: str) -> None:
        try:
            p, g, their_pub = DHExchange.parse_init_message(line)
            dh = DHExchange(p=p, g=g)
            key = dh.compute_shared_key(their_pub)
            self._addr_keys[session_id] = key
            self.sock_send(dh.format_reply_message().encode("utf-8"), addr)
            self.log(f"[CRYPTO] client DH established with {session_id}")
        except Exception as e:
            self.log(f"[CRYPTO] CRYPTOINIT DH failed from {session_id}: {e}")

    def _handle_slinkdh(self, line: str, addr: tuple, session_id: str) -> None:
        try:
            their_pub = int(line.split()[1], 16)
            dh = DHExchange()
            key = dh.compute_shared_key(their_pub)
            self._addr_keys[session_id] = key
            link = self.sync_mesh.find_link_by_addr(addr)
            if link:
                link.crypto_key = key
            self.sock_send(f"SLINKDHREPLY {dh.public:x}\r\n".encode("utf-8"), addr)
            self.log(f"[CRYPTO] S2S DH established with {session_id}")
        except Exception as e:
            self.log(f"[CRYPTO] SLINKDH failed from {session_id}: {e}")

    def _handle_slinkdhreply(self, line: str, addr: tuple, session_id: str) -> None:
        try:
            their_pub = int(line.split()[1], 16)
            dh = self._addr_dh.pop(session_id, None)
            if not dh:
                self.log(f"[CRYPTO] SLINKDHREPLY from {session_id} but no pending DH")
                return
            key = dh.compute_shared_key(their_pub)
            self._addr_keys[session_id] = key
            link = self.sync_mesh.find_link_by_addr(addr)
            if link:
                link.crypto_key = key
            self.log(f"[CRYPTO] S2S DH reply received from {session_id}")
        except Exception as e:
            self.log(f"[CRYPTO] SLINKDHREPLY failed from {session_id}: {e}")

    @staticmethod
    def _session_id_for_addr(addr: tuple[str, int]) -> str:
        return f"{addr[0]}:{addr[1]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="csc-server")
    parser.add_argument("--host", default=os.environ.get("CSC_SERVER_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CSC_SERVER_PORT", "9525")))
    parser.add_argument("--name", default=os.environ.get("CSC_SERVER_NAME") or None)
    parser.add_argument(
        "--debug",
        action="store_true",
        default=os.environ.get("CSC_SERVER_DEBUG", "").lower() in {"1", "true", "yes", "on"},
        help="Enable verbose queue/dispatch debug logging.",
    )
    parser.add_argument(
        "--peer",
        action="append",
        default=[],
        help="Add a linked peer as host:port. May be passed multiple times.",
    )
    args = parser.parse_args(argv)

    peers = []
    for peer in args.peer:
        host, sep, port = peer.partition(":")
        if not sep:
            raise SystemExit(f"Invalid --peer value {peer!r}; expected host:port")
        peers.append((host, int(port)))

    server = Server(host=args.host, port=args.port, debug=args.debug, peers=peers, name=args.name)
    if args.debug:
        server.debug(f"[DEBUG] startup host={args.host} port={args.port} name={server.name} peers={peers}")
    server.run()
    return 0
