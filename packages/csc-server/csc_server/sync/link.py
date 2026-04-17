"""Link: a single peer connection in the SyncMesh.

A Link owns EVERYTHING associated with one side of a server-to-server
connection. That includes:

    - Stable local identity (id, a uuid4 minted at construction)
    - Routing identity (origin_server, bound when we learn who's on the
      other end -- either from startup config or from the first SYNCLINE)
    - Transport + crypto (delegated to self.connection, a Connection object)
    - Stats (delegated to self.connection)
    - Known domain entities living on the far side (users, channels, opers)
    - Cert state for signature-based handshake (Link-only, not on Connection)

Transport and crypto are owned by Connection. Link owns domain-specific
identity, entity tracking, and cert-based authentication.
"""
from __future__ import annotations

import time
import uuid
from typing import Iterable

from csc_crypto.connection import Connection
from csc_server.channel import Channel


class Link:
    """A single peer link in the mesh."""

    __slots__ = (
        "id",
        "name",
        "origin_server",
        "connection",
        "users",
        "channels",
        "opers",
        "servers_behind",
        "nicks_behind",
        "is_inbound",
        "ftpd_role",
        "cert_fingerprint",
        "peer_cert_fingerprint",
        "cert_distributed",
    )

    def __init__(
        self,
        server,
        host: str,
        port: int,
        *,
        origin_server: str | None = None,
        name: str | None = None,
        resolve: bool = True,
    ):
        self.id: str = uuid.uuid4().hex
        self.name: str = name or origin_server or f"{host}:{port}"
        self.origin_server: str | None = origin_server
        self.connection: Connection = Connection(server, host, port)
        self.connection.owner = self
        self.users: dict[str, dict] = {}
        self.channels: dict[str, Channel] = {}
        self.opers: set[str] = set()
        self.servers_behind: list[str] = []
        self.nicks_behind: set[str] = set()
        self.is_inbound: bool = False
        self.ftpd_role: str | None = None
        self.cert_fingerprint: str | None = None
        self.peer_cert_fingerprint: str | None = None
        self.cert_distributed: bool = False
        if resolve:
            self.connection.resolve()

    # ------------------------------------------------------------------
    # Identity binding
    # ------------------------------------------------------------------

    def bind_origin(self, origin_server: str) -> None:
        """Bind this Link to a specific peer identity."""
        if self.origin_server is not None and self.origin_server != origin_server:
            raise ValueError(
                f"Link {self.id} already bound to origin_server="
                f"{self.origin_server!r}, refusing rebind to {origin_server!r}"
            )
        self.origin_server = origin_server
        if self.name == f"{self.connection.host}:{self.connection.port}":
            self.name = origin_server

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

    def get_channel(self, name: str) -> Channel:
        """Get or create channel."""
        if name not in self.channels:
            self.channels[name] = Channel(name=name)
        return self.channels[name]

    def add_channel(self, name: str, channel: Channel | None = None) -> Channel:
        """Add or replace channel."""
        if channel is None:
            channel = Channel(name=name)
        self.channels[name] = channel
        return channel

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

    def set_servers_behind(self, servers: list[str]) -> None:
        """Set servers reachable through this link."""
        self.servers_behind = servers

    def set_nicks_behind(self, nicks: set[str]) -> None:
        """Set nicks reachable through this link."""
        self.nicks_behind = nicks

    def add_nick_behind(self, nick: str) -> None:
        """Add nick to reachable set."""
        self.nicks_behind.add(nick)

    def remove_nick_behind(self, nick: str) -> bool:
        """Remove nick from reachable set."""
        return bool(self.nicks_behind.discard(nick))

    def has_nick_behind(self, nick: str) -> bool:
        """Check if nick is reachable through this link."""
        return nick in self.nicks_behind

    def clear_remote_state(self) -> tuple[list[str], list[str]]:
        """Remove all known entities from this link.

        Returns (removed_nicks, removed_channels) for cleanup notification.
        """
        removed_nicks = list(self.users.keys()) + sorted(self.nicks_behind)
        removed_channels = list(self.channels.keys())
        self.users.clear()
        self.channels.clear()
        self.opers.clear()
        self.nicks_behind.clear()
        self.servers_behind.clear()
        return removed_nicks, removed_channels

    def rename_nick(self, old_nick: str, new_nick: str) -> None:
        """Rename a nick across users, nicks_behind, opers, and all channels."""
        # users dict
        if old_nick in self.users:
            self.users[new_nick] = self.users.pop(old_nick)
        # nicks_behind
        if old_nick in self.nicks_behind:
            self.nicks_behind.discard(old_nick)
            self.nicks_behind.add(new_nick)
        # opers
        if old_nick in self.opers:
            self.opers.discard(old_nick)
            self.opers.add(new_nick)
        # channel user lists
        for channel in self.channels.values():
            if channel.has_user(old_nick):
                modes = channel.get_user_modes(old_nick)
                channel.remove_user(old_nick)
                channel.add_user(new_nick, modes=modes)

    def serialize_for_burst(self) -> dict:
        """Serialize link state for BURST transmission."""
        return {
            "servers_behind": self.servers_behind,
            "nicks_behind": sorted(self.nicks_behind),
            "channels": {
                name: channel.to_dict()
                for name, channel in self.channels.items()
            }
        }

    def apply_burst(self, burst_data: dict) -> None:
        """Apply BURST data from peer."""
        self.set_servers_behind(burst_data.get("servers_behind", []))
        self.set_nicks_behind(set(burst_data.get("nicks_behind", [])))
        for channel_data in burst_data.get("channels", {}).values():
            channel = Channel.from_dict(channel_data)
            self.channels[channel.name] = channel

    # ------------------------------------------------------------------
    # Serialization / introspection
    # ------------------------------------------------------------------

    def stats_dict(self) -> dict:
        """Per-link stats row used by STATS L / link_stats()."""
        d = self.connection.stats_dict()
        d["id"] = self.id
        d["linkname"] = self.name
        d["origin_server"] = self.origin_server or ""
        d["users_known"] = len(self.users)
        d["channels_known"] = len(self.channels)
        d["opers_known"] = len(self.opers)
        return d

    def to_dict(self) -> dict:
        """Full dict representation (config + state + known entities)."""
        d = self.stats_dict()
        d["resolved_ips"] = sorted(self.connection.resolved_ips)
        d["users"] = list(self.users.keys())
        d["channels"] = list(self.channels.keys())
        d["opers"] = sorted(self.opers)
        d["cert_distributed"] = self.cert_distributed
        return d

    @classmethod
    def from_peer_tuple(
        cls,
        server,
        peer: tuple,
        *,
        name: str | None = None,
    ) -> "Link":
        """Build a Link from a peer config tuple.

        Accepts either (host, port) or (origin_server, host, port).
        """
        if len(peer) == 3:
            origin_server, host, port = peer
            return cls(server, host, int(port), origin_server=origin_server, name=name or origin_server)
        if len(peer) == 2:
            host, port = peer
            return cls(server, host, int(port), name=name)
        raise ValueError(f"Unsupported peer tuple shape: {peer!r}")

    def __repr__(self) -> str:
        return (
            f"Link(id={self.id[:8]} name={self.name!r} origin={self.origin_server!r} "
            f"conn={self.connection!r} "
            f"users={len(self.users)} chans={len(self.channels)} opers={len(self.opers)})"
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
