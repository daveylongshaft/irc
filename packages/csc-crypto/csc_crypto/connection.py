"""Connection: transport + crypto state for a single network peer.

A Connection owns everything about the transport layer of a peer
relationship: addressing, encryption, key exchange, and send/recv
accounting.  Both User (client) and Link (server-to-server) compose
a Connection as ``self.connection``.

Integration with the CSC chain is through ``self.server`` -- the
running Server instance passed at construction.  This gives
Connection access to log(), sock_send(), s2s_sock_send(), platform
methods, etc.

Callers never handle encryption manually.  ``sendto()`` auto-prepends
the 16-byte key_hash header and AES-GCM-encrypts when a crypto_key is
set.  Callers always pass plaintext.

The ``owner`` slot is a back-reference to the User or Link that owns
this Connection.  After a key_hash lookup in the server's
``_connections_by_key_hash`` index, ``conn.owner`` tells the ingress
dispatcher whether to route to mesh (Link) or IRC dispatch (User).

Crypto state is delegated to a composed CryptoState object at
``self.crypto``.  Connection adds server integration on top: key_hash
registry, logging, transport send.  The compat properties crypto_key,
key_hash, dh_pending, dh_initiated_at expose CryptoState internals
for existing code that reads them.
"""
from __future__ import annotations

import socket
import time
import uuid

from csc_crypto.crypto import DHExchange
from csc_crypto.crypto_state import CryptoState


CONN_STATE_UNKNOWN = "UNKNOWN"
CONN_STATE_UP = "UP"
CONN_STATE_DOWN = "DOWN"

# Default idle threshold before sending a keepalive PING
CONN_IDLE_THRESHOLD = 60.0
# Number of unanswered PINGs before timeout
CONN_MAX_UNANSWERED_PINGS = 2


class Connection:
    """Transport + crypto state for a single network peer."""

    __slots__ = (
        "server",
        "owner",
        "id",
        "host",
        "port",
        "last_addr",
        "resolved_ips",
        "crypto",
        "last_ping_sent",
        "ping_waiting",
        "state",
        "opened_at",
        "last_seen",
        "sent_msgs",
        "sent_bytes",
        "recv_msgs",
        "recv_bytes",
    )

    def __init__(self, server, host: str, port: int, addr: tuple | None = None):
        self.server = server
        self.owner = None
        self.id: str = uuid.uuid4().hex
        self.host: str = host
        self.port: int = int(port)
        self.last_addr: tuple[str, int] | None = addr
        self.resolved_ips: set[str] = set()
        self.crypto: CryptoState = CryptoState()
        self.last_ping_sent: float = 0.0
        self.ping_waiting: int = 0
        self.state: str = CONN_STATE_UNKNOWN
        self.opened_at: float = time.time()
        self.last_seen: float = 0.0
        self.sent_msgs: int = 0
        self.sent_bytes: int = 0
        self.recv_msgs: int = 0
        self.recv_bytes: int = 0

    # ------------------------------------------------------------------
    # Compat properties -- delegate to self.crypto for existing readers
    # ------------------------------------------------------------------

    @property
    def crypto_key(self) -> bytes | None:
        return self.crypto.aes_key

    @property
    def key_hash(self) -> bytes | None:
        return self.crypto.key_hash

    @property
    def dh_pending(self) -> DHExchange | None:
        return self.crypto._dh

    @property
    def dh_initiated_at(self) -> float:
        return self.crypto.dh_initiated_at

    # ------------------------------------------------------------------
    # Address resolution + soft matching
    # ------------------------------------------------------------------

    def send_address(self) -> tuple[str, int]:
        """Where to send outbound data.

        Prefers last observed address (handles NAT rebind). Falls back
        to configured (host, port) for initial handshake before any
        recv has occurred.
        """
        if self.last_addr is not None:
            return self.last_addr
        return (self.host, self.port)

    def resolve(self) -> set[str]:
        """Resolve host to a set of IPs for soft validation."""
        ips: set[str] = set()
        try:
            infos = socket.getaddrinfo(
                self.host, self.port, proto=socket.IPPROTO_UDP,
            )
            for info in infos:
                sockaddr = info[4]
                if sockaddr:
                    ips.add(sockaddr[0])
        except (socket.gaierror, OSError):
            pass
        ips.add(self.host)
        self.resolved_ips = ips
        return ips

    def addr_matches(self, addr: tuple[str, int] | None) -> bool:
        """Soft check: is addr consistent with our configured endpoint?

        Used only during bootstrap binding. Never a routing primitive.
        """
        if addr is None:
            return False
        host, port = addr[0], int(addr[1])
        if port != self.port:
            return False
        if host == self.host:
            return True
        return host in self.resolved_ips

    def update_addr(self, new_addr: tuple[str, int]) -> None:
        """Update last_addr on recv. Logs changes and reindexes User session."""
        if new_addr != self.last_addr:
            old = self.last_addr
            old_session_id = None
            if old is not None:
                old_session_id = f"{old[0]}:{old[1]}"
            self.last_addr = new_addr
            if old is not None:
                self.server.log(
                    f"[CONN] {self.host} addr changed "
                    f"{old[0]}:{old[1]} -> {new_addr[0]}:{new_addr[1]}"
                )
            # Reindex User session when source address changes (F2 fix)
            if old_session_id is not None and self.owner is not None:
                reindex = getattr(self.server, "reindex_user_session", None)
                if reindex is not None:
                    reindex(self.owner, old_session_id)

    # ------------------------------------------------------------------
    # Transport: send / recv
    # ------------------------------------------------------------------

    def sendto(self, data: bytes) -> None:
        """Send data to this connection's peer.

        Auto-encrypts if crypto is ready: prepends 16-byte key_hash
        header + AES-256-GCM ciphertext.  Callers always pass plaintext.

        Port determines which socket: S2S_PORT -> s2s_sock_send, else
        sock_send (from Network layer).
        """
        addr = self.send_address()
        wire = data
        if self.crypto.is_ready:
            wire = self.crypto.wrap(data)
        if self.port == getattr(self.server, "S2S_PORT", 0):
            self.server.s2s_sock_send(wire, addr)
        else:
            self.server.sock_send(wire, addr)
        self.sent_msgs += 1
        self.sent_bytes += len(wire)
        if self.state == CONN_STATE_UNKNOWN:
            self.state = CONN_STATE_UP

    def record_recv(self, nbytes: int, addr: tuple[str, int] | None = None) -> None:
        """Record receipt of nbytes. Updates last_seen, addr, stats, resets ping_waiting."""
        self.recv_msgs += 1
        self.recv_bytes += nbytes
        self.last_seen = time.time()
        self.ping_waiting = 0
        self.state = CONN_STATE_UP
        if addr is not None:
            self.update_addr(addr)

    # ------------------------------------------------------------------
    # Crypto: key management + DH (delegates to self.crypto)
    # ------------------------------------------------------------------

    def set_crypto_key(self, key: bytes) -> None:
        """Set AES key, compute key_hash, register with server."""
        old_hash = self.crypto.key_hash
        if old_hash is not None:
            self.server.unregister_connection_key(self)
        self.crypto.set_key(key)
        self.last_seen = time.time()
        self.server.register_connection_key(self)
        self.server.log(
            f"[CONN] Crypto key set for {self.host} "
            f"hash={self.crypto.key_hash[:4].hex()}..."
        )

    def clear_crypto(self) -> None:
        """Unregister key_hash, clear all crypto state."""
        if self.crypto.key_hash is not None:
            self.server.unregister_connection_key(self)
            self.server.log(
                f"[CONN] Crypto cleared for {self.host} "
                f"hash={self.crypto.key_hash[:4].hex()}..."
            )
        self.crypto.clear()

    def matches_key_hash(self, hash_bytes: bytes) -> bool:
        """Does this connection own the given key_hash?"""
        return self.crypto.matches_key_hash(hash_bytes)

    def start_dh(self) -> DHExchange:
        """Create a new DH exchange and store as pending."""
        return self.crypto.start_dh()

    def complete_dh(self, other_public: int) -> bytes:
        """Finish DH exchange: compute shared key, set crypto, return key."""
        key = self.crypto.complete_dh(other_public)
        self.last_seen = time.time()
        self.server.register_connection_key(self)
        self.server.log(
            f"[CONN] Crypto key set for {self.host} "
            f"hash={self.crypto.key_hash[:4].hex()}..."
        )
        return key

    # ------------------------------------------------------------------
    # Liveness / keepalive
    # ------------------------------------------------------------------

    def is_idle(self, threshold: float = CONN_IDLE_THRESHOLD) -> bool:
        """True if no traffic (recv or ping sent) for threshold seconds.

        Only returns True when the connection has been seen at least once
        AND both last_seen and last_ping_sent are older than threshold.
        This means: after we send a PING, is_idle won't fire again until
        another threshold seconds pass without any recv.
        """
        if self.last_seen == 0.0:
            return False
        now = time.time()
        if (now - self.last_seen) <= threshold:
            return False
        if self.last_ping_sent > 0 and (now - self.last_ping_sent) <= threshold:
            return False
        return True

    def is_timed_out(self, max_unanswered: int = CONN_MAX_UNANSWERED_PINGS) -> bool:
        """True if we've sent max_unanswered PINGs with no PONG."""
        return self.ping_waiting >= max_unanswered

    def dh_timed_out(self, timeout_secs: float = 10.0) -> bool:
        """True if DH is pending and has exceeded timeout."""
        return self.crypto.dh_timed_out(timeout_secs)

    def record_ping_sent(self) -> None:
        """Record that we sent a PING. Increments unanswered counter."""
        self.last_ping_sent = time.time()
        self.ping_waiting += 1

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def stats_dict(self) -> dict:
        """Transport + crypto stats snapshot."""
        now = time.time()
        addr_str = ""
        if self.last_addr:
            addr_str = f"{self.last_addr[0]}:{self.last_addr[1]}"
        return {
            "conn_id": self.id,
            "host": self.host,
            "port": self.port,
            "last_addr": addr_str,
            "state": self.state,
            "sent_msgs": self.sent_msgs,
            "sent_bytes": self.sent_bytes,
            "sent_kb": self.sent_bytes // 1024,
            "recv_msgs": self.recv_msgs,
            "recv_bytes": self.recv_bytes,
            "recv_kb": self.recv_bytes // 1024,
            "opened_at": self.opened_at,
            "time_open": int(now - self.opened_at),
            "last_seen": self.last_seen,
            "has_crypto": self.crypto.is_ready,
            "key_hash": self.crypto.key_hash[:4].hex() if self.crypto.key_hash else "",
            "dh_pending": self.crypto.is_pending,
            "dh_initiated_at": self.crypto.dh_initiated_at,
            "last_ping_sent": self.last_ping_sent,
            "ping_waiting": self.ping_waiting,
        }

    def to_dict(self) -> dict:
        """Full state dict."""
        d = self.stats_dict()
        d["resolved_ips"] = sorted(self.resolved_ips)
        return d

    def __repr__(self) -> str:
        addr = f"{self.last_addr[0]}:{self.last_addr[1]}" if self.last_addr else "none"
        return (
            f"Connection(id={self.id[:8]} host={self.host} port={self.port} "
            f"last_addr={addr} state={self.state} "
            f"crypto={'yes' if self.crypto.is_ready else 'no'} "
            f"sent={self.sent_msgs}/{self.sent_bytes}B "
            f"recv={self.recv_msgs}/{self.recv_bytes}B)"
        )
