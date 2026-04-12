from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field

from csc_server.queue.command import CommandEnvelope


@dataclass
class ServerState:
    """In-memory state scaffold for queue-driven server execution."""

    server_name: str
    bind_host: str
    bind_port: int
    executed_commands: list[str] = field(default_factory=list)
    outbound_messages: list[str] = field(default_factory=list)
    outbound_events: list[dict] = field(default_factory=list)
    service_results: list[dict] = field(default_factory=list)
    protocol_events: list[dict] = field(default_factory=list)
    skipped_service_commands: list[dict] = field(default_factory=list)
    session_contexts: dict[str, dict] = field(default_factory=dict)
    sessions: dict[str, dict] = field(default_factory=dict)
    channels: dict[str, dict] = field(default_factory=dict)

    def record_execution(self, envelope: CommandEnvelope) -> None:
        self.executed_commands.append(envelope.command_id)

    def record_outbound(self, line: str) -> None:
        self.outbound_messages.append(line)

    def record_session_outbound(self, session_id: str, line: str) -> None:
        self.outbound_messages.append(line)
        self.outbound_events.append({"session_id": session_id, "line": line})

    def record_service_result(
        self,
        envelope: CommandEnvelope,
        class_name: str,
        method_name: str,
        result: str,
    ) -> None:
        self.service_results.append(
            {
                "command_id": envelope.command_id,
                "class_name": class_name,
                "method_name": method_name,
                "result": result,
            }
        )

    def record_protocol_event(self, envelope: CommandEnvelope, event: str, detail: dict) -> None:
        self.protocol_events.append(
            {
                "command_id": envelope.command_id,
                "event": event,
                "detail": detail,
            }
        )

    def record_skipped_service_command(
        self,
        envelope: CommandEnvelope,
        target: str,
        reason: str,
        detail: dict | None = None,
    ) -> None:
        record = {
            "command_id": envelope.command_id,
            "target": target,
            "reason": reason,
        }
        if detail:
            record["detail"] = detail
        self.skipped_service_commands.append(record)

    def set_session_context(
        self,
        session_id: str,
        *,
        source_nick: str | None = None,
        source_is_oper: bool | None = None,
        channel_ops: set[str] | None = None,
    ) -> dict:
        context = dict(self.session_contexts.get(session_id, {}))
        if source_nick is not None:
            context["source_nick"] = source_nick
        if source_is_oper is not None:
            context["source_is_oper"] = bool(source_is_oper)
        if channel_ops is not None:
            context["channel_ops"] = {str(channel).lower() for channel in channel_ops}
        self.session_contexts[session_id] = context
        return dict(context)

    def get_session_context(self, session_id: str) -> dict:
        context = self.session_contexts.get(session_id, {})
        return {
            "source_nick": context.get("source_nick"),
            "source_is_oper": bool(context.get("source_is_oper", False)),
            "channel_ops": set(context.get("channel_ops", set())),
        }

    def ensure_session(self, session_id: str) -> dict:
        session = self.sessions.get(session_id)
        if session is None:
            session = {
                "state": "new",
                "nick": None,
                "user": None,
                "realname": None,
                "password": None,
                "oper_account": None,
                "oper_flags": "",
                "channels": set(),
                "user_modes": set(),
                "away": None,
                "signon_time": None,
                "last_active": time.time(),
                "last_server": self.server_name,
            }
            self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> dict | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None
        return dict(session)

    def touch_session_activity(
        self,
        session_id: str,
        *,
        when: float | None = None,
        origin_server: str | None = None,
    ) -> dict:
        session = self.ensure_session(session_id)
        session["last_active"] = time.time() if when is None else float(when)
        if origin_server:
            session["last_server"] = str(origin_server)
        return session

    def mark_session_registered(
        self,
        session_id: str,
        *,
        when: float | None = None,
        origin_server: str | None = None,
    ) -> dict:
        session = self.touch_session_activity(session_id, when=when, origin_server=origin_server)
        if session.get("signon_time") is None:
            session["signon_time"] = session["last_active"]
        return session

    def session_channels(self, session_id: str) -> set[str]:
        session = self.sessions.get(session_id)
        if session is None:
            return set()
        return set(session.get("channels", set()))

    def set_away(self, session_id: str, message: str | None) -> None:
        session = self.ensure_session(session_id)
        normalized = str(message).strip() if message is not None else ""
        session["away"] = normalized or None
        if session["away"]:
            session["user_modes"].add("a")
        else:
            session["user_modes"].discard("a")

    def get_away(self, session_id: str) -> str | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None
        return session.get("away")

    def idle_seconds(self, session_id: str, *, now: float | None = None) -> int:
        session = self.sessions.get(session_id)
        if session is None:
            return 0
        last_active = session.get("last_active")
        if last_active is None:
            return 0
        current = time.time() if now is None else float(now)
        return max(0, int(current - float(last_active)))

    def signon_time(self, session_id: str) -> int:
        session = self.sessions.get(session_id)
        if session is None or session.get("signon_time") is None:
            return 0
        return int(float(session["signon_time"]))

    def remove_session(self, session_id: str) -> dict | None:
        self.session_contexts.pop(session_id, None)
        return self.sessions.pop(session_id, None)

    @staticmethod
    def normalize_channel_name(channel_name: str) -> str:
        channel_name = str(channel_name).strip()
        if not channel_name:
            return ""
        if not channel_name.startswith("#"):
            channel_name = f"#{channel_name}"
        return channel_name.lower()

    def ensure_channel(self, channel_name: str) -> dict:
        normalized = self.normalize_channel_name(channel_name)
        channel = self.channels.get(normalized)
        if channel is None:
            channel = {
                "name": normalized,
                "topic": "",
                "topic_author": None,
                "topic_time": None,
                "members": {},
                "modes": set(),
                "mode_params": {},
                "ban_list": set(),
                "invite_list": set(),
            }
            self.channels[normalized] = channel
        return channel

    def get_channel(self, channel_name: str) -> dict | None:
        return self.channels.get(self.normalize_channel_name(channel_name))

    def list_channels(self) -> list[dict]:
        return [self.channels[name] for name in sorted(self.channels)]

    def add_channel_member(self, channel_name: str, session_id: str, nick: str, *, op: bool = False) -> dict:
        channel = self.ensure_channel(channel_name)
        normalized = channel["name"]
        member = channel["members"].get(nick.lower())
        if member is None:
            member = {"nick": nick, "session_id": session_id, "modes": set()}
            channel["members"][nick.lower()] = member
        member["nick"] = nick
        member["session_id"] = session_id
        if op:
            member["modes"].add("o")

        session = self.ensure_session(session_id)
        session["channels"].add(normalized)
        self._refresh_session_channel_ops(session_id)
        return member

    def remove_channel_member(self, channel_name: str, nick: str) -> bool:
        channel = self.get_channel(channel_name)
        if channel is None:
            return False
        removed = channel["members"].pop(str(nick).lower(), None)
        if removed is None:
            return False
        session = self.ensure_session(removed["session_id"])
        session["channels"].discard(channel["name"])
        self._refresh_session_channel_ops(removed["session_id"])
        if not channel["members"]:
            self.channels.pop(channel["name"], None)
        return True

    def remove_session_from_all_channels(self, session_id: str) -> list[str]:
        removed_channels = []
        session = self.sessions.get(session_id)
        if session is None:
            return removed_channels
        for channel_name in list(session.get("channels", set())):
            channel = self.get_channel(channel_name)
            if channel is None:
                continue
            for key, member in list(channel["members"].items()):
                if member.get("session_id") == session_id:
                    channel["members"].pop(key, None)
                    removed_channels.append(channel_name)
            if not channel["members"]:
                self.channels.pop(channel["name"], None)
        session["channels"].clear()
        self._refresh_session_channel_ops(session_id)
        return removed_channels

    def channel_member_sessions(self, channel_name: str) -> list[str]:
        channel = self.get_channel(channel_name)
        if channel is None:
            return []
        return [member["session_id"] for member in channel["members"].values()]

    def channel_members(self, channel_name: str) -> list[dict]:
        channel = self.get_channel(channel_name)
        if channel is None:
            return []
        return list(channel["members"].values())

    def is_channel_member(self, channel_name: str, nick: str) -> bool:
        channel = self.get_channel(channel_name)
        if channel is None:
            return False
        return str(nick).lower() in channel["members"]

    def is_channel_op(self, channel_name: str, nick: str) -> bool:
        channel = self.get_channel(channel_name)
        if channel is None:
            return False
        member = channel["members"].get(str(nick).lower())
        if member is None:
            return False
        return "o" in member.get("modes", set())

    def session_nick(self, session_id: str) -> str | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None
        return session.get("nick")

    def find_session_by_nick(self, nick: str) -> str | None:
        target = str(nick).lower()
        for session_id, session in self.sessions.items():
            if str(session.get("nick") or "").lower() == target:
                return session_id
        return None

    def rename_session_nick(self, session_id: str, old_nick: str, new_nick: str) -> None:
        old_key = str(old_nick).lower()
        new_key = str(new_nick).lower()
        for channel in self.channels.values():
            member = channel["members"].pop(old_key, None)
            if member is None:
                continue
            member["nick"] = new_nick
            channel["members"][new_key] = member
        self._refresh_session_channel_ops(session_id)

    def _refresh_session_channel_ops(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        channel_ops = set()
        nick = session.get("nick")
        if nick:
            for channel_name in session.get("channels", set()):
                if self.is_channel_op(channel_name, nick):
                    channel_ops.add(channel_name)
        self.set_session_context(
            session_id,
            source_nick=nick,
            source_is_oper=bool(session.get("oper_flags")),
            channel_ops=channel_ops,
        )

    # ==================================================================
    # Channel mode helpers
    # ==================================================================

    def set_channel_mode(self, channel_name: str, mode: str, param: str | int | None = None) -> None:
        channel = self.get_channel(channel_name)
        if channel is None:
            return
        channel["modes"].add(mode)
        if param is not None:
            channel["mode_params"][mode] = param

    def unset_channel_mode(self, channel_name: str, mode: str) -> None:
        channel = self.get_channel(channel_name)
        if channel is None:
            return
        channel["modes"].discard(mode)
        channel["mode_params"].pop(mode, None)

    def get_channel_modes(self, channel_name: str) -> tuple[set, dict]:
        channel = self.get_channel(channel_name)
        if channel is None:
            return set(), {}
        return set(channel["modes"]), dict(channel["mode_params"])

    # ==================================================================
    # Channel member mode helpers (op, voice)
    # ==================================================================

    def set_member_mode(self, channel_name: str, nick: str, mode: str) -> bool:
        channel = self.get_channel(channel_name)
        if channel is None:
            return False
        member = channel["members"].get(str(nick).lower())
        if member is None:
            return False
        member["modes"].add(mode)
        if mode == "o":
            self._refresh_session_channel_ops(member["session_id"])
        return True

    def unset_member_mode(self, channel_name: str, nick: str, mode: str) -> bool:
        channel = self.get_channel(channel_name)
        if channel is None:
            return False
        member = channel["members"].get(str(nick).lower())
        if member is None:
            return False
        member["modes"].discard(mode)
        if mode == "o":
            self._refresh_session_channel_ops(member["session_id"])
        return True

    def is_voiced(self, channel_name: str, nick: str) -> bool:
        channel = self.get_channel(channel_name)
        if channel is None:
            return False
        member = channel["members"].get(str(nick).lower())
        if member is None:
            return False
        return "v" in member.get("modes", set())

    # ==================================================================
    # Ban helpers
    # ==================================================================

    _MAX_BANS_PER_CHANNEL = 100

    def add_ban(self, channel_name: str, mask: str) -> bool:
        channel = self.get_channel(channel_name)
        if channel is None:
            return False
        normalized = self.normalize_ban_mask(mask)
        if normalized.lower() in {b.lower() for b in channel["ban_list"]}:
            return False
        if len(channel["ban_list"]) >= self._MAX_BANS_PER_CHANNEL:
            return False
        channel["ban_list"].add(normalized)
        return True

    def remove_ban(self, channel_name: str, mask: str) -> bool:
        channel = self.get_channel(channel_name)
        if channel is None:
            return False
        normalized = self.normalize_ban_mask(mask)
        to_remove = None
        for existing in channel["ban_list"]:
            if existing.lower() == normalized.lower():
                to_remove = existing
                break
        if to_remove is None:
            return False
        channel["ban_list"].discard(to_remove)
        return True

    def get_bans(self, channel_name: str) -> list[str]:
        channel = self.get_channel(channel_name)
        if channel is None:
            return []
        return sorted(channel["ban_list"])

    @staticmethod
    def normalize_ban_mask(mask: str) -> str:
        if "!" not in mask and "@" not in mask:
            return f"{mask}!*@*"
        if "!" not in mask:
            return f"*!{mask}"
        if "@" not in mask:
            return f"{mask}@*"
        return mask

    @staticmethod
    def match_ban_mask(mask: str, nick_user_host: str) -> bool:
        if "!" in mask:
            mask_nick, mask_rest = mask.split("!", 1)
        else:
            mask_nick, mask_rest = "*", mask

        if "!" in nick_user_host:
            actual_nick, actual_rest = nick_user_host.split("!", 1)
        else:
            actual_nick, actual_rest = nick_user_host, "*@*"

        if not fnmatch.fnmatch(actual_nick.lower(), mask_nick.lower()):
            return False

        if "@" in mask_rest and "@" in actual_rest:
            mask_user, mask_host = mask_rest.split("@", 1)
            actual_user, actual_host = actual_rest.split("@", 1)
            if not fnmatch.fnmatch(actual_user, mask_user):
                return False
            if not fnmatch.fnmatch(actual_host.lower(), mask_host.lower()):
                return False
            return True

        return fnmatch.fnmatch(actual_rest, mask_rest)

    def is_banned(self, channel_name: str, nick: str, user: str, host: str) -> bool:
        channel = self.get_channel(channel_name)
        if channel is None:
            return False
        if not channel["ban_list"]:
            return False
        nick_user_host = f"{nick}!{user}@{host}"
        for mask in channel["ban_list"]:
            if self.match_ban_mask(mask, nick_user_host):
                return True
        return False

    # ==================================================================
    # Invite helpers
    # ==================================================================

    def add_invite(self, channel_name: str, nick: str) -> None:
        channel = self.get_channel(channel_name)
        if channel is None:
            return
        channel["invite_list"].add(str(nick).lower())

    def is_invited(self, channel_name: str, nick: str) -> bool:
        channel = self.get_channel(channel_name)
        if channel is None:
            return False
        return str(nick).lower() in channel["invite_list"]

    # ==================================================================
    # Permission helpers
    # ==================================================================

    def can_speak(self, channel_name: str, nick: str) -> bool:
        """Check if nick can speak in channel. Always True unless +m is set,
        in which case only ops and voiced users can speak."""
        channel = self.get_channel(channel_name)
        if channel is None:
            return False
        if "m" not in channel["modes"]:
            return True
        member = channel["members"].get(str(nick).lower())
        if member is None:
            return False
        modes = member.get("modes", set())
        return "o" in modes or "v" in modes

    def can_set_topic(self, channel_name: str, nick: str) -> bool:
        """Check if nick can set topic. Always True unless +t is set,
        in which case only ops can set topic."""
        channel = self.get_channel(channel_name)
        if channel is None:
            return False
        if "t" not in channel["modes"]:
            return True
        return self.is_channel_op(channel_name, nick)

    # ==================================================================
    # User mode helpers
    # ==================================================================

    def set_user_mode(self, session_id: str, mode: str) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        session["user_modes"].add(mode)

    def unset_user_mode(self, session_id: str, mode: str) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        session["user_modes"].discard(mode)

    def get_user_modes(self, session_id: str) -> set:
        session = self.sessions.get(session_id)
        if session is None:
            return set()
        return set(session.get("user_modes", set()))
