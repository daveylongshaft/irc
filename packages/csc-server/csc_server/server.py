from __future__ import annotations

import argparse
import os
import re
import signal
import socket
import subprocess
import threading
import time

from csc_platform import Platform
from csc_services import SERVER_NAME, Service
from csc_crypto import DHExchange, decrypt, is_encrypted
from csc_crypto.connection import Connection

from csc_server.exec.dispatcher import CommandDispatcher
from csc_server.irc.ingress import IRCIngress
from csc_server.queue.local_queue import LocalCommandQueue
from csc_server.queue.store import CommandStore
from csc_server.state.server_state import ServerState
from csc_server.sync.link_mixin import LinkMixin
from csc_server.sync.mesh import SyncMesh
from csc_server.user import User
from csc_server.user_mixin import UserMixin


class Server(Service, LinkMixin, UserMixin):
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
        master: tuple | None = None,
    ):
        super().__init__(self)
        self._init_links()
        self._init_users()
        self.name = name or SERVER_NAME
        self.debug_enabled = debug
        self.master_peer = master  # (host, port) we connect to as subordinate
        self.server_addr = (host, port)
        self._running = False
        self._stop_event = threading.Event()
        self._bound = False
        self._outbound_cursor = 0
        self._connections_by_key_hash: dict[bytes, Connection] = {}
        self._dh_reattempt_times: dict[str, float] = {}  # ip -> last DH attempt time
        self._err_not_registered_times: dict[str, float] = {}  # session_id -> last ERR time
        self._last_heartbeat: float = time.time()
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

    # ------------------------------------------------------------------
    # Connection key_hash registry
    # ------------------------------------------------------------------

    def register_connection_key(self, conn: Connection) -> None:
        """Register a connection's key_hash for O(1) lookup on recv."""
        if conn.key_hash is not None:
            self._connections_by_key_hash[conn.key_hash] = conn

    def unregister_connection_key(self, conn: Connection) -> None:
        """Unregister a connection's key_hash."""
        if conn.key_hash is not None:
            self._connections_by_key_hash.pop(conn.key_hash, None)

    # ------------------------------------------------------------------

    def _find_link_for_addr(self, addr: tuple[str, int]) -> "Link | None":
        """Find the Link associated with a peer address.

        Checks in order:
        1. last_addr exact match (post-handshake, fast path)
        2. Host-IP match against configured host or resolved IPs
           (pre-handshake, ignores port since peer source port is ephemeral)
        """
        # Fast path: exact last_addr match
        link = self.sync_mesh.find_link_by_addr(addr)
        if link:
            return link
        # Fallback: match by host IP only (peer source port is ephemeral)
        peer_ip = addr[0]
        for l in self.iter_links():
            if l.connection.host == peer_ip:
                return l
            if peer_ip in l.connection.resolved_ips:
                return l
        return None

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
                self.sync_mesh.heartbeat_tick()
                time.sleep(0.05)

        self._flush_outbound_events()
        self.sync_mesh.stop()
        self._close_s2s_socket()
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

    S2S_PORT = 9520

    def _bind_socket(self) -> None:
        if self._bound:
            return
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(self.server_addr)
        bound_host, bound_port = self.sock.getsockname()[:2]
        self.server_addr = (bound_host, bound_port)
        self._bound = True
        # Bind S2S listener on dedicated port
        self._bind_s2s_socket()

    def _bind_s2s_socket(self) -> None:
        """Bind a second UDP socket on S2S_PORT for inter-server traffic."""
        host = self.server_addr[0]
        self._s2s_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._s2s_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._s2s_sock.settimeout(1.0)
        self._s2s_sock.bind((host, self.S2S_PORT))
        self._s2s_thread = threading.Thread(
            target=self._s2s_listener, daemon=True
        )
        self._s2s_thread.start()
        self.log(f"[S2S] Listening on {host}:{self.S2S_PORT}")

    def s2s_sock_send(self, data: bytes, addr: tuple) -> None:
        """Send data via the S2S socket (port 9520)."""
        s2s = getattr(self, "_s2s_sock", None)
        if s2s:
            host, port = addr
            # Resolve hostname to IP -- UDP sendto can't resolve hostnames
            if not host.replace('.', '').isdigit():
                try:
                    host = socket.gethostbyname(host)
                except socket.gaierror as e:
                    self.log(f"[S2S] DNS resolution failed for {addr[0]}: {e}")
                    return
            try:
                s2s.sendto(data, (host, port))
            except OSError as e:
                self.log(f"[S2S] Send failed to {host}:{port}: {e}")
        else:
            self.log("[S2S] No S2S socket available for send")

    def _close_s2s_socket(self) -> None:
        """Shut down the S2S listener thread and close its socket."""
        s2s = getattr(self, "_s2s_sock", None)
        if s2s:
            try:
                s2s.close()
                self.log(f"[S2S] Socket closed.")
            except Exception as e:
                self.log(f"[S2S] Error closing socket: {e}")

    def _s2s_listener(self) -> None:
        """Listener thread for the S2S port — feeds into the same message_queue."""
        while self._running:
            try:
                data, addr = self._s2s_sock.recvfrom(self.buffsize)
                self.message_queue.put((data, addr, "s2s"))
            except socket.timeout:
                continue
            except ConnectionResetError:
                continue
            except Exception as e:
                if self._running:
                    self.log(f"[S2S] Listener error: {e}")
                    time.sleep(1)

    def _ingest_network_messages(self) -> None:
        while True:
            message = self.get_message()
            if message is None:
                return
            # Messages from S2S listener have 3 elements (data, addr, "s2s")
            is_s2s = len(message) == 3
            data, addr = message[0], message[1]
            session_id = self._session_id_for_addr(addr)

            # Ensure a User exists for every client-port session (F1 fix)
            if not is_s2s:
                user = self.get_user_by_session(session_id)
                if not user:
                    user = User(self, addr[0], self.server_addr[1], addr=addr)
                    self.add_user(user)

            # Try key_hash header first (16-byte plaintext prefix)
            conn = None
            if len(data) >= 16:
                potential_key_hash = data[:16]
                conn = self._connections_by_key_hash.get(potential_key_hash)
                if conn:
                    data = data[16:]  # Strip key_hash header
                    try:
                        data = decrypt(conn.crypto_key, data)
                        conn.record_recv(len(data), addr=addr)
                    except Exception as e:
                        self.log(f"[CRYPTO] decrypt failed for keyhash from {session_id}: {e}")
                        continue

            # No key_hash match -- check if encrypted
            if not conn and is_encrypted(data):
                # Check if any user connection has a key for this session
                user = self.get_user_by_session(session_id)
                if user and user.connection.crypto_key:
                    try:
                        data = decrypt(user.connection.crypto_key, data)
                    except Exception as e:
                        self.log(f"[CRYPTO] decrypt failed from {session_id}: {e}")
                        continue
                else:
                    now = time.time()
                    last_err = self._err_not_registered_times.get(session_id, 0)
                    if now - last_err >= 10:
                        self._err_not_registered_times[session_id] = now
                        if is_s2s:
                            self.s2s_sock_send(b"ERR_NOT_REGISTERED\r\n", addr)
                            self._maybe_initiate_dh_for_addr(addr, session_id)
                        else:
                            self.log(f"[CRYPTO] encrypted data from {session_id} on client port - no key, sending ERR_NOT_REGISTERED")
                            self.sock_send(b"ERR_NOT_REGISTERED\r\n", addr)
                    continue

            try:
                text = data.decode("utf-8", errors="ignore")
            except Exception as exc:
                self.log(f"[INGRESS] decode error from {addr}: {exc}")
                continue

            for raw_line in text.splitlines():
                line = raw_line.rstrip()
                if not line:
                    continue
                if line.upper().startswith("SYNCLINE "):
                    self.sync_mesh.receive_command_line(line, peer=addr)
                    continue
                if line.upper().startswith("BURST "):
                    self._handle_burst(line, addr, session_id)
                    continue
                upper = line.upper()
                if upper.startswith("WRU "):
                    self._handle_wru(line, addr, session_id)
                    continue
                if upper.startswith("HIA "):
                    self._handle_hia(line, addr, session_id)
                    continue
                if upper.startswith("CRYPTOINIT DH "):
                    self._handle_cryptoinit_dh(line, addr, session_id)
                    continue
                if upper.startswith("SLINKDH_CERT "):
                    self._handle_slinkdh_cert(line, addr, session_id)
                    continue
                if upper.startswith("SLINKDH "):
                    self._handle_slinkdh(line, addr, session_id)
                    continue
                if upper.startswith("SLINKDHREPLY_CERT "):
                    self._handle_slinkdhreply_cert(line, addr, session_id)
                    continue
                if upper.startswith("SLINKDHREPLY "):
                    self._handle_slinkdhreply(line, addr, session_id)
                    continue
                if upper.startswith("ERR_NOT_REGISTERED"):
                    self._handle_err_not_registered(addr, session_id)
                    continue
                self.enqueue_client_line(line, source_session=session_id)

    def _maybe_initiate_dh_for_addr(self, addr: tuple, session_id: str) -> None:
        """If addr matches a configured peer, initiate fresh DH (rate-limited to once per 10s per IP)."""
        now = time.time()
        peer_ip = addr[0]
        last = self._dh_reattempt_times.get(peer_ip, 0)
        if now - last < 10:
            return
        self._dh_reattempt_times[peer_ip] = now
        link = self._find_link_for_addr(addr)
        if link:
            self.log(f"[S2S] Stale encrypted traffic from {session_id} -- re-initiating DH for {link.name}")
            self.sync_mesh._initiate_link_dh(link)
        else:
            self.log(f"[S2S] Stale encrypted traffic from {session_id} -- no matching link")

    def _handle_burst(self, line: str, addr: tuple, session_id: str) -> None:
        """Receive BURST: link state from peer."""
        import json
        try:
            burst_json = line[6:].strip()
            burst_data = json.loads(burst_json)
            link = self._find_link_for_addr(addr)
            if link:
                self.sync_mesh.receive_burst(link, burst_data)
            else:
                self.log(f"[BURST] Received from unknown address {session_id}")
        except Exception as e:
            self.log(f"[BURST] Parse error from {session_id}: {e}")

    def _handle_wru(self, line: str, addr: tuple, session_id: str) -> None:
        """Receive WRU: query for nick/server location."""
        import json
        try:
            parts = line.split(None, 1)
            if len(parts) < 2:
                return
            query_json = parts[1]
            query_data = json.loads(query_json)
            target_type = query_data.get("target_type")
            target = query_data.get("target")
            request_id = query_data.get("id")
            origin_link = self._find_link_for_addr(addr)

            found_link = None
            if target_type == "nick":
                for link in self.iter_links():
                    if link != origin_link and link.has_nick_behind(target):
                        found_link = link
                        break
            elif target_type == "server":
                for link in self.iter_links():
                    if link != origin_link and target in link.servers_behind:
                        found_link = link
                        break

            if found_link:
                hia_json = json.dumps({
                    "target_type": target_type,
                    "target": target,
                    "id": request_id,
                })
                hia_line = f"HIA {hia_json}\r\n"
                if origin_link:
                    origin_link.connection.sendto(hia_line.encode("utf-8"))
                    self.log(f"[WRU] Replied HIA for {target_type}:{target}")
        except Exception as e:
            self.log(f"[WRU] Parse error: {e}")

    def _handle_hia(self, line: str, addr: tuple, session_id: str) -> None:
        """Receive HIA: nick/server location response."""
        import json
        try:
            parts = line.split(None, 1)
            if len(parts) < 2:
                return
            response_json = parts[1]
            response_data = json.loads(response_json)
            target_type = response_data.get("target_type")
            target = response_data.get("target")
            from_link = self._find_link_for_addr(addr)

            if from_link:
                if target_type == "nick":
                    from_link.add_nick_behind(target)
                    self.log(f"[HIA] Learned {target} is behind {from_link.name}")
                elif target_type == "server":
                    if target not in from_link.servers_behind:
                        from_link.servers_behind.append(target)
                    self.log(f"[HIA] Learned {target} is behind {from_link.name}")
        except Exception as e:
            self.log(f"[HIA] Parse error: {e}")

    def _flush_outbound_events(self) -> None:
        while self._outbound_cursor < len(self.state.outbound_events):
            event = self.state.outbound_events[self._outbound_cursor]
            self._outbound_cursor += 1
            session_id = event["session_id"]
            user = self.get_user_by_session(session_id)
            if user:
                # User.send auto-encrypts via Connection.sendto
                data = (event["line"] + "\r\n").encode("utf-8")
                user.send(data)
            else:
                self.debug(f"[DEBUG] drop outbound for unknown session={session_id} line={event['line']!r}")

    def _handle_cryptoinit_dh(self, line: str, addr: tuple, session_id: str) -> None:
        """Handle client-initiated DH key exchange."""
        try:
            p, g, their_pub = DHExchange.parse_init_message(line)
            dh = DHExchange(p=p, g=g)
            key = dh.compute_shared_key(their_pub)
            # Get or create User for this client
            user = self.get_user_by_session(session_id)
            if not user:
                user = User(self, addr[0], self.server_addr[1], addr=addr)
                self.add_user(user)
            user.connection.set_crypto_key(key)
            self.sock_send(dh.format_reply_message().encode("utf-8"), addr)
            self.log(f"[CRYPTO] client DH established with {session_id}")
        except Exception as e:
            self.log(f"[CRYPTO] CRYPTOINIT DH failed from {session_id}: {e}")

    def _validate_s2s_cert_and_get_peer_name(self, cert_pem: str, ca_cert_path: str) -> str | None:
        """Validate S2S cert PEM against CA. Return peer name (cert CN) if valid, else None."""
        try:
            import tempfile

            if not os.path.exists(ca_cert_path):
                self.log(f"[S2S-CERT] CA cert not found: {ca_cert_path}")
                return None

            # Write cert PEM to temp file for validation
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
                f.write(cert_pem)
                cert_path = f.name

            try:
                # Extract peer name from cert CN field
                result = subprocess.run(
                    ["openssl", "x509", "-noout", "-subject"],
                    input=cert_pem,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode != 0:
                    self.log(f"[S2S-CERT] Failed to extract CN from cert: {result.stderr}")
                    return None

                # Parse CN from subject line: "subject=CN=haven-ef6e,..."
                match = re.search(r'CN\s*=\s*([^,/]+)', result.stdout)
                if not match:
                    self.log(f"[S2S-CERT] No CN found in cert subject: {result.stdout}")
                    return None

                peer_name = match.group(1).strip()

                # Validate cert against CA
                result = subprocess.run(
                    ["openssl", "verify", "-CAfile", ca_cert_path, cert_path],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode != 0:
                    self.log(f"[S2S-CERT] Certificate validation failed for {peer_name}: {result.stderr}")
                    return None

                self.log(f"[S2S-CERT] Certificate valid for peer: {peer_name}")
                return peer_name
            finally:
                os.unlink(cert_path)
        except Exception as e:
            self.log(f"[S2S-CERT] Exception during cert validation: {e}")
            return None

    def _handle_slinkdh_cert(self, line: str, addr: tuple, session_id: str) -> None:
        """Handle inbound S2S cert + DH handshake. Validates cert, creates link if valid."""
        try:
            import base64
            parts = line.split(" ", 2)
            if len(parts) < 3:
                self.log(f"[S2S-CERT] Invalid SLINKDH_CERT format from {session_id}")
                return

            their_pub_hex = parts[1]
            cert_b64 = parts[2]

            try:
                cert_pem = base64.b64decode(cert_b64).decode("utf-8")
            except Exception as e:
                self.log(f"[S2S-CERT] Failed to decode cert from {session_id}: {e}")
                return

            # Get CA cert path
            etc = str(Platform.get_etc_dir())
            s2s_ca_path = os.environ.get("CSC_S2S_CA") or f"{etc}/ca.crt"

            # Validate cert and get peer name
            peer_name = self._validate_s2s_cert_and_get_peer_name(cert_pem, s2s_ca_path)
            if not peer_name:
                self.log(f"[S2S-CERT] Rejected connection from {session_id} - invalid certificate")
                return

            # Find existing link by origin identity, then by address, then auto-create
            link = self.get_link_by_origin(peer_name)
            if not link:
                link = self._find_link_for_addr(addr)
            if not link:
                # Auto-create link from valid cert (inbound responder)
                link = self.add_link_from_peer_tuple((peer_name, addr[0], addr[1]))
                link.is_inbound = True
                link.ftpd_role = "master"
                self.log(f"[S2S] Auto-created inbound link from {peer_name} (cert-based, we are FTPD master)")

            # DH race tiebreaker: if we also initiated DH to this peer
            # (dh_pending is set), both sides sent SLINKDH_CERT at the
            # same time. Each side would complete both exchanges with
            # different keys, breaking encryption. Tiebreaker: the server
            # whose name sorts lower wins as initiator; the other yields
            # by accepting the inbound DH and dropping its pending outbound.
            if link.connection.dh_pending is not None:
                our_name = self.name.lower()
                their_name = peer_name.lower()
                if our_name < their_name:
                    # We win the tiebreaker -- ignore their DH, they will
                    # accept our SLINKDHREPLY when it arrives.
                    self.log(
                        f"[S2S-CERT] DH race with {peer_name}: we win tiebreaker "
                        f"({our_name} < {their_name}), ignoring inbound DH"
                    )
                    return
                else:
                    # They win -- drop our pending outbound DH and accept theirs.
                    self.log(
                        f"[S2S-CERT] DH race with {peer_name}: they win tiebreaker "
                        f"({their_name} < {our_name}), accepting inbound DH"
                    )
                    link.connection.clear_crypto()

            # Peer wants to rekey -- allow it even if we have a live key.
            # The peer may have lost state or expired their side.
            elif link.connection.crypto_key is not None:
                self.log(f"[S2S-CERT] Rekeying link {peer_name} (peer requested new DH)")
                link.connection.clear_crypto()

            # Perform DH exchange via Connection
            their_pub = int(their_pub_hex, 16)
            dh = DHExchange()
            key = dh.compute_shared_key(their_pub)
            link.connection.set_crypto_key(key)
            link.connection.update_addr(addr)

            # Send DH reply with our cert
            s2s_cert_path = self._get_s2s_cert_path()
            try:
                with open(s2s_cert_path, 'r') as f:
                    our_cert_pem = f.read()
                our_cert_b64 = base64.b64encode(our_cert_pem.encode()).decode()
                reply = f"SLINKDHREPLY_CERT {dh.public:x} {our_cert_b64}\r\n"
            except Exception as e:
                self.log(f"[S2S-CERT] Failed to read own cert for reply: {e}")
                # Fall back to plain reply
                reply = f"SLINKDHREPLY {dh.public:x}\r\n"

            self.s2s_sock_send(reply.encode("utf-8"), addr)
            self.log(f"[S2S-CERT] Accepted inbound link from {peer_name}, DH established with cert validation")
        except Exception as e:
            self.log(f"[S2S-CERT] SLINKDH_CERT failed from {session_id}: {e}")

    def _handle_slinkdh(self, line: str, addr: tuple, session_id: str) -> None:
        try:
            their_pub = int(line.split()[1], 16)

            link = self._find_link_for_addr(addr)
            if not link:
                self.log(f"[CRYPTO] SLINKDH from {session_id} but no matching link -- ignoring")
                return

            if link.connection.crypto_key is not None and not link.connection.is_expired():
                self.log(f"[CRYPTO] Ignoring inbound SLINKDH from {session_id} -- link already has live key")
                link.connection.update_addr(addr)
                return

            dh = DHExchange()
            key = dh.compute_shared_key(their_pub)
            link.connection.set_crypto_key(key)
            link.connection.update_addr(addr)

            self.s2s_sock_send(f"SLINKDHREPLY {dh.public:x}\r\n".encode("utf-8"), addr)
            self.log(f"[CRYPTO] S2S DH established with {session_id}")
        except Exception as e:
            self.log(f"[CRYPTO] SLINKDH failed from {session_id}: {e}")

    def _handle_slinkdhreply_cert(self, line: str, addr: tuple, session_id: str) -> None:
        """Handle SLINKDHREPLY_CERT: master's reply with cert + DH public key."""
        try:
            import base64
            parts = line.split(" ", 2)
            if len(parts) < 3:
                self.log(f"[S2S-CERT] Invalid SLINKDHREPLY_CERT format from {session_id}")
                return

            their_pub_hex = parts[1]
            cert_b64 = parts[2]

            # Validate master's cert
            try:
                cert_pem = base64.b64decode(cert_b64).decode("utf-8")
            except Exception as e:
                self.log(f"[S2S-CERT] Failed to decode reply cert from {session_id}: {e}")
                return

            etc = str(Platform.get_etc_dir())
            s2s_ca_path = os.environ.get("CSC_S2S_CA") or f"{etc}/ca.crt"
            peer_name = self._validate_s2s_cert_and_get_peer_name(cert_pem, s2s_ca_path)
            if not peer_name:
                self.log(f"[S2S-CERT] Rejected SLINKDHREPLY_CERT from {session_id} - invalid certificate")
                return

            # Find the link with pending DH
            their_pub = int(their_pub_hex, 16)
            link = self.get_link_by_origin(peer_name)
            if not link:
                link = self._find_link_for_addr(addr)
            if not link:
                self.log(f"[S2S-CERT] SLINKDHREPLY_CERT from {session_id} but no matching link")
                return
            if not link.connection.dh_pending:
                self.log(f"[S2S-CERT] SLINKDHREPLY_CERT from {session_id} but no pending DH on link")
                return

            # Complete DH via Connection
            link.connection.complete_dh(their_pub)
            link.connection.update_addr(addr)
            if not link.origin_server:
                self.bind_link_origin(link, peer_name)
            self.log(f"[S2S-CERT] Link established with {peer_name} (we are slave), DH complete")
        except Exception as e:
            self.log(f"[S2S-CERT] SLINKDHREPLY_CERT failed from {session_id}: {e}")

    def _handle_slinkdhreply(self, line: str, addr: tuple, session_id: str) -> None:
        try:
            their_pub = int(line.split()[1], 16)
            link = self._find_link_for_addr(addr)
            if not link or not link.connection.dh_pending:
                self.log(f"[CRYPTO] SLINKDHREPLY from {session_id} but no pending DH")
                return
            link.connection.complete_dh(their_pub)
            link.connection.update_addr(addr)
            self.log(f"[CRYPTO] S2S DH reply received from {session_id}")
        except Exception as e:
            self.log(f"[CRYPTO] SLINKDHREPLY failed from {session_id}: {e}")

    def _handle_err_not_registered(self, addr: tuple, session_id: str) -> None:
        """Handle ERR_NOT_REGISTERED: link was forgotten, trigger re-auth."""
        link = self._find_link_for_addr(addr)
        if link:
            link.connection.clear_crypto()
            self.log(f"[S2S] Received ERR_NOT_REGISTERED from {link.name} - reinitiate handshake")
            self.sync_mesh._initiate_link_dh(link)
        else:
            self.log(f"[S2S] Received ERR_NOT_REGISTERED from unknown {session_id}")

    def _get_s2s_cert_path(self) -> str:
        """Return path to our S2S certificate chain via data layer."""
        from_env = os.environ.get("CSC_S2S_CERT")
        if from_env:
            return from_env
        from csc_data.config import ConfigManager
        try:
            cfg = ConfigManager()
            from_config = cfg.get_value("s2s_cert")
            if from_config:
                return from_config
        except Exception:
            pass
        etc = Platform.get_etc_dir()
        return str(etc / "server.chain.pem")

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
    parser.add_argument(
        "--master",
        default=os.environ.get("CSC_S2S_MASTER"),
        help="Master server to link to as subordinate (ip:port). Auto-initiates outbound link.",
    )
    args = parser.parse_args(argv)

    peers = []
    for peer in args.peer:
        host, sep, port = peer.partition(":")
        if not sep:
            raise SystemExit(f"Invalid --peer value {peer!r}; expected host:port")
        peers.append((host, int(port)))

    # If --master specified, add as outbound peer (becomes FTPD slave)
    master = None
    if args.master:
        host, sep, port = args.master.partition(":")
        if not sep:
            raise SystemExit(f"Invalid --master value {args.master!r}; expected host:port")
        master = (host, int(port))
        peers.append(master)

    server = Server(host=args.host, port=args.port, debug=args.debug, peers=peers, name=args.name, master=master)
    if args.debug:
        server.debug(f"[DEBUG] startup host={args.host} port={args.port} name={server.name} peers={peers}")
    server.run()
    return 0
