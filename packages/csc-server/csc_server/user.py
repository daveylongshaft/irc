"""User: a single client connection to the server.

A User owns EVERYTHING about one client session:

    - Stable local identity (id, uuid4)
    - Transport + crypto (delegated to self.connection, a Connection object)
    - IRC identity (nick, username, realname)
    - IRC state (channels, user_modes, away, oper)
    - Session lifecycle (state: new -> registered -> disconnected)

Chain access is through self.connection.server -- User does not hold a
direct server reference.  This keeps the ownership clear: Connection is
the integration point with the CSC chain.

For remote users (arriving via S2S link), is_remote=True and link_id
identifies which Link the user arrived through.

session_id (property) returns the same "ip:port" string that ServerState
and Dispatcher/Ingress expect, bridging User objects to existing code.
"""
from __future__ import annotations

import time
import uuid

from csc_crypto.connection import Connection


class User:
    """A single client connection to the server."""

    __slots__ = (
        "id",
        "connection",
        "nick",
        "username",
        "realname",
        "password",
        "state",
        "channels",
        "user_modes",
        "away",
        "oper_account",
        "oper_flags",
        "signon_time",
        "last_active",
        "last_server",
        "is_remote",
        "link_id",
    )

    def __init__(
        self,
        server,
        host: str,
        port: int,
        addr: tuple[str, int] | None = None,
    ):
        self.id: str = uuid.uuid4().hex
        self.connection: Connection = Connection(server, host, port, addr=addr)
        self.connection.owner = self
        self.nick: str | None = None
        self.username: str | None = None
        self.realname: str | None = None
        self.password: str | None = None
        self.state: str = "new"
        self.channels: set[str] = set()
        self.user_modes: set[str] = set()
        self.away: str | None = None
        self.oper_account: str | None = None
        self.oper_flags: str = ""
        self.signon_time: float | None = None
        self.last_active: float = time.time()
        self.last_server: str = server.name
        self.is_remote: bool = False
        self.link_id: str | None = None

    # ------------------------------------------------------------------
    # Session identity
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        """Return ip:port string matching ServerState/Dispatcher convention."""
        if self.connection.last_addr:
            return f"{self.connection.last_addr[0]}:{self.connection.last_addr[1]}"
        return f"{self.connection.host}:{self.connection.port}"

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def mark_registered(self) -> None:
        """Transition from 'new' to 'registered'."""
        self.state = "registered"
        now = time.time()
        if self.signon_time is None:
            self.signon_time = now
        self.last_active = now

    def set_user_info(self, username: str, realname: str) -> None:
        self.username = username
        self.realname = realname

    # ------------------------------------------------------------------
    # Nick management
    # ------------------------------------------------------------------

    def rename(self, new_nick: str) -> str | None:
        """Update nick. Returns old nick or None if first set."""
        old = self.nick
        self.nick = new_nick
        return old

    # ------------------------------------------------------------------
    # Channel tracking
    # ------------------------------------------------------------------

    def join_channel(self, name: str) -> None:
        self.channels.add(name.lower())

    def part_channel(self, name: str) -> None:
        self.channels.discard(name.lower())

    def channel_list(self) -> list[str]:
        return sorted(self.channels)

    # ------------------------------------------------------------------
    # User modes
    # ------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        self.user_modes.add(mode)

    def unset_mode(self, mode: str) -> None:
        self.user_modes.discard(mode)

    def has_mode(self, mode: str) -> bool:
        return mode in self.user_modes

    # ------------------------------------------------------------------
    # Oper
    # ------------------------------------------------------------------

    def set_oper(self, account: str, flags: str) -> None:
        self.oper_account = account
        self.oper_flags = flags

    def clear_oper(self) -> None:
        self.oper_account = None
        self.oper_flags = ""

    @property
    def is_oper(self) -> bool:
        return bool(self.oper_flags)

    # ------------------------------------------------------------------
    # Away
    # ------------------------------------------------------------------

    def set_away(self, message: str) -> None:
        self.away = message.strip() or None
        if self.away:
            self.user_modes.add("a")
        else:
            self.user_modes.discard("a")

    def clear_away(self) -> None:
        self.away = None
        self.user_modes.discard("a")

    # ------------------------------------------------------------------
    # Activity tracking
    # ------------------------------------------------------------------

    def touch_activity(self, origin_server: str | None = None) -> None:
        self.last_active = time.time()
        if origin_server:
            self.last_server = origin_server

    def idle_seconds(self) -> int:
        return max(0, int(time.time() - self.last_active))

    # ------------------------------------------------------------------
    # Transport delegation
    # ------------------------------------------------------------------

    def send(self, data: bytes) -> None:
        """Send data to this user. Connection handles encryption."""
        self.connection.sendto(data)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def stats_dict(self) -> dict:
        """User stats snapshot."""
        d = self.connection.stats_dict()
        d["user_id"] = self.id
        d["nick"] = self.nick or ""
        d["username"] = self.username or ""
        d["state"] = self.state
        d["channels"] = len(self.channels)
        d["is_oper"] = self.is_oper
        d["away"] = self.away is not None
        d["idle"] = self.idle_seconds()
        d["is_remote"] = self.is_remote
        return d

    def to_dict(self) -> dict:
        """Full state dict."""
        d = self.stats_dict()
        d["realname"] = self.realname or ""
        d["user_modes"] = sorted(self.user_modes)
        d["channel_list"] = self.channel_list()
        d["oper_account"] = self.oper_account or ""
        d["last_server"] = self.last_server
        d["link_id"] = self.link_id or ""
        return d

    def __repr__(self) -> str:
        return (
            f"User(id={self.id[:8]} nick={self.nick!r} "
            f"state={self.state} session={self.session_id} "
            f"remote={self.is_remote} "
            f"chans={len(self.channels)} conn={self.connection!r})"
        )
