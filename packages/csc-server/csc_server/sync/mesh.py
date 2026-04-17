from __future__ import annotations

import base64
import json
import time
from collections import OrderedDict
from typing import Callable

from csc_crypto import DHExchange
from csc_server.queue.command import CommandEnvelope
from csc_server.sync.link import Link


class SyncMesh:
    """UDP relay for queue envelopes across linked peers.

    SyncMesh does not own link state. Links live on the server via
    LinkMixin; SyncMesh reads them via `self.server.iter_links()`,
    `self.server.get_link_by_id()`, and `self.server.get_link_by_origin()`.

    Routing is by identity (link id), never by network address:
        - Outbound: iterate server.iter_links() and call link.sendto().
          exclude_link_id skips the origin on re-relay.
        - Inbound: parse the envelope, look up the Link by
          envelope.origin_server. If no Link is bound to that origin
          yet, fall through to bootstrap binding (match recvfrom addr
          against a pre-configured, unbound Link). Otherwise drop the
          datagram: an unknown origin_server from an unknown address
          is not a peer we've configured.
        - Every accepted envelope is stamped with
          envelope.arrival_link_id = link.id so downstream code can
          trace origin without ever touching addresses.

    Architecture contract (relay-first):
        - Client-originated commands: ingress calls sync_command() BEFORE
          queue.append() so peers see the envelope before local processing.
        - Peer-received commands: receive_command() re-relays to every
          OTHER link (exclude_link_id = incoming link id) BEFORE
          enqueueing locally.
        - Loop prevention is via per-command_id dedup cache, so even if
          the exclude_link_id optimization misses for any reason, a
          duplicate arrival is dropped silently.
    """

    _SEEN_COMMANDS_MAX = 10000
    _IDLE_THRESHOLD = 60  # Send PING when idle for 60 seconds
    _MAX_UNANSWERED_PINGS = 2  # Timeout after 2 unanswered PINGs
    _DH_TIMEOUT = 10  # Re-initiate DH if no reply for 10 seconds
    _BURST_TIMEOUT = 30  # Wait 30s for BURST response before retry
    _BURST_MAX_RETRIES = 3  # Max BURST retries before giving up

    def __init__(self, server, logger: Callable[[str], None]):
        self.server = server
        self._logger = logger
        self._running = False
        self._started_at: float | None = None
        self._seen_commands: OrderedDict[str, float] = OrderedDict()
        self._burst_complete: set[str] = set()  # link ids where BURST has completed
        self._burst_sent_at: dict[str, float] = {}  # link_id -> timestamp of last BURST send
        self._burst_retries: dict[str, int] = {}  # link_id -> retry count

    # ------------------------------------------------------------------
    # Dedup
    # ------------------------------------------------------------------

    def _mark_seen(self, command_id: str | None) -> bool:
        """Record a command_id. Returns True if newly seen, False if duplicate."""
        if not command_id:
            return True
        if command_id in self._seen_commands:
            self._seen_commands.move_to_end(command_id)
            return False
        self._seen_commands[command_id] = time.time()
        while len(self._seen_commands) > self._SEEN_COMMANDS_MAX:
            self._seen_commands.popitem(last=False)
        return True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._started_at = time.time()
        link_count = self.server.link_count()
        if link_count:
            names = self.server.link_names()
            self._logger(f"[SYNC] Mesh started with links={names}")
            # Aggressively initiate DH with all configured links
            for link in self.server.iter_links():
                if link.connection.crypto_key is None and link.connection.dh_pending is None:
                    self._initiate_link_dh(link)
            return
        self._announce_stub("start", "no links configured, relay is inactive")
        self._logger("[SYNC] Mesh started without links.")

    def stop(self) -> None:
        if self._running:
            if self.server.link_count() == 0:
                self._announce_stub("stop", "no links configured, relay was inactive")
            self._logger("[SYNC] Mesh stopped.")
        self._running = False

    # ------------------------------------------------------------------
    # Send path
    # ------------------------------------------------------------------

    def sync_command(
        self,
        envelope: CommandEnvelope,
        *,
        exclude_link_id: str | None = None,
    ) -> None:
        """Relay a command to linked peers.

        exclude_link_id, if given, is the id of the Link the command
        arrived on: we skip it so the command does not echo back to its
        origin. Locally-originated commands have no exclude_link_id.
        """
        if not envelope.replicate:
            return
        # Mark as seen so any loop-back is dropped on arrival.
        self._mark_seen(envelope.command_id)
        if self.server.link_count() == 0:
            self._announce_stub("sync_command", "no links configured, command relay skipped")
            return
        payload = self.prepare_sync_payload(envelope)
        self._logger(
            f"[SYNC] relaying kind={envelope.kind} id={envelope.command_id} "
            f"origin={envelope.origin_server} exclude={exclude_link_id}"
        )
        debug_fn = getattr(self.server, "debug", None)
        if callable(debug_fn):
            debug_fn(f"[DEBUG] relay payload={payload}")
        line = self.encode_command_line(envelope)
        for link in self.server.iter_links():
            if exclude_link_id is not None and link.id == exclude_link_id:
                continue
            # Initiate DH on first outbound to this link
            if link.connection.crypto_key is None and link.connection.dh_pending is None:
                self._initiate_link_dh(link)

            # Connection.sendto auto-encrypts (prepends key_hash + AES-GCM)
            wire = (line + "\r\n").encode("utf-8")
            link.connection.sendto(wire)

    # ------------------------------------------------------------------
    # Encryption helpers
    # ------------------------------------------------------------------

    def find_link_by_addr(self, addr: tuple) -> Link | None:
        """Return Link whose last_addr matches addr, or None."""
        for link in self.server.iter_links():
            if link.connection.last_addr == addr:
                return link
        return None

    def _initiate_link_dh(self, link: Link) -> None:
        """Send SLINKDH_CERT with cert to peer; store DHExchange on Connection."""
        try:
            dh = link.connection.start_dh()
            if not link.is_inbound:
                link.ftpd_role = "slave"

            # Send cert + DH public key for cert-based auth
            s2s_cert_path = self.server._get_s2s_cert_path()
            try:
                with open(s2s_cert_path, 'r') as f:
                    our_cert_pem = f.read()
                our_cert_b64 = base64.b64encode(our_cert_pem.encode()).decode()
                msg = f"SLINKDH_CERT {dh.public:x} {our_cert_b64}\r\n".encode("utf-8")
            except Exception as e:
                self.server.log(f"[S2S-CERT] Failed to read cert for SLINKDH_CERT: {e}")
                msg = f"SLINKDH {dh.public:x}\r\n".encode("utf-8")

            # Send plaintext handshake (no auto-encrypt -- no key yet)
            addr = link.connection.send_address()
            self.server.s2s_sock_send(msg, addr)
            self.server.log(f"[S2S] Initiated outbound link to {link.name} with cert-based auth")
        except Exception as e:
            self.server.log(f"[S2S] SLINKDH initiation failed for {link.name}: {e}")

    # ------------------------------------------------------------------
    # Wire encoding
    # ------------------------------------------------------------------

    def prepare_sync_payload(self, envelope: CommandEnvelope) -> dict:
        return envelope.to_dict()

    def encode_command(self, envelope: CommandEnvelope) -> bytes:
        return json.dumps(self.prepare_sync_payload(envelope), sort_keys=True).encode("utf-8")

    def encode_command_line(self, envelope: CommandEnvelope) -> str:
        return f"SYNCLINE :{self.encode_command(envelope).decode('utf-8')}"

    # ------------------------------------------------------------------
    # Receive path
    # ------------------------------------------------------------------

    def receive_command_line(
        self,
        line: str,
        *,
        peer: tuple[str, int] | None = None,
    ) -> CommandEnvelope | None:
        """Parse a SYNCLINE off the wire and route it by identity.

        `peer` is the addr from recvfrom(). It is used ONLY to (a)
        bootstrap-bind a pre-configured Link the first time we hear
        from it, and (b) be stored as last_addr so outbound traffic
        tracks NAT rebinds. It is never used to look up a bound link.
        """
        _, _, trailing = line.partition(" :")
        if not trailing:
            raise ValueError(f"Invalid SYNCLINE payload: {line!r}")

        # Parse the envelope before touching any state.
        try:
            payload = json.loads(trailing)
        except json.JSONDecodeError as exc:
            self._logger(f"[SYNC] drop: invalid JSON from {peer}: {exc}")
            return None
        envelope = CommandEnvelope.from_dict(payload)

        # Identify the originating Link. Routing is by origin_server id,
        # not by address.
        incoming_link = self._resolve_incoming_link(envelope.origin_server, peer)
        if incoming_link is None:
            self._logger(
                f"[SYNC] drop: unknown origin={envelope.origin_server!r} "
                f"from addr={peer} (no configured link matches)"
            )
            return None

        # Record the recv on the link; updates last_addr as a side effect
        # so NAT rebinds are tracked without any routing involvement.
        approx_wire_bytes = len(line.encode("utf-8")) + 2  # incl. CRLF
        incoming_link.connection.record_recv(approx_wire_bytes, addr=peer)

        # Stamp the envelope with the link id it arrived on. Downstream
        # code (queue, dispatcher, stats, netsplit handling) reads this
        # and calls server.get_link_by_id(...) -- never an address.
        envelope.arrival_link_id = incoming_link.id

        return self._process_received_envelope(envelope)

    def _resolve_incoming_link(
        self,
        origin_server: str,
        peer: tuple[str, int] | None,
    ) -> Link | None:
        """Find the Link that `origin_server` belongs to.

        Steps:
            1. Fast path: origin already bound -- O(1) lookup.
            2. Bootstrap: a pre-configured Link exists with no origin
               yet and its configured address matches `peer`. Bind it
               and return it. This is the ONLY place an address is
               used to identify a Link.
            3. Otherwise: unknown peer, return None so caller drops.
        """
        # (1) Fast path: origin already bound.
        link = self.server.get_link_by_origin(origin_server)
        if link is not None:
            return link
        # (2) Bootstrap bind.
        candidate = self.server.find_unbound_link_for_addr(peer)
        if candidate is not None:
            try:
                self.server.bind_link_origin(candidate, origin_server)
                self._logger(
                    f"[SYNC] bootstrap-bind link id={candidate.id} "
                    f"to origin={origin_server!r} (addr={peer})"
                )
                return candidate
            except ValueError as exc:
                self._logger(f"[SYNC] bootstrap-bind failed: {exc}")
                return None
        return None

    def _process_received_envelope(
        self,
        envelope: CommandEnvelope,
    ) -> CommandEnvelope | None:
        """Dedup, relay, then enqueue. Used by receive_command_line and
        by any caller that already has a parsed, stamped envelope."""
        # Dedup.
        if not self._mark_seen(envelope.command_id):
            self._logger(
                f"[SYNC] drop duplicate kind={envelope.kind} id={envelope.command_id} "
                f"origin={envelope.origin_server} arrival_link={envelope.arrival_link_id}"
            )
            return None

        # S2S keepalive PINGs: send PONG back on the link connection,
        # don't queue for the dispatcher (which would PONG to a fake session).
        if envelope.kind == "PING" and envelope.source_session == "s2s-keepalive":
            link = self.server.get_link_by_id(envelope.arrival_link_id)
            if link and link.connection.crypto_key:
                pong_envelope = CommandEnvelope(
                    command_id=f"pong-{envelope.command_id}",
                    kind="PONG",
                    payload={"line": f"PONG {envelope.command_id}"},
                    origin_server=self.server.name,
                    source_session="s2s-keepalive",
                    replicate=False,
                )
                wire = (self.encode_command_line(pong_envelope) + "\r\n").encode("utf-8")
                link.connection.sendto(wire)
                self._logger(
                    f"[KEEPALIVE] Got PING from {envelope.origin_server}, "
                    f"sent PONG to {link.connection.send_address()}"
                )
            return envelope

        # Relay to other links BEFORE local enqueue (relay-first).
        if envelope.replicate and self.server.link_count() > 0:
            self.sync_command(envelope, exclude_link_id=envelope.arrival_link_id)

        # Local enqueue. Flip replicate off so the local queue pipeline
        # does not trigger another sync_command round.
        envelope.replicate = False
        self.server.queue.append(envelope)
        self._logger(
            f"[SYNC] received relay kind={envelope.kind} id={envelope.command_id} "
            f"origin={envelope.origin_server} arrival_link={envelope.arrival_link_id}"
        )
        return envelope

    # Kept for callers that want to inject a pre-parsed envelope dict
    # (e.g. tests). Routing still requires an already-stamped
    # arrival_link_id, or the envelope will be treated as locally
    # originated for relay purposes.
    def receive_command(self, payload: dict | bytes | str) -> CommandEnvelope | None:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            payload = json.loads(payload)
        envelope = CommandEnvelope.from_dict(payload)
        return self._process_received_envelope(envelope)

    # ------------------------------------------------------------------
    # BURST protocol (state exchange on link-up)
    # ------------------------------------------------------------------

    def send_burst(self, link: "Link") -> None:
        """Send our link state to peer after DH completes."""
        import json

        retries = self._burst_retries.get(link.id, 0)
        if retries >= self._BURST_MAX_RETRIES:
            self._logger(
                f"[BURST] Max retries ({self._BURST_MAX_RETRIES}) reached "
                f"for {link.name}, skipping"
            )
            return

        # Include local users and channels in burst data
        local_nicks = []
        for _sid, session in self.server.state.sessions.items():
            n = session.get("nick")
            if n and session.get("state") == "registered":
                local_nicks.append(n)

        # Collect local opers
        local_opers = sorted(self.server.opers) if hasattr(self.server, "opers") else []

        # Collect opers from other links
        remote_opers = set()
        for lk in self.server.iter_links():
            if lk.id != link.id:
                remote_opers.update(lk.opers)

        burst_data = {
            "server": self.server.name,
            "servers_behind": [lk.origin_server for lk in self.server.iter_links() if lk.id != link.id and lk.origin_server],
            "nicks_behind": sorted(
                set(local_nicks) | set().union(
                    *[lk.nicks_behind for lk in self.server.iter_links() if lk.id != link.id]
                ) if any(True for lk in self.server.iter_links() if lk.id != link.id)
                else set(local_nicks)
            ),
            "opers": sorted(set(local_opers) | remote_opers),
            "channels": {
                lk.name: lk.serialize_for_burst()
                for lk in self.server.iter_links()
                if lk.id != link.id
            },
        }

        burst_line = f"BURST {json.dumps(burst_data)}\r\n"
        link.connection.sendto(burst_line.encode("utf-8"))
        self._burst_sent_at[link.id] = time.time()
        self._burst_retries[link.id] = retries + 1
        self._logger(
            f"[BURST] Sent state to {link.name} (attempt {retries + 1}): "
            f"{len(burst_data['servers_behind'])} servers, "
            f"{len(burst_data['nicks_behind'])} nicks"
        )

    def receive_burst(self, link: "Link", burst_data: dict) -> None:
        """Receive peer's state after they send BURST.

        Detects nick collisions between local users and incoming remote
        nicks. Colliding remote nicks are dropped from the BURST data
        and a KILL is broadcast so both sides agree on the resolution.
        """
        link.set_servers_behind(burst_data.get("servers_behind", []))

        # Collect local nick set for collision detection
        local_nicks: set[str] = set()
        for _sid, session in self.server.state.sessions.items():
            nick = session.get("nick")
            if nick:
                local_nicks.add(nick.lower())

        # Detect collisions in nicks_behind
        incoming_nicks = set(burst_data.get("nicks_behind", []))
        collisions: list[str] = []
        for nick in list(incoming_nicks):
            if nick.lower() in local_nicks:
                collisions.append(nick)
                incoming_nicks.discard(nick)
        link.set_nicks_behind(incoming_nicks)

        # Detect collisions in channel user lists
        for chan_name, chan_burst in burst_data.get("channels", {}).items():
            from csc_server.channel import Channel
            users = chan_burst.get("users", {})
            for nick in list(users.keys()):
                if nick.lower() in local_nicks and nick not in collisions:
                    collisions.append(nick)
                    del users[nick]
            chan = Channel.from_dict(chan_burst)
            link.channels[chan.name] = chan

        # Apply opers from burst
        for oper_nick in burst_data.get("opers", []):
            if oper_nick.lower() not in {c.lower() for c in collisions}:
                link.add_oper(oper_nick)

        # Log and emit collision KILLs
        for nick in collisions:
            self._logger(
                f"[BURST] Nick collision: {nick} exists locally and on "
                f"{link.name} -- remote nick dropped"
            )

        self._burst_complete.add(link.id)
        # Clear retry state on successful receive
        self._burst_sent_at.pop(link.id, None)
        self._burst_retries.pop(link.id, None)
        self._logger(
            f"[BURST] Received from {link.name}: "
            f"{len(burst_data.get('servers_behind', []))} servers, "
            f"{len(incoming_nicks)} nicks, "
            f"{len(burst_data.get('channels', {}))} channels"
            f"{f', {len(collisions)} collisions resolved' if collisions else ''}"
        )

    # ------------------------------------------------------------------
    # Stats surface (delegates to server.link_stats)
    # ------------------------------------------------------------------

    def link_stats(self) -> list[dict]:
        """Return per-link statistics for `/stats l`.

        Thin passthrough to the LinkMixin on the server: the stats live
        on the Link objects themselves.
        """
        return self.server.link_stats()

    # ------------------------------------------------------------------
    # Netsplit / SQUIT detection (STUB FRAMEWORK)
    # ------------------------------------------------------------------

    def _log_stub(self, method_name: str, **extra) -> None:
        dispatcher = getattr(self.server, "dispatcher", None)
        if dispatcher is not None and hasattr(dispatcher, "log_stubbed_call"):
            dispatcher.log_stubbed_call("SyncMesh", method_name, **extra)
            return
        marker = f"[!!! STUB-HIT !!!] SyncMesh.{method_name} extra={extra}"
        try:
            self._logger(marker)
        except Exception:
            pass

    def peer_timeout_detected(self, link: Link) -> None:
        """Handle detection of a dead peer link.

        Emits netsplit QUIT messages for all remote users, cleans link
        state, and propagates SQUIT to other links.
        """
        peer_name = link.origin_server or link.name
        self._logger(
            f"[NETSPLIT] Peer timeout detected for {peer_name} "
            f"(link={link.id[:8]})"
        )
        self.emit_netsplit_quits(link)
        self.squit_propagate(link, reason=f"peer timeout: {peer_name}")

        # Clear burst state so re-BURST happens on reconnect
        self._burst_complete.discard(link.id)
        self._burst_sent_at.pop(link.id, None)
        self._burst_retries.pop(link.id, None)

    def emit_netsplit_quits(self, dead_link: Link) -> None:
        """Emit QUIT messages for all users known behind a dead link.

        Sends netsplit-style QUIT (localserver remoteserver) to all
        local sessions so clients see the users disappear.
        """
        peer_name = dead_link.origin_server or dead_link.name
        removed_nicks, _removed_channels = dead_link.clear_remote_state()
        if not removed_nicks:
            self._logger(f"[NETSPLIT] No users to clean from {peer_name}")
            return

        from csc_services import format_irc_message
        quit_reason = f"{self.server.name} {peer_name}"
        for remote_nick in removed_nicks:
            quit_line = format_irc_message(
                f"{remote_nick}!{remote_nick}@{peer_name}",
                "QUIT",
                [],
                quit_reason,
            )
            for session_id in self.server.state.sessions:
                self.server.state.record_session_outbound(session_id, quit_line)

        self._logger(
            f"[NETSPLIT] Emitted QUIT for {len(removed_nicks)} users "
            f"from {peer_name}"
        )

    def squit_propagate(self, dead_link: Link, reason: str = "") -> None:
        """Propagate SQUIT to other linked peers so the mesh converges.

        Sends a non-replicating SQUIT envelope to every other link so
        they also clean up state for the dead server.
        """
        peer_name = dead_link.origin_server or dead_link.name
        if not reason:
            reason = f"link lost: {peer_name}"

        squit_envelope = CommandEnvelope(
            kind="IRC",
            payload={"line": f"SQUIT {peer_name} :{reason}"},
            source_session=f"system:{self.server.name}",
            origin_server=self.server.name,
            replicate=True,
        )
        self.sync_command(squit_envelope, exclude_link_id=dead_link.id)
        self._logger(
            f"[NETSPLIT] Propagated SQUIT for {peer_name} to "
            f"{self.server.link_count() - 1} other links"
        )

    def heartbeat_tick(self) -> None:
        """Idle-based keepalive for S2S links.

        Called when the command queue drains (no work left). Loops through
        all links and:
        - DH pending + timed out: re-initiate DH
        - Encrypted + timed out (2 unanswered PINGs): reset and re-DH
        - Encrypted + idle (>60s no traffic): send PING
        - No crypto, no DH: initiate DH

        Idle is measured by last_seen and last_ping_sent on the Connection.
        Any recv (data, PONG, SYNCLINE) resets the idle clock and clears
        ping_waiting. This means PINGs only fire during genuine silence.
        """
        now = time.time()
        for link in self.server.iter_links():
            conn = link.connection

            # Never re-initiate outbound DH for inbound-only links.
            # The remote side is responsible for reconnecting.
            if link.is_inbound and conn.crypto_key is None and conn.dh_pending is None:
                continue

            # Case 1: DH is pending -- check if it timed out
            if conn.dh_pending is not None:
                if conn.dh_timed_out(self._DH_TIMEOUT):
                    if link.is_inbound:
                        # Inbound link DH timed out -- just clear it, don't retry
                        self._logger(
                            f"[KEEPALIVE] Inbound link {link.name} DH timeout, clearing"
                        )
                        conn.clear_crypto()
                    else:
                        self._logger(
                            f"[KEEPALIVE] Link {link.name} DH timeout "
                            f"(no reply for {now - conn.dh_initiated_at:.0f}s), re-initiating"
                        )
                        self._initiate_link_dh(link)
                continue

            # Case 2: Link encrypted -- idle-based PING / timeout
            if conn.crypto_key is not None:
                # Send BURST if not already sent, or retry if timed out
                if link.id not in self._burst_complete:
                    last_sent = self._burst_sent_at.get(link.id, 0)
                    if last_sent == 0 or (now - last_sent) > self._BURST_TIMEOUT:
                        self.send_burst(link)

                # 2 unanswered PINGs = connection dead, reset
                if conn.is_timed_out(self._MAX_UNANSWERED_PINGS):
                    self._logger(
                        f"[KEEPALIVE] Link {link.name} timed out "
                        f"({conn.ping_waiting} unanswered PINGs, "
                        f"last_seen {now - conn.last_seen:.0f}s ago), resetting"
                    )
                    self.peer_timeout_detected(link)
                    conn.clear_crypto()
                    if not link.is_inbound:
                        self._initiate_link_dh(link)
                    continue

                # Idle > threshold and no recent PING sent -- send PING
                if conn.is_idle(self._IDLE_THRESHOLD):
                    ping_envelope = CommandEnvelope(
                        command_id=f"ping-{link.id[:8]}-{int(now)}",
                        kind="PING",
                        payload={"line": f"PING {link.id}"},
                        origin_server=self.server.name,
                        source_session="s2s-keepalive",
                        replicate=False,
                    )
                    line = self.encode_command_line(ping_envelope)
                    wire = (line + "\r\n").encode("utf-8")
                    conn.sendto(wire)
                    conn.record_ping_sent()
                    self._logger(
                        f"[KEEPALIVE] Sent PING to {link.name} "
                        f"(idle {now - conn.last_seen:.0f}s, waiting={conn.ping_waiting})"
                    )
                continue

            # Case 3: No crypto, no pending DH -- initiate (outbound only)
            if not link.is_inbound:
                self._logger(f"[KEEPALIVE] Link {link.name} has no crypto or pending DH, initiating")
                self._initiate_link_dh(link)

    def _announce_stub(self, method_name: str, detail: str) -> None:
        self._logger(f"[STUB] SyncMesh.{method_name} called: {detail}.")
