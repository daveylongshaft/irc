from __future__ import annotations

import fnmatch
import os
import re
import sys
import time
from typing import Callable

from csc_services import Service, format_irc_message, numeric_reply, parse_irc_message

from csc_server.queue.command import CommandEnvelope
from csc_server.queue.store import CommandStore
from csc_server.state.server_state import ServerState

RPL_WELCOME = "001"
RPL_YOURHOST = "002"
RPL_CREATED = "003"
RPL_MYINFO = "004"
RPL_ISUPPORT = "005"
RPL_NOTOPIC = "331"
RPL_TOPIC = "332"
RPL_NAMREPLY = "353"
RPL_ENDOFNAMES = "366"
RPL_LIST = "322"
RPL_LISTEND = "323"
RPL_UMODEIS = "221"
RPL_CHANNELMODEIS = "324"
RPL_TOPICWHOTIME = "333"
RPL_WHOREPLY = "352"
RPL_ENDOFWHO = "315"
RPL_WHOISUSER = "311"
RPL_WHOISSERVER = "312"
RPL_WHOISOPERATOR = "313"
RPL_WHOISIDLE = "317"
RPL_ENDOFWHOIS = "318"
RPL_WHOISCHANNELS = "319"
RPL_AWAY = "301"
RPL_UNAWAY = "305"
RPL_NOWAWAY = "306"
RPL_BANLIST = "367"
RPL_ENDOFBANLIST = "368"
RPL_MOTD = "372"
RPL_MOTDSTART = "375"
RPL_ENDOFMOTD = "376"
RPL_YOUREOPER = "381"
RPL_STATSLINKINFO = "211"
RPL_STATSCOMMANDS = "212"
RPL_STATSCLINE = "213"
RPL_STATSNLINE = "214"
RPL_STATSILINE = "215"
RPL_STATSKLINE = "216"
RPL_STATSYLINE = "218"
RPL_ENDOFSTATS = "219"
RPL_STATSUPTIME = "242"
RPL_STATSOLINE = "243"
RPL_STATSHLINE = "244"
RPL_LUSERCLIENT = "251"
RPL_LUSEROP = "252"
RPL_LUSERUNKNOWN = "253"
RPL_LUSERCHANNELS = "254"
RPL_LUSERME = "255"
RPL_ADMINME = "256"
RPL_ADMINLOC1 = "257"
RPL_ADMINLOC2 = "258"
RPL_ADMINEMAIL = "259"
RPL_USERHOST = "302"
RPL_ISON = "303"
RPL_INVITING = "341"
RPL_VERSION = "351"
RPL_LINKS = "364"
RPL_ENDOFLINKS = "365"
RPL_INFO = "371"
RPL_ENDOFINFO = "374"
RPL_TIME = "391"

ERR_NOSUCHNICK = "401"
ERR_NOSUCHSERVER = "402"
ERR_NOSUCHCHANNEL = "403"
ERR_CANNOTSENDTOCHAN = "404"
ERR_NEEDMOREPARAMS = "461"
ERR_ALREADYREGISTRED = "462"
ERR_NONICKNAMEGIVEN = "431"
ERR_ERRONEUSNICKNAME = "432"
ERR_NICKNAMEINUSE = "433"
ERR_NOTREGISTERED = "451"
ERR_NOTONCHANNEL = "442"
ERR_USERNOTINCHANNEL = "441"
ERR_USERONCHANNEL = "443"
ERR_PASSWDMISMATCH = "464"
ERR_CHANNELISFULL = "471"
ERR_INVITEONLYCHAN = "473"
ERR_BANNEDFROMCHAN = "474"
ERR_BADCHANNELKEY = "475"
ERR_NOPRIVILEGES = "481"
ERR_CHANOPRIVSNEEDED = "482"
ERR_UMODEUNKNOWNFLAG = "501"
ERR_USERSDONTMATCH = "502"

NICK_RE = re.compile(r"^[A-Za-z\[\]\\`_^{|}][A-Za-z0-9\[\]\\`_^{|}\-]*$")


class CommandDispatcher:
    """Executes queued commands against local server state."""

    def __init__(
        self,
        server,
        state: ServerState,
        logger: Callable[[str], None],
        store: CommandStore | None = None,
    ):
        self.server = server
        self.state = state
        self._logger = logger
        self._store = store
        self._file_buffers: dict[str, dict] = {}  # session_id -> {"name": str, "lines": list, "target": str}
        # STATS accounting
        self._started_at: float = time.time()
        self._command_counts: dict[str, dict[str, int]] = {}  # kind -> {"count": int, "bytes": int}

    def dispatch(self, envelope: CommandEnvelope) -> None:
        self._logger(
            f"[EXEC] apply kind={envelope.kind} id={envelope.command_id} "
            f"payload={envelope.payload}"
        )
        self.state.touch_session_activity(
            envelope.source_session,
            origin_server=envelope.origin_server or self.server.name,
        )
        # Cross-server channel broadcast (server-generated lines relayed via sync_mesh).
        if envelope.kind == "BROADCAST":
            channel = str(envelope.payload.get("channel", ""))
            line = str(envelope.payload.get("line", ""))
            if channel and line:
                self._broadcast_to_channel(channel, line, exclude_session=None)
            self.state.record_execution(envelope)
            if self._store is not None:
                self._store.record_executed(envelope)
            return
        # If session has active file buffer, intercept raw lines
        if envelope.source_session in self._file_buffers:
            line = str(envelope.payload.get("line", ""))
            if '<end file>' in line:
                buf = self._file_buffers.pop(envelope.source_session)
                module_name = buf["name"]
                content = '\n'.join(buf["lines"]) + '\n'
                channel_name = buf["channel"]
                self._logger(f"[FILE] Upload complete: {module_name} ({len(buf['lines'])} lines)")
                try:
                    self._install_uploaded_module(module_name, content)
                    confirm = f":{self.server.name} NOTICE {channel_name} :{module_name} validated and activated"
                    self.state.record_session_outbound(envelope.source_session, confirm)
                    self._logger(f"[FILE] Module {module_name} validated and activated")
                except Exception as e:
                    err = f":{self.server.name} NOTICE {channel_name} :Upload failed for {module_name}: {e}"
                    self.state.record_session_outbound(envelope.source_session, err)
                    self._logger(f"[FILE] Module {module_name} install failed: {e}")
            else:
                # Strip PRIVMSG wrapper if present, otherwise use raw line
                text = line
                parsed_msg = parse_irc_message(line)
                if parsed_msg.command == "PRIVMSG":
                    text = parsed_msg.trailing or (parsed_msg.params[-1] if parsed_msg.params else line)
                self._file_buffers[envelope.source_session]["lines"].append(text)
            self.state.record_execution(envelope)
            if self._store is not None:
                self._store.record_executed(envelope)
            return
        self._dispatch_irc(envelope)
        self.state.record_execution(envelope)
        if self._store is not None:
            self._store.record_executed(envelope)

    def _dispatch_irc(self, envelope: CommandEnvelope) -> None:
        line = str(envelope.payload.get("line", ""))
        message = parse_irc_message(line)
        self._debug(f"[DEBUG] parsed line id={envelope.command_id} command={message.command} params={message.params}")
        # STATS m accounting: count every parsed IRC command by kind.
        kind = message.command or "UNKNOWN"
        bucket = self._command_counts.setdefault(kind, {"count": 0, "bytes": 0, "remote_count": 0})
        bucket["count"] += 1
        bucket["bytes"] += len(line.encode("utf-8", errors="replace"))
        if envelope.origin_server and envelope.origin_server != self.server.name:
            bucket["remote_count"] += 1

        if message.command == "PASS":
            self._handle_pass(message, envelope)
            return

        if message.command == "NICK":
            self._handle_nick(message, envelope)
            return

        if message.command == "USER":
            self._handle_user(message, envelope)
            return

        if message.command == "OPER":
            self._handle_oper(message, envelope)
            return

        if message.command == "QUIT":
            self._handle_quit(message, envelope)
            return

        if message.command == "JOIN":
            self._handle_join(message, envelope)
            return

        if message.command == "PART":
            self._handle_part(message, envelope)
            return

        if message.command == "NAMES":
            self._handle_names(message, envelope)
            return

        if message.command == "LIST":
            self._handle_list(envelope)
            return

        if message.command == "PING":
            token = message.trailing or (message.params[0] if message.params else "")
            pong = format_irc_message(self.server.name, "PONG", trailing=token)
            self.state.record_session_outbound(envelope.source_session, pong)
            self.state.record_protocol_event(
                envelope,
                "ping",
                {"token": token, "response": pong},
            )
            self._logger(f"[EXEC] responded to PING id={envelope.command_id} token={token}")
            return

        if message.command == "PRIVMSG":
            self._handle_privmsg(message, envelope)
            return

        if message.command == "NOTICE":
            self._handle_notice(message, envelope)
            return

        if message.command == "WHO":
            self._handle_who(message, envelope)
            return

        if message.command == "WHOIS":
            self._handle_whois(message, envelope)
            return

        if message.command == "MOTD":
            self._handle_motd(envelope)
            return

        if message.command == "STATS":
            self._handle_stats(message, envelope)
            return

        if message.command == "AWAY":
            self._handle_away(message, envelope)
            return

        if message.command == "MODE":
            self._handle_mode(message, envelope)
            return

        if message.command == "TOPIC":
            self._handle_topic(message, envelope)
            return

        if message.command == "KICK":
            self._handle_kick(message, envelope)
            return

        if message.command == "INVITE":
            self._handle_invite(message, envelope)
            return

        # ----- Info / query commands (loud stubs) -----
        if message.command == "LUSERS":
            self._handle_lusers(message, envelope)
            return

        if message.command == "VERSION":
            self._handle_version(message, envelope)
            return

        if message.command == "TIME":
            self._handle_time(message, envelope)
            return

        if message.command == "ADMIN":
            self._handle_admin(message, envelope)
            return

        if message.command == "INFO":
            self._handle_info(message, envelope)
            return

        if message.command == "LINKS":
            self._handle_links(message, envelope)
            return

        if message.command == "USERHOST":
            self._handle_userhost(message, envelope)
            return

        if message.command == "ISON":
            self._handle_ison(message, envelope)
            return

        # ----- Oper / server-to-server commands (loud stubs, oper-gated) -----
        if message.command == "KILL":
            self._handle_kill(message, envelope)
            return

        if message.command == "SQUIT":
            self._handle_squit(message, envelope)
            return

        if message.command == "WALLOPS":
            self._handle_wallops(message, envelope)
            return

        if message.command == "CONNECT":
            self._handle_connect(message, envelope)
            return

        if message.command == "REHASH":
            self._handle_rehash(message, envelope)
            return

        if message.command == "RESTART":
            self._handle_restart(message, envelope)
            return

        if message.command == "DIE":
            self._handle_die(message, envelope)
            return

        self.state.record_protocol_event(
            envelope,
            "unhandled",
            {"command": message.command, "line": line},
        )

    def _handle_privmsg(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if len(message.params) < 2:
            self._send_numeric(envelope, ERR_NEEDMOREPARAMS, nick, "PRIVMSG :Not enough parameters")
            return

        target_name = str(message.params[0]).strip()
        text = message.trailing or (message.params[-1] if message.params else "")
        if target_name.startswith("#"):
            channel_name = self.state.normalize_channel_name(target_name)
            if not self.state.get_channel(channel_name):
                self._send_numeric(envelope, ERR_NOSUCHCHANNEL, nick, f"{channel_name} :No such channel")
                return
            if not self.state.is_channel_member(channel_name, nick):
                self._send_numeric(envelope, ERR_CANNOTSENDTOCHAN, nick, f"{channel_name} :Cannot send to channel")
                return
            if not self.state.can_speak(channel_name, nick):
                self._send_numeric(envelope, ERR_CANNOTSENDTOCHAN, nick, f"{channel_name} :Cannot send to channel (+m)")
                return

            # Always broadcast the PRIVMSG to channel first -- it's a
            # chat message regardless of whether it's also a service
            # command.  S2S sync already happened at ingress time;
            # this is the local channel echo.
            out = format_irc_message(self._user_host(nick, envelope), "PRIVMSG", [channel_name], text)
            self._broadcast_to_channel(channel_name, out, exclude_session=envelope.source_session)

            # File upload handling: <begin file=name> ... <end file>
            if self._handle_file_upload(envelope, channel_name, nick, text):
                return

            parsed = Service.parse_service_command(text)
            if parsed is None:
                self._debug(f"[DEBUG] non-service PRIVMSG id={envelope.command_id} text={text!r}")
                self.state.record_protocol_event(
                    envelope,
                    "privmsg",
                    {"text": text, "service_command": False, "channel": channel_name},
                )
                return

            local_targets = {
                str(self.server.name).lower(),
            }
            target = str(parsed["target"] or self.server.name).lower()
            if target not in local_targets:
                self._debug(
                    f"[DEBUG] skip id={envelope.command_id} target={parsed['target']} "
                    f"local_targets={sorted(local_targets)} reason=target_mismatch"
                )
                self.state.record_protocol_event(
                    envelope,
                    "privmsg",
                    {
                        "text": text,
                        "service_command": True,
                        "executed": False,
                        "target": parsed["target"],
                    },
                )
                return

            authorized, auth_detail = self._is_authorized_service_command(message, envelope)
            if not authorized:
                self._debug(
                    f"[DEBUG] skip id={envelope.command_id} target={parsed['target']} "
                    f"reason=not_authorized auth={auth_detail}"
                )
                self.state.record_skipped_service_command(
                    envelope,
                    parsed["target"],
                    "not_authorized",
                    auth_detail,
                )
                self.state.record_protocol_event(
                    envelope,
                    "privmsg",
                    {
                        "text": text,
                        "service_command": True,
                        "executed": False,
                        "target": parsed["target"],
                        "authorization": auth_detail,
                    },
                )
                return

            self._debug(
                f"[DEBUG] execute id={envelope.command_id} target={parsed['target']} "
                f"class={parsed['class_name']} method={parsed['method']} args={parsed['args']} "
                f"auth={auth_detail}"
            )
            result = self.server.handle_command(
                parsed["class_name"],
                parsed["method"],
                list(parsed["args"]),
                parsed["target"],
                envelope.origin_server,
            )
            self.state.record_service_result(
                envelope,
                parsed["class_name"],
                parsed["method"],
                result,
            )
            self._logger(
                f"[EXEC] service result id={envelope.command_id} "
                f"{parsed['class_name']}.{parsed['method']} -> {result}"
            )
            sname = self.server.name
            token = parsed.get("token", "")
            reply_text = f"{token} {result}" if token else str(result)
            out = format_irc_message(f"{sname}!service@{sname}", "PRIVMSG", [channel_name], reply_text)
            self._broadcast_channel_line(channel_name, out)
            self.state.record_protocol_event(
                envelope,
                "privmsg",
                {
                    "text": text,
                    "service_command": True,
                    "executed": True,
                    "target": parsed["target"],
                    "authorization": auth_detail,
                    "channel": channel_name,
                },
            )
            return

        target_session = self.state.find_session_by_nick(target_name)
        if target_session is None:
            # Try to route to remote nick via link
            for link in self.server.iter_links():
                if link.has_nick_behind(target_name):
                    # Relay to peer
                    from csc_server.queue.command import CommandEnvelope as CmdEnv
                    relay_envelope = CmdEnv(
                        kind="PRIVMSG",
                        payload={"line": f"PRIVMSG {target_name} :{text}", "source_nick": nick},
                        origin_server=self.server.name,
                        source_session=envelope.source_session,
                        replicate=True,
                    )
                    self.server.sync_mesh.sync_command(relay_envelope)
                    self.state.record_protocol_event(
                        envelope,
                        "privmsg",
                        {"text": text, "service_command": False, "target_nick": target_name, "remote": True},
                    )
                    return

            self._send_numeric(envelope, ERR_NOSUCHNICK, nick, f"{target_name} :No such nick/channel")
            return
        out = format_irc_message(self._user_host(nick, envelope), "PRIVMSG", [target_name], text)
        self.state.record_session_outbound(target_session, out)
        self.state.record_protocol_event(
            envelope,
            "privmsg",
            {"text": text, "service_command": False, "target_nick": target_name},
        )

    def _handle_notice(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if len(message.params) < 2:
            return

        target_name = str(message.params[0]).strip()
        text = message.trailing or (message.params[-1] if message.params else "")
        if target_name.startswith("#"):
            channel_name = self.state.normalize_channel_name(target_name)
            if not self.state.is_channel_member(channel_name, nick):
                return
            if not self.state.can_speak(channel_name, nick):
                return
            out = format_irc_message(self._user_host(nick, envelope), "NOTICE", [channel_name], text)
            self._broadcast_to_channel(channel_name, out, exclude_session=envelope.source_session)
            self.state.record_protocol_event(
                envelope,
                "notice",
                {"text": text, "channel": channel_name},
            )
            return

        target_session = self.state.find_session_by_nick(target_name)
        if target_session is None:
            # Try to route to remote nick via link
            for link in self.server.iter_links():
                if link.has_nick_behind(target_name):
                    from csc_server.queue.command import CommandEnvelope as CmdEnv
                    relay_envelope = CmdEnv(
                        kind="NOTICE",
                        payload={"line": f"NOTICE {target_name} :{text}", "source_nick": nick},
                        origin_server=self.server.name,
                        source_session=envelope.source_session,
                        replicate=True,
                    )
                    self.server.sync_mesh.sync_command(relay_envelope)
                    self.state.record_protocol_event(
                        envelope,
                        "notice",
                        {"text": text, "target_nick": target_name, "remote": True},
                    )
                    return
            return
        out = format_irc_message(self._user_host(nick, envelope), "NOTICE", [target_name], text)
        self.state.record_session_outbound(target_session, out)
        self.state.record_protocol_event(
            envelope,
            "notice",
            {"text": text, "target_nick": target_name},
        )

    # ==================================================================
    # WHO / WHOIS / MOTD / AWAY
    # ==================================================================

    def _handle_who(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if not message.params:
            self.state.record_session_outbound(
                envelope.source_session,
                f":{self.server.name} {RPL_ENDOFWHO} {nick} * :End of /WHO list",
            )
            return

        target = str(message.params[0]).strip()
        if target.startswith("#"):
            self._handle_who_channel(envelope, nick, target)
            return
        self._handle_who_mask(envelope, nick, target)

    def _handle_who_channel(self, envelope: CommandEnvelope, nick: str, channel_name: str) -> None:
        normalized = self.state.normalize_channel_name(channel_name)
        channel = self.state.get_channel(normalized)
        requester_session = self.state.ensure_session(envelope.source_session)
        requester_is_oper = bool(requester_session.get("oper_flags"))
        requester_is_member = self.state.is_channel_member(normalized, nick)

        # Channel must exist locally or on a link
        has_remote = any(lk.has_channel(normalized) for lk in self.server.iter_links())
        if channel is None and not has_remote:
            self._send_numeric(envelope, ERR_NOSUCHCHANNEL, nick, f"{normalized} :No such channel")
            return
        if channel is not None and {"p", "s"} & set(channel.get("modes", set())) \
                and not requester_is_member and not requester_is_oper:
            self._send_numeric(envelope, ERR_NOSUCHCHANNEL, nick, f"{normalized} :No such channel")
            return

        # Local members
        if channel is not None:
            for member in channel["members"].values():
                member_session = self.state.get_session(member["session_id"]) or {}
                member_modes = self.state.get_user_modes(member["session_id"])
                if "i" in member_modes and not requester_is_member and not requester_is_oper:
                    continue
                flags = self._who_flags(member["session_id"], member, member_session)
                user = member_session.get("user") or member["nick"]
                host = member_session.get("last_server") or self.server.name
                realname = member_session.get("realname") or member["nick"]
                self.state.record_session_outbound(
                    envelope.source_session,
                    f":{self.server.name} {RPL_WHOREPLY} {nick} {normalized} {user} "
                    f"{host} {host} {member['nick']} {flags} :0 {realname}",
                )

        # Remote members from all links
        for link in self.server.iter_links():
            if not link.has_channel(normalized):
                continue
            remote_chan = link.channels[normalized]
            remote_server = link.origin_server or link.name
            for remote_nick in remote_chan.get_all_users():
                modes = remote_chan.get_user_modes(remote_nick)
                flags = "H"
                if "@" in modes:
                    flags += "@"
                elif "+" in modes:
                    flags += "+"
                self.state.record_session_outbound(
                    envelope.source_session,
                    f":{self.server.name} {RPL_WHOREPLY} {nick} {normalized} {remote_nick} "
                    f"{remote_server} {remote_server} {remote_nick} {flags} :1 {remote_nick}",
                )

        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_ENDOFWHO} {nick} {normalized} :End of /WHO list",
        )

    def _handle_who_mask(self, envelope: CommandEnvelope, nick: str, mask: str) -> None:
        requester_session = self.state.ensure_session(envelope.source_session)
        requester_is_oper = bool(requester_session.get("oper_flags"))
        requester_channels = self.state.session_channels(envelope.source_session)
        lowered_mask = mask.lower()

        # Local users
        for session_id, session in self.state.sessions.items():
            target_nick = str(session.get("nick") or "")
            if not target_nick or not fnmatch.fnmatch(target_nick.lower(), lowered_mask):
                continue
            target_channels = self.state.session_channels(session_id)
            if "i" in self.state.get_user_modes(session_id):
                shared = requester_channels & target_channels
                if not requester_is_oper and not shared and target_nick.lower() != nick.lower():
                    continue
            flags = self._who_flags(session_id, None, session)
            user = session.get("user") or target_nick
            host = session.get("last_server") or self.server.name
            realname = session.get("realname") or target_nick
            self.state.record_session_outbound(
                envelope.source_session,
                f":{self.server.name} {RPL_WHOREPLY} {nick} * {user} "
                f"{host} {host} {target_nick} {flags} :0 {realname}",
            )

        # Remote users from all links
        seen_remote = set()
        for link in self.server.iter_links():
            remote_server = link.origin_server or link.name
            for remote_nick in link.user_list():
                if remote_nick.lower() in seen_remote:
                    continue
                if not fnmatch.fnmatch(remote_nick.lower(), lowered_mask):
                    continue
                seen_remote.add(remote_nick.lower())
                self.state.record_session_outbound(
                    envelope.source_session,
                    f":{self.server.name} {RPL_WHOREPLY} {nick} * {remote_nick} "
                    f"{remote_server} {remote_server} {remote_nick} H :1 {remote_nick}",
                )
            for remote_nick in link.nicks_behind:
                if remote_nick.lower() in seen_remote:
                    continue
                if not fnmatch.fnmatch(remote_nick.lower(), lowered_mask):
                    continue
                seen_remote.add(remote_nick.lower())
                self.state.record_session_outbound(
                    envelope.source_session,
                    f":{self.server.name} {RPL_WHOREPLY} {nick} * {remote_nick} "
                    f"{remote_server} {remote_server} {remote_nick} H :1 {remote_nick}",
                )

        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_ENDOFWHO} {nick} {mask} :End of /WHO list",
        )

    def _handle_whois(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if not message.params:
            self._send_numeric(envelope, ERR_NONICKNAMEGIVEN, nick, "No nickname given")
            return

        target_nick = str(message.params[-1]).strip()
        target_session_id = self.state.find_session_by_nick(target_nick)

        # Check remote links if not found locally
        if target_session_id is None:
            remote_link = None
            for link in self.server.iter_links():
                if link.has_user(target_nick) or link.has_nick_behind(target_nick):
                    remote_link = link
                    break
            if remote_link is None:
                self._send_numeric(envelope, ERR_NOSUCHNICK, nick, f"{target_nick} :No such nick/channel")
                return
            # Build WHOIS reply from link state
            remote_server = remote_link.origin_server or remote_link.name
            self.state.record_session_outbound(
                envelope.source_session,
                f":{self.server.name} {RPL_WHOISUSER} {nick} {target_nick} {target_nick} {remote_server} * :{target_nick}",
            )
            self.state.record_session_outbound(
                envelope.source_session,
                f":{self.server.name} {RPL_WHOISSERVER} {nick} {target_nick} {remote_server} :CSC IRC Server",
            )
            # Show channels the remote user is in
            remote_channels = []
            for chan_name, channel in remote_link.channels.items():
                if channel.has_user(target_nick):
                    modes = channel.get_user_modes(target_nick)
                    prefix = ""
                    if "@" in modes:
                        prefix = "@"
                    elif "+" in modes:
                        prefix = "+"
                    remote_channels.append(f"{prefix}{chan_name}")
            if remote_channels:
                self.state.record_session_outbound(
                    envelope.source_session,
                    f":{self.server.name} {RPL_WHOISCHANNELS} {nick} {target_nick} :{' '.join(remote_channels)}",
                )
            # Check if remote oper
            if target_nick in remote_link.opers:
                self.state.record_session_outbound(
                    envelope.source_session,
                    f":{self.server.name} {RPL_WHOISOPERATOR} {nick} {target_nick} :is an IRC operator",
                )
            self.state.record_session_outbound(
                envelope.source_session,
                f":{self.server.name} {RPL_ENDOFWHOIS} {nick} {target_nick} :End of /WHOIS list",
            )
            self.state.record_protocol_event(envelope, "whois", {"target": target_nick, "remote": True})
            return

        target_session = self.state.ensure_session(target_session_id)
        actual_nick = target_session.get("nick") or target_nick
        user = target_session.get("user") or actual_nick
        host = target_session.get("last_server") or self.server.name
        realname = target_session.get("realname") or actual_nick

        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_WHOISUSER} {nick} {actual_nick} {user} {host} * :{realname}",
        )
        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_WHOISSERVER} {nick} {actual_nick} {host} :CSC IRC Server",
        )

        away_message = self.state.get_away(target_session_id)
        if away_message:
            self.state.record_session_outbound(
                envelope.source_session,
                f":{self.server.name} {RPL_AWAY} {nick} {actual_nick} :{away_message}",
            )

        if target_session.get("oper_flags"):
            self.state.record_session_outbound(
                envelope.source_session,
                f":{self.server.name} {RPL_WHOISOPERATOR} {nick} {actual_nick} :is an IRC operator",
            )

        visible_channels = self._visible_whois_channels(
            envelope.source_session,
            nick,
            target_session_id,
            actual_nick,
        )
        if visible_channels:
            self.state.record_session_outbound(
                envelope.source_session,
                f":{self.server.name} {RPL_WHOISCHANNELS} {nick} {actual_nick} :{' '.join(visible_channels)}",
            )

        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_WHOISIDLE} {nick} {actual_nick} "
            f"{self.state.idle_seconds(target_session_id)} {self.state.signon_time(target_session_id)} "
            f":seconds idle, signon time",
        )
        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_ENDOFWHOIS} {nick} {actual_nick} :End of /WHOIS list",
        )

        self.state.record_protocol_event(
            envelope,
            "whois",
            {"target": actual_nick},
        )

    def _visible_whois_channels(
        self,
        requester_session_id: str,
        requester_nick: str,
        target_session_id: str,
        target_nick: str,
    ) -> list[str]:
        requester = self.state.ensure_session(requester_session_id)
        requester_is_oper = bool(requester.get("oper_flags"))
        visible = []
        for channel_name in sorted(self.state.session_channels(target_session_id)):
            channel = self.state.get_channel(channel_name)
            if channel is None:
                continue
            if {"s", "p"} & set(channel.get("modes", set())):
                if not requester_is_oper and not self.state.is_channel_member(channel_name, requester_nick):
                    continue
            prefix = ""
            member = channel["members"].get(target_nick.lower())
            if member is not None:
                if "o" in member.get("modes", set()):
                    prefix = "@"
                elif "v" in member.get("modes", set()):
                    prefix = "+"
            visible.append(f"{prefix}{channel_name}")
        return visible

    def _handle_motd(self, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        self._send_motd(envelope, nick)
        self.state.record_protocol_event(
            envelope,
            "motd",
            {"sent": True},
        )

    def _handle_stats(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        query = ""
        if message.params:
            query = str(message.params[0]).strip()
        letter = query[:1].lower() if query else ""

        if letter == "l":
            self._handle_stats_l(envelope, nick)
        elif letter == "u":
            self._handle_stats_u(envelope, nick)
        elif letter == "m":
            self._handle_stats_m(envelope, nick)
        elif letter == "o":
            self._handle_stats_o(envelope, nick)
        elif letter in ("y", "i", "k", "c", "h"):
            # Known letters we haven't implemented yet.
            self.log_stubbed_call(
                "CommandDispatcher", f"_handle_stats_{letter}",
                letter=letter,
            )
        else:
            # Unknown or empty letter: still terminate with end-of-stats so clients don't hang.
            pass

        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_ENDOFSTATS} {nick} {letter or '*'} :End of /STATS report",
        )
        self.state.record_protocol_event(
            envelope,
            "stats",
            {"letter": letter},
        )

    def _handle_stats_l(self, envelope: CommandEnvelope, nick: str) -> None:
        """STATS L: list server link info (one 211 numeric per S2S peer).

        Numeric 211 format (RFC 1459/2812):
          <linkname> <sendq> <sent_msgs> <sent_kb> <recv_msgs> <recv_kb> <time_open>
        """
        sync_mesh = getattr(self.server, "sync_mesh", None)
        if sync_mesh is None or not hasattr(sync_mesh, "link_stats"):
            return
        for link in sync_mesh.link_stats():
            self.state.record_session_outbound(
                envelope.source_session,
                f":{self.server.name} {RPL_STATSLINKINFO} {nick} "
                f"{link['linkname']} 0 "
                f"{link['sent_msgs']} {link['sent_kb']} "
                f"{link['recv_msgs']} {link['recv_kb']} "
                f"{link['time_open']}",
            )

    def _handle_stats_u(self, envelope: CommandEnvelope, nick: str) -> None:
        """STATS U: server uptime (RPL_STATSUPTIME 242).

        Format: ":Server Up <days> days <HH:MM:SS>"
        """
        elapsed = int(time.time() - self._started_at)
        days, rem = divmod(elapsed, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_STATSUPTIME} {nick} "
            f":Server Up {days} days {hours:02d}:{minutes:02d}:{seconds:02d}",
        )

    def _handle_stats_m(self, envelope: CommandEnvelope, nick: str) -> None:
        """STATS M: per-command counters (RPL_STATSCOMMANDS 212).

        Format: <command> <count> <bytes> <remote_count>
        """
        for cmd in sorted(self._command_counts.keys()):
            bucket = self._command_counts[cmd]
            self.state.record_session_outbound(
                envelope.source_session,
                f":{self.server.name} {RPL_STATSCOMMANDS} {nick} "
                f"{cmd} {bucket['count']} {bucket['bytes']} {bucket['remote_count']}",
            )

    def _handle_stats_o(self, envelope: CommandEnvelope, nick: str) -> None:
        """STATS O: configured oper host patterns (RPL_STATSOLINE 243).

        Pulls from server.get_data('opers') if available, otherwise stubs.
        Format: O <hostmask> * <name>
        """
        get_data = getattr(self.server, "get_data", None)
        opers = None
        if callable(get_data):
            try:
                opers = get_data("opers") or {}
            except Exception:
                opers = None
        if not opers:
            self.log_stubbed_call("CommandDispatcher", "_handle_stats_o",
                                  reason="no oper data available")
            return
        # opers.json shape: {name: {"password_hash": ..., "hosts": [...]}, ...}
        for oper_name, entry in sorted(opers.items()):
            hosts = entry.get("hosts") if isinstance(entry, dict) else None
            if not hosts:
                hosts = ["*@*"]
            for host in hosts:
                self.state.record_session_outbound(
                    envelope.source_session,
                    f":{self.server.name} {RPL_STATSOLINE} {nick} "
                    f"O {host} * {oper_name}",
                )

    def _send_motd(self, envelope: CommandEnvelope, nick: str) -> None:
        motd = None
        get_data = getattr(self.server, "get_data", None)
        if callable(get_data):
            motd = get_data("motd")
        motd = motd or "Welcome to csc-server!"
        self._send_numeric(envelope, RPL_MOTDSTART, nick, f"- {self.server.name} Message of the Day -")
        for line in str(motd).splitlines():
            self._send_numeric(envelope, RPL_MOTD, nick, f"- {line}")
        self._send_numeric(envelope, RPL_ENDOFMOTD, nick, "End of /MOTD command")

    def _handle_away(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        away_message = message.trailing
        if away_message is None and message.params:
            away_message = str(message.params[0])
        away_message = str(away_message or "").strip()
        self.state.set_away(envelope.source_session, away_message or None)
        if away_message:
            self._send_numeric(envelope, RPL_NOWAWAY, nick, "You have been marked as being away")
        else:
            self._send_numeric(envelope, RPL_UNAWAY, nick, "You are no longer marked as being away")
        self.state.record_protocol_event(
            envelope,
            "away",
            {"enabled": bool(away_message)},
        )

    def _who_flags(self, session_id: str, member: dict | None, session: dict) -> str:
        flags = "G" if self.state.get_away(session_id) else "H"
        if session.get("oper_flags"):
            flags += "*"
        member_modes = set((member or {}).get("modes", set()))
        if "o" in member_modes:
            flags += "@"
        elif "v" in member_modes:
            flags += "+"
        return flags

    # ==================================================================
    # MODE
    # ==================================================================

    _NICK_MODES = frozenset(("o", "v"))
    _FLAG_MODES = frozenset(("m", "t", "n", "i", "s", "p", "Q"))
    _PARAM_MODES = frozenset(("k", "l"))
    _LIST_MODES = frozenset(("b",))

    def _handle_mode(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if not message.params:
            self._send_numeric(envelope, ERR_NEEDMOREPARAMS, nick, "MODE :Not enough parameters")
            return

        target = message.params[0]
        if target.startswith("#"):
            self._handle_channel_mode(message, envelope, nick, target)
        else:
            self._handle_user_mode(message, envelope, nick, target)

    def _handle_user_mode(self, message, envelope: CommandEnvelope, nick: str, target_nick: str) -> None:
        session = self.state.ensure_session(envelope.source_session)
        is_oper = bool(session.get("oper_flags"))

        if target_nick.lower() != nick.lower() and not is_oper:
            self._send_numeric(envelope, ERR_USERSDONTMATCH, nick, "Cannot change mode for other users")
            return

        # Find the target session
        target_session_id = self.state.find_session_by_nick(target_nick)
        if target_session_id is None:
            self._send_numeric(envelope, ERR_NOSUCHNICK, nick, f"{target_nick} :No such nick/channel")
            return

        # Query mode (no mode string)
        if len(message.params) < 2:
            user_modes = self.state.get_user_modes(target_session_id)
            mode_str = "+" + "".join(sorted(user_modes)) if user_modes else "+"
            self._send_numeric(envelope, RPL_UMODEIS, nick, mode_str)
            return

        # Parse and apply mode changes
        mode_str = message.params[1]
        adding = True

        valid_modes = {"i", "w", "s", "o"}
        for char in mode_str:
            if char == "+":
                adding = True
            elif char == "-":
                adding = False
            elif char in valid_modes:
                if char == "o":
                    # +o cannot be self-granted, only removed (or granted by oper to others)
                    if adding and not is_oper:
                        continue
                    if not adding:
                        self.state.unset_user_mode(target_session_id, "o")
                elif adding:
                    self.state.set_user_mode(target_session_id, char)
                else:
                    self.state.unset_user_mode(target_session_id, char)
            else:
                self._send_numeric(envelope, ERR_UMODEUNKNOWNFLAG, nick, f"Unknown MODE flag: {char}")
                return

        user_modes = self.state.get_user_modes(target_session_id)
        mode_str = "+" + "".join(sorted(user_modes)) if user_modes else "+"
        self._send_numeric(envelope, RPL_UMODEIS, nick, mode_str)

    def _handle_channel_mode(self, message, envelope: CommandEnvelope, nick: str, chan_name: str) -> None:
        normalized = self.state.normalize_channel_name(chan_name)
        channel = self.state.get_channel(normalized)
        if channel is None:
            # Channel might exist only on a link
            has_remote = any(lk.has_channel(normalized) for lk in self.server.iter_links())
            if not has_remote:
                self._send_numeric(envelope, ERR_NOSUCHCHANNEL, nick, f"{chan_name} :No such channel")
                return
            # For remote-only channels, create a local placeholder so mode logic works
            channel = self.state.ensure_channel(normalized)

        # Query mode (no mode string)
        if len(message.params) < 2:
            modes, params = self.state.get_channel_modes(normalized)
            # Also check link channel modes if local is empty
            if not modes:
                for link in self.server.iter_links():
                    if link.has_channel(normalized):
                        link_modes = link.channels[normalized].modes
                        if link_modes:
                            modes = set(link_modes)
                            break
            mode_str = "+" + "".join(sorted(modes)) if modes else "+"
            param_parts = []
            for m in sorted(modes):
                if m in params:
                    param_parts.append(str(params[m]))
            if param_parts:
                mode_str += " " + " ".join(param_parts)
            self._send_numeric(envelope, RPL_CHANNELMODEIS, nick, f"{normalized} {mode_str}")
            return

        mode_str = message.params[1]

        # Special case: MODE #chan +b (list bans, no op required)
        if mode_str in ("+b", "b") and len(message.params) <= 2:
            self._send_ban_list(envelope, nick, normalized)
            return

        # Require chanop or oper for mode changes (skip for remote-origin commands
        # since the originating server already authorized the change)
        is_remote = envelope.origin_server and envelope.origin_server != self.server.name
        session = self.state.ensure_session(envelope.source_session)
        is_oper = bool(session.get("oper_flags"))
        if not is_remote and not is_oper and not self.state.is_channel_op(normalized, nick):
            self._send_numeric(envelope, ERR_CHANOPRIVSNEEDED, nick, f"{normalized} :You're not channel operator")
            return

        # Parse mode string into (direction, char) tuples
        changes = []
        direction = "+"
        for ch in mode_str:
            if ch in ("+", "-"):
                direction = ch
            elif ch in self._NICK_MODES or ch in self._FLAG_MODES or ch in self._PARAM_MODES or ch in self._LIST_MODES:
                changes.append((direction, ch))
        if len(changes) > 8:
            changes = changes[:8]

        param_index = 2  # params[0]=channel, [1]=modestring, [2..]=params

        applied_modes = ""
        applied_params = []
        last_dir = None

        for dir_char, mode_char in changes:
            if mode_char in self._LIST_MODES:
                # Ban list mode
                if dir_char == "+":
                    if param_index >= len(message.params):
                        self._send_ban_list(envelope, nick, normalized)
                        continue
                    ban_mask = message.params[param_index]
                    param_index += 1
                    if self.state.add_ban(normalized, ban_mask):
                        if dir_char != last_dir:
                            applied_modes += dir_char
                            last_dir = dir_char
                        applied_modes += mode_char
                        applied_params.append(self.state.normalize_ban_mask(ban_mask))
                else:
                    if param_index >= len(message.params):
                        continue
                    ban_mask = message.params[param_index]
                    param_index += 1
                    if self.state.remove_ban(normalized, ban_mask):
                        if dir_char != last_dir:
                            applied_modes += dir_char
                            last_dir = dir_char
                        applied_modes += mode_char
                        applied_params.append(self.state.normalize_ban_mask(ban_mask))

            elif mode_char in self._NICK_MODES:
                if param_index >= len(message.params):
                    self._send_numeric(envelope, ERR_NEEDMOREPARAMS, nick,
                                       f"MODE :Not enough parameters for {dir_char}{mode_char}")
                    continue
                target_nick = message.params[param_index]
                param_index += 1

                if not self.state.is_channel_member(normalized, target_nick):
                    self._send_numeric(envelope, ERR_USERNOTINCHANNEL, nick,
                                       f"{target_nick} {normalized} :They aren't on that channel")
                    continue

                if dir_char == "+":
                    self.state.set_member_mode(normalized, target_nick, mode_char)
                else:
                    self.state.unset_member_mode(normalized, target_nick, mode_char)

                if dir_char != last_dir:
                    applied_modes += dir_char
                    last_dir = dir_char
                applied_modes += mode_char
                applied_params.append(target_nick)

            elif mode_char in self._PARAM_MODES:
                if dir_char == "+":
                    if param_index >= len(message.params):
                        self._send_numeric(envelope, ERR_NEEDMOREPARAMS, nick,
                                           f"MODE :Not enough parameters for {dir_char}{mode_char}")
                        continue
                    mode_param = message.params[param_index]
                    param_index += 1

                    if mode_char == "l":
                        try:
                            self.state.set_channel_mode(normalized, mode_char, int(mode_param))
                        except ValueError:
                            continue
                    elif mode_char == "k":
                        self.state.set_channel_mode(normalized, mode_char, mode_param)

                    if dir_char != last_dir:
                        applied_modes += dir_char
                        last_dir = dir_char
                    applied_modes += mode_char
                    applied_params.append(mode_param)
                else:
                    self.state.unset_channel_mode(normalized, mode_char)
                    if param_index < len(message.params):
                        param_index += 1
                    if dir_char != last_dir:
                        applied_modes += dir_char
                        last_dir = dir_char
                    applied_modes += mode_char

            elif mode_char in self._FLAG_MODES:
                if dir_char == "+":
                    self.state.set_channel_mode(normalized, mode_char)
                else:
                    self.state.unset_channel_mode(normalized, mode_char)

                if dir_char != last_dir:
                    applied_modes += dir_char
                    last_dir = dir_char
                applied_modes += mode_char

        if not applied_modes:
            return

        # Sync link channel states from local server state
        self._sync_link_channel_state(normalized)

        # Broadcast mode change to channel
        prefix = self._user_host(nick, envelope)
        params_str = (" " + " ".join(applied_params)) if applied_params else ""
        mode_msg = format_irc_message(prefix, "MODE", [normalized, f"{applied_modes}{params_str}"])
        self._broadcast_to_channel(normalized, mode_msg, exclude_session=None)

        self.state.record_protocol_event(
            envelope, "mode",
            {"channel": normalized, "modes": applied_modes, "params": applied_params},
        )

    def _send_ban_list(self, envelope: CommandEnvelope, nick: str, channel_name: str) -> None:
        for ban_mask in self.state.get_bans(channel_name):
            self.state.record_session_outbound(
                envelope.source_session,
                f":{self.server.name} {RPL_BANLIST} {nick} {channel_name} {ban_mask}",
            )
        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_ENDOFBANLIST} {nick} {channel_name} :End of channel ban list",
        )

    # ==================================================================
    # TOPIC
    # ==================================================================

    def _handle_topic(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if not message.params:
            self._send_numeric(envelope, ERR_NEEDMOREPARAMS, nick, "TOPIC :Not enough parameters")
            return

        chan_name = message.params[0]
        normalized = self.state.normalize_channel_name(chan_name)
        channel = self.state.get_channel(normalized)
        if channel is None:
            self._send_numeric(envelope, ERR_NOSUCHCHANNEL, nick, f"{normalized} :No such channel")
            return
        if not self.state.is_channel_member(normalized, nick):
            self._send_numeric(envelope, ERR_NOTONCHANNEL, nick, f"{normalized} :You're not on that channel")
            return

        # Query topic
        if len(message.params) < 2 and not message.trailing:
            if channel.get("topic"):
                self._send_numeric(envelope, RPL_TOPIC, nick, f"{normalized} :{channel['topic']}")
                if channel.get("topic_author") and channel.get("topic_time"):
                    self.state.record_session_outbound(
                        envelope.source_session,
                        f":{self.server.name} {RPL_TOPICWHOTIME} {nick} {normalized} "
                        f"{channel['topic_author']} {int(channel['topic_time'])}",
                    )
            else:
                self._send_numeric(envelope, RPL_NOTOPIC, nick, f"{normalized} :No topic is set")
            return

        # Set topic — check +t
        session = self.state.ensure_session(envelope.source_session)
        is_oper = bool(session.get("oper_flags"))
        if not is_oper and not self.state.can_set_topic(normalized, nick):
            self._send_numeric(envelope, ERR_CHANOPRIVSNEEDED, nick,
                               f"{normalized} :You're not channel operator (+t)")
            return

        new_topic = message.trailing or message.params[-1]
        channel["topic"] = new_topic
        channel["topic_author"] = nick
        channel["topic_time"] = time.time()

        # Update topic in link channel states
        for link in self.server.iter_links():
            if link.has_channel(normalized):
                link.channels[normalized].set_topic(new_topic)

        topic_line = format_irc_message(self._user_host(nick, envelope), "TOPIC", [normalized], new_topic)
        self._broadcast_to_channel(normalized, topic_line, exclude_session=None)

        self.state.record_protocol_event(
            envelope, "topic",
            {"channel": normalized, "topic": new_topic, "author": nick},
        )

    # ==================================================================
    # KICK
    # ==================================================================

    def _handle_kick(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if len(message.params) < 2:
            self._send_numeric(envelope, ERR_NEEDMOREPARAMS, nick, "KICK :Not enough parameters")
            return

        chan_name = message.params[0]
        target_nick = message.params[1]
        reason = message.trailing or (message.params[2] if len(message.params) > 2 else nick)

        normalized = self.state.normalize_channel_name(chan_name)
        channel = self.state.get_channel(normalized)
        if channel is None:
            self._send_numeric(envelope, ERR_NOSUCHCHANNEL, nick, f"{normalized} :No such channel")
            return

        session = self.state.ensure_session(envelope.source_session)
        is_oper = bool(session.get("oper_flags"))
        if not is_oper and not self.state.is_channel_op(normalized, nick):
            self._send_numeric(envelope, ERR_CHANOPRIVSNEEDED, nick,
                               f"{normalized} :You're not channel operator")
            return

        if not self.state.is_channel_member(normalized, target_nick):
            self._send_numeric(envelope, ERR_USERNOTINCHANNEL, nick,
                               f"{target_nick} {normalized} :They aren't on that channel")
            return

        kick_line = format_irc_message(
            self._user_host(nick, envelope), "KICK", [normalized, target_nick], reason,
        )
        self._broadcast_to_channel(normalized, kick_line, exclude_session=None)
        self.state.remove_channel_member(normalized, target_nick)

        # Remove from link channels
        for link in self.server.iter_links():
            if link.has_channel(normalized):
                link.channels[normalized].remove_user(target_nick)

        # Clean up empty channels from link tracking
        self._cleanup_empty_link_channels(normalized)

        self.state.record_protocol_event(
            envelope, "kick",
            {"channel": normalized, "target": target_nick, "reason": reason},
        )

    # ==================================================================
    # Registration and basic handlers
    # ==================================================================

    def _handle_pass(self, message, envelope: CommandEnvelope) -> None:
        session = self.state.ensure_session(envelope.source_session)
        target = session.get("nick") or "*"
        if session.get("state") == "registered":
            self._send_numeric(envelope, ERR_ALREADYREGISTRED, target, "You may not reregister")
            return
        if not message.params:
            self._send_numeric(envelope, ERR_NEEDMOREPARAMS, target, "PASS :Not enough parameters")
            return

        session["password"] = str(message.params[0])
        self.state.record_protocol_event(
            envelope,
            "pass",
            {"accepted": True, "has_password": bool(session["password"])},
        )

    def _handle_nick(self, message, envelope: CommandEnvelope) -> None:
        session = self.state.ensure_session(envelope.source_session)
        current_nick = session.get("nick") or "*"
        if not message.params:
            self._send_numeric(envelope, ERR_NONICKNAMEGIVEN, current_nick, "No nickname given")
            return

        new_nick = str(message.params[0]).strip()
        if not NICK_RE.match(new_nick) or len(new_nick) > 30:
            self._send_numeric(envelope, ERR_ERRONEUSNICKNAME, current_nick, f"{new_nick} :Erroneous nickname")
            return

        if self._nick_in_use(new_nick, envelope.source_session):
            self._send_numeric(envelope, ERR_NICKNAMEINUSE, current_nick, f"{new_nick} :Nickname is already in use")
            return

        old_nick = session.get("nick")
        session["nick"] = new_nick
        self.state.set_session_context(
            envelope.source_session,
            source_nick=new_nick,
            source_is_oper=bool(session.get("oper_flags")),
        )
        if session.get("state") == "registered" and old_nick and old_nick.lower() != new_nick.lower():
            self.state.rename_session_nick(envelope.source_session, old_nick, new_nick)
            if session.get("oper_flags"):
                self.server.remove_active_oper(old_nick.lower())
                self.server.add_active_oper(new_nick.lower(), session.get("oper_account") or new_nick.lower(), session["oper_flags"])
            nick_msg = format_irc_message(self._user_host(old_nick, envelope), "NICK", [new_nick])
            # Broadcast NICK change to all channel members (like QUIT does)
            affected_sessions = {envelope.source_session}
            for channel_name in list(session.get("channels", set())):
                for member_session in self.state.channel_member_sessions(channel_name):
                    affected_sessions.add(member_session)
            for sid in affected_sessions:
                self.state.record_session_outbound(sid, nick_msg)

            # Propagate nick change to all link channel user lists
            for link in self.server.iter_links():
                link.rename_nick(old_nick, new_nick)

            self.state.record_protocol_event(
                envelope,
                "nick_change",
                {"old_nick": old_nick, "new_nick": new_nick},
            )
            return

        self.state.record_protocol_event(
            envelope,
            "nick",
            {"nick": new_nick, "registered": bool(session.get("user"))},
        )
        self._try_complete_registration(envelope)

    def _handle_user(self, message, envelope: CommandEnvelope) -> None:
        session = self.state.ensure_session(envelope.source_session)
        target = session.get("nick") or "*"
        if session.get("state") == "registered":
            self._send_numeric(envelope, ERR_ALREADYREGISTRED, target, "You may not reregister")
            return
        if len(message.params) < 4:
            self._send_numeric(envelope, ERR_NEEDMOREPARAMS, target, "USER :Not enough parameters")
            return

        session["user"] = str(message.params[0]).strip()
        session["realname"] = str(message.trailing or message.params[-1]).strip()
        self.state.record_protocol_event(
            envelope,
            "user",
            {"user": session["user"], "realname": session["realname"]},
        )
        self._try_complete_registration(envelope)

    def _handle_oper(self, message, envelope: CommandEnvelope) -> None:
        session = self.state.ensure_session(envelope.source_session)
        nick = session.get("nick") or "*"
        if session.get("state") != "registered":
            self._send_numeric(envelope, ERR_NOTREGISTERED, nick, "You have not registered")
            return
        if len(message.params) < 2:
            self._send_numeric(envelope, ERR_NEEDMOREPARAMS, nick, "OPER :Not enough parameters")
            return

        account = str(message.params[0]).strip()
        password = str(message.params[1])
        username = session.get("user") or nick
        client_mask = f"{nick}!{username}@{envelope.source_session}"
        flags = self.server.check_oper_auth(account, password, self.server.name, client_mask)
        if not flags:
            self._send_numeric(envelope, ERR_PASSWDMISMATCH, nick, "Password incorrect")
            self.state.record_protocol_event(
                envelope,
                "oper",
                {"account": account, "authenticated": False},
            )
            return

        session["oper_account"] = account
        session["oper_flags"] = str(flags)
        self.server.add_active_oper(nick.lower(), account, flags)
        # Sync oper status to all links
        for link in self.server.iter_links():
            link.add_oper(nick)
        self.state.set_session_context(
            envelope.source_session,
            source_nick=nick,
            source_is_oper=True,
        )
        self._send_numeric(envelope, RPL_YOUREOPER, nick, "You are now an IRC operator")
        self.state.record_protocol_event(
            envelope,
            "oper",
            {"account": account, "authenticated": True, "flags": str(flags)},
        )
        self._logger(f"[EXEC] oper auth session={envelope.source_session} nick={nick} account={account} flags={flags}")

    def _try_complete_registration(self, envelope: CommandEnvelope) -> None:
        session = self.state.ensure_session(envelope.source_session)
        if session.get("state") == "registered":
            return
        if not session.get("nick") or not session.get("user"):
            return

        session["state"] = "registered"
        self.state.mark_session_registered(
            envelope.source_session,
            origin_server=envelope.origin_server or self.server.name,
        )
        nick = session["nick"]
        self._send_numeric(envelope, RPL_WELCOME, nick, f"Welcome to {self.server.name} Network, {nick}")
        self._send_numeric(envelope, RPL_YOURHOST, nick, f"Your host is {self.server.name}, running csc-server")
        self._send_numeric(envelope, RPL_CREATED, nick, "This server was created recently")
        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_MYINFO} {nick} {self.server.name} csc-server iosw opsimnqbvk",
        )
        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_ISUPPORT} {nick} CHANTYPES=# PREFIX=(ov)@+ "
            f"CHANMODES=b,k,l,imnpst NICKLEN=30 CHANNELLEN=50 NETWORK={self.server.name} "
            f":are supported by this server",
        )
        self._send_motd(envelope, nick)
        self.state.record_protocol_event(
            envelope,
            "registration_complete",
            {"nick": nick, "user": session["user"], "realname": session["realname"]},
        )
        self._logger(f"[EXEC] registered session={envelope.source_session} nick={nick}")

    def _send_numeric(self, envelope: CommandEnvelope, numeric: str, target: str, *text_parts: str) -> None:
        self.state.record_session_outbound(
            envelope.source_session,
            numeric_reply(self.server.name, numeric, target, *text_parts),
        )

    def _nick_in_use(self, new_nick: str, source_session: str) -> bool:
        target = new_nick.lower()
        # Check local sessions
        for session_id, session in self.state.sessions.items():
            if session_id == source_session:
                continue
            if str(session.get("nick") or "").lower() == target:
                return True
        # Check remote nicks on all links
        for link in self.server.iter_links():
            if target in {n.lower() for n in link.users}:
                return True
            if target in {n.lower() for n in link.nicks_behind}:
                return True
        return False

    def _require_registered(self, envelope: CommandEnvelope) -> str | None:
        session = self.state.ensure_session(envelope.source_session)
        nick = session.get("nick") or "*"
        if session.get("state") != "registered":
            self._send_numeric(envelope, ERR_NOTREGISTERED, nick, "You have not registered")
            return None
        return str(session["nick"])

    def _handle_file_upload(self, envelope: CommandEnvelope, channel_name: str, nick: str, text: str) -> bool:
        """Handle IRC file upload markers. Returns True if the message was consumed."""
        import re as _re
        sid = envelope.source_session

        # Check for <begin file=name> (possibly prefixed with server target)
        begin_match = _re.search(r'<begin file=(\S+)>', text)
        if begin_match and sid not in self._file_buffers:
            module_name = begin_match.group(1).replace('.py', '')
            self._file_buffers[sid] = {"name": module_name, "lines": [], "channel": channel_name}
            self._logger(f"[FILE] Upload started: {module_name} from {nick}")
            return True

        # Check for <end file> while buffering
        if sid in self._file_buffers and '<end file>' in text:
            buf = self._file_buffers.pop(sid)
            module_name = buf["name"]
            content = '\n'.join(buf["lines"]) + '\n'
            self._logger(f"[FILE] Upload complete: {module_name} ({len(buf['lines'])} lines) from {nick}")
            try:
                self._install_uploaded_module(module_name, content)
                confirm = f":{self.server.name} NOTICE {channel_name} :{module_name} validated and activated"
                self.state.record_session_outbound(sid, confirm)
                self._broadcast_to_channel(channel_name, confirm, exclude_session=sid)
                self._logger(f"[FILE] Module {module_name} validated and activated")
            except Exception as e:
                err = f":{self.server.name} NOTICE {channel_name} :Upload failed for {module_name}: {e}"
                self.state.record_session_outbound(sid, err)
                self._logger(f"[FILE] Module {module_name} install failed: {e}")
            return True

        # Accumulate content lines while buffering
        if sid in self._file_buffers:
            self._file_buffers[sid]["lines"].append(text)
            return True

        return False

    def _install_uploaded_module(self, module_name: str, content: str) -> None:
        """Write uploaded module to csc_services package directory for handle_command to find."""
        import importlib
        import csc_services
        pkg_dir = os.path.dirname(csc_services.__file__)
        file_path = os.path.join(pkg_dir, f"{module_name.lower()}.py")
        with open(file_path, 'w') as f:
            f.write(content)
        # Clear from sys.modules so handle_command does a fresh import
        full_name = f"csc_services.{module_name.lower()}"
        if full_name in sys.modules:
            del sys.modules[full_name]

    def _broadcast_to_channel(self, channel_name: str, line: str, exclude_session: str | None = None) -> None:
        for session_id in self.state.channel_member_sessions(channel_name):
            if exclude_session is not None and session_id == exclude_session:
                continue
            self.state.record_session_outbound(session_id, line)

    def _broadcast_channel_line(self, channel_name: str, line: str) -> None:
        """Broadcast a server-generated channel line locally AND to peers via sync_mesh.

        Used for server-origin messages (e.g., service command responses) that must
        reach clients on linked peers. Peers receive a BROADCAST envelope and perform
        the same local broadcast on their side.
        """
        self._broadcast_to_channel(channel_name, line, exclude_session=None)
        sync_mesh = getattr(self.server, "sync_mesh", None)
        if sync_mesh is None:
            return
        if self.server.link_count() == 0:
            return
        sname = self.server.name
        envelope = CommandEnvelope(
            kind="BROADCAST",
            payload={"channel": channel_name, "line": line},
            source_session=f"system:{sname}",
            origin_server=sname,
            replicate=True,
        )
        sync_mesh.sync_command(envelope)

    def _cleanup_empty_link_channels(self, channel_name: str) -> None:
        """Remove a channel from link tracking if it has no users anywhere."""
        local_channel = self.state.get_channel(channel_name)
        local_has_members = local_channel is not None and bool(local_channel.get("members"))
        if local_has_members:
            return
        for link in self.server.iter_links():
            if link.has_channel(channel_name):
                if link.channels[channel_name].user_count() == 0:
                    link.del_channel(channel_name)

    def _sync_link_channel_state(self, channel_name: str) -> None:
        """Sync local channel member modes, channel modes, and bans to all link channel objects."""
        channel = self.state.get_channel(channel_name)
        if channel is None:
            return
        for link in self.server.iter_links():
            link_channel = link.get_channel(channel_name)
            # Clear and repopulate users from local state
            link_channel.users.clear()
            for member in self.state.channel_members(channel_name):
                member_nick = member["nick"]
                member_modes = member.get("modes", set())
                modes_list = []
                if "o" in member_modes:
                    modes_list.append("@")
                if "v" in member_modes:
                    modes_list.append("+")
                link_channel.add_user(member_nick, modes=modes_list)

            # Sync channel modes (+i, +m, +n, +t, +s, +p, +Q, +k, +l)
            modes, params = self.state.get_channel_modes(channel_name)
            mode_str = "".join(sorted(modes)) if modes else ""
            link_channel.set_modes(mode_str)

            # Sync bans from local state
            link_channel.bans = self.state.get_bans(channel_name) or []

            # Sync topic
            topic = channel.get("topic", "")
            if topic:
                link_channel.set_topic(topic)

    def _send_names_reply(self, envelope: CommandEnvelope, channel_name: str, nick: str) -> None:
        members = []
        # Local members
        for member in self.state.channel_members(channel_name):
            member_name = member["nick"]
            member_modes = member.get("modes", set())
            if "o" in member_modes:
                member_name = f"@{member_name}"
            elif "v" in member_modes:
                member_name = f"+{member_name}"
            members.append(member_name)

        # Remote members from all links
        for link in self.server.iter_links():
            if link.has_channel(channel_name):
                channel = link.channels[channel_name]
                for remote_nick in channel.get_all_users():
                    modes = channel.get_user_modes(remote_nick)
                    prefix = ""
                    if "@" in modes:
                        prefix = "@"
                    elif "+" in modes:
                        prefix = "+"
                    members.append(prefix + remote_nick)

        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_NAMREPLY} {nick} = {channel_name} :{' '.join(sorted(members))}",
        )
        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_ENDOFNAMES} {nick} {channel_name} :End of /NAMES list.",
        )

    def _join_channel(
        self, envelope: CommandEnvelope, channel_name: str, *, auto: bool = False, key: str | None = None,
    ) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        normalized = self.state.normalize_channel_name(channel_name)
        channel = self.state.ensure_channel(normalized)
        if self.state.is_channel_member(normalized, nick):
            return

        session = self.state.ensure_session(envelope.source_session)
        is_oper = bool(session.get("oper_flags"))

        # Enforce channel modes (skip for opers and auto-join)
        if not auto and not is_oper and channel["members"]:
            # +i (invite only)
            if "i" in channel["modes"] and not self.state.is_invited(normalized, nick):
                self._send_numeric(envelope, ERR_INVITEONLYCHAN, nick,
                                   f"{normalized} :Cannot join channel (+i)")
                return
            # +k (channel key)
            if "k" in channel["modes"]:
                expected_key = channel["mode_params"].get("k")
                if key != expected_key:
                    self._send_numeric(envelope, ERR_BADCHANNELKEY, nick,
                                       f"{normalized} :Cannot join channel (+k) - Bad channel key")
                    return
            # +l (user limit)
            if "l" in channel["modes"]:
                limit = channel["mode_params"].get("l", 0)
                if len(channel["members"]) >= limit:
                    self._send_numeric(envelope, ERR_CHANNELISFULL, nick,
                                       f"{normalized} :Cannot join channel (+l) - Channel is full")
                    return
            # +b (ban)
            if channel["ban_list"]:
                user = session.get("user") or nick
                host = envelope.origin_server or self.server.name
                if self.state.is_banned(normalized, nick, user, host):
                    self._send_numeric(envelope, ERR_BANNEDFROMCHAN, nick,
                                       f"{normalized} :Cannot join channel (+b) - You are banned")
                    return

        is_first_member = not channel["members"]
        if is_first_member:
            self.state.set_channel_mode(normalized, "n")
            self.state.set_channel_mode(normalized, "t")
        self.state.add_channel_member(normalized, envelope.source_session, nick, op=is_first_member)

        # Update link states: add nick to all links' channel tracking
        for link in self.server.iter_links():
            link_channel = link.get_channel(normalized)
            modes = ["@"] if is_first_member else []
            link_channel.add_user(nick, modes=modes)

        join_line = format_irc_message(self._user_host(nick, envelope), "JOIN", [normalized])
        self._broadcast_to_channel(normalized, join_line, exclude_session=None)
        topic = channel.get("topic", "")
        if topic:
            self._send_numeric(envelope, RPL_TOPIC, nick, f"{normalized} :{topic}")
        else:
            self._send_numeric(envelope, RPL_NOTOPIC, nick, f"{normalized} :No topic is set")
        self._send_names_reply(envelope, normalized, nick)
        self.state.record_protocol_event(
            envelope,
            "join",
            {"channel": normalized, "auto": auto},
        )

    def _handle_join(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if not message.params:
            self._send_numeric(envelope, ERR_NEEDMOREPARAMS, nick, "JOIN :Not enough parameters")
            return
        channels = str(message.params[0]).split(",")
        keys = str(message.params[1]).split(",") if len(message.params) > 1 else []
        for i, channel_name in enumerate(channels):
            key = keys[i] if i < len(keys) else None
            self._join_channel(envelope, channel_name, key=key)

    def _handle_part(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if not message.params:
            self._send_numeric(envelope, ERR_NEEDMOREPARAMS, nick, "PART :Not enough parameters")
            return
        reason = str(message.trailing or (message.params[1] if len(message.params) > 1 else "Leaving"))
        for channel_name in str(message.params[0]).split(","):
            normalized = self.state.normalize_channel_name(channel_name)
            if not self.state.get_channel(normalized):
                self._send_numeric(envelope, ERR_NOSUCHCHANNEL, nick, f"{normalized} :No such channel")
                continue
            if not self.state.is_channel_member(normalized, nick):
                self._send_numeric(envelope, ERR_NOTONCHANNEL, nick, f"{normalized} :You're not on that channel")
                continue
            part_line = format_irc_message(self._user_host(nick, envelope), "PART", [normalized], reason)
            self._broadcast_to_channel(normalized, part_line, exclude_session=None)
            self.state.remove_channel_member(normalized, nick)

            # Update link states: remove nick from all links' channel tracking
            for link in self.server.iter_links():
                if link.has_channel(normalized):
                    link.channels[normalized].remove_user(nick)

            # Clean up empty channels from link tracking
            self._cleanup_empty_link_channels(normalized)

            self.state.record_protocol_event(
                envelope,
                "part",
                {"channel": normalized, "reason": reason},
            )

    def _handle_names(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if message.params:
            normalized = self.state.normalize_channel_name(message.params[0])
            if not self.state.get_channel(normalized):
                self._send_numeric(envelope, ERR_NOSUCHCHANNEL, nick, f"{normalized} :No such channel")
                return
            self._send_names_reply(envelope, normalized, nick)
            return
        for channel in self.state.list_channels():
            self._send_names_reply(envelope, channel["name"], nick)

    def _handle_list(self, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        for channel in self.state.list_channels():
            member_count = len(channel["members"])
            self.state.record_session_outbound(
                envelope.source_session,
                f":{self.server.name} {RPL_LIST} {nick} {channel['name']} {member_count} :{channel.get('topic', '')}",
            )
        self.state.record_session_outbound(
            envelope.source_session,
            f":{self.server.name} {RPL_LISTEND} {nick} :End of /LIST",
        )

    def _handle_quit(self, message, envelope: CommandEnvelope) -> None:
        session = self.state.ensure_session(envelope.source_session)
        nick = session.get("nick") or envelope.source_session
        reason = str(message.trailing or (message.params[0] if message.params else "Client Quit"))
        quit_line = format_irc_message(self._user_host(nick, envelope), "QUIT", [], reason)
        affected_sessions = set()
        quit_channels = list(session.get("channels", set()))
        for channel_name in quit_channels:
            for member_session in self.state.channel_member_sessions(channel_name):
                if member_session != envelope.source_session:
                    affected_sessions.add(member_session)
        for member_session in affected_sessions:
            self.state.record_session_outbound(member_session, quit_line)
        self.state.remove_session_from_all_channels(envelope.source_session)

        # Remove nick from all link channels
        for link in self.server.iter_links():
            for channel in link.channels.values():
                channel.remove_user(nick)

        # Clean up empty channels from link tracking
        for channel_name in quit_channels:
            self._cleanup_empty_link_channels(channel_name)

        if session.get("oper_flags"):
            self.server.remove_active_oper(str(nick).lower())
            # Remove oper status from all links
            for link in self.server.iter_links():
                link.del_oper(nick)
        self.state.remove_session(envelope.source_session)
        self.state.record_protocol_event(
            envelope,
            "quit",
            {"nick": nick, "reason": reason},
        )

    def _is_authorized_service_command(self, message, envelope: CommandEnvelope) -> tuple[bool, dict]:
        channel = message.params[0] if message.params else ""
        source_nick = str(envelope.payload.get("source_nick", envelope.source_session or "")).strip()
        source_is_oper = bool(envelope.payload.get("source_is_oper", False))
        source_is_channel_op = bool(envelope.payload.get("source_is_channel_op", False))

        detail = {
            "source_nick": source_nick,
            "channel": channel,
            "source_is_oper": source_is_oper,
            "source_is_channel_op": source_is_channel_op,
        }
        # Service commands in channels are allowed for any channel member.
        # Callers must already be in the channel to PRIVMSG it (enforced upstream),
        # so membership is the natural authorization gate. Operator/chanop status
        # is recorded for audit/protocol events but is not required to execute.
        return True, detail

    def _user_host(self, nick: str, envelope: CommandEnvelope) -> str:
        """Build hostmask preserving origin server for relayed commands."""
        origin = envelope.origin_server or self.server.name
        return f"{nick}!{nick}@{origin}"

    def _debug(self, message: str) -> None:
        debug_fn = getattr(self.server, "debug", None)
        if callable(debug_fn):
            debug_fn(message)

    # ==================================================================
    # INVITE (real implementation — required for +i channels to be usable)
    # ==================================================================

    def _handle_invite(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if len(message.params) < 2:
            self._send_numeric(envelope, ERR_NEEDMOREPARAMS, nick, "INVITE :Not enough parameters")
            return

        target_nick = str(message.params[0]).strip()
        chan_name = str(message.params[1]).strip()
        normalized = self.state.normalize_channel_name(chan_name)
        channel = self.state.get_channel(normalized)
        if channel is None:
            self._send_numeric(envelope, ERR_NOSUCHCHANNEL, nick, f"{normalized} :No such channel")
            return
        if not self.state.is_channel_member(normalized, nick):
            self._send_numeric(envelope, ERR_NOTONCHANNEL, nick, f"{normalized} :You're not on that channel")
            return
        # +i channels require chanop to invite
        if "i" in channel["modes"] and not self.state.is_channel_op(normalized, nick):
            self._send_numeric(envelope, ERR_CHANOPRIVSNEEDED, nick,
                               f"{normalized} :You're not channel operator")
            return
        if self.state.is_channel_member(normalized, target_nick):
            self._send_numeric(envelope, ERR_USERONCHANNEL, nick,
                               f"{target_nick} {normalized} :is already on channel")
            return

        self.state.add_invite(normalized, target_nick)

        # Sync invite to link channel objects
        for link in self.server.iter_links():
            if link.has_channel(normalized):
                link.channels[normalized].add_invite(target_nick)

        # RPL_INVITING to inviter
        self._send_numeric(envelope, RPL_INVITING, nick, f"{target_nick} {normalized}")
        # INVITE notification to target (local)
        target_session = self.state.find_session_by_nick(target_nick)
        if target_session is not None:
            invite_line = format_irc_message(
                self._user_host(nick, envelope),
                "INVITE",
                [target_nick, normalized],
            )
            self.state.record_session_outbound(target_session, invite_line)
        self.state.record_protocol_event(
            envelope,
            "invite",
            {"from": nick, "to": target_nick, "channel": normalized},
        )

    # ==================================================================
    # Info / query command stubs (LUSERS / VERSION / TIME / ADMIN / INFO /
    # LINKS / USERHOST / ISON)
    #
    # Each stub:
    #   1. Requires a registered user (so unregistered clients get 451)
    #   2. Calls self.log_stubbed_call("CommandDispatcher", "<method>")
    #   3. Emits the RFC-mandated closing numeric so clients don't hang
    #      waiting for a terminator
    # ==================================================================

    def _handle_lusers(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        self.log_stubbed_call("CommandDispatcher", "_handle_lusers")
        # Minimal valid close so clients don't hang
        self._send_numeric(envelope, RPL_LUSERCLIENT, nick,
                           ":There are 0 users and 0 invisible on 1 servers")
        self._send_numeric(envelope, RPL_LUSEROP, nick, "0 :operator(s) online")
        self._send_numeric(envelope, RPL_LUSERUNKNOWN, nick, "0 :unknown connection(s)")
        self._send_numeric(envelope, RPL_LUSERCHANNELS, nick, "0 :channels formed")
        self._send_numeric(envelope, RPL_LUSERME, nick,
                           f":I have 0 clients and 0 servers")

    def _handle_version(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        self.log_stubbed_call("CommandDispatcher", "_handle_version")
        self._send_numeric(envelope, RPL_VERSION, nick,
                           f"csc-server-stub.0 {self.server.name} :STUB not implemented")

    def _handle_time(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        self.log_stubbed_call("CommandDispatcher", "_handle_time")
        now = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        self._send_numeric(envelope, RPL_TIME, nick, f"{self.server.name} :{now}")

    def _handle_admin(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        self.log_stubbed_call("CommandDispatcher", "_handle_admin")
        self._send_numeric(envelope, RPL_ADMINME, nick, f"{self.server.name} :Administrative info")
        self._send_numeric(envelope, RPL_ADMINLOC1, nick, ":STUB not implemented")
        self._send_numeric(envelope, RPL_ADMINLOC2, nick, ":STUB not implemented")
        self._send_numeric(envelope, RPL_ADMINEMAIL, nick, ":STUB not implemented")

    def _handle_info(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        self.log_stubbed_call("CommandDispatcher", "_handle_info")
        self._send_numeric(envelope, RPL_INFO, nick, ":csc-server (stubbed INFO)")
        self._send_numeric(envelope, RPL_ENDOFINFO, nick, ":End of INFO list")

    def _handle_links(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        self.log_stubbed_call("CommandDispatcher", "_handle_links")
        # Best-effort: emit one RPL_LINKS per Link registered on the server.
        # The formatting is valid per RFC even though the hop-count/info
        # are stubbed -- real enumeration belongs with netsplit work.
        mask = "*"
        iter_links = getattr(self.server, "iter_links", None)
        if callable(iter_links):
            for link in iter_links():
                self._send_numeric(envelope, RPL_LINKS, nick,
                                   f"{mask} {link.name} :0 STUB link info")
        self._send_numeric(envelope, RPL_ENDOFLINKS, nick, f"{mask} :End of LINKS list")

    def _handle_userhost(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        self.log_stubbed_call("CommandDispatcher", "_handle_userhost")
        # RFC: up to 5 target nicks, single RPL_USERHOST with space-separated replies
        replies = []
        for target in message.params[:5]:
            tnick = str(target).strip()
            if self.state.find_session_by_nick(tnick) is not None:
                replies.append(f"{tnick}=+{tnick}@{self.server.name}")
        self._send_numeric(envelope, RPL_USERHOST, nick, ":" + " ".join(replies))

    def _handle_ison(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        self.log_stubbed_call("CommandDispatcher", "_handle_ison")
        online = []
        for target in message.params:
            tnick = str(target).strip()
            if tnick and self.state.find_session_by_nick(tnick) is not None:
                online.append(tnick)
        self._send_numeric(envelope, RPL_ISON, nick, ":" + " ".join(online))

    # ==================================================================
    # Oper / server-to-server command stubs
    # Each stub enforces ERR_NOPRIVILEGES for non-opers, then logs the hit.
    # ==================================================================

    def _require_oper(self, envelope: CommandEnvelope, nick: str) -> bool:
        session = self.state.ensure_session(envelope.source_session)
        if session.get("oper_flags"):
            return True
        # For remote-origin commands, check if nick is known as oper on any link
        if envelope.origin_server and envelope.origin_server != self.server.name:
            for link in self.server.iter_links():
                if nick in link.opers:
                    return True
        self._send_numeric(envelope, ERR_NOPRIVILEGES, nick,
                           ":Permission Denied- You're not an IRC operator")
        return False

    def _handle_kill(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        # Remote-origin KILLs (e.g., from SQUIT propagation) are trusted
        is_remote = envelope.origin_server and envelope.origin_server != self.server.name
        if not is_remote and not self._require_oper(envelope, nick):
            return
        if not message.params:
            self._send_numeric(envelope, ERR_NEEDMOREPARAMS, nick, "KILL :Not enough parameters")
            return

        target_nick = str(message.params[0]).strip()
        reason = message.trailing or (message.params[1] if len(message.params) > 1 else "Killed")

        # Try local user first
        target_session_id = self.state.find_session_by_nick(target_nick)
        if target_session_id is not None:
            # Emit KILL to all channel members
            kill_line = format_irc_message(
                self._user_host(nick, envelope),
                "KILL",
                [target_nick],
                f"Killed ({nick} ({reason}))",
            )
            target_session = self.state.ensure_session(target_session_id)
            affected_sessions = set()
            for channel_name in list(target_session.get("channels", set())):
                for member_session in self.state.channel_member_sessions(channel_name):
                    affected_sessions.add(member_session)
            for sid in affected_sessions:
                self.state.record_session_outbound(sid, kill_line)

            # Remove from all channels and clean up
            quit_channels = list(target_session.get("channels", set()))
            self.state.remove_session_from_all_channels(target_session_id)
            for link in self.server.iter_links():
                for channel in link.channels.values():
                    channel.remove_user(target_nick)
            for channel_name in quit_channels:
                self._cleanup_empty_link_channels(channel_name)

            if target_session.get("oper_flags"):
                self.server.remove_active_oper(target_nick.lower())
            self.state.remove_session(target_session_id)

            self.state.record_protocol_event(
                envelope, "kill",
                {"killer": nick, "target": target_nick, "reason": reason, "local": True},
            )
            self._logger(f"[EXEC] KILL {target_nick} by {nick}: {reason}")
            return

        # Try remote user -- remove from link state
        found = False
        for link in self.server.iter_links():
            if link.has_user(target_nick) or link.has_nick_behind(target_nick):
                link.del_user(target_nick)
                link.remove_nick_behind(target_nick)
                for channel in link.channels.values():
                    channel.remove_user(target_nick)
                link.del_oper(target_nick)
                found = True
                break

        if not found:
            self._send_numeric(envelope, ERR_NOSUCHNICK, nick, f"{target_nick} :No such nick/channel")
            return

        # Broadcast QUIT for the killed remote user to local clients
        quit_line = format_irc_message(
            f"{target_nick}!{target_nick}@{envelope.origin_server or 'remote'}",
            "QUIT",
            [],
            f"Killed ({nick} ({reason}))",
        )
        for session_id in self.state.sessions:
            self.state.record_session_outbound(session_id, quit_line)

        self.state.record_protocol_event(
            envelope, "kill",
            {"killer": nick, "target": target_nick, "reason": reason, "local": False},
        )
        self._logger(f"[EXEC] KILL (remote) {target_nick} by {nick}: {reason}")

    def _handle_squit(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if not self._require_oper(envelope, nick):
            return
        if not message.params:
            self._send_numeric(envelope, ERR_NEEDMOREPARAMS, nick, "SQUIT :Not enough parameters")
            return

        target_server = str(message.params[0]).strip()
        reason = message.trailing or (message.params[1] if len(message.params) > 1 else "No reason")
        link = self.server.get_link_by_origin(target_server)
        if link is None:
            # Try matching by link name
            for lk in self.server.iter_links():
                if lk.name == target_server:
                    link = lk
                    break
        if link is None:
            self._send_numeric(envelope, ERR_NOSUCHSERVER, nick,
                               f"{target_server} :No such server")
            return

        # Clean up all remote state from this link
        removed_nicks, removed_channels = link.clear_remote_state()

        # Emit QUIT messages for all remote users on this link
        for remote_nick in removed_nicks:
            quit_line = format_irc_message(
                f"{remote_nick}!{remote_nick}@{target_server}",
                "QUIT",
                [],
                f"{self.server.name} {target_server}",
            )
            for session_id in self.state.sessions:
                self.state.record_session_outbound(session_id, quit_line)

        # Remove link users from local channel state
        for remote_nick in removed_nicks:
            link.del_user(remote_nick)

        # Reset crypto so link can re-establish
        link.connection.clear_crypto()

        # Notify oper
        squit_notice = f":{self.server.name} NOTICE {nick} :SQUIT {target_server} ({reason}) " \
                       f"-- {len(removed_nicks)} users, {len(removed_channels)} channels removed"
        self.state.record_session_outbound(envelope.source_session, squit_notice)

        self.state.record_protocol_event(
            envelope, "squit",
            {"target": target_server, "reason": reason,
             "removed_nicks": len(removed_nicks),
             "removed_channels": len(removed_channels)},
        )
        self._logger(
            f"[EXEC] SQUIT {target_server} by {nick}: "
            f"{len(removed_nicks)} users, {len(removed_channels)} channels cleaned"
        )

    def _handle_wallops(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if not self._require_oper(envelope, nick):
            return
        self.log_stubbed_call("CommandDispatcher", "_handle_wallops")

    def _handle_connect(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if not self._require_oper(envelope, nick):
            return
        self.log_stubbed_call(
            "CommandDispatcher", "_handle_connect",
            target=message.params[0] if message.params else None,
        )

    def _handle_rehash(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if not self._require_oper(envelope, nick):
            return
        self.log_stubbed_call("CommandDispatcher", "_handle_rehash")

    def _handle_restart(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if not self._require_oper(envelope, nick):
            return
        self.log_stubbed_call("CommandDispatcher", "_handle_restart")

    def _handle_die(self, message, envelope: CommandEnvelope) -> None:
        nick = self._require_registered(envelope)
        if not nick:
            return
        if not self._require_oper(envelope, nick):
            return
        self.log_stubbed_call("CommandDispatcher", "_handle_die")

    # ==================================================================
    # Stub accounting
    # ==================================================================
    #
    # Any unimplemented or partially-implemented method should call
    #   self.log_stubbed_call("ClassName", "method_name", extra=...)
    # on every invocation. This writes a structured line to the per-server
    # stub log (stubs.log under the server's data dir, falling back to
    # csc_root/stubs.log, falling back to stderr) AND emits a loud
    # [STUB-HIT] marker to the normal logger so it's obvious in journals.
    #
    # The stub log format is deliberately greppable:
    #   <iso-ts>\t<server>\t<class>\t<method>\t<extra-json>
    #
    # A later workorder can grep both the source tree (for occurrences of
    # log_stubbed_call) and the stub log (for what has actually been hit
    # in production) to reconcile "what remains stubbed" vs "what is dead".

    _stub_log_path_cache: str | None = None

    def _resolve_stub_log_path(self) -> str:
        if self._stub_log_path_cache:
            return self._stub_log_path_cache
        candidates = []
        data_dir = getattr(self.server, "data_dir", None)
        if data_dir:
            candidates.append(os.path.join(str(data_dir), "stubs.log"))
        csc_root = os.environ.get("CSC_ROOT") or os.environ.get("CSC_INSTALL_ROOT")
        if csc_root:
            candidates.append(os.path.join(str(csc_root), "stubs.log"))
        candidates.append(os.path.join(os.getcwd(), "stubs.log"))
        for path in candidates:
            try:
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                self._stub_log_path_cache = path
                return path
            except Exception:
                continue
        self._stub_log_path_cache = ""
        return ""

    def log_stubbed_call(self, class_name: str, method_name: str, **extra) -> None:
        """Record that a stubbed/unimplemented method was invoked.

        Emits a loud [STUB-HIT] line to the normal logger so it appears in
        journalctl output, and appends a structured tab-separated record to
        the stub log file for later reconciliation.
        """
        import json as _json
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        sname = getattr(self.server, "name", "?")
        extra_blob = _json.dumps(extra, sort_keys=True, default=str) if extra else "{}"
        marker = (
            f"[!!! STUB-HIT !!!] {class_name}.{method_name} "
            f"server={sname} extra={extra_blob}"
        )
        try:
            self._logger(marker)
        except Exception:
            pass
        try:
            print(marker, file=sys.stderr, flush=True)
        except Exception:
            pass
        path = self._resolve_stub_log_path()
        if path:
            try:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(f"{ts}\t{sname}\t{class_name}\t{method_name}\t{extra_blob}\n")
            except Exception:
                pass
