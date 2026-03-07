"""
IRC-compliant message handler for csc-server.

Routes all incoming UDP messages through an IRC command dispatcher.
Supports registration (NICK/USER/PASS), channels (JOIN/PART/PRIVMSG/TOPIC/NAMES/LIST),
oper commands (OPER/MODE/KICK/KILL), service commands (AI), file uploads,
and legacy IDENT/RENAME compatibility.

All service commands and file uploads are transparent on the chatline.
"""

import re
import time
import threading
from csc_service.shared.irc import (
    parse_irc_message, format_irc_message, numeric_reply, SERVER_NAME,
    RPL_WELCOME, RPL_YOURHOST, RPL_CREATED, RPL_MYINFO,
    RPL_LIST, RPL_LISTEND, RPL_NOTOPIC, RPL_TOPIC,
    RPL_NAMREPLY, RPL_ENDOFNAMES,
    RPL_MOTDSTART, RPL_MOTD, RPL_ENDOFMOTD, RPL_YOUREOPER,
    ERR_NOSUCHNICK, ERR_NOSUCHCHANNEL, ERR_CANNOTSENDTOCHAN,
    ERR_NORECIPIENT, ERR_NOTEXTTOSEND, ERR_NONICKNAMEGIVEN,
    ERR_ERRONEUSNICKNAME, ERR_NICKNAMEINUSE,
    ERR_USERNOTINCHANNEL, ERR_NOTONCHANNEL, ERR_NOTREGISTERED,
    ERR_NEEDMOREPARAMS, ERR_ALREADYREGISTRED, ERR_PASSWDMISMATCH,
    ERR_CHANOPRIVSNEEDED,
)
from csc_service.shared.crypto import DHExchange

# Valid IRC nick: letter or special first char, then letters/digits/specials
NICK_RE = re.compile(r'^[A-Za-z\[\]\\`_^{|}][A-Za-z0-9\[\]\\`_^{|}\-]*$')


class MessageHandler:
    """
    Handles all incoming UDP messages from clients, acting as the central router
    for IRC registration, chat messages, file transfers, and service commands.
    """

    def __init__(self, server, file_handler):
        """
        Initializes the instance.
        """
        self.server = server
        self.file_handler = file_handler
        self.client_registry = self.server.get_data("clients") or {}
        self.server.log(
            f"[INIT] MessageHandler loaded {len(self.client_registry)} persistent clients."
        )

        # Per-addr registration state: {addr: {state, nick, user, realname, password}}
        # state: "new", "nick_received", "user_received", "registered"
        self.registration_state = {}
        self.reg_lock = threading.Lock()

        # Track which PM buffers have been replayed per client session.
        # Set of (addr, canonical_pm_key) tuples — prevents duplicate replay.
        self._pm_buffer_replayed = set()

    # ======================================================================
    # Main Entry Point
    # ======================================================================

    def process(self, data, addr):
        """Process a raw UDP datagram from a client."""
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception as e:
            self.server.log(f"[DECODE ERROR] from {addr}: {e}")
            return

        for line in text.splitlines(True):
            raw_line = line
            line_stripped = line.strip()

            # Active file upload sessions take priority
            if addr in self.file_handler.sessions:
                self._handle_file_session_line(addr, line_stripped, raw_line)
                continue

            if not line_stripped:
                continue

            # Parse as IRC message
            msg = parse_irc_message(line_stripped)

            # Dispatch
            self._dispatch_irc_command(msg, addr, line_stripped)

    # ======================================================================
    # File Session Handling (transparent)
    # ======================================================================

    def _handle_file_session_line(self, addr, line_stripped, raw_line):
        """Handle a line while in an active file upload session."""
        nick = self._get_nick(addr)
        channel = self._get_client_channel(addr)
        prefix = f"{nick}!{nick}@{SERVER_NAME}" if nick else None

        if line_stripped.startswith("<begin file=") or line_stripped.startswith("<append file="):
            self.file_handler.abort_session(addr)
            error_msg = "[Server] Error: Nested file uploads are not supported. Session aborted.\n"
            self.server.sock_send(error_msg.encode(), addr)
        elif line_stripped.startswith("<end file>"):
            # Broadcast end marker to channel
            if nick and channel:
                broadcast_msg = format_irc_message(prefix, "PRIVMSG", [channel], line_stripped)
                self.server.broadcast_to_channel(channel, broadcast_msg + "\r\n", exclude=addr)

            result = self.file_handler.complete_session(addr)
            # Send result to sender
            self.server.sock_send(f"[Server] {result}\n".encode(), addr)
            # Broadcast result from ServiceBot
            if channel:
                result_msg = format_irc_message(
                    f"ServiceBot!service@{SERVER_NAME}", "PRIVMSG", [channel], result
                )
                self.server.broadcast_to_channel(channel, result_msg + "\r\n")
        else:
            self.file_handler.process_chunk(addr, raw_line)
            # Broadcast file chunk to channel (transparency)
            if nick and channel:
                chunk_text = raw_line.rstrip("\r\n")
                broadcast_msg = format_irc_message(prefix, "PRIVMSG", [channel], chunk_text)
                self.server.broadcast_to_channel(channel, broadcast_msg + "\r\n", exclude=addr)

    # ======================================================================
    # IRC Command Dispatcher
    # ======================================================================

    def _dispatch_irc_command(self, msg, addr, raw_line):
        """Route an IRC command to the appropriate handler."""
        command = msg.command.upper() if msg.command else ""

        # Pre-registration commands (always allowed)
        pre_reg_commands = {
            "PASS": self._handle_pass,
            "NICK": self._handle_nick,
            "USER": self._handle_user,
            "PING": self._handle_ping,
            "PONG": self._handle_pong,
            "QUIT": self._handle_quit,
            "CAP":  self._handle_cap,
            "CRYPTOINIT": self._handle_cryptoinit,
        }

        # Legacy compat
        if command == "IDENT":
            self._handle_legacy_ident(msg, addr, raw_line)
            return
        if command == "RENAME":
            self._handle_legacy_rename(msg, addr, raw_line)
            return

        if command in pre_reg_commands:
            pre_reg_commands[command](msg, addr)
            return

        # Everything else requires registration
        if not self._is_registered(addr):
            # Fallback: treat as plain text from unregistered client
            if not command or command not in (
                "JOIN", "PART", "PRIVMSG", "NOTICE", "TOPIC", "NAMES",
                "LIST", "WHO", "OPER", "KICK", "MODE", "MOTD", "KILL",
            ):
                # Could be plain text before registration — reject
                self._send_numeric(addr, ERR_NOTREGISTERED, "*", "You have not registered")
                return
            self._send_numeric(addr, ERR_NOTREGISTERED, "*", "You have not registered")
            return

        nick = self._get_nick(addr)
        self._update_last_seen(nick, addr)
        self.server.log(f"[RECV] ({nick} @ {addr}): {raw_line}")

        # Post-registration commands
        post_reg_commands = {
            "JOIN":    self._handle_join,
            "PART":    self._handle_part,
            "PRIVMSG": self._handle_privmsg,
            "NOTICE":  self._handle_notice,
            "TOPIC":   self._handle_topic,
            "NAMES":   self._handle_names,
            "LIST":    self._handle_list,
            "WHO":     self._handle_who,
            "OPER":    self._handle_oper,
            "KICK":    self._handle_kick,
            "MODE":    self._handle_mode,
            "MOTD":    self._handle_motd,
            "KILL":    self._handle_kill,
            "ISOP":    self._handle_isop,
            "WALLOPS": self._handle_wallops,
            "BUFFER":  self._handle_buffer,
        }

        if command in post_reg_commands:
            post_reg_commands[command](msg, addr)
            return

        # Service command: AI <token> <class> [method] [args]
        if command == "AI" or raw_line.upper().startswith("AI "):
            self._handle_service_via_chatline(raw_line, addr, nick)
            return

        # File upload start
        if raw_line.startswith("<begin file=") or raw_line.startswith("<append file="):
            # Require ircop or chanop for file uploads
            channel = self._get_client_channel(addr)
            if not self._is_authorized(nick, channel):
                self.server.log(f"[SECURITY] 🚫 File upload blocked from unauthorized user {nick}@{addr}")
                self.server.sock_send(b"[Server] Error: IRC operator or channel operator status required for file uploads.\n", addr)
                return

            # Broadcast start marker
            if nick and channel:
                prefix = f"{nick}!{nick}@{SERVER_NAME}"
                broadcast_msg = format_irc_message(prefix, "PRIVMSG", [channel], raw_line)
                self.server.broadcast_to_channel(channel, broadcast_msg + "\r\n", exclude=addr)
            self.file_handler.start_session(addr, raw_line)
            return

        # Fallback: treat unrecognized text from registered client as PRIVMSG to current channel
        channel = self._get_client_channel(addr)
        if channel:
            prefix = f"{nick}!{nick}@{SERVER_NAME}"
            out = format_irc_message(prefix, "PRIVMSG", [channel], raw_line)
            self.server.broadcast_to_channel(channel, out + "\r\n", exclude=addr)
        else:
            self.server.broadcast(f"({nick}) > {raw_line}", exclude=addr)

    # ======================================================================
    # Registration Handlers
    # ======================================================================

    def _ensure_reg_state(self, addr):
        """Ensure registration state exists for addr."""
        if addr not in self.registration_state:
            self.registration_state[addr] = {
                "state": "new",
                "nick": None,
                "user": None,
                "realname": None,
                "password": None,
            }

    def _handle_pass(self, msg, addr):
        """PASS <password>"""
        self._ensure_reg_state(addr)
        if self._is_registered(addr):
            self._send_numeric(addr, ERR_ALREADYREGISTRED, self._get_nick(addr),
                               "You may not reregister")
            return
        if len(msg.params) < 1:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, "*", "PASS :Not enough parameters")
            return
        self.registration_state[addr]["password"] = msg.params[0]

    def _handle_nick(self, msg, addr):
        """NICK <nickname>"""
        self._ensure_reg_state(addr)

        if len(msg.params) < 1:
            self._send_numeric(addr, ERR_NONICKNAMEGIVEN, "*", "No nickname given")
            return

        new_nick = msg.params[0]

        # Validate nick
        if not NICK_RE.match(new_nick) or len(new_nick) > 30:
            target = self._get_nick(addr) or "*"
            self._send_numeric(addr, ERR_ERRONEUSNICKNAME, target,
                               f"{new_nick} :Erroneous nickname")
            return

        # Check collision (allow self-rename)
        old_nick = self._get_nick(addr)
        if old_nick and old_nick.lower() == new_nick.lower():
            # Same nick, just update case
            pass
        else:
            for a, info in list(self.server.clients.items()):
                if info.get("name", "").lower() == new_nick.lower() and a != addr:
                    target = old_nick or "*"
                    self._send_numeric(addr, ERR_NICKNAMEINUSE, target,
                                       f"{new_nick} :Nickname is already in use")
                    return

        reg = self.registration_state[addr]

        # Already registered? This is a nick change
        if self._is_registered(addr):
            old_nick = reg["nick"]
            old_prefix = f"{old_nick}!{old_nick}@{SERVER_NAME}"

            # Update all tracking
            reg["nick"] = new_nick
            self.server.clients[addr]["name"] = new_nick

            # Update channel memberships
            for ch in self.server.channel_manager.find_channels_for_nick(old_nick):
                member_info = ch.members.pop(old_nick, None)
                if member_info:
                    ch.members[new_nick] = member_info

            # Update oper status
            if old_nick in self.server.opers:
                self.server.opers.discard(old_nick)
                self.server.opers.add(new_nick)

            # Update persistent registry
            if old_nick in self.client_registry:
                entry = self.client_registry.pop(old_nick)
                self.client_registry[new_nick] = entry
                self.server.put_data("clients", self.client_registry)

            # Broadcast nick change to all channels the user is in
            nick_msg = f":{old_prefix} NICK {new_nick}\r\n"
            notified = set()
            for ch in self.server.channel_manager.find_channels_for_nick(new_nick):
                for member_nick, member_info in list(ch.members.items()):
                    member_addr = member_info.get("addr")
                    if member_addr and member_addr not in notified:
                        self.server.sock_send(nick_msg.encode(), member_addr)
                        notified.add(member_addr)
            # Also notify the user themselves
            if addr not in notified:
                self.server.sock_send(nick_msg.encode(), addr)

            self.server.log(f"[NICK] {old_nick} changed nick to {new_nick}")
        else:
            reg["nick"] = new_nick
            self._try_complete_registration(addr)

    def _handle_user(self, msg, addr):
        """USER <username> <mode> <unused> :<realname>"""
        self._ensure_reg_state(addr)
        if self._is_registered(addr):
            self._send_numeric(addr, ERR_ALREADYREGISTRED, self._get_nick(addr),
                               "You may not reregister")
            return

        if len(msg.params) < 4:
            target = self._get_nick(addr) or "*"
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, target, "USER :Not enough parameters")
            return

        reg = self.registration_state[addr]
        reg["user"] = msg.params[0]
        reg["realname"] = msg.params[3]  # trailing param (after the :)
        self._try_complete_registration(addr)

    def _try_complete_registration(self, addr):
        """Check if both NICK and USER have been received; if so, complete registration."""
        reg = self.registration_state.get(addr)
        if not reg:
            return
        if not reg["nick"] or not reg["user"]:
            return
        if reg["state"] == "registered":
            return

        nick = reg["nick"]
        reg["state"] = "registered"
        now = time.time()

        # Persist to client registry
        password = reg.get("password") or ""
        if nick not in self.client_registry:
            self.client_registry[nick] = {
                "password": password,
                "addresses": [list(addr)],
                "last_seen": {f"{addr[0]}:{addr[1]}": now},
            }
        else:
            entry = self.client_registry[nick]
            if list(addr) not in entry.get("addresses", []):
                entry.setdefault("addresses", []).append(list(addr))
            entry.setdefault("last_seen", {})[f"{addr[0]}:{addr[1]}"] = now

        self.server.clients[addr] = {"name": nick, "last_seen": now}
        self.server.put_data("clients", self.client_registry)

        # Send welcome burst (001-004)
        self._send_numeric(addr, RPL_WELCOME, nick,
                           f"Welcome to {SERVER_NAME} Network, {nick}")
        self._send_numeric(addr, RPL_YOURHOST, nick,
                           f"Your host is {SERVER_NAME}, running csc-server")
        self._send_numeric(addr, RPL_CREATED, nick,
                           "This server was created recently")
        self._send_numeric(addr, RPL_MYINFO, nick,
                           f"{SERVER_NAME} csc-server o o")

        # Send MOTD
        self._send_motd(addr, nick)

        # Auto-join #general
        from irc import IRCMessage
        join_msg = IRCMessage(command="JOIN", params=["#general"])
        self._handle_join(join_msg, addr)

        self.server.log(f"[REG] {nick} completed registration from {addr}")

    # ======================================================================
    # Channel Handlers
    # ======================================================================

    def _handle_join(self, msg, addr):
        """JOIN <channel>[,<channel>...]"""
        nick = self._get_nick(addr)
        if not nick:
            self.server.log(f"[JOIN] ERROR: Could not get nick for {addr}, cannot JOIN")
            return
        if len(msg.params) < 1:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "JOIN :Not enough parameters")
            return

        channels = msg.params[0].split(",")
        for chan_name in channels:
            chan_name = chan_name.strip()
            if not chan_name.startswith("#"):
                chan_name = "#" + chan_name

            channel = self.server.channel_manager.ensure_channel(chan_name)

            if channel.has_member(nick):
                self.server.log(f"[JOIN] {nick} already in {chan_name}")
                continue  # Already in channel

            channel.add_member(nick, addr)
            self.server.log(f"[JOIN] Added {nick} to {chan_name}, channel now has {channel.member_count()} members")

            # Broadcast JOIN to all channel members (including the joiner)
            prefix = f"{nick}!{nick}@{SERVER_NAME}"
            join_msg = f":{prefix} JOIN {chan_name}\r\n"
            for member_nick, member_info in list(channel.members.items()):
                member_addr = member_info.get("addr")
                if member_addr:
                    self.server.sock_send(join_msg.encode(), member_addr)

            # Send topic
            if channel.topic:
                self._send_numeric(addr, RPL_TOPIC, nick, f"{chan_name} :{channel.topic}")
            else:
                self._send_numeric(addr, RPL_NOTOPIC, nick, f"{chan_name} :No topic is set")

            # Send names list
            self._send_names(addr, nick, channel)

            # Auto-replay chat buffer
            self._send_buffer_replay(addr, nick, chan_name)

    def _handle_part(self, msg, addr):
        """PART <channel>[,<channel>...] [:<reason>]"""
        nick = self._get_nick(addr)
        if len(msg.params) < 1:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "PART :Not enough parameters")
            return

        chan_names = msg.params[0].split(",")
        reason = msg.params[1] if len(msg.params) > 1 else "Leaving"

        for chan_name in chan_names:
            chan_name = chan_name.strip()
            channel = self.server.channel_manager.get_channel(chan_name)
            if not channel:
                self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                                   f"{chan_name} :No such channel")
                continue
            if not channel.has_member(nick):
                self._send_numeric(addr, ERR_NOTONCHANNEL, nick,
                                   f"{chan_name} :You're not on that channel")
                continue

            # Broadcast PART to channel members (including the parting user)
            prefix = f"{nick}!{nick}@{SERVER_NAME}"
            part_msg = format_irc_message(prefix, "PART", [chan_name], reason) + "\r\n"
            for member_nick, member_info in list(channel.members.items()):
                member_addr = member_info.get("addr")
                if member_addr:
                    self.server.sock_send(part_msg.encode(), member_addr)

            channel.remove_member(nick)

            # Clean up empty non-default channels
            if channel.member_count() == 0 and chan_name != self.server.channel_manager.DEFAULT_CHANNEL:
                self.server.channel_manager.remove_channel(chan_name)

    def _handle_privmsg(self, msg, addr):
        """PRIVMSG <target> :<text>"""
        nick = self._get_nick(addr)
        if len(msg.params) < 1:
            self._send_numeric(addr, ERR_NORECIPIENT, nick, "No recipient given (PRIVMSG)")
            return
        if len(msg.params) < 2:
            self._send_numeric(addr, ERR_NOTEXTTOSEND, nick, "No text to send")
            return

        target = msg.params[0]
        text = msg.params[-1]  # trailing text

        prefix = f"{nick}!{nick}@{SERVER_NAME}"

        if target.startswith("#"):
            # Channel message
            channel = self.server.channel_manager.get_channel(target)
            if not channel:
                self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                                   f"{target} :No such channel")
                return
            if not channel.has_member(nick):
                self._send_numeric(addr, ERR_CANNOTSENDTOCHAN, nick,
                                   f"{target} :Cannot send to channel")
                return
            # Check +m (moderated) — only ops/voiced/opers can speak
            if not channel.can_speak(nick) and nick not in self.server.opers:
                self._send_numeric(addr, ERR_CANNOTSENDTOCHAN, nick,
                                   f"{target} :Cannot send to channel (+m)")
                return

            out = format_irc_message(prefix, "PRIVMSG", [target], text) + "\r\n"
            self.server.broadcast_to_channel(target, out, exclude=addr)
            self.server.chat_buffer.append(target, nick, "PRIVMSG", text)

            # Check for embedded service command (AI ...)
            if text.upper().startswith("AI "):
                self._handle_service_via_chatline(text, addr, nick)
            # Check for embedded file upload start
            elif text.startswith("<begin file=") or text.startswith("<append file="):
                # Require ircop or chanop for file uploads
                if not self._is_authorized(nick, target):
                    self.server.log(f"[SECURITY] 🚫 File upload blocked from unauthorized user {nick}@{addr}")
                    self.server.sock_send(b"[Server] Error: IRC operator or channel operator status required for file uploads.\n", addr)
                    return
                self.file_handler.start_session(addr, text)
        else:
            # Private message to a nick
            self._maybe_replay_pm_buffer(target, nick)
            out = format_irc_message(prefix, "PRIVMSG", [target], text) + "\r\n"
            if not self.server.send_to_nick(target, out):
                self._send_numeric(addr, ERR_NOSUCHNICK, nick,
                                   f"{target} :No such nick/channel")
            else:
                self.server.chat_buffer.append(target, nick, "PRIVMSG", text)

    def _handle_notice(self, msg, addr):
        """NOTICE <target> :<text> — same as PRIVMSG but no auto-reply expected."""
        nick = self._get_nick(addr)
        if len(msg.params) < 2:
            return  # NOTICE errors are silently dropped per RFC

        target = msg.params[0]
        text = msg.params[-1]
        prefix = f"{nick}!{nick}@{SERVER_NAME}"

        if target.startswith("#"):
            channel = self.server.channel_manager.get_channel(target)
            if channel and channel.has_member(nick):
                out = format_irc_message(prefix, "NOTICE", [target], text) + "\r\n"
                self.server.broadcast_to_channel(target, out, exclude=addr)
                self.server.chat_buffer.append(target, nick, "NOTICE", text)
        else:
            self._maybe_replay_pm_buffer(target, nick)
            out = format_irc_message(prefix, "NOTICE", [target], text) + "\r\n"
            if self.server.send_to_nick(target, out):
                self.server.chat_buffer.append(target, nick, "NOTICE", text)

    def _handle_topic(self, msg, addr):
        """TOPIC <channel> [:<new topic>]"""
        nick = self._get_nick(addr)
        if len(msg.params) < 1:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "TOPIC :Not enough parameters")
            return

        chan_name = msg.params[0]
        channel = self.server.channel_manager.get_channel(chan_name)
        if not channel:
            self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                               f"{chan_name} :No such channel")
            return
        if not channel.has_member(nick):
            self._send_numeric(addr, ERR_NOTONCHANNEL, nick,
                               f"{chan_name} :You're not on that channel")
            return

        if len(msg.params) < 2:
            # Query topic
            if channel.topic:
                self._send_numeric(addr, RPL_TOPIC, nick, f"{chan_name} :{channel.topic}")
            else:
                self._send_numeric(addr, RPL_NOTOPIC, nick, f"{chan_name} :No topic is set")
        else:
            # Set topic — check +t mode
            if not channel.can_set_topic(nick) and nick not in self.server.opers:
                self._send_numeric(addr, ERR_CHANOPRIVSNEEDED, nick,
                                   f"{chan_name} :You're not channel operator (+t)")
                return
            new_topic = msg.params[-1]
            channel.topic = new_topic
            prefix = f"{nick}!{nick}@{SERVER_NAME}"
            topic_msg = format_irc_message(prefix, "TOPIC", [chan_name], new_topic) + "\r\n"
            for member_nick, member_info in list(channel.members.items()):
                member_addr = member_info.get("addr")
                if member_addr:
                    self.server.sock_send(topic_msg.encode(), member_addr)

    def _handle_names(self, msg, addr):
        """NAMES [<channel>]"""
        nick = self._get_nick(addr)
        if msg.params:
            chan_name = msg.params[0]
            channel = self.server.channel_manager.get_channel(chan_name)
            if channel:
                self._send_names(addr, nick, channel)
            else:
                self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                                   f"{chan_name} :No such channel")
        else:
            # Names for all channels
            for channel in self.server.channel_manager.list_channels():
                self._send_names(addr, nick, channel)

    def _handle_list(self, msg, addr):
        """LIST — list all channels."""
        nick = self._get_nick(addr)
        for channel in self.server.channel_manager.list_channels():
            reply = f":{SERVER_NAME} {RPL_LIST} {nick} {channel.name} {channel.member_count()} :{channel.topic}\r\n"
            self.server.sock_send(reply.encode(), addr)
        end = f":{SERVER_NAME} {RPL_LISTEND} {nick} :End of /LIST\r\n"
        self.server.sock_send(end.encode(), addr)

    def _handle_who(self, msg, addr):
        """WHO <channel> — basic WHO reply."""
        nick = self._get_nick(addr)
        if not msg.params:
            return
        chan_name = msg.params[0]
        channel = self.server.channel_manager.get_channel(chan_name)
        if channel:
            for member_nick in channel.members:
                # Simplified WHO reply
                line = f":{SERVER_NAME} 352 {nick} {chan_name} {member_nick} {SERVER_NAME} {SERVER_NAME} {member_nick} H :0 {member_nick}\r\n"
                self.server.sock_send(line.encode(), addr)
        end = f":{SERVER_NAME} 315 {nick} {chan_name} :End of /WHO list\r\n"
        self.server.sock_send(end.encode(), addr)

    # ======================================================================
    # Oper / Admin Handlers
    # ======================================================================

    def _handle_oper(self, msg, addr):
        """OPER <name> <password>"""
        nick = self._get_nick(addr)
        if len(msg.params) < 2:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "OPER :Not enough parameters")
            return

        oper_name = msg.params[0]
        oper_pass = msg.params[1]

        creds = self.server.oper_credentials
        if oper_name in creds and creds[oper_name] == oper_pass:
            self.server.opers.add(nick)
            self._send_numeric(addr, RPL_YOUREOPER, nick, "You are now an IRC operator")
            self.server.log(f"[OPER] {nick} authenticated as oper '{oper_name}'")
            self.server.send_wallops(f"{nick} is now an IRC operator (auth: {oper_name})")
        else:
            self._send_numeric(addr, ERR_PASSWDMISMATCH, nick, "Password incorrect")

    # Modes that require a nick parameter
    _NICK_MODES = frozenset(("o", "v"))
    # Channel-level flag modes (no parameter)
    _FLAG_MODES = frozenset(("m", "t"))

    def _handle_mode(self, msg, addr):
        """
        MODE <target> <modestring> [param1] [param2] ...

        Supports combined mode strings with up to 6 changes per command.
        Examples:
          MODE #general +ov nick1 nick2
          MODE #general +mt
          MODE #general -o+v nick1 nick2
          MODE +o <nick> <pass>  — oper auth (like OPER)
        """
        nick = self._get_nick(addr)
        if len(msg.params) < 2:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "MODE :Not enough parameters")
            return

        target = msg.params[0]

        if target.startswith("#"):
            self._handle_channel_mode(msg, addr, nick, target)
        else:
            # User mode — support MODE +o <nick> <pass> as oper auth
            mode_str = target
            if mode_str == "+o" and len(msg.params) >= 3:
                oper_nick = msg.params[1]
                oper_pass = msg.params[2]
                from irc import IRCMessage
                oper_msg = IRCMessage(command="OPER", params=[oper_nick, oper_pass])
                self._handle_oper(oper_msg, addr)

    def _handle_channel_mode(self, msg, addr, nick, chan_name):
        """Parse and apply combined channel mode changes (up to 6 per command)."""
        mode_str = msg.params[1]
        channel = self.server.channel_manager.get_channel(chan_name)
        if not channel:
            self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                               f"{chan_name} :No such channel")
            return

        # Require chanop or oper for all channel mode changes
        if nick not in self.server.opers and not channel.is_op(nick):
            self._send_numeric(addr, ERR_CHANOPRIVSNEEDED, nick,
                               f"{chan_name} :You're not channel operator")
            return

        # Parse the mode string into a list of (direction, char) tuples
        changes = []
        direction = "+"
        for ch in mode_str:
            if ch in ("+", "-"):
                direction = ch
            elif ch in self._NICK_MODES or ch in self._FLAG_MODES:
                changes.append((direction, ch))
            # Ignore unknown mode chars silently

        # Enforce max 6 mode changes per command
        if len(changes) > 6:
            changes = changes[:6]

        # Parameters for nick-targeting modes, consumed in order
        param_index = 2  # msg.params[0]=channel, [1]=modestring, [2..]=params

        # Track what was actually applied for the broadcast
        applied_modes = ""
        applied_params = []
        last_dir = None

        for direction, mode_char in changes:
            if mode_char in self._NICK_MODES:
                # Needs a nick parameter
                if param_index >= len(msg.params):
                    self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick,
                                       f"MODE :Not enough parameters for {direction}{mode_char}")
                    continue
                target_nick = msg.params[param_index]
                param_index += 1

                if not channel.has_member(target_nick):
                    self._send_numeric(addr, ERR_USERNOTINCHANNEL, nick,
                                       f"{target_nick} {chan_name} :They aren't on that channel")
                    continue

                if direction == "+":
                    channel.members[target_nick]["modes"].add(mode_char)
                else:
                    channel.members[target_nick]["modes"].discard(mode_char)

                if direction != last_dir:
                    applied_modes += direction
                    last_dir = direction
                applied_modes += mode_char
                applied_params.append(target_nick)

            elif mode_char in self._FLAG_MODES:
                # Channel flag, no parameter
                if direction == "+":
                    channel.modes.add(mode_char)
                else:
                    channel.modes.discard(mode_char)

                if direction != last_dir:
                    applied_modes += direction
                    last_dir = direction
                applied_modes += mode_char

        if not applied_modes:
            return

        # Broadcast the combined mode change
        prefix = f"{nick}!{nick}@{SERVER_NAME}"
        params_str = (" " + " ".join(applied_params)) if applied_params else ""
        mode_msg = f":{prefix} MODE {chan_name} {applied_modes}{params_str}\r\n"
        for m_nick, m_info in list(channel.members.items()):
            m_addr = m_info.get("addr")
            if m_addr:
                self.server.sock_send(mode_msg.encode(), m_addr)

        # WALLOPS for mode changes
        self.server.send_wallops(f"{nick} set MODE {chan_name} {applied_modes}{params_str}")

    def _handle_kick(self, msg, addr):
        """KICK <channel> <nick> [:<reason>]"""
        nick = self._get_nick(addr)
        if len(msg.params) < 2:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "KICK :Not enough parameters")
            return

        chan_name = msg.params[0]
        target_nick = msg.params[1]
        reason = msg.params[2] if len(msg.params) > 2 else nick

        channel = self.server.channel_manager.get_channel(chan_name)
        if not channel:
            self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                               f"{chan_name} :No such channel")
            return

        # Require oper or chanop
        if nick not in self.server.opers and not channel.is_op(nick):
            self._send_numeric(addr, ERR_CHANOPRIVSNEEDED, nick,
                               f"{chan_name} :You're not channel operator")
            return

        if not channel.has_member(target_nick):
            self._send_numeric(addr, ERR_USERNOTINCHANNEL, nick,
                               f"{target_nick} {chan_name} :They aren't on that channel")
            return

        # Broadcast KICK
        prefix = f"{nick}!{nick}@{SERVER_NAME}"
        kick_msg = format_irc_message(prefix, "KICK", [chan_name, target_nick], reason) + "\r\n"
        for m_nick, m_info in list(channel.members.items()):
            m_addr = m_info.get("addr")
            if m_addr:
                self.server.sock_send(kick_msg.encode(), m_addr)

        channel.remove_member(target_nick)
        self.server.send_wallops(f"{nick} kicked {target_nick} from {chan_name}: {reason}")

    def _handle_kill(self, msg, addr):
        """KILL <nick> [:<reason>] — oper only, disconnect user from all channels."""
        nick = self._get_nick(addr)
        if nick not in self.server.opers:
            self._send_numeric(addr, ERR_CHANOPRIVSNEEDED, nick,
                               "KILL :Permission Denied- You're not an IRC operator")
            return

        if len(msg.params) < 1:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "KILL :Not enough parameters")
            return

        target_nick = msg.params[0]
        reason = msg.params[1] if len(msg.params) > 1 else "Killed by operator"

        # Find target address
        target_addr = None
        for a, info in list(self.server.clients.items()):
            if info.get("name") == target_nick:
                target_addr = a
                break

        if not target_addr:
            self._send_numeric(addr, ERR_NOSUCHNICK, nick,
                               f"{target_nick} :No such nick/channel")
            return

        # Broadcast KILL to channels
        prefix = f"{nick}!{nick}@{SERVER_NAME}"
        kill_msg = format_irc_message(prefix, "KILL", [target_nick], reason) + "\r\n"

        # Notify all channels the target was in
        channels = self.server.channel_manager.find_channels_for_nick(target_nick)
        for ch in channels:
            for m_nick, m_info in list(ch.members.items()):
                m_addr = m_info.get("addr")
                if m_addr:
                    self.server.sock_send(kill_msg.encode(), m_addr)

        # Remove from all channels
        self.server.channel_manager.remove_nick_from_all(target_nick)

        # Send ERROR to the killed user
        error_msg = f"ERROR :Closing Link: {target_nick} (Killed ({nick} ({reason})))\r\n"
        self.server.sock_send(error_msg.encode(), target_addr)

        # Remove from active clients
        self.server.clients.pop(target_addr, None)
        self.registration_state.pop(target_addr, None)
        self._pm_buffer_replayed = {k for k in self._pm_buffer_replayed if k[0] != target_addr}

        self.server.log(f"[KILL] {nick} killed {target_nick}: {reason}")
        self.server.send_wallops(f"{nick} killed {target_nick}: {reason}")

    def _handle_motd(self, msg, addr):
        """MOTD — send the message of the day."""
        nick = self._get_nick(addr)
        self._send_motd(addr, nick)

    # ======================================================================
    # Buffer Replay
    # ======================================================================

    def _handle_buffer(self, msg, addr):
        """BUFFER <target> [full] — replay the chat buffer for a channel or PM target."""
        nick = self._get_nick(addr)
        if len(msg.params) < 1:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "BUFFER :Not enough parameters")
            return

        target = msg.params[0]
        full_history = False
        if len(msg.params) > 1:
            arg = msg.params[1].lower()
            if arg in ("full", "all") or (arg.isdigit() and int(arg) > 1024):
                full_history = True

        if target.startswith("#"):
            channel = self.server.channel_manager.get_channel(target)
            if not channel:
                self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                                   f"{target} :No such channel")
                return
            if not channel.has_member(nick):
                self._send_numeric(addr, ERR_NOTONCHANNEL, nick,
                                   f"{target} :You're not on that channel")
                return

        self._send_buffer_replay(addr, nick, target, full_history=full_history)

    def _send_buffer_replay(self, addr, nick, target, full_history=False):
        """Read the buffer for *target* and send each line as a NOTICE to *addr*."""
        limit = None if full_history else 1024
        lines = self.server.chat_buffer.read(target, sender_nick=nick, limit_bytes=limit)
        count = len(lines)

        prefix = f":{SERVER_NAME} NOTICE {nick} :[BUFFER]"

        # Start marker
        mode_str = "FULL" if full_history else "PARTIAL (1KB)"
        start = f"{prefix} -- Start of buffer replay for {target} ({count} lines, {mode_str}) --\r\n"
        self.server.sock_send(start.encode(), addr)

        for line in lines:
            stripped = line.rstrip("\n\r")
            replay = f"{prefix} {stripped}\r\n"
            self.server.sock_send(replay.encode(), addr)

        # End marker
        end = f"{prefix} -- End of buffer replay for {target} --\r\n"
        self.server.sock_send(end.encode(), addr)

    def _is_authorized(self, nick, channel_name=None):
        """
        Check if a nick is authorized (IRC operator or channel operator).
        
        Args:
            nick: The nickname to check.
            channel_name: Optional channel name to check for chanop status.
            
        Returns:
            bool: True if authorized, False otherwise.
        """
        if not nick:
            return False

        # IRC operators are globally authorized
        if nick in self.server.opers:
            return True

        # Check channel operator status
        if channel_name:
            channel = self.server.channel_manager.get_channel(channel_name)
            if channel and channel.is_op(nick):
                return True
        else:
            # Check if op on ANY channel
            for ch in self.server.channel_manager.find_channels_for_nick(nick):
                if ch.is_op(nick):
                    return True

        return False

    def _maybe_replay_pm_buffer(self, recipient_nick, sender_nick):
        """
        On first PM to *recipient_nick* from *sender_nick* in this session,
        auto-replay the PM buffer to the recipient so they see prior history.
        """
        # Find recipient address
        recipient_addr = None
        for a, info in list(self.server.clients.items()):
            if info.get("name") == recipient_nick:
                recipient_addr = a
                break
        if not recipient_addr:
            return

        # Canonical PM key: sorted lowercase nicks
        pm_key = tuple(sorted([sender_nick.lower(), recipient_nick.lower()]))
        track_key = (recipient_addr, pm_key)

        if track_key in self._pm_buffer_replayed:
            return  # already replayed this session

        # Check if there's actually any history to replay
        lines = self.server.chat_buffer.read(recipient_nick, sender_nick=sender_nick)
        if not lines:
            self._pm_buffer_replayed.add(track_key)
            return

        self._pm_buffer_replayed.add(track_key)
        self._send_buffer_replay(recipient_addr, recipient_nick, sender_nick, full_history=False)

    # ======================================================================
    # Utility Handlers
    # ======================================================================

    def _handle_ping(self, msg, addr):
        """PING :<token> -> PONG :<token>"""
        token = msg.params[0] if msg.params else SERVER_NAME
        pong = f":{SERVER_NAME} PONG {SERVER_NAME} :{token}\r\n"
        self.server.sock_send(pong.encode(), addr)

    def _handle_pong(self, msg, addr):
        """PONG — just update last_seen."""
        nick = self._get_nick(addr)
        if nick:
            self._update_last_seen(nick, addr)

    def _handle_quit(self, msg, addr):
        """QUIT [:<message>]"""
        nick = self._get_nick(addr)
        reason = msg.params[0] if msg.params else "Client Quit"

        if nick:
            prefix = f"{nick}!{nick}@{SERVER_NAME}"
            quit_msg = format_irc_message(prefix, "QUIT", [], reason) + "\r\n"

            # Notify all channels
            channels = self.server.channel_manager.find_channels_for_nick(nick)
            notified = set()
            for ch in channels:
                for m_nick, m_info in list(ch.members.items()):
                    m_addr = m_info.get("addr")
                    if m_addr and m_addr != addr and m_addr not in notified:
                        self.server.sock_send(quit_msg.encode(), m_addr)
                        notified.add(m_addr)

            self.server.channel_manager.remove_nick_from_all(nick)

        # Send ERROR to the quitting client
        error_msg = f"ERROR :Closing Link: {nick or 'unknown'} ({reason})\r\n"
        self.server.sock_send(error_msg.encode(), addr)

        self.server.clients.pop(addr, None)
        self.registration_state.pop(addr, None)
        self._pm_buffer_replayed = {k for k in self._pm_buffer_replayed if k[0] != addr}

    def _handle_cap(self, msg, addr):
        """CAP — capability negotiation stub. Just acknowledge."""
        # We don't support CAP negotiation, but some clients send it
        pass

    def _handle_cryptoinit(self, msg, addr):
        """CRYPTOINIT DH <p> <g> <pub>"""
        # Reconstruct the raw line from the message object since parse_init_message expects it
        # Or just adapt parse_init_message? DHExchange.parse_init_message takes a string line.
        # We can construct a synthetic line or manually parse params.
        
        # params: ["DH", "p_hex", "g_hex", "pub_hex"]
        if len(msg.params) < 4 or msg.params[0] != "DH":
            return

        try:
            p = int(msg.params[1], 16)
            g = int(msg.params[2], 16)
            client_pub = int(msg.params[3], 16)

            # Generate server-side keypair
            dh = DHExchange()
            
            # Compute shared key
            shared_key = dh.compute_shared_key(client_pub)
            
            # Store key for this address
            self.server.encryption_keys[addr] = shared_key
            self.server.log(f"[CRYPTO] Established encrypted session with {addr}")

            # Send reply
            # CRYPTOINIT DHREPLY <pub_hex>
            # We send this as plaintext because the client doesn't have the key yet until it processes this reply.
            reply = dh.format_reply_message()
            self.server.sock_send(reply.encode("utf-8"), addr)

        except Exception as e:
            self.server.log(f"[CRYPTO] Handshake error with {addr}: {e}")

    # ======================================================================
    # Legacy Compatibility
    # ======================================================================

    def _handle_legacy_ident(self, msg, addr, raw_line):
        """Convert legacy IDENT <name> [password] to NICK + USER registration."""
        parts = raw_line.split(maxsplit=2)
        name = parts[1] if len(parts) > 1 else None
        password = parts[2] if len(parts) > 2 else None

        if not name:
            self.server.sock_send(b"[Server] Invalid IDENT syntax.\n", addr)
            return

        self._ensure_reg_state(addr)

        if password:
            self.registration_state[addr]["password"] = password

        # Simulate NICK
        from irc import IRCMessage
        nick_msg = IRCMessage(command="NICK", params=[name])
        self._handle_nick(nick_msg, addr)

        # Simulate USER
        user_msg = IRCMessage(command="USER", params=[name, "0", "*", name])
        self._handle_user(user_msg, addr)

    def _handle_legacy_rename(self, msg, addr, raw_line):
        """Convert legacy RENAME <old> <new> to NICK change."""
        parts = raw_line.split(maxsplit=2)
        if len(parts) < 3:
            self.server.sock_send(b"[Server] Invalid RENAME command. Usage: RENAME <old> <new>\n", addr)
            return

        new_name = parts[2]
        from irc import IRCMessage
        nick_msg = IRCMessage(command="NICK", params=[new_name])
        self._handle_nick(nick_msg, addr)

    # ======================================================================
    # ISOP and WALLOPS
    # ======================================================================

    def _handle_isop(self, msg, addr):
        """ISOP <nick> — returns whether nick is an IRC operator."""
        nick = self._get_nick(addr)
        target = msg.params[0] if msg.params else nick
        is_oper = target in self.server.opers
        reply = f":{SERVER_NAME} NOTICE {nick} :ISOP {target} {'YES' if is_oper else 'NO'}\r\n"
        self.server.sock_send(reply.encode(), addr)

    def _handle_wallops(self, msg, addr):
        """WALLOPS :<message> — oper only, broadcasts to all opers."""
        nick = self._get_nick(addr)
        if nick not in self.server.opers:
            self._send_numeric(addr, ERR_CHANOPRIVSNEEDED, nick,
                               "WALLOPS :Permission Denied- You're not an IRC operator")
            return
        if len(msg.params) < 1:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "WALLOPS :Not enough parameters")
            return
        text = msg.params[-1]
        wallops_msg = f":{nick}!{nick}@{SERVER_NAME} WALLOPS :{text}\r\n"
        for a, info in list(self.server.clients.items()):
            client_nick = info.get("name")
            if client_nick and client_nick in self.server.opers:
                self.server.sock_send(wallops_msg.encode(), a)
        self.server.log(f"[WALLOPS] {nick}: {text}")

    # ======================================================================
    # Service Command (Transparent on Chatline)
    # ======================================================================

    def _handle_service_via_chatline(self, line, addr, nick):
        """
        Handle a service command (AI <token> <class> [method] [args]).
        The command has already been broadcast as PRIVMSG to the channel.
        Execute and broadcast result from ServiceBot.
        Requires ircop status for server-side execution.
        """
        token = ""
        result = ""
        channel = self._get_client_channel(addr)

        # Require ircop or chanop for server-side AI service commands
        if not self._is_authorized(nick, channel):
            err_msg = f"Permission denied — IRC operator or channel operator status required"
            self.server.log(f"[COMMAND DENIED] {nick} is not authorized: {line}")
            if channel:
                service_prefix = f"ServiceBot!service@{SERVER_NAME}"
                result_msg = format_irc_message(service_prefix, "PRIVMSG", [channel], err_msg) + "\r\n"
                self.server.broadcast_to_channel(channel, result_msg)
            return

        try:
            parts = line.split()
            if len(parts) < 3:
                result = "Error: Invalid command format. Expected: AI <token> <class> [method] [args...]"
            else:
                keyword, token, class_name_raw = parts[:3]
                method_name_raw = parts[3] if len(parts) > 3 else "default"
                args = parts[4:] if len(parts) > 4 else []
                arg_str = ' '.join(args) if args else "no args"
                self.server.log(
                    f"[COMMAND] from {nick}: token={token}, class={class_name_raw}, "
                    f"method={method_name_raw}, args=[{arg_str}]"
                )
                result = self.server.handle_command(class_name_raw, method_name_raw, args, nick, addr)
        except Exception as e:
            result = f"Error executing command: {e}"
            self.server.log(f"[COMMAND ERROR] {e}")

        if token == "0":
            self.server.log(f"Token '0' received. Suppressing response for command: {line}")
            return

        # Broadcast result from ServiceBot to the channel
        full_response = f"{token} {result}"
        if not full_response.endswith('\n'):
            full_response = full_response.rstrip('\n')

        self.server.log(f"[SERVICE_RESPONSE] Channel='{channel}', Result='{result}', FullResponse='{full_response}'")
        if channel:
            service_prefix = f"ServiceBot!service@{SERVER_NAME}"
            result_msg = format_irc_message(service_prefix, "PRIVMSG", [channel], full_response) + "\r\n"
            self.server.log(f"[SERVICE_RESPONSE] Broadcasting to channel '{channel}'")
            self.server.broadcast_to_channel(channel, result_msg)
        else:
            # Fallback: broadcast to all
            self.server.log(f"[SERVICE_RESPONSE] No channel found, broadcasting to all")
            broadcast_text = full_response + "\n"
            self.server.broadcast(broadcast_text.encode("utf-8"))

    # ======================================================================
    # Helper Methods
    # ======================================================================

    def _get_nick(self, addr):
        """Get the nick for an address."""
        reg = self.registration_state.get(addr)
        if reg and reg.get("nick"):
            return reg["nick"]
        record = self.server.clients.get(addr)
        if record:
            return record.get("name")
        return None

    def _get_user(self, addr):
        """Get the username for an address."""
        reg = self.registration_state.get(addr)
        if reg:
            return reg.get("user")
        return None

    def _is_registered(self, addr):
        """Check if an address has completed IRC registration."""
        reg = self.registration_state.get(addr)
        if reg and reg.get("state") == "registered":
            return True
        # Check if they were previously registered (reconnection)
        record = self.server.clients.get(addr)
        if record and "name" in record:
            nick = record["name"]
            # Auto-populate registration state
            self._ensure_reg_state(addr)
            self.registration_state[addr]["state"] = "registered"
            self.registration_state[addr]["nick"] = nick
            self.registration_state[addr]["user"] = nick
            return True
        # Check persistent registry
        for name, entry in list(self.client_registry.items()):
            addr_list = [tuple(a) if isinstance(a, list) else a for a in entry.get("addresses", [])]
            if addr in addr_list:
                self.server.clients[addr] = {"name": name, "last_seen": time.time()}
                self._ensure_reg_state(addr)
                self.registration_state[addr]["state"] = "registered"
                self.registration_state[addr]["nick"] = name
                self.registration_state[addr]["user"] = name
                return True
        return False

    def _get_client_channel(self, addr):
        """Find the primary/current channel for a client."""
        nick = self._get_nick(addr)
        if not nick:
            return None
        channels = self.server.channel_manager.find_channels_for_nick(nick)
        if channels:
            return channels[0].name
        return self.server.channel_manager.DEFAULT_CHANNEL

    def _send_numeric(self, addr, numeric, target_nick, text):
        """Send a numeric reply to an address."""
        line = f":{SERVER_NAME} {numeric} {target_nick} :{text}\r\n"
        self.server.sock_send(line.encode(), addr)

    def _send_names(self, addr, nick, channel):
        """Send RPL_NAMREPLY + RPL_ENDOFNAMES for a channel."""
        names = channel.get_names_list()
        reply = f":{SERVER_NAME} {RPL_NAMREPLY} {nick} = {channel.name} :{names}\r\n"
        self.server.sock_send(reply.encode(), addr)
        end = f":{SERVER_NAME} {RPL_ENDOFNAMES} {nick} {channel.name} :End of /NAMES list\r\n"
        self.server.sock_send(end.encode(), addr)

    def _send_motd(self, addr, nick):
        """Send MOTD as 375/372/376 numerics."""
        motd = self.server.get_data("motd") or "Welcome to csc-server!"
        self._send_numeric(addr, RPL_MOTDSTART, nick, f"- {SERVER_NAME} Message of the Day -")
        # Split MOTD into lines
        for line in motd.split("\n"):
            self._send_numeric(addr, RPL_MOTD, nick, f"- {line}")
        self._send_numeric(addr, RPL_ENDOFMOTD, nick, "End of /MOTD command")

    def _update_last_seen(self, name, addr):
        """Update the last_seen timestamp for an active client."""
        now = time.time()
        if addr in self.server.clients:
            self.server.clients[addr]["last_seen"] = now
        if name in self.client_registry:
            entry = self.client_registry[name]
            if "last_seen" not in entry:
                entry["last_seen"] = {}
            entry["last_seen"][f"{addr[0]}:{addr[1]}"] = now

    # Legacy compatibility for handle_service_command
    def handle_service_command(self, line, addr, client_name):
        """Legacy entry point for service commands."""
        self._handle_service_via_chatline(line, addr, client_name)
