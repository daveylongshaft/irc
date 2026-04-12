"""Link: a single peer connection in the SyncMesh.

A Link owns EVERYTHING associated with one side of a server-to-server
connection. That includes:

    - Stable local identity (`id`, a uuid4 minted at construction)
    - Routing identity (`origin_server`, bound when we learn who's on the
      other end -- either from startup config or from the first SYNCLINE)
    - Transport addressing (configured_host/port for bootstrap,
      last_addr for the most recent observed source/destination)
    - Stats (sent/recv msgs and bytes, opened_at, last_seen)
    - State (UP / DOWN / UNKNOWN)
    - Known domain entities living on the far side (users, channels, opers)

Routing identity and addressing are deliberately separated. The id and
origin_server are stable; last_addr is just "where we last saw this
link" and may change across a NAT rebind or a peer hostname change
without affecting routing, stats, or known-entity tracking. Losing a
Link tells you exactly which users and channels desynced: they are the
ones this Link object was tracking. No parallel dicts, no tuple keys.
"""
from __future__ import annotations

import socket
import time
import uuid
from typing import Iterable


LINK_STATE_UNKNOWN = "UNKNOWN"
LINK_STATE_UP = "UP"
LINK_STATE_DOWN = "DOWN"


class Link:
    """A single peer link in the mesh."""

    __slots__ = (
        "id",
        "name",
        "origin_server",
        "configured_host",
        "configured_port",
        "last_addr",
        "resolved_ips",
        "state",
        "opened_at",
        "last_seen",
        "sent_msgs",
        "sent_bytes",
        "recv_msgs",
        "recv_bytes",
        "users",
        "channels",
        "opers",
        "crypto_key",
        "dh_pending",
    )

    def __init__(
        self,
        host: str,
        port: int,
        *,
        origin_server: str | None = None,
        name: str | None = None,
        resolve: bool = True,
    ):
        # Stable local identity. This is what the rest of the system
        # uses to refer to this Link. It never changes across the
        # lifetime of the object and is never derived from an address.
        self.id: str = uuid.uuid4().hex
        # Human-readable label for logs / STATS L rows. Defaults to
        # origin_server (once bound) or "host:port" (pre-binding).
        self.name: str = name or origin_server or f"{host}:{port}"
        # Routing identity: the server name on the far side. If None,
        # we have not yet bound this Link to a peer (bootstrap state).
        self.origin_server: str | None = origin_server
        self.configured_host: str = host
        self.configured_port: int = int(port)
        # Most recently observed source/destination address. Updated on
        # every recv. Used as the sendto destination so a peer that
        # rebinds to a new source port keeps working.
        self.last_addr: tuple[str, int] | None = None
        # Soft validation only. Not used for routing.
        self.resolved_ips: set[str] = set()
        self.state: str = LINK_STATE_UNKNOWN
        self.opened_at: float = time.time()
        self.last_seen: float = 0.0
        self.sent_msgs: int = 0
        self.sent_bytes: int = 0
        self.recv_msgs: int = 0
        self.recv_bytes: int = 0
        # Domain entities known via this link.
        self.users: dict[str, dict] = {}
        self.channels: dict[str, dict] = {}
        self.opers: set[str] = set()
        # Encryption state for this link
        self.crypto_key: bytes | None = None
        self.dh_pending: "DHExchange | None" = None
        if resolve:
            self.resolve()

    # ------------------------------------------------------------------
    # Identity binding
    # ------------------------------------------------------------------

    def bind_origin(self, origin_server: str) -> None:
        """Bind this Link to a specific peer identity.

        Called once, when we learn which server is on the far side
        (either from startup config or from the first SYNCLINE we
        receive that matches this Link's configured address).
        """
        if self.origin_server is not None and self.origin_server != origin_server:
            raise ValueError(
                f"Link {self.id} already bound to origin_server="
                f"{self.origin_server!r}, refusing rebind to {origin_server!r}"
            )
        self.origin_server = origin_server
        if self.name == f"{self.configured_host}:{self.configured_port}":
            self.name = origin_server

    # ------------------------------------------------------------------
    # Address resolution + soft matching (NOT used for routing)
    # ------------------------------------------------------------------

    def resolve(self) -> set[str]:
        """Resolve configured_host to a set of IPs for soft validation."""
        ips: set[str] = set()
        try:
            infos = socket.getaddrinfo(
                self.configured_host,
                self.configured_port,
                proto=socket.IPPROTO_UDP,
            )
            for info in infos:
                sockaddr = info[4]
                if sockaddr:
                    ips.add(sockaddr[0])
        except (socket.gaierror, OSError):
            pass
        ips.add(self.configured_host)
        self.resolved_ips = ips
        return ips

    def configured_addr_matches(self, addr: tuple[str, int] | None) -> bool:
        """Soft check: is `addr` consistent with our configured endpoint?

        Used ONLY during bootstrap binding (first-packet matching of an
        unbound Link) and for optional integrity logging. Never a
        routing primitive post-bind.
        """
        if addr is None:
            return False
        host, port = addr[0], int(addr[1])
        if port != self.configured_port:
            return False
        if host == self.configured_host:
            return True
        return host in self.resolved_ips

    # ------------------------------------------------------------------
    # Transport: send / recv accounting
    # ------------------------------------------------------------------

    def send_address(self) -> tuple[str, int]:
        """Where to send outbound datagrams.

        Prefers the most recently observed address (handles NAT rebind,
        peer reconfig) and falls back to the configured bootstrap
        endpoint if we have not yet received anything from this link.
        """
        if self.last_addr is not None:
            return self.last_addr
        return (self.configured_host, self.configured_port)

    def sendto(self, sock_send_fn, wire: bytes) -> None:
        """Send a wire payload to this link and update sent stats.

        sock_send_fn is the caller-provided send callable, typically
        `server.sock_send`. We don't hold a socket reference directly
        so Link stays decoupled from the server's transport layer.
        """
        sock_send_fn(wire, self.send_address())
        self.sent_msgs += 1
        self.sent_bytes += len(wire)
        if self.state == LINK_STATE_UNKNOWN:
            self.state = LINK_STATE_UP

    def record_recv(self, nbytes: int, addr: tuple[str, int] | None = None) -> None:
        """Record receipt of nbytes from this link.

        If addr is given, it becomes the new last_addr. This is how we
        learn about NAT rebinds and peer reconfigurations: the
        identity (origin_server, id) stays; the address updates.
        """
        self.recv_msgs += 1
        self.recv_bytes += nbytes
        self.last_seen = time.time()
        self.state = LINK_STATE_UP
        if addr is not None:
            self.last_addr = addr

    # ------------------------------------------------------------------
    # Known-entity bookkeeping
    # ------------------------------------------------------------------

    def add_user(self, nick: str, **attrs) -> None:
        self.users[nick] = attrs

    def del_user(self, nick: str) -> bool:
        return self.users.pop(nick, None) is not None

    def has_user(self, nick: str) -> bool:
        return nick in self.users

    def user_list(self) -> list[str]:
        return list(self.users.keys())

    def add_channel(self, name: str, **attrs) -> None:
        self.channels[name] = attrs

    def del_channel(self, name: str) -> bool:
        return self.channels.pop(name, None) is not None

    def has_channel(self, name: str) -> bool:
        return name in self.channels

    def channel_list(self) -> list[str]:
        return list(self.channels.keys())

    def add_oper(self, nick: str) -> None:
        self.opers.add(nick)

    def del_oper(self, nick: str) -> bool:
        was_present = nick in self.opers
        self.opers.discard(nick)
        return was_present

    # ------------------------------------------------------------------
    # Serialization / introspection
    # ------------------------------------------------------------------

    def stats_dict(self) -> dict:
        """The per-link stats row used by STATS L / link_stats()."""
        now = time.time()
        last_addr_str = (
            f"{self.last_addr[0]}:{self.last_addr[1]}" if self.last_addr else ""
        )
        return {
            "id": self.id,
            "linkname": self.name,
            "origin_server": self.origin_server or "",
            "host": self.configured_host,
            "port": self.configured_port,
            "last_addr": last_addr_str,
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
            "users_known": len(self.users),
            "channels_known": len(self.channels),
            "opers_known": len(self.opers),
        }

    def to_dict(self) -> dict:
        """Full dict representation (config + state + known entities)."""
        d = self.stats_dict()
        d["resolved_ips"] = sorted(self.resolved_ips)
        d["users"] = list(self.users.keys())
        d["channels"] = list(self.channels.keys())
        d["opers"] = sorted(self.opers)
        return d

    @classmethod
    def from_peer_tuple(
        cls,
        peer: tuple,
        *,
        name: str | None = None,
    ) -> "Link":
        """Build a Link from a peer config tuple.

        Accepts either (host, port) or (origin_server, host, port). The
        3-element form binds origin_server at construction so the Link
        is immediately routable by identity and needs no bootstrap
        first-packet binding. The 2-element form leaves origin_server
        unbound; the first SYNCLINE received whose source address
        matches this Link's configured endpoint will bind it.
        """
        if len(peer) == 3:
            origin_server, host, port = peer
            return cls(host, int(port), origin_server=origin_server, name=name or origin_server)
        if len(peer) == 2:
            host, port = peer
            return cls(host, int(port), name=name)
        raise ValueError(f"Unsupported peer tuple shape: {peer!r}")

    def __repr__(self) -> str:
        return (
            f"Link(id={self.id[:8]} name={self.name!r} origin={self.origin_server!r} "
            f"addr={self.configured_host}:{self.configured_port} "
            f"last_addr={self.last_addr} state={self.state} "
            f"sent={self.sent_msgs}/{self.sent_bytes}B "
            f"recv={self.recv_msgs}/{self.recv_bytes}B users={len(self.users)} "
            f"chans={len(self.channels)} opers={len(self.opers)})"
        )


def aggregate_user_lists(local_users: Iterable[str], links: Iterable["Link"]) -> set[str]:
    """Build a complete user list by unioning local and all links' user lists."""
    full = set(local_users)
    for link in links:
        full.update(link.user_list())
    return full


def aggregate_channel_lists(local_channels: Iterable[str], links: Iterable["Link"]) -> set[str]:
    full = set(local_channels)
    for link in links:
        full.update(link.channel_list())
    return full
