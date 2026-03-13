# Logging policy: Use ASCII-only characters in log messages
# Examples: [OK], [FAIL], [BLOCKED], [WARN], [INFO]

"""
IRC-compliant message handler for csc-server.

Routes all incoming UDP messages through an IRC command dispatcher.
Supports registration (NICK/USER/PASS), channels (JOIN/PART/PRIVMSG/TOPIC/NAMES/LIST),
oper commands (OPER/MODE/KICK/KILL), service commands (AI), file uploads,
and legacy IDENT/RENAME compatibility.

All service commands and file uploads are transparent on the chatline.
"""

import os
import re
import time
import threading
from csc_service.shared.irc import (
    parse_irc_message, format_irc_message, numeric_reply, SERVER_NAME,
    RPL_WELCOME, RPL_YOURHOST, RPL_CREATED, RPL_MYINFO,
    RPL_LIST, RPL_LISTEND, RPL_NOTOPIC, RPL_TOPIC,
    RPL_NAMREPLY, RPL_ENDOFNAMES,
    RPL_WHOISUSER, RPL_WHOISSERVER, RPL_WHOISOPERATOR, RPL_ENDOFWHOIS,
    RPL_WHOWASUSER, RPL_ENDOFWHOWAS, ERR_WASNOSUCHNICK,
    RPL_MOTDSTART, RPL_MOTD, RPL_ENDOFMOTD, RPL_YOUREOPER,
    RPL_UMODEIS, ERR_UMODEUNKNOWNFLAG, ERR_USERSDONTMATCH,
    RPL_AWAY, RPL_UNAWAY, RPL_NOWAWAY,
    ERR_NOSUCHNICK, ERR_NOSUCHCHANNEL, ERR_CANNOTSENDTOCHAN,
    ERR_NORECIPIENT, ERR_NOTEXTTOSEND, ERR_NONICKNAMEGIVEN,
    ERR_ERRONEUSNICKNAME, ERR_NICKNAMEINUSE,
    ERR_USERNOTINCHANNEL, ERR_NOTONCHANNEL, ERR_NOTREGISTERED,
    ERR_NEEDMOREPARAMS, ERR_ALREADYREGISTRED, ERR_PASSWDMISMATCH,
    ERR_NOPRIVILEGES, ERR_CHANOPRIVSNEEDED, ERR_INVITEONLYCHAN, ERR_CHANNELISFULL, ERR_BADCHANNELKEY,
    ERR_UNKNOWNMODE, RPL_INVITING,
    RPL_WHOISCHANNELS,
    RPL_BANLIST, RPL_ENDOFBANLIST, ERR_BANNEDFROMCHAN, ERR_BANLISTFULL, ERR_UNKNOWNERROR,
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

        # Extract content from PRIVMSG/NOTICE if wrapped in IRC format
        # This preserves indentation in the trailing content
        content = raw_line
        content_stripped = line_stripped
        if line_stripped.upper().startswith("PRIVMSG ") or line_stripped.upper().startswith("NOTICE "):
            # Parse the IRC message to extract trailing content
            msg = parse_irc_message(raw_line)
            if msg.params:
                content = msg.params[-1]  # trailing content with whitespace preserved
                content_stripped = content.strip()

        if content_stripped.startswith("<begin file=") or content_stripped.startswith("<append file="):
            self.file_handler.abort_session(addr)
            error_msg = "[Server] Error: Nested file uploads are not supported. Session aborted.\n"
            self.server.sock_send(error_msg.encode(), addr)
        elif content_stripped.startswith("<end file>"):
            # Broadcast end marker to channel
            if nick and channel:
                broadcast_msg = format_irc_message(prefix, "PRIVMSG", [channel], content_stripped)
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
            # Use extracted content (preserves indentation)
            self.file_handler.process_chunk(addr, content)
            # Broadcast file chunk to channel (transparency)
            if nick and channel:
                chunk_text = content.rstrip("\r\n")
                broadcast_msg = format_irc_message(prefix, "PRIVMSG", [channel], chunk_text)
                self.server.broadcast_to_channel(channel, broadcast_msg + "\r\n", exclude=addr)

    # ======================================================================
    # IRC Command Dispatcher
    # ======================================================================

    def _dispatch_irc_command(self, msg, addr, raw_line):
        """Route an IRC command to the appropriate handler."""
        command = msg.command.upper() if msg.command else ""
        self.server.log(f"[DEBUG DISPATCH] Received command: '{command}', Raw: '{raw_line}', Registered: {self._is_registered(addr)}")

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

        # NickServ interception — allowed even before registration
        # so clients can GHOST a stuck nick before re-registering
        if command == "PRIVMSG" and len(msg.params) >= 2:
            target_lower = msg.params[0].lower()
            if target_lower == "nickserv":
                self._handle_nickserv(msg, addr)
                return
            if target_lower == "chanserv":
                self._handle_chanserv(msg, addr)
                return
            if target_lower == "botserv":
                self._handle_botserv(msg, addr)
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
            "INVITE":  self._handle_invite, 
            "NAMES":   self._handle_names,
            "LIST":    self._handle_list,
            "WHO":     self._handle_who,
            "WHOIS":   self._handle_whois,
            "WHOWAS":  self._handle_whowas,
            "OPER":        self._handle_oper,
            "KICK":        self._handle_kick,
            "MODE":        self._handle_mode,
            "AWAY":        self._handle_away,
            "MOTD":        self._handle_motd,
            "KILL":        self._handle_kill,
            "ISOP":        self._handle_isop,
            "WALLOPS":     self._handle_wallops,
            "BUFFER":      self._handle_buffer,
            "WAKEWORD":    self._handle_wakeword,
            "CONNECT":     self._handle_connect,
            "SQUIT":       self._handle_squit_cmd,
            "TRUST":       self._handle_trust,
            "SETMOTD":     self._handle_setmotd,
            "STATS":       self._handle_stats,
            "REHASH":      self._handle_rehash,
            "SHUTDOWN":    self._handle_shutdown,
            "LINK":        self._handle_link,
            "RELINK":      self._handle_relink,
            "DELINK":      self._handle_delink,
            "LOCALCONFIG": self._handle_localconfig,
            "HELP":        self._handle_help,
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
                self.server.log(f"[SECURITY] [BLOCKED] File upload blocked from unauthorized user {nick}@{addr}")
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
        try:
            self._ensure_reg_state(addr)
            if self._is_registered(addr):
                self._send_numeric(addr, ERR_ALREADYREGISTRED, self._get_nick(addr),
                                   "You may not reregister")
                return
            if len(msg.params) < 1:
                self._send_numeric(addr, ERR_NEEDMOREPARAMS, "*", "PASS :Not enough parameters")
                return
            self.registration_state[addr]["password"] = msg.params[0]
        except Exception as e:
            self.server.log(f"[ERROR] PASS handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, "*", "Internal server error during PASS")

    def _handle_nick(self, msg, addr):
        """NICK <nickname>"""
        try:
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
                
                # S2S: Check remote collision
                if hasattr(self.server, 's2s_network'):
                    remote_info = self.server.s2s_network.get_user_from_network(new_nick)
                    if remote_info:
                        target = old_nick or "*"
                        self._send_numeric(addr, ERR_NICKNAMEINUSE, target,
                                           f"{new_nick} :Nickname is already in use on the network")
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
                    member_info = ch.members.pop(old_nick.lower(), None)
                    if member_info:
                        member_info["nick"] = new_nick  # update display nick
                        ch.members[new_nick.lower()] = member_info

                # Update oper status
                if old_nick.lower() in self.server.opers:
                    self.server.remove_active_oper(old_nick.lower())
                    self.server.add_active_oper(new_nick.lower())

                # Update persistent registry
                if old_nick in self.client_registry:
                    entry = self.client_registry.copy().pop(old_nick)
                    self.server.remove_user(old_nick)
                    self.server.set_user(new_nick, entry)

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

                # S2S: Notify federation network of nick change
                if hasattr(self.server, 's2s_network'):
                    self.server.s2s_network.sync_nick_change(old_nick, new_nick)

                # Clear identified status on nick change
                self.server.nickserv_identified.pop(addr, None)

                # NickServ enforcement for new nick
                ns_info = self.server.nickserv_get(new_nick)
                if ns_info:
                    settings = self.server.load_settings().get("nickserv", {})
                    timeout = settings.get("enforce_timeout", 60)
                    self._nickserv_notice(addr,
                        f"This nickname is registered. You have {timeout} seconds to identify via: /msg NickServ IDENTIFY <password>")
                    enforce_timer = threading.Timer(float(timeout), self._nickserv_enforce, args=(addr, new_nick))
                    enforce_timer.daemon = True
                    enforce_timer.start()
                    timer_key = f"_nickserv_enforce_{addr}"
                    # Cancel existing timer if any
                    existing_timer = getattr(self, timer_key, None)
                    if existing_timer:
                        existing_timer.cancel()
                    setattr(self, timer_key, enforce_timer)

                # Real-time persistence: Save session state immediately
                self.server._persist_session_data()
            else:
                reg["nick"] = new_nick
                self._try_complete_registration(addr)
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] NICK handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, "*", "NICK :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] NICK handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, "*", "Internal server error during NICK")

    def _handle_user(self, msg, addr):
        """USER <username> <mode> <unused> :<realname>"""
        try:
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
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] USER handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, "*", "USER :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] USER handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, "*", "Internal server error during USER")

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

        # DEBUG: Log registration
        self.server.log(f"[REG DEBUG] Registering {nick} at {addr}")

        # Update persistent registry
        password = reg.get("password") or ""
        registry = self.client_registry.copy()
        if nick not in registry:
            entry = {
                "password": password,
                "addresses": [list(addr)],
                "last_seen": {f"{addr[0]}:{addr[1]}": now},
            }
        else:
            entry = registry[nick]
            if list(addr) not in entry.get("addresses", []):
                entry.setdefault("addresses", []).append(list(addr))
            entry.setdefault("last_seen", {})[f"{addr[0]}:{addr[1]}"] = now
        
        # Save to disk immediately
        self.server.set_user(nick, entry)

        # Restore saved user modes (ircop, etc.) if this nick was seen before
        saved_modes = set()
        try:
            saved = entry.get("user_modes", []) # Registry entry should have them now
            if saved:
                saved_modes = set(saved)
                self.server.log(f"[REG] Restoring saved modes for {nick}: {saved_modes}")
        except Exception:
            pass
        self.server.clients[addr] = {"name": nick, "last_seen": now, "user_modes": saved_modes}
        # Restore ircop status if they had +o
        if "o" in saved_modes:
            self.server.add_active_oper(nick.lower())
            self.server.log(f"[REG] Restored ircop status for {nick}")

        # Send welcome burst (001-005)
        self._send_numeric(addr, RPL_WELCOME, nick,
                           f"Welcome to {SERVER_NAME} Network, {nick}")
        self._send_numeric(addr, RPL_YOURHOST, nick,
                           f"Your host is {SERVER_NAME}, running csc-server")
        self._send_numeric(addr, RPL_CREATED, nick,
                           "This server was created recently")
        # 004 uses space-separated params, not trailing
        line_004 = f":{SERVER_NAME} {RPL_MYINFO} {nick} {SERVER_NAME} csc-server iosw opsimnqbvk\r\n"
        self.server.sock_send(line_004.encode(), addr)
        # 005 ISUPPORT
        line_005 = (f":{SERVER_NAME} 005 {nick} CHANTYPES=# PREFIX=(ov)@+ "
                    f"CHANMODES=b,k,l,imnpst NICKLEN=30 CHANNELLEN=50 "
                    f"NETWORK={SERVER_NAME} :are supported by this server\r\n")
        self.server.sock_send(line_005.encode(), addr)

        # Send MOTD
        self._send_motd(addr, nick)

        # Auto-join #general
        from csc_service.shared.irc import IRCMessage
        join_msg = IRCMessage(command="JOIN", params=["#general"])
        self._handle_join(join_msg, addr)

        self.server.log(f"[REG] {nick} completed registration from {addr}")

        # NickServ enforcement: if nick is registered, require IDENTIFY
        ns_info = self.server.nickserv_get(nick)
        if ns_info and self.server.nickserv_identified.get(addr) != nick:
            settings = self.server.load_settings().get("nickserv", {})
            timeout = settings.get("enforce_timeout", 60)
            self._nickserv_notice(addr,
                f"This nickname is registered. You have {timeout} seconds to identify via: /msg NickServ IDENTIFY <password>")
            enforce_timer = threading.Timer(float(timeout), self._nickserv_enforce, args=(addr, nick))
            enforce_timer.daemon = True
            enforce_timer.start()
            # Store timer so IDENTIFY can cancel it
            timer_key = f"_nickserv_enforce_{addr}"
            setattr(self, timer_key, enforce_timer)

        # Real-time persistence: Save session state immediately
        self.server._persist_session_data()

    # ======================================================================
    # Channel Handlers
    # ======================================================================

    def _handle_join(self, msg, addr):
        """JOIN <channel>[,<channel>...]"""
        try:
            nick = self._get_nick(addr)
            if not nick:
                self._send_numeric(addr, ERR_NOTREGISTERED, "*", "You have not registered")
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

                # Remove and re-add member to update address if client reconnected
                if channel.has_member(nick):
                    channel.remove_member(nick)

                # Check +i (invite-only)
                if "i" in channel.modes and nick.lower() not in channel.invite_list:
                    self._send_numeric(addr, ERR_INVITEONLYCHAN, nick,
                                       f"{chan_name} :Cannot join channel (+i)")
                    return
                
                # Check +k (key/password)
                # A JOIN message can have 2 params: <channel> <key>
                key_provided = msg.params[1] if len(msg.params) > 1 else None
                if "k" in channel.modes and channel.mode_params.get("k") != key_provided:
                    self._send_numeric(addr, ERR_BADCHANNELKEY, nick,
                                       f"{chan_name} :Cannot join channel (+k) - Bad channel key")
                    return

                # Check +l (user limit)
                if "l" in channel.modes:
                    limit = channel.mode_params.get("l", 0)
                    if len(channel.members) >= limit:
                        self._send_numeric(addr, ERR_CHANNELISFULL, nick,
                                           f"{chan_name} :Cannot join channel (+l) - Channel is full")
                        return

                # Check +b (ban list) - skip check for opers
                if channel.ban_list and nick.lower() not in self.server.opers:
                    reg = self.registration_state.get(addr, {})
                    user = reg.get("user", nick)
                    host = SERVER_NAME
                    if self._is_banned(channel, nick, user, host):
                        self._send_numeric(addr, ERR_BANNEDFROMCHAN, nick,
                                           f"{chan_name} :Cannot join channel (+b) - You are banned")
                        return

                # Auto-op founder: first joiner of empty channel gets +o, channel gets +nt
                initial_modes = set()
                if channel.member_count() == 0:
                    initial_modes.add("o")
                    channel.modes.add("n")   # no external messages
                    channel.modes.add("t")   # topic locked to ops
                    channel.created = time.time()

                # ChanServ Enforcement (JOIN)
                chanserv_info = self.server.chanserv_get(chan_name)
                if chanserv_info:
                    # Check ChanServ banlist (even if not set in channel.ban_list)
                    banlist = chanserv_info.get("banlist", [])
                    reg = self.registration_state.get(addr, {})
                    user = reg.get("user", nick)
                    nick_user_host = f"{nick}!{user}@{SERVER_NAME}"
                    # Simple mask matching for now
                    for mask in banlist:
                        if self._match_ban_mask(mask, nick_user_host):
                            self._send_numeric(addr, ERR_BANNEDFROMCHAN, nick,
                                               f"{chan_name} :Cannot join channel (ChanServ BAN) - You are banned")
                            return
                    
                    # Auto-op/voice
                    is_identified = self.server.nickserv_identified.get(addr) == nick
                    
                    # Enforce Mode (+E): require identification for modes
                    should_grant = True
                    if chanserv_info.get("enforce_mode") and not is_identified:
                        should_grant = False

                    if should_grant:
                        if nick.lower() in [n.lower() for n in chanserv_info.get("oplist", [])]:
                            initial_modes.add("o")
                        elif nick.lower() in [n.lower() for n in chanserv_info.get("voicelist", [])]:
                            initial_modes.add("v")
                    
                    # Sync topic from ChanServ if unset
                    if chanserv_info.get("topic") and not channel.topic:
                        channel.topic = chanserv_info["topic"]

                channel.add_member(nick, addr, modes=initial_modes)

                # Broadcast JOIN to all channel members (including the joiner)
                prefix = f"{nick}!{nick}@{SERVER_NAME}"
                join_msg = f":{prefix} JOIN {chan_name}\r\n"
                if "Q" in channel.modes:
                    # Silent mode: only notify the joiner
                    self.server.sock_send(join_msg.encode(), addr)
                else:
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

                # Note: Buffer replay is NOT sent on JOIN to maintain IRC compatibility.
                # Standard IRC clients expect only the channel topic, names list, and future
                # messages - not historical chat. Users can request buffer with BUFFER command.

                # Real-time persistence: Save session state immediately
                self.server._persist_session_data()

                # S2S: Notify federation network of user join
                if hasattr(self.server, 's2s_network'):
                    host = f"{addr[0]}:{addr[1]}" if isinstance(addr, tuple) else str(addr)
                    modes = "+" + "".join(sorted(self.server.clients.get(addr, {}).get("modes", set()) or set()))
                    self.server.s2s_network.sync_user_join(nick, host, modes, channel=chan_name)
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] JOIN handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, self._get_nick(addr) or "*", "JOIN :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] JOIN handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during JOIN")

    def _handle_part(self, msg, addr):
        """PART <channel>[,<channel>...] [:<reason>]"""
        try:
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
                if "Q" in channel.modes:
                    # Silent mode: only notify the parting user
                    self.server.sock_send(part_msg.encode(), addr)
                else:
                    for member_nick, member_info in list(channel.members.items()):
                        member_addr = member_info.get("addr")
                        if member_addr:
                            self.server.sock_send(part_msg.encode(), member_addr)

                channel.remove_member(nick)

                # Clean up empty non-default channels
                if channel.member_count() == 0 and chan_name != self.server.channel_manager.DEFAULT_CHANNEL:
                    self.server.channel_manager.remove_channel(chan_name)

                # Real-time persistence: Save session state immediately
                self.server._persist_session_data()

                # S2S: Notify federation network of user part
                if hasattr(self.server, 's2s_network'):
                    self.server.s2s_network.sync_user_part(nick, chan_name, reason)
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] PART handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, self._get_nick(addr) or "*", "PART :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] PART handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during PART")

    def _handle_privmsg(self, msg, addr):
        """PRIVMSG <target> :<text>"""
        try:
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
                # Check +n (no external messages) — only members can send
                if "n" in channel.modes and not channel.has_member(nick):
                    self._send_numeric(addr, ERR_CANNOTSENDTOCHAN, nick,
                                       f"{target} :Cannot send to channel (+n)")
                    return
                # Check +m (moderated) — only ops/voiced/opers can speak
                if not channel.can_speak(nick) and nick.lower() not in self.server.opers:
                    self._send_numeric(addr, ERR_CANNOTSENDTOCHAN, nick,
                                       f"{target} :Cannot send to channel (+m)")
                    return

                # Normalize channel name to lowercase for consistent output (RFC 1459)
                normalized_target = target.lower()
                out = format_irc_message(prefix, "PRIVMSG", [normalized_target], text) + "\r\n"
                # Wakeword-filtered broadcast: check each recipient individually
                self._broadcast_privmsg_filtered(channel, out, text, nick, exclude=addr)
                self.server.chat_buffer.append(normalized_target, nick, "PRIVMSG", text)

                # S2S: Route channel message to federation network
                if hasattr(self.server, 's2s_network'):
                    self.server.s2s_network.route_message(nick, normalized_target, text)

                # Check for embedded service command (AI ...)
                if text.upper().startswith("AI "):
                    self._handle_service_via_chatline(text, addr, nick, normalized_target)
                # Check for embedded file upload start
                elif text.startswith("<begin file=") or text.startswith("<append file="):
                    # Require ircop or chanop for file uploads
                    if not self._is_authorized(nick, normalized_target):
                        self.server.log(f"[SECURITY] [BLOCKED] File upload blocked from unauthorized user {nick}@{addr}")
                        self.server.sock_send(b"[Server] Error: IRC operator or channel operator status required for file uploads.\n", addr)
                        return
                    self.file_handler.start_session(addr, text)
            else:
                # Private message to a nick
                self._maybe_replay_pm_buffer(target, nick)
                out = format_irc_message(prefix, "PRIVMSG", [target], text) + "\r\n"
                if not self.server.send_to_nick(target, out):
                    # Try S2S routing for remote users
                    if hasattr(self.server, 's2s_network'):
                        remote_info = self.server.s2s_network.get_user_from_network(target)
                        if remote_info:
                            self.server.s2s_network.route_message(nick, target, text)
                            self.server.chat_buffer.append(target, nick, "PRIVMSG", text)
                            return
                    self._send_numeric(addr, ERR_NOSUCHNICK, nick,
                                       f"{target} :No such nick/channel")
                else:
                    self.server.chat_buffer.append(target, nick, "PRIVMSG", text)
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] PRIVMSG handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, self._get_nick(addr) or "*", "PRIVMSG :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] PRIVMSG handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during PRIVMSG")

    # ==================================================================
    # Wakeword Filtering
    # ==================================================================

    def _handle_wakeword(self, msg, addr):
        """WAKEWORD ENABLE|DISABLE - Toggle wakeword-based message filtering for this client.

        When enabled, the server only forwards channel PRIVMSGs to this client
        if the message contains the client's nick, starts with 'AI ', or
        contains a word from the global wakeword list.

        Default: DISABLED (all messages forwarded, backward compatible).
        """
        nick = self._get_nick(addr)
        if not msg.params:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick,
                               "WAKEWORD :Not enough parameters. Usage: WAKEWORD ENABLE|DISABLE")
            return

        action = msg.params[0].upper()

        if action == "ENABLE":
            if addr in self.server.clients:
                self.server.clients[addr]["wakeword_enabled"] = True
            self._send_notice(addr, "Wakeword filtering ENABLED. Only matching messages will be forwarded.")
            self.server.log(f"[WAKEWORD] {nick} enabled wakeword filtering")
        elif action == "DISABLE":
            if addr in self.server.clients:
                self.server.clients[addr]["wakeword_enabled"] = False
            self._send_notice(addr, "Wakeword filtering DISABLED. All messages will be forwarded.")
            self.server.log(f"[WAKEWORD] {nick} disabled wakeword filtering")
        else:
            self._send_notice(addr, "Usage: WAKEWORD ENABLE|DISABLE")

    def _should_forward_to_client(self, recipient_addr, message_text, sender_nick):
        """Check whether a PRIVMSG should be forwarded to a specific recipient.

        If the recipient has wakeword filtering enabled, the message is only
        forwarded if it matches one of:
          - The recipient's nick appears in the message (case-insensitive)
          - The message starts with 'AI ' (AI command token)
          - The message contains any global wakeword (case-insensitive substring)

        If the recipient does NOT have wakeword filtering enabled (default),
        the message is always forwarded (backward compatible).

        Args:
            recipient_addr: The (host, port) tuple of the recipient.
            message_text: The text body of the PRIVMSG.
            sender_nick: The nick of the sender (not used for filtering, for logging).

        Returns:
            True if the message should be forwarded, False to suppress.
        """
        client_info = self.server.clients.get(recipient_addr)
        if not client_info:
            return True  # Unknown client, forward by default

        # If wakeword filtering is not enabled, forward everything
        if not client_info.get("wakeword_enabled", False):
            return True

        recipient_nick = client_info.get("name", "")
        msg_lower = message_text.lower()

        # Check 1: Nick match - message mentions the recipient's nick
        if recipient_nick and recipient_nick.lower() in msg_lower:
            return True

        # Check 2: AI command token - message starts with "AI "
        if message_text.upper().startswith("AI "):
            return True

        # Check 3: Wakeword match - message contains any wakeword
        wakewords = self.server.wakewords
        if wakewords:
            for word in wakewords:
                if word in msg_lower:
                    return True

        # No match - suppress this message for the AI client
        return False

    def _broadcast_privmsg_filtered(self, channel, out_msg, message_text, sender_nick, exclude=None):
        """Broadcast a PRIVMSG to channel members with wakeword filtering.

        For each channel member:
        - If wakeword filtering is enabled for that member, check if the message
          should be forwarded using _should_forward_to_client().
        - If not enabled (default), always forward (backward compatible).

        Args:
            channel: The Channel object.
            out_msg: The formatted IRC message string to send.
            message_text: The raw text of the message (for wakeword matching).
            sender_nick: The nick of the sender.
            exclude: Address to exclude (usually the sender).
        """
        msg_bytes = out_msg.encode("utf-8") if isinstance(out_msg, str) else out_msg
        for member_nick, info in list(channel.members.items()):
            member_addr = info.get("addr")
            if not member_addr or member_addr == exclude:
                continue

            if not self._should_forward_to_client(member_addr, message_text, sender_nick):
                self.server.log(
                    f"[WAKEWORD] Filtered message from {sender_nick} to {member_nick} "
                    f"(no nick/token/wakeword match)"
                )
                continue

            try:
                self.server.sock_send(msg_bytes, member_addr)
            except Exception as e:
                self.server.log(f"[BROADCAST_FILTERED] Error sending to {member_nick}@{member_addr}: {e}")

    def _handle_service_via_chatline(self, raw_line, addr, nick, channel=None):
        """
        Handle service commands received via chatline (e.g., AI 1 agent assign...).
        Parses the command, executes via server.handle_command (which handles
        dynamic loading), and sends output back to the channel.
        """
        self.server.log(f"[DEBUG] _handle_service_via_chatline entered for {nick}@{addr}: {raw_line}")
        
        # Strip "AI " prefix if present for handle_command
        cmd_text = raw_line
        if raw_line.upper().startswith("AI "):
            cmd_text = raw_line[3:].strip()
            
        parts = cmd_text.split()
        if not parts:
            return

        token = parts[0]

        if len(parts) < 3:
            self._send_notice(addr, f"{token} AI : Usage: AI <token> <service> <method> [args...]")
            return

        class_name = parts[1]
        method_name = parts[2]
        method_args = parts[3:]

        # Execute via server.handle_command (Service.handle_command signature)
        result = self.server.handle_command(class_name, method_name, method_args, nick, addr)
        
        if token == "0":
            return # Fire and forget
            
        # Send result back — prefix every line with the token
        for line in str(result).splitlines():
            prefixed = f"{token} AI : {line}"
            if channel:
                prefix = f"ServiceBot!service@{SERVER_NAME}"
                msg = format_irc_message(prefix, "PRIVMSG", [channel], prefixed) + "\r\n"
                self.server.broadcast_to_channel(channel, msg)
            else:
                self._send_notice(addr, prefixed)
        self.server.log(f"[SERVICE] '{cmd_text}' from {nick}@{addr}: OK")

    def _send_notice(self, addr, text):
        """Helper to send a NOTICE message to a client."""
        nick = self._get_nick(addr) or "*"
        notice = format_irc_message(f":{SERVER_NAME}", "NOTICE", [nick], text) + "\r\n"
        self.server.sock_send(notice.encode(), addr)

    def _handle_notice(self, msg, addr):
        """NOTICE <target> :<text> — same as PRIVMSG but no auto-reply expected."""
        try:
            nick = self._get_nick(addr)
            if len(msg.params) < 2:
                return  # NOTICE errors are silently dropped per RFC

            target = msg.params[0]
            text = msg.params[-1]
            prefix = f"{nick}!{nick}@{SERVER_NAME}"

            if target.startswith("#"):
                channel = self.server.channel_manager.get_channel(target)
                if channel and channel.has_member(nick):
                    # Normalize channel name to lowercase for consistent output (RFC 1459)
                    normalized_target = target.lower()
                    out = format_irc_message(prefix, "NOTICE", [normalized_target], text) + "\r\n"
                    self.server.broadcast_to_channel(normalized_target, out, exclude=addr)
                    self.server.chat_buffer.append(normalized_target, nick, "NOTICE", text)
            else:
                self._maybe_replay_pm_buffer(target, nick)
                out = format_irc_message(prefix, "NOTICE", [target], text) + "\r\n"
                if self.server.send_to_nick(target, out):
                    self.server.chat_buffer.append(target, nick, "NOTICE", text)
        except Exception as e:
            # NOTICE never generates a reply, so just log the error
            self.server.log(f"[ERROR] NOTICE handler unexpected error from {addr}: {type(e).__name__}: {e}")

    def _handle_topic(self, msg, addr):
        """TOPIC <channel> [:<new topic>]"""
        try:
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
                # Set topic — check +t mode and ChanServ enforcement
                chanserv_info = self.server.chanserv_get(chan_name)
                if chanserv_info and chanserv_info.get("enforce_topic"):
                    if chanserv_info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
                        self._send_numeric(addr, ERR_CHANOPRIVSNEEDED, nick,
                                           f"{chan_name} :Only the channel owner can change the topic (+T)")
                        return

                if not channel.can_set_topic(nick) and nick.lower() not in self.server.opers:
                    self._send_numeric(addr, ERR_CHANOPRIVSNEEDED, nick,
                                       f"{chan_name} :You're not channel operator (+t)")
                    return
                new_topic = msg.params[-1]
                channel.topic = new_topic
                prefix = f"{nick}!{nick}@{SERVER_NAME}"
                topic_msg = format_irc_message(prefix, "TOPIC", [chan_name], new_topic) + "\r\n"
                self.server.broadcast_to_channel(chan_name, topic_msg)

                # S2S: Notify federation network of topic change
                if hasattr(self.server, 's2s_network'):
                    self.server.s2s_network.sync_topic(chan_name, new_topic)

                # Real-time persistence: Save session state immediately
                self.server._persist_session_data()
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] TOPIC handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, self._get_nick(addr) or "*", "TOPIC :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] TOPIC handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during TOPIC")

    def _handle_invite(self, msg, addr):
        """INVITE <nick> <channel>"""
        try:
            nick = self._get_nick(addr)
            if len(msg.params) < 2:
                self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "INVITE :Not enough parameters")
                return

            target_nick = msg.params[0]
            chan_name = msg.params[1]

            channel = self.server.channel_manager.get_channel(chan_name)
            if not channel:
                self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                                   f"{chan_name} :No such channel")
                return

            # Only channel ops or IRC ops can invite to +i channels
            if "i" in channel.modes and not (channel.is_op(nick) or nick.lower() in self.server.opers):
                self._send_numeric(addr, ERR_CHANOPRIVSNEEDED, nick,
                                   f"{chan_name} :You're not channel operator")
                return
            
            # Target nick must exist
            target_addr = None
            for a, info in list(self.server.clients.items()):
                if info.get("name", "").lower() == target_nick.lower():
                    target_addr = a
                    break
            
            if not target_addr:
                self._send_numeric(addr, ERR_NOSUCHNICK, nick,
                                   f"{target_nick} :No such nick/channel")
                return

            # Add to invite list (case-insensitive)
            channel.invite_list.add(target_nick.lower())

            # Send RPL_INVITING (341) to inviter
            self._send_numeric(addr, RPL_INVITING, nick, f"{target_nick} {chan_name}")

            # Send INVITE message to target
            prefix = f"{nick}!{nick}@{SERVER_NAME}"
            invite_msg = format_irc_message(prefix, "INVITE", [target_nick, chan_name]) + "\r\n"
            self.server.sock_send(invite_msg.encode(), target_addr)

            self.server.log(f"[INVITE] {nick} invited {target_nick} to {chan_name}")
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] INVITE handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, self._get_nick(addr) or "*", "INVITE :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] INVITE handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during INVITE")


    def _handle_names(self, msg, addr):
        """NAMES [<channel>]"""
        try:
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
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] NAMES handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, self._get_nick(addr) or "*", "NAMES :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] NAMES handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during NAMES")

    def _handle_list(self, msg, addr):
        """LIST — list all channels."""
        try:
            nick = self._get_nick(addr)
            for channel in self.server.channel_manager.list_channels():
                # Skip secret channels if nick is not a member
                if "s" in channel.modes and not channel.has_member(nick):
                    continue
                reply = f":{SERVER_NAME} {RPL_LIST} {nick} {channel.name} {channel.member_count()} :{channel.topic}\r\n"
                self.server.sock_send(reply.encode(), addr)
            end = f":{SERVER_NAME} {RPL_LISTEND} {nick} :End of /LIST\r\n"
            self.server.sock_send(end.encode(), addr)
        except Exception as e:
            self.server.log(f"[ERROR] LIST handler unexpected error from {addr}: {type(e).__name__}: {e}")
            # This command is broad, so sending a specific error code is tricky.
            # We'll send a general error if something goes wrong during iteration.
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during LIST")

    def _handle_who(self, msg, addr):
        """WHO <channel> — basic WHO reply."""
        try:
            nick = self._get_nick(addr)
            if not msg.params:
                return
            chan_name = msg.params[0]
            channel = self.server.channel_manager.get_channel(chan_name)
            if channel:
                # Hide +p channels from non-members
                if "p" in channel.modes and not channel.has_member(nick):
                    self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                                       f"{chan_name} :No such channel")
                    return

                # Check if querier is an oper or in the channel
                is_oper = nick.lower() in self.server.opers
                is_member = channel.has_member(nick)

                for member_nick in channel.members:
                    # Skip invisible users unless querier is in the channel or is an oper
                    member_addr = self._find_client_addr(member_nick)
                    if member_addr:
                        member_modes = self.server.clients.get(member_addr, {}).get("user_modes", set())
                        if "i" in member_modes and not is_member and not is_oper:
                            continue

                    # Simplified WHO reply
                    line = f":{SERVER_NAME} 352 {nick} {chan_name} {member_nick} {SERVER_NAME} {SERVER_NAME} {member_nick} H :0 {member_nick}\r\n"
                    self.server.sock_send(line.encode(), addr)
            end = f":{SERVER_NAME} 315 {nick} {chan_name} :End of /WHO list\r\n"
            self.server.sock_send(end.encode(), addr)
        except Exception as e:
            self.server.log(f"[ERROR] WHO handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during WHO")

    def _handle_whois(self, msg, addr):
        """WHOIS <nick> — return information about a user per RFC 2812."""
        try:
            nick = self._get_nick(addr)
            if not msg.params:
                self._send_numeric(addr, ERR_NONICKNAMEGIVEN, nick, "No nickname given")
                return

            # WHOIS can be: WHOIS <nick> or WHOIS <server> <nick>
            # We ignore the server parameter if present
            target_nick = msg.params[-1]

            # Find target user by nickname
            target_addr = None
            actual_target_nick = None

            for a, info in list(self.server.clients.items()):
                client_nick = info.get("name", "")
                if client_nick.lower() == target_nick.lower():
                    target_addr = a
                    actual_target_nick = client_nick
                    break

            if not target_addr:
                # S2S: Check remote network if not found locally
                if hasattr(self.server, 's2s_network'):
                    remote_info = self.server.s2s_network.get_user_from_network(target_nick)
                    if remote_info:
                        # RPL_WHOISUSER (311)
                        whoisuser = f":{SERVER_NAME} {RPL_WHOISUSER} {nick} {remote_info['nick']} {remote_info['nick']} {remote_info['server_id']} * :{remote_info['nick']}\r\n"
                        self.server.sock_send(whoisuser.encode(), addr)
                        # RPL_WHOISSERVER (312)
                        whoisserver = f":{SERVER_NAME} {RPL_WHOISSERVER} {nick} {remote_info['nick']} {remote_info['server_id']} :Federated CSC Server\r\n"
                        self.server.sock_send(whoisserver.encode(), addr)
                        # RPL_ENDOFWHOIS (318)
                        endwhois = f":{SERVER_NAME} {RPL_ENDOFWHOIS} {nick} {remote_info['nick']} :End of WHOIS list\r\n"
                        self.server.sock_send(endwhois.encode(), addr)
                        return

                self._send_numeric(addr, ERR_NOSUCHNICK, nick,
                                   f"{target_nick} :No such nick/channel")
                return

            # Get target user's registration info
            target_reg = self.registration_state.get(target_addr, {})
            target_user = target_reg.get("user", target_nick)
            target_realname = target_reg.get("realname", target_nick)

            # RPL_WHOISUSER (311): <nick> <user> <host> * :<real name>
            whoisuser = f":{SERVER_NAME} {RPL_WHOISUSER} {nick} {target_nick} {target_user} {SERVER_NAME} * :{target_realname}\r\n"
            self.server.sock_send(whoisuser.encode(), addr)

            # RPL_WHOISSERVER (312): <nick> <server> :<server info>
            whoisserver = f":{SERVER_NAME} {RPL_WHOISSERVER} {nick} {target_nick} {SERVER_NAME} :CSC IRC Server\r\n"
            self.server.sock_send(whoisserver.encode(), addr)

            # RPL_AWAY (301): <nick> :<away message> (if away)
            target_client = self.server.clients.get(target_addr, {})
            away_message = target_client.get("away_message")
            if away_message:
                away_reply = f":{SERVER_NAME} {RPL_AWAY} {nick} {target_nick} :{away_message}\r\n"
                self.server.sock_send(away_reply.encode(), addr)

            # RPL_WHOISOPERATOR (313): <nick> :is an IRC operator (if applicable)
            if actual_target_nick and actual_target_nick.lower() in self.server.opers:
                whoisoper = f":{SERVER_NAME} {RPL_WHOISOPERATOR} {nick} {target_nick} :is an IRC operator\r\n"
                self.server.sock_send(whoisoper.encode(), addr)

            # RPL_WHOISCHANNELS (319): <nick> :<channel> <channel> ...
            # List channels the target is on, respecting +s and +p
            # Use actual_target_nick (exact case) rather than target_nick (search param) for channel lookup
            target_channels = self.server.channel_manager.find_channels_for_nick(actual_target_nick)
            visible_channels = []
            for channel in target_channels:
                # Hide +s and +p channels from non-members
                if ("s" in channel.modes or "p" in channel.modes) and not channel.has_member(nick):
                    continue
                visible_channels.append(channel.name)
            if visible_channels:
                channels_str = " ".join(visible_channels)
                whoischannels = f":{SERVER_NAME} {RPL_WHOISCHANNELS} {nick} {target_nick} :{channels_str}\r\n"
                self.server.sock_send(whoischannels.encode(), addr)

            # RPL_ENDOFWHOIS (318): <nick> :End of WHOIS list
            endofwhois = f":{SERVER_NAME} {RPL_ENDOFWHOIS} {nick} {target_nick} :End of /WHOIS list\r\n"
            self.server.sock_send(endofwhois.encode(), addr)

            self.server.log(f"[WHOIS] {nick} queried information for {target_nick}")
        except Exception as e:
            self.server.log(f"[ERROR] WHOIS handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during WHOIS")

    def _handle_whowas(self, msg, addr):
        """WHOWAS <nick> — return information about a disconnected user per RFC 2812."""
        try:
            nick = self._get_nick(addr)
            if not msg.params:
                self._send_numeric(addr, ERR_NONICKNAMEGIVEN, nick, "No nickname given")
                return

            target_nick = msg.params[-1]

            # Check if user is in disconnected clients history
            if target_nick in self.server.disconnected_clients:
                disc_info = self.server.disconnected_clients[target_nick]
                target_user = disc_info.get("user", target_nick)
                target_realname = disc_info.get("realname", target_nick)
                target_host = disc_info.get("host", SERVER_NAME)
                quit_time = disc_info.get("quit_time", "Unknown")
                quit_reason = disc_info.get("quit_reason", "")

                # RPL_WHOWASUSER (314): <nick> <user> <host> * :<real name>
                whowasuser = f":{SERVER_NAME} {RPL_WHOWASUSER} {nick} {target_nick} {target_user} {target_host} * :{target_realname}\r\n"
                self.server.sock_send(whowasuser.encode(), addr)

                # Optional: Send quit info as server notice
                quit_info = f":{SERVER_NAME} {RPL_WHOISSERVER} {nick} {target_nick} {SERVER_NAME} :Disconnected at {quit_time} ({quit_reason})\r\n"
                self.server.sock_send(quit_info.encode(), addr)

                # RPL_ENDOFWHOWAS (369): <nick> :End of WHOWAS
                endofwhowas = f":{SERVER_NAME} {RPL_ENDOFWHOWAS} {nick} {target_nick} :End of WHOWAS\r\n"
                self.server.sock_send(endofwhowas.encode(), addr)

                self.server.log(f"[WHOWAS] {nick} queried information for disconnected user {target_nick}")
            else:
                # ERR_WASNOSUCHNICK (406): <nick> :There was no such nickname
                self._send_numeric(addr, ERR_WASNOSUCHNICK, nick,
                                   f"{target_nick} :There was no such nickname")
        except Exception as e:
            self.server.log(f"[ERROR] WHOWAS handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during WHOWAS")


    # ======================================================================
    # Oper / Admin Handlers
    # ======================================================================

    def _handle_oper(self, msg, addr):
        """OPER <account> <password>

        Authenticates the client as an IRC operator using the named O-line.
        On success grants oper user modes per flags, stores oper info in
        active_opers, and broadcasts a WALLOPS notice.
        """
        nick = self._get_nick(addr)
        if len(msg.params) < 2:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "OPER :Not enough parameters")
            return

        account = msg.params[0]
        password = msg.params[1]

        # Build client mask for host check
        reg = self.registration_state.get(addr, {})
        client_user = reg.get("user", nick)
        client_host = addr[0] if addr else "unknown"
        client_mask = f"{nick}!{client_user}@{client_host}"

        server_name = SERVER_NAME

        flags = self.server.check_oper_auth(account, password, server_name, client_mask)
        if flags is not None:
            if addr not in self.server.clients:
                self.server.clients[addr] = {"name": nick, "last_seen": time.time(), "user_modes": set()}
            modes = self.server.clients[addr].setdefault("user_modes", set())
            for flag in flags:
                if flag in "oOaA":
                    modes.add(flag)
            self.server.add_active_oper(nick.lower(), account, flags)
            if not hasattr(self.server, "_active_opers_full"):
                self.server._active_opers_full = []
            self.server._active_opers_full = [
                e for e in self.server._active_opers_full
                if e.get("nick", "").lower() != nick.lower()
            ]
            self.server._active_opers_full.append({"nick": nick.lower(), "account": account, "flags": flags})
            self._send_numeric(addr, RPL_YOUREOPER, nick, "You are now an IRC operator")
            self.server.log(f"[OPER] {nick} authenticated as oper '{account}' flags={flags}")
            self.server.send_wallops(f"{nick} is now an IRC operator (account: {account}, flags: {flags})")
            self.server._persist_session_data()
        else:
            self._send_numeric(addr, ERR_PASSWDMISMATCH, nick, "Password incorrect")

    def _handle_away(self, msg, addr):
        """
        AWAY [:<message>]

        Set or unset away status. With a message, sets away and stores message.
        Without a message, clears away status.
        """
        nick = self._get_nick(addr)

        # Ensure client record exists
        if addr not in self.server.clients:
            self.server.clients[addr] = {"name": nick, "last_seen": time.time(), "user_modes": set()}

        # Get or initialize user_modes
        user_modes = self.server.clients[addr].setdefault("user_modes", set())

        if msg.params and msg.params[0]:
            # Set away with message
            away_message = msg.params[0]
            self.server.clients[addr]["away_message"] = away_message
            user_modes.add("a")
            self._send_numeric(addr, RPL_NOWAWAY, nick, "You have been marked as being away")
            self.server.log(f"[AWAY] {nick} set away: {away_message}")
        else:
            # Unset away
            if "away_message" in self.server.clients[addr]:
                del self.server.clients[addr]["away_message"]
            user_modes.discard("a")
            self._send_numeric(addr, RPL_UNAWAY, nick, "You are no longer marked as being away")
            self.server.log(f"[AWAY] {nick} removed away status")

        # Persist session data
        self.server._persist_session_data()

    # Modes that require a nick parameter
    _NICK_MODES = frozenset(("o", "v"))
    # Channel-level flag modes (no parameter)
    _FLAG_MODES = frozenset(("m", "t", "n", "i", "s", "p", "Q"))
    # Channel-level modes that require a parameter
    _PARAM_MODES = frozenset(("k", "l"))
    # List modes (like bans) that maintain a list of entries
    _LIST_MODES = frozenset(("b",))
    # Maximum number of bans per channel
    _MAX_BANS_PER_CHANNEL = 100

    def _handle_mode(self, msg, addr):
        """
        MODE <target> <modestring> [param1] [param2] ...

        Supports combined mode strings with up to 8 changes per command.
        Compact syntax: +/- signs only needed when changing direction.

        Examples:
          MODE #general +ov nick1 nick2           (op two users)
          MODE #general +ooo-ooo a b c d e f      (op a,b,c then deop d,e,f)
          MODE #general +int                      (set 3 flags, compact)
          MODE #general -o+v nick1 nick2          (deop+voice)
          MODE #chan +ibnlstk nick!*@* 24 pineapple  (7 mixed modes)
          MODE +o <nick> <pass>                   (oper auth, like OPER)
          MODE <nick>                             (query user modes)
        """
        nick = self._get_nick(addr)
        if len(msg.params) < 1:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "MODE :Not enough parameters")
            return

        target = msg.params[0]

        if target.startswith("#"):
            # Channel modes require at least 2 params (channel + modestring)
            if len(msg.params) < 2:
                self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "MODE :Not enough parameters")
                return
            self._handle_channel_mode(msg, addr, nick, target)
        else:
            # User mode handling (allows 1 param for query, 2+ for setting)
            self._handle_user_mode(msg, addr, nick, target)

    def _handle_user_mode(self, msg, addr, nick, target_nick):
        """
        Handle user MODE commands.

        MODE <nick> [+/-modes]

        Supported modes:
          +i  invisible (hide from WHO/NAMES unless on common channel)
          +w  wallops (receive WALLOPS messages)
          +s  server notices
          +o  operator (granted via OPER command or MODE by existing opers)
          +a  away (set via AWAY command, can't be set via MODE)

        Only users can change their own modes (except opers can change others).
        """
        # Only allow setting your own modes (unless you're an oper)
        is_oper = nick.lower() in self.server.opers
        if target_nick.lower() != nick.lower():
            if not is_oper:
                self._send_numeric(addr, ERR_USERSDONTMATCH, nick,
                                 "Cannot change mode for other users")
                return
            # Oper: only +o/-o allowed on other users
            if len(msg.params) >= 2:
                oper_mode_str = msg.params[1]
                has_only_o = all(c in "+-o" for c in oper_mode_str)
                if not has_only_o:
                    self._send_numeric(addr, ERR_USERSDONTMATCH, nick,
                                     "Can only change +o/-o on other users")
                    return

        # If no mode string provided, return current modes
        if len(msg.params) < 2:
            # MODE <nick> - query current modes
            target_addr = self._find_client_addr(target_nick)
            if not target_addr:
                self._send_numeric(addr, ERR_NOSUCHNICK, nick,
                                 f"{target_nick} :No such nick/channel")
                return

            user_modes = self.server.clients.get(target_addr, {}).get("user_modes", set())
            mode_str = "+" + "".join(sorted(user_modes)) if user_modes else "+"
            self._send_numeric(addr, RPL_UMODEIS, nick, mode_str)
            return

        # Parse mode changes
        mode_str = msg.params[1]
        target_addr = self._find_client_addr(target_nick)
        if not target_addr:
            self._send_numeric(addr, ERR_NOSUCHNICK, nick,
                             f"{target_nick} :No such nick/channel")
            return

        # Get current modes
        if target_addr not in self.server.clients:
            self.server.clients[target_addr] = {"name": target_nick, "last_seen": time.time(), "user_modes": set()}

        current_modes = self.server.clients[target_addr].setdefault("user_modes", set())

        # Parse mode string (+i-w+s etc)
        adding = True
        changes_made = False

        # Dict-based mode handler dispatcher
        # Supports simple toggle modes (i, w, s) that just add/remove from current_modes
        # Special modes require custom logic (o = oper, a = away/no-op)
        mode_handlers = {
            "i": "simple",  # invisible mode
            "w": "simple",  # wallops mode
            "s": "simple",  # server notices mode
            "o": "oper",    # operator mode (requires permission checks and storage)
            "a": "noop",    # away mode (set via AWAY command only)
        }

        for char in mode_str:
            if char == "+":
                adding = True
            elif char == "-":
                adding = False
            elif char in mode_handlers:
                handler_type = mode_handlers[char]

                if handler_type == "simple":
                    # Simple toggle modes: just add or remove from current_modes
                    if adding:
                        if char not in current_modes:
                            current_modes.add(char)
                            changes_made = True
                    else:
                        if char in current_modes:
                            current_modes.discard(char)
                            changes_made = True

                elif handler_type == "oper":
                    # Operator mode: requires oper privilege, updates storage
                    if adding:
                        # Only opers can grant +o to other users
                        if not is_oper:
                            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                                             ":Permission Denied- You're not an IRC operator")
                            return
                        # Grant operator status
                        if target_nick.lower() not in self.server.opers:
                            self.server.add_active_oper(target_nick.lower())
                            current_modes.add("o")
                            changes_made = True
                    else:
                        # Revoke operator status (only opers can do this)
                        if not is_oper:
                            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                                             ":Permission Denied- You're not an IRC operator")
                            return
                        if target_nick.lower() in self.server.opers:
                            self.server.remove_active_oper(target_nick.lower())
                            current_modes.discard("o")
                            changes_made = True

                elif handler_type == "noop":
                    # Away mode: set via AWAY command only, silently ignore MODE changes
                    pass

            else:
                # Unknown mode flag
                self._send_numeric(addr, ERR_UMODEUNKNOWNFLAG, nick,
                                 f"Unknown MODE flag: {char}")
                return

        # Persist session data if changes were made
        if changes_made:
            self.server._persist_session_data()

        # Send updated mode string
        mode_str = "+" + "".join(sorted(current_modes)) if current_modes else "+"
        self._send_numeric(addr, RPL_UMODEIS, target_nick, mode_str)

    def _handle_channel_mode(self, msg, addr, nick, chan_name):
        """Parse and apply combined channel mode changes (up to 8 per command)."""
        mode_str = msg.params[1]
        channel = self.server.channel_manager.get_channel(chan_name)
        if not channel:
            self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                               f"{chan_name} :No such channel")
            return

        # Special case: MODE #channel +b (no params) = list bans (no chanop required)
        if mode_str in ("+b", "b") and len(msg.params) <= 2 and (len(msg.params) < 3):
            # If there's no ban mask parameter, just list bans
            if len(msg.params) == 2 or (len(msg.params) == 3 and not msg.params[2].strip()):
                self._send_ban_list(addr, nick, chan_name, channel)
                return

        # Require chanop or oper for all channel mode changes
        if nick.lower() not in self.server.opers and not channel.is_op(nick):
            self._send_numeric(addr, ERR_CHANOPRIVSNEEDED, nick,
                               f"{chan_name} :You're not channel operator")
            return

        # Parse the mode string into a list of (direction, char) tuples
        changes = []
        direction = "+"
        for ch in mode_str:
            if ch in ("+", "-"):
                direction = ch
            elif ch in self._NICK_MODES or ch in self._FLAG_MODES or ch in self._PARAM_MODES or ch in self._LIST_MODES:
                changes.append((direction, ch))
        # Enforce max 8 mode changes per command
        if len(changes) > 8:
            changes = changes[:8]

        # Parameters for nick-targeting modes and parametrized channel modes, consumed in order
        param_index = 2  # msg.params[0]=channel, [1]=modestring, [2..]=params

        # Track what was actually applied for the broadcast
        applied_modes = ""
        applied_params = []
        last_dir = None

        for direction, mode_char in changes:
            if mode_char in self._LIST_MODES:
                # Ban list mode (+b/-b)
                if direction == "+":
                    if param_index >= len(msg.params):
                        # +b with no param = list bans
                        self._send_ban_list(addr, nick, chan_name, channel)
                        continue
                    ban_mask = msg.params[param_index]
                    param_index += 1

                    # Normalize the ban mask
                    ban_mask = self._normalize_ban_mask(ban_mask)

                    # Check for duplicate
                    if ban_mask.lower() in {b.lower() for b in channel.ban_list}:
                        continue

                    # Check ban list limit
                    if len(channel.ban_list) >= self._MAX_BANS_PER_CHANNEL:
                        self._send_numeric(addr, ERR_BANLISTFULL, nick,
                                           f"{chan_name} {ban_mask} :Channel ban list is full")
                        continue

                    channel.ban_list.add(ban_mask)

                    if direction != last_dir:
                        applied_modes += direction
                        last_dir = direction
                    applied_modes += mode_char
                    applied_params.append(ban_mask)

                else:  # direction == "-"
                    if param_index >= len(msg.params):
                        continue
                    ban_mask = msg.params[param_index]
                    param_index += 1

                    ban_mask = self._normalize_ban_mask(ban_mask)

                    # Case-insensitive removal
                    to_remove = None
                    for existing in channel.ban_list:
                        if existing.lower() == ban_mask.lower():
                            to_remove = existing
                            break

                    if to_remove:
                        channel.ban_list.discard(to_remove)
                        if direction != last_dir:
                            applied_modes += direction
                            last_dir = direction
                        applied_modes += mode_char
                        applied_params.append(ban_mask)
                    # Removing non-existent ban is a silent no-op

                continue

            elif mode_char in self._NICK_MODES:
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

                member = channel.get_member(target_nick)
                if direction == "+":
                    # ChanServ Enforcement for modes
                    chanserv_info = self.server.chanserv_get(chan_name)
                    if chanserv_info:
                        # Enforce Mode (+E): require identification
                        if chanserv_info.get("enforce_mode"):
                            target_addr = self._find_client_addr(target_nick)
                            is_identified = target_addr and self.server.nickserv_identified.get(target_addr) == target_nick
                            if not is_identified:
                                self._chanserv_notice(addr, f"Cannot set +{mode_char} on {target_nick}: User is not identified (+E).")
                                continue

                        # Strict Ops (+S)
                        if mode_char == "o" and chanserv_info.get("strict_ops"):
                            if target_nick.lower() not in [n.lower() for n in chanserv_info.get("oplist", [])]:
                                self._chanserv_notice(addr, f"Cannot set +o on {target_nick}: User is not in oplist (+S).")
                                continue

                        # Strict Voice (+V)
                        if mode_char == "v" and chanserv_info.get("strict_voice"):
                            if target_nick.lower() not in [n.lower() for n in chanserv_info.get("voicelist", [])]:
                                self._chanserv_notice(addr, f"Cannot set +v on {target_nick}: User is not in voicelist (+V).")
                                continue

                    member["modes"].add(mode_char)
                else:
                    member["modes"].discard(mode_char)

                if direction != last_dir:
                    applied_modes += direction
                    last_dir = direction
                applied_modes += mode_char
                applied_params.append(target_nick)

            elif mode_char in self._PARAM_MODES:
                # Channel mode with a parameter (+l, +k)
                if direction == "+":
                    if param_index >= len(msg.params):
                        self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick,
                                           f"MODE :Not enough parameters for {direction}{mode_char}")
                        continue
                    mode_param = msg.params[param_index]
                    param_index += 1

                    if mode_char == "l":  # User limit
                        try:
                            channel.mode_params[mode_char] = int(mode_param)
                        except ValueError:
                            self._send_numeric(addr, ERR_UNKNOWNMODE, nick,
                                               f"MODE :Invalid limit for +l") 
                            continue
                    elif mode_char == "k": # Channel key
                        channel.mode_params[mode_char] = mode_param

                    channel.modes.add(mode_char)
                    applied_params.append(mode_param)
                else:  # direction == "-"
                    channel.modes.discard(mode_char)
                    channel.mode_params.pop(mode_char, None) 

                    # For removal, parameter is optional on the command line, but we consume it if present.
                    if param_index < len(msg.params):
                         param_index += 1


                if direction != last_dir:
                    applied_modes += direction
                    last_dir = direction
                applied_modes += mode_char
                

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

        # S2S: Notify federation network of mode change
        if hasattr(self.server, 's2s_network'):
            self.server.s2s_network.sync_channel_state(chan_name)

        # Real-time persistence: Save session state immediately
        self.server._persist_session_data()

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
        if nick.lower() not in self.server.opers and not channel.is_op(nick):
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

        # S2S: Notify federation network of membership change
        if hasattr(self.server, 's2s_network'):
            self.server.s2s_network.sync_channel_state(chan_name)

        # Real-time persistence: Save session state immediately
        self.server._persist_session_data()

    def _handle_kill(self, msg, addr):
        """KILL <nick> [:<reason>] — requires oper 'kill' flag."""
        nick = self._get_nick(addr)
        if not self.server.oper_has_flag(nick, "kill"):
            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                               "KILL :Permission Denied- You do not have the kill flag")
            return

        if len(msg.params) < 1:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "KILL :Not enough parameters")
            return

        target_nick = msg.params[0]
        reason = msg.params[1] if len(msg.params) > 1 else "Killed by operator"

        # protect_local_opers: local opers cannot kill other opers unless they have O flag
        if target_nick.lower() in self.server.opers:
            if not self.server.is_global_oper(nick):
                self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                                   "Permission Denied- Cannot KILL an IRC operator (need global oper flag O)")
                return

        kill_reason = f"Killed by {nick}: {reason}"
        if not self._server_kill(target_nick, kill_reason):
            self._send_numeric(addr, ERR_NOSUCHNICK, nick,
                               f"{target_nick} :No such nick/channel")
            return

        self.server.log(f"[KILL] {nick} killed {target_nick}: {reason}")
        self.server.send_wallops(f"{nick} killed {target_nick}: {reason}")

    def _handle_connect(self, msg, addr):
        """CONNECT <host> <port> [password] — Initiate S2S link. Requires 'connect' flag."""
        nick = self._get_nick(addr)
        if not self.server.oper_has_flag(nick, "connect"):
            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                               "Permission Denied- You do not have the connect flag")
            return

        if len(msg.params) < 2:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "CONNECT :Not enough parameters. Usage: CONNECT <host> <port> [password]")
            return

        host = msg.params[0]
        try:
            port = int(msg.params[1])
        except ValueError:
            self._send_notice(addr, "Invalid port number.")
            return

        password = msg.params[2] if len(msg.params) > 2 else None

        if not hasattr(self.server, 's2s_network'):
            self._send_notice(addr, "S2S network not initialized.")
            return

        self.server.log(f"[S2S] {nick} initiated CONNECT to {host}:{port}")
        self._send_notice(addr, f"Attempting to connect to {host}:{port}...")
        
        # Link in background to avoid blocking the main server loop
        def do_link():
            success = self.server.s2s_network.link_to(host, port, password)
            if success:
                self._send_notice(addr, f"Successfully linked to {host}:{port}.")
            else:
                self._send_notice(addr, f"Failed to link to {host}:{port}. Check logs for details.")

        threading.Thread(target=do_link, daemon=True).start()

    def _handle_squit_cmd(self, msg, addr):
        """SQUIT <server_id> [:<reason>] — Drop an S2S link. Requires 'squit' flag."""
        nick = self._get_nick(addr)
        if not self.server.oper_has_flag(nick, "squit"):
            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                               "Permission Denied- You do not have the squit flag")
            return

        if len(msg.params) < 1:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "SQUIT :Not enough parameters. Usage: SQUIT <server_id> [:<reason>]")
            return

        server_id = msg.params[0]
        reason = msg.params[1] if len(msg.params) > 1 else "Dropped by operator"

        if not hasattr(self.server, 's2s_network'):
            self._send_notice(addr, "S2S network not initialized.")
            return

        link = self.server.s2s_network.get_link(server_id)
        if not link:
            self._send_notice(addr, f"No active link to {server_id}.")
            return

        self.server.log(f"[S2S] {nick} initiated SQUIT for {server_id}: {reason}")
        link.send_message("SQUIT", self.server.s2s_network.server_id, reason)
        link.close()
        self._send_notice(addr, f"Link to {server_id} closed.")

    # ======================================================================
    # Oper Hierarchy Commands: TRUST, SETMOTD, STATS, REHASH, SHUTDOWN, LOCALCONFIG
    # ======================================================================

    def _handle_trust(self, msg, addr):
        """TRUST <ADD|REMOVE|LIST> [nick_or_host] — Manage trusted hosts/nicks.

        Requires 'trust' oper flag.

        ADD <nick>    - Mark a connected nick as trusted (bypasses some restrictions).
        REMOVE <nick> - Remove trust from a nick.
        LIST          - Show all currently trusted nicks.
        """
        nick = self._get_nick(addr)
        if not self.server.oper_has_flag(nick, "trust"):
            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                               "TRUST :Permission Denied- You do not have the trust flag")
            return

        if not msg.params:
            self._send_notice(addr, "Usage: TRUST <ADD|REMOVE|LIST> [nick]")
            return

        subcmd = msg.params[0].upper()

        if subcmd == "LIST":
            trust_list = self.server.load_settings().get("trusted_nicks", [])
            if not trust_list:
                self._send_notice(addr, "No trusted nicks configured.")
            else:
                for trusted_nick in trust_list:
                    self._send_notice(addr, f"  TRUST: {trusted_nick}")
            self._send_notice(addr, "End of TRUST list.")
            return

        if len(msg.params) < 2:
            self._send_notice(addr, "Usage: TRUST ADD <nick> | TRUST REMOVE <nick>")
            return

        target = msg.params[1]

        if subcmd == "ADD":
            settings = self.server.load_settings()
            trusted = set(settings.get("trusted_nicks", []))
            trusted.add(target.lower())
            settings["trusted_nicks"] = sorted(trusted)
            self.server.save_settings(settings)
            self._send_notice(addr, f"Added {target} to trusted list.")
            self.server.log(f"[TRUST] {nick} added {target} to trusted nicks")
            self.server.send_wallops(f"{nick} added {target} to trusted nicks")

        elif subcmd == "REMOVE":
            settings = self.server.load_settings()
            trusted = set(settings.get("trusted_nicks", []))
            trusted.discard(target.lower())
            settings["trusted_nicks"] = sorted(trusted)
            self.server.save_settings(settings)
            self._send_notice(addr, f"Removed {target} from trusted list.")
            self.server.log(f"[TRUST] {nick} removed {target} from trusted nicks")
        else:
            self._send_notice(addr, "Usage: TRUST <ADD|REMOVE|LIST> [nick]")

    def _handle_setmotd(self, msg, addr):
        """SETMOTD :<new message of the day> — Requires 'setmotd' oper flag."""
        nick = self._get_nick(addr)
        if not self.server.oper_has_flag(nick, "setmotd"):
            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                               "SETMOTD :Permission Denied- You do not have the setmotd flag")
            return

        if not msg.params:
            self._send_notice(addr, "Usage: SETMOTD :<message>")
            return

        new_motd = msg.params[0]
        # Persist MOTD
        self.server.put_data("motd", new_motd)
        self._send_notice(addr, f"MOTD updated: {new_motd}")
        self.server.log(f"[SETMOTD] {nick} set new MOTD: {new_motd!r}")
        self.server.send_wallops(f"{nick} set a new MOTD")

        # Broadcast update notice to all channels
        prefix = f"{nick}!{nick}@{SERVER_NAME}"
        for channel in self.server.channel_manager.list_channels():
            notice = format_irc_message(
                prefix, "NOTICE", [channel.name], f"MOTD updated by {nick}: {new_motd}"
            ) + "\r\n"
            self.server.broadcast_to_channel(channel.name, notice)

    def _handle_stats(self, msg, addr):
        """STATS [letter] — Server statistics query. Requires 'stats' oper flag.

        Letters:
          o - List all configured O-lines (oper blocks).
          u - Server uptime.
          m - Active oper count.
          c - Connected client count.
        """
        nick = self._get_nick(addr)
        if not self.server.oper_has_flag(nick, "stats"):
            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                               "STATS :Permission Denied- You do not have the stats flag")
            return

        letter = msg.params[0].lower() if msg.params else "u"

        if letter == "o":
            # O-lines
            olines = self.server.get_olines()
            if not olines:
                self._send_notice(addr, "STATS o: No O-lines configured.")
            else:
                for oper_name, info in olines.items():
                    flags_str = ",".join(info.get("flags", []))
                    self._send_notice(
                        addr,
                        f"O-line: {oper_name} host={info.get('host','*')} "
                        f"class={info.get('class','local')} flags=[{flags_str}]"
                    )

        elif letter == "u":
            # Uptime
            uptime = int(time.time() - getattr(self.server, "startup_time", time.time()))
            days, rem = divmod(uptime, 86400)
            hours, rem = divmod(rem, 3600)
            mins, secs = divmod(rem, 60)
            self._send_notice(addr,
                f"STATS u: Server up {days}d {hours:02d}h {mins:02d}m {secs:02d}s")

        elif letter == "m":
            # Active opers
            active = list(self.server.opers)
            self._send_notice(addr, f"STATS m: {len(active)} active oper(s): "
                              f"{', '.join(active) if active else '(none)'}")

        elif letter == "c":
            # Client count
            total = len(self.server.clients)
            registered = sum(1 for i in self.server.clients.values() if i.get("name"))
            self._send_notice(addr,
                f"STATS c: {total} connections, {registered} registered clients")

        else:
            self._send_notice(addr,
                f"STATS: Unknown letter '{letter}'. Known: o (olines), u (uptime), "
                f"m (opers), c (clients)")

    def _handle_rehash(self, msg, addr):
        """REHASH — no longer supported. opers.json is the sole authority."""
        nick = self._get_nick(addr)
        if not nick:
            return
        self._send_notice(addr, "REHASH is no longer supported. Edit opers.json directly.")

    def _handle_shutdown(self, msg, addr):
        """SHUTDOWN [:<reason>] — Gracefully shut down the server. Requires 'shutdown' flag."""
        nick = self._get_nick(addr)
        if not self.server.oper_has_flag(nick, "shutdown"):
            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                               "SHUTDOWN :Permission Denied- You do not have the shutdown flag")
            return

        reason = msg.params[0] if msg.params else "Operator shutdown"
        self.server.log(f"[SHUTDOWN] {nick} initiated server shutdown: {reason}")
        self.server.send_wallops(f"Server is shutting down: {reason} (initiated by {nick})")

        # Broadcast ERROR to all clients
        error_msg = f"ERROR :Server shutting down: {reason}\r\n"
        for saddr in list(self.server.clients.keys()):
            try:
                self.server.sock_send(error_msg.encode(), saddr)
            except Exception:
                pass

        self.server._running = False

    def _handle_localconfig(self, msg, addr):
        """LOCALCONFIG <key> [value] — Read or set a local server config value.

        Requires 'localconfig' oper flag.

        LOCALCONFIG <key>          - Get current value of key.
        LOCALCONFIG <key> <value>  - Set key to value.
        LOCALCONFIG LIST           - List all local config keys.
        """
        nick = self._get_nick(addr)
        if not self.server.oper_has_flag(nick, "localconfig"):
            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                               "LOCALCONFIG :Permission Denied- You do not have the localconfig flag")
            return

        if not msg.params:
            self._send_notice(addr, "Usage: LOCALCONFIG <key> [value] | LOCALCONFIG LIST")
            return

        key = msg.params[0]

        if key.upper() == "LIST":
            settings = self.server.load_settings()
            local_cfg = settings.get("local_config", {})
            if not local_cfg:
                self._send_notice(addr, "LOCALCONFIG: No local config entries.")
            else:
                for k, v in sorted(local_cfg.items()):
                    self._send_notice(addr, f"  {k} = {v}")
            self._send_notice(addr, "End of LOCALCONFIG list.")
            return

        settings = self.server.load_settings()
        local_cfg = settings.setdefault("local_config", {})

        if len(msg.params) == 1:
            # Query
            val = local_cfg.get(key)
            if val is None:
                self._send_notice(addr, f"LOCALCONFIG: {key} is not set.")
            else:
                self._send_notice(addr, f"LOCALCONFIG: {key} = {val}")
        else:
            # Set
            value = msg.params[1]
            local_cfg[key] = value
            self.server.save_settings(settings)
            self._send_notice(addr, f"LOCALCONFIG: {key} set to {value!r}")
            self.server.log(f"[LOCALCONFIG] {nick} set {key}={value!r}")

    # ======================================================================
    # Server Kill — core disconnect logic used by KILL, QUIT, GHOST, NickServ
    # ======================================================================

    def _server_kill(self, target_nick, reason="Disconnected"):
        """Disconnect a client by nick. Cleans up channels, clients, registration,
        NickServ state, PM buffers, persists to disk. Returns the killed nick if found, else False."""
        # Find target address
        target_addr = None
        actual_nick = None
        for a, info in list(self.server.clients.items()):
            if info.get("name", "").lower() == target_nick.lower():
                target_addr = a
                actual_nick = info.get("name")
                break

        if not target_addr:
            return False

        nick = actual_nick or target_nick

        # Broadcast QUIT to all channels the user is in
        prefix = f"{nick}!{nick}@{SERVER_NAME}"
        quit_msg = format_irc_message(prefix, "QUIT", [], reason) + "\r\n"
        
        # S2S: Notify federation network of user quit
        if hasattr(self.server, 's2s_network'):
            self.server.s2s_network.sync_user_quit(nick, reason)

        channels = self.server.channel_manager.find_channels_for_nick(nick)
        notified = set()
        for ch in channels:
            for m_nick, m_info in list(ch.members.items()):
                m_addr = m_info.get("addr")
                if m_addr and m_addr != target_addr and m_addr not in notified:
                    self.server.sock_send(quit_msg.encode(), m_addr)
                    notified.add(m_addr)

        # Remove from all channels
        self.server.channel_manager.remove_nick_from_all(nick)

        # Send ERROR to the disconnected client
        error_msg = f"ERROR :Closing Link: {nick} ({reason})\r\n"
        self.server.sock_send(error_msg.encode(), target_addr)

        # Capture registration info for WHOWAS before cleanup
        target_reg = self.registration_state.get(target_addr, {})
        target_user = target_reg.get("user", nick)
        target_realname = target_reg.get("realname", nick)

        # Remove from active opers on disk if they were an oper
        if nick.lower() in self.server.opers:
            self.server.remove_active_oper(nick.lower())

        # Remove from all server state
        self.server.clients.pop(target_addr, None)
        self.registration_state.pop(target_addr, None)
        self.server.nickserv_identified.pop(target_addr, None)
        self._pm_buffer_replayed = {k for k in self._pm_buffer_replayed if k[0] != target_addr}

        # Persist disconnection to history.json for WHOWAS
        try:
            self.server.add_disconnection(
                nick=nick, user=target_user, realname=target_realname,
                host=SERVER_NAME, quit_reason=reason,
            )
        except Exception as e:
            self.server.log(f"[STORAGE ERROR] Failed to persist disconnection for {nick}: {e}")

        # Persist session state
        self.server._persist_session_data()
        return nick

    # ======================================================================
    # NickServ (Ghost Recovery)
    # ======================================================================

    def _handle_nickserv(self, msg, addr):
        """Handle PRIVMSG NickServ :COMMAND args — virtual NickServ service.

        Works even from unregistered clients so they can GHOST/IDENTIFY
        before re-registering.

        Commands: REGISTER, IDENTIFY, GHOST, INFO, DROP
        """
        text = msg.params[-1].strip()
        parts = text.split()
        if not parts:
            self._nickserv_notice(addr, "NickServ commands: REGISTER <password>, IDENTIFY <password>, GHOST <nick> <password>, INFO <nick>, DROP <password>")
            return

        subcmd = parts[0].upper()
        args = parts[1:]

        commands = {
            "REGISTER": self._nickserv_register,
            "IDENTIFY": self._nickserv_identify,
            "GHOST": self._nickserv_ghost,
            "INFO": self._nickserv_info,
            "DROP": self._nickserv_drop,
        }

        handler = commands.get(subcmd)
        if handler:
            handler(args, addr)
        else:
            self._nickserv_notice(addr, f"Unknown command: {subcmd}. Commands: REGISTER, IDENTIFY, GHOST, INFO, DROP")

    def _nickserv_register(self, args, addr):
        """REGISTER <password> — register your current nick with NickServ."""
        if not self._is_registered(addr):
            self._nickserv_notice(addr, "You must be connected and registered to use REGISTER.")
            return

        nick = self._get_nick(addr)
        if not nick:
            self._nickserv_notice(addr, "You must have a nick to register.")
            return

        if len(args) < 1:
            self._nickserv_notice(addr, "Syntax: REGISTER <password>")
            return

        password = args[0]

        if len(password) < 1:
            self._nickserv_notice(addr, "Password cannot be empty.")
            return

        # Check if already registered
        existing = self.server.nickserv_get(nick)
        if existing:
            self._nickserv_notice(addr, f"Nick {nick} is already registered.")
            return

        reg_info = self.registration_state.get(addr, {})
        registered_by = f"{reg_info.get('user', nick)}@{SERVER_NAME}"

        if self.server.nickserv_register(nick, password, registered_by):
            # Auto-identify on register
            self.server.nickserv_identified[addr] = nick
            self._nickserv_notice(addr, f"Nick {nick} has been registered. You are now identified.")
            self.server.log(f"[NICKSERV] {nick} registered their nick")
        else:
            self._nickserv_notice(addr, "Registration failed. Nick may already be registered.")

    def _nickserv_identify(self, args, addr):
        """IDENTIFY <password> — identify as the owner of your current nick."""
        nick = self._get_nick(addr)
        if not nick:
            self._nickserv_notice(addr, "You must have a nick to identify.")
            return

        if len(args) < 1:
            self._nickserv_notice(addr, "Syntax: IDENTIFY <password>")
            return

        password = args[0]

        if self.server.nickserv_check_password(nick, password):
            self.server.nickserv_identified[addr] = nick
            self._nickserv_notice(addr, f"You are now identified for {nick}.")
            self.server.log(f"[NICKSERV] {nick} identified from {addr}")

            # Cancel any pending enforcement timer
            timer_key = f"_nickserv_enforce_{addr}"
            timer = getattr(self, timer_key, None)
            if timer:
                timer.cancel()
                delattr(self, timer_key)
        else:
            self._nickserv_notice(addr, "Invalid password.")
            self.server.log(f"[NICKSERV] Failed IDENTIFY for {nick} from {addr}")

    def _nickserv_ghost(self, args, addr):
        """GHOST <nickname> <password> — kill a ghost session to reclaim a nick."""
        if len(args) < 2:
            self._nickserv_notice(addr, "Syntax: GHOST <nickname> <password>")
            return

        target_nick = args[0]
        password = args[1]

        # Validate against NickServ password
        if not self.server.nickserv_check_password(target_nick, password):
            self._nickserv_notice(addr, "Authentication failed. Nick is not registered or wrong password.")
            self.server.log(f"[NICKSERV] GHOST failed for {target_nick} from {addr}: bad credentials")
            return

        killed_nick = self._server_kill(target_nick, "Ghosted")
        if not killed_nick:
            self._nickserv_notice(addr, f"No session found for {target_nick}.")
            return

        self._nickserv_notice(addr, f"Session for {killed_nick} has been killed. You may now use that nick.")
        self.server.log(f"[NICKSERV] GHOST: {killed_nick} ghosted by {addr}")
        self.server.send_wallops(f"NickServ: {killed_nick} was ghosted by {addr}")

    def _nickserv_info(self, args, addr):
        """INFO <nickname> — show registration info for a nick."""
        if len(args) < 1:
            self._nickserv_notice(addr, "Syntax: INFO <nickname>")
            return

        target = args[0]
        info = self.server.nickserv_get(target)
        if not info:
            self._nickserv_notice(addr, f"{target} is not registered.")
            return

        registered_at = info.get("registered_at", 0)
        if registered_at:
            import datetime
            ts = datetime.datetime.fromtimestamp(registered_at).strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts = "unknown"

        self._nickserv_notice(addr, f"Info for {info.get('nick', target)}:")
        self._nickserv_notice(addr, f"  Registered: {ts}")
        self._nickserv_notice(addr, f"  Registered by: {info.get('registered_by', 'unknown')}")

    def _nickserv_drop(self, args, addr):
        """DROP <password> — unregister your current nick."""
        if not self._is_registered(addr):
            self._nickserv_notice(addr, "You must be connected to use DROP.")
            return

        nick = self._get_nick(addr)
        if not nick:
            self._nickserv_notice(addr, "You must have a nick to drop.")
            return

        if len(args) < 1:
            self._nickserv_notice(addr, "Syntax: DROP <password>")
            return

        password = args[0]

        if not self.server.nickserv_check_password(nick, password):
            self._nickserv_notice(addr, "Invalid password.")
            return

        if self.server.nickserv_drop(nick):
            self.server.nickserv_identified.pop(addr, None)
            self._nickserv_notice(addr, f"Nick {nick} has been dropped.")
            self.server.log(f"[NICKSERV] {nick} dropped their registration")
        else:
            self._nickserv_notice(addr, "Failed to drop nick.")

    def _nickserv_notice(self, addr, text):
        """Send a NOTICE from NickServ to a client."""
        nick = self._get_nick(addr) or "*"
        notice = f":NickServ!NickServ@{SERVER_NAME} NOTICE {nick} :{text}\r\n"
        self.server.sock_send(notice.encode(), addr)

    # ======================================================================
    # ChanServ
    # ======================================================================

    def _handle_chanserv(self, msg, addr):
        """Handle PRIVMSG ChanServ :COMMAND args — virtual ChanServ service.

        Commands: REGISTER, OP, DEOP, VOICE, DEVOICE, BAN, UNBAN, INFO, LIST
        """
        text = msg.params[-1].strip()
        parts = text.split()
        if not parts:
            self._chanserv_notice(addr, "ChanServ commands: REGISTER <#chan> <topic>, OP <#chan> <nick>, VOICE <#chan> <nick>, BAN <#chan> <mask>, INFO <#chan>, LIST")
            return

        subcmd = parts[0].upper()
        args = parts[1:]

        commands = {
            "REGISTER": self._chanserv_register,
            "OP":       self._chanserv_op,
            "DEOP":     self._chanserv_deop,
            "VOICE":    self._chanserv_voice,
            "DEVOICE":  self._chanserv_devoice,
            "BAN":      self._chanserv_ban,
            "UNBAN":    self._chanserv_unban,
            "SET":      self._chanserv_set,
            "INFO":     self._chanserv_info,
            "LIST":     self._chanserv_list,
        }

        handler = commands.get(subcmd)
        if handler:
            handler(args, addr)
        else:
            self._chanserv_notice(addr, f"Unknown command: {subcmd}. Commands: REGISTER, OP, VOICE, BAN, SET, INFO, LIST")

    def _chanserv_set(self, args, addr):
        """SET <#chan> <option> <on/off>"""
        nick = self._get_nick(addr)
        if len(args) < 3:
            self._chanserv_notice(addr, "Syntax: SET <#chan> <option> <on/off>")
            return

        chan_name, option, value = args[0], args[1].upper(), args[2].lower()
        info = self.server.chanserv_get(chan_name)
        if not info:
            self._chanserv_notice(addr, f"Channel {chan_name} is not registered.")
            return

        if info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
            self._chanserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
            return

        bool_value = value in ("on", "true", "1", "yes")
        
        option_map = {
            "ENFORCEMODE":  "enforce_mode",
            "ENFORCETOPIC": "enforce_topic",
            "STRICTOPS":    "strict_ops",
            "STRICTVOICE":  "strict_voice",
        }

        if option not in option_map:
            self._chanserv_notice(addr, f"Unknown option: {option}. Options: ENFORCEMODE, ENFORCETOPIC, STRICTOPS, STRICTVOICE")
            return

        info[option_map[option]] = bool_value
        self.server.chanserv_update(chan_name, info)
        self._chanserv_notice(addr, f"Option {option} for {chan_name} set to {'on' if bool_value else 'off'}.")
        
        # Sync with channel modes if applicable
        channel = self.server.channel_manager.get_channel(chan_name)
        if channel:
            mode_map = {
                "ENFORCEMODE":  "E",
                "ENFORCETOPIC": "T",
                "STRICTOPS":    "S",
                "STRICTVOICE":  "V",
            }
            mode_char = mode_map[option]
            if bool_value:
                channel.modes.add(mode_char)
            else:
                channel.modes.discard(mode_char)
            
            # Broadcast mode change
            prefix = f"ChanServ!ChanServ@{SERVER_NAME}"
            mode_msg = f":{prefix} MODE {chan_name} {'+' if bool_value else '-'}{mode_char}\r\n"
            self.server.broadcast_to_channel(chan_name, mode_msg)

    def _chanserv_register(self, args, addr):
        """REGISTER <#chan> <topic>"""
        nick = self._get_nick(addr)
        if not nick:
            self._chanserv_notice(addr, "You must be registered to use ChanServ.")
            return

        if len(args) < 1:
            self._chanserv_notice(addr, "Syntax: REGISTER <#chan> <topic>")
            return

        chan_name = args[0]
        topic = " ".join(args[1:]) if len(args) > 1 else ""

        if not chan_name.startswith("#"):
            self._chanserv_notice(addr, f"Invalid channel name '{chan_name}'. Must start with #.")
            return

        channel = self.server.channel_manager.get_channel(chan_name)
        if not channel:
            self._chanserv_notice(addr, f"Channel {chan_name} does not exist. Join it first.")
            return

        # Authorization: Must be chanop or oper
        if not self._is_authorized(nick, chan_name):
            self._chanserv_notice(addr, f"You must be a channel operator of {chan_name} to register it.")
            return

        if self.server.chanserv_register(chan_name, nick, topic):
            self._chanserv_notice(addr, f"Channel {chan_name} is now registered to {nick}.")
            self.server.log(f"[CHANSERV] {nick} registered channel {chan_name}")
            # Apply state
            if topic:
                channel.topic = topic
                # Broadcast topic change
                prefix = f"ChanServ!ChanServ@{SERVER_NAME}"
                topic_msg = format_irc_message(prefix, "TOPIC", [chan_name], topic) + "\r\n"
                self.server.broadcast_to_channel(chan_name, topic_msg)
        else:
            self._chanserv_notice(addr, f"Channel {chan_name} is already registered.")

    def _chanserv_op(self, args, addr):
        """OP <#chan> <nick>"""
        nick = self._get_nick(addr)
        if len(args) < 2:
            self._chanserv_notice(addr, "Syntax: OP <#chan> <nick>")
            return

        chan_name, target_nick = args[0], args[1]
        info = self.server.chanserv_get(chan_name)
        if not info:
            self._chanserv_notice(addr, f"Channel {chan_name} is not registered.")
            return

        # Only owner or oper
        if info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
            self._chanserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
            return

        oplist = info.setdefault("oplist", [])
        if target_nick.lower() not in [n.lower() for n in oplist]:
            oplist.append(target_nick)
            self.server.chanserv_update(chan_name, info)
            self._chanserv_notice(addr, f"{target_nick} added to {chan_name} oplist.")
        
        # Grant mode if in channel
        channel = self.server.channel_manager.get_channel(chan_name)
        if channel and channel.has_member(target_nick):
            member = channel.get_member(target_nick)
            if "o" not in member["modes"]:
                member["modes"].add("o")
                # Broadcast mode change
                prefix = f"ChanServ!ChanServ@{SERVER_NAME}"
                mode_msg = f":{prefix} MODE {chan_name} +o {target_nick}\r\n"
                self.server.broadcast_to_channel(chan_name, mode_msg)

    def _chanserv_deop(self, args, addr):
        """DEOP <#chan> <nick>"""
        nick = self._get_nick(addr)
        if len(args) < 2:
            self._chanserv_notice(addr, "Syntax: DEOP <#chan> <nick>")
            return

        chan_name, target_nick = args[0], args[1]
        info = self.server.chanserv_get(chan_name)
        if not info:
            self._chanserv_notice(addr, f"Channel {chan_name} is not registered.")
            return

        if info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
            self._chanserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
            return

        oplist = info.get("oplist", [])
        new_oplist = [n for n in oplist if n.lower() != target_nick.lower()]
        if len(new_oplist) < len(oplist):
            info["oplist"] = new_oplist
            self.server.chanserv_update(chan_name, info)
            self._chanserv_notice(addr, f"{target_nick} removed from {chan_name} oplist.")
        
        # Revoke mode
        channel = self.server.channel_manager.get_channel(chan_name)
        if channel and channel.has_member(target_nick):
            member = channel.get_member(target_nick)
            if "o" in member["modes"]:
                member["modes"].discard("o")
                prefix = f"ChanServ!ChanServ@{SERVER_NAME}"
                mode_msg = f":{prefix} MODE {chan_name} -o {target_nick}\r\n"
                self.server.broadcast_to_channel(chan_name, mode_msg)

    def _chanserv_voice(self, args, addr):
        """VOICE <#chan> <nick>"""
        nick = self._get_nick(addr)
        if len(args) < 2:
            self._chanserv_notice(addr, "Syntax: VOICE <#chan> <nick>")
            return

        chan_name, target_nick = args[0], args[1]
        info = self.server.chanserv_get(chan_name)
        if not info:
            self._chanserv_notice(addr, f"Channel {chan_name} is not registered.")
            return

        if info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
            self._chanserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
            return

        voicelist = info.setdefault("voicelist", [])
        if target_nick.lower() not in [n.lower() for n in voicelist]:
            voicelist.append(target_nick)
            self.server.chanserv_update(chan_name, info)
            self._chanserv_notice(addr, f"{target_nick} added to {chan_name} voicelist.")
        
        # Grant mode
        channel = self.server.channel_manager.get_channel(chan_name)
        if channel and channel.has_member(target_nick):
            member = channel.get_member(target_nick)
            if "v" not in member["modes"]:
                member["modes"].add("v")
                prefix = f"ChanServ!ChanServ@{SERVER_NAME}"
                mode_msg = f":{prefix} MODE {chan_name} +v {target_nick}\r\n"
                self.server.broadcast_to_channel(chan_name, mode_msg)

    def _chanserv_devoice(self, args, addr):
        """DEVOICE <#chan> <nick>"""
        nick = self._get_nick(addr)
        if len(args) < 2:
            self._chanserv_notice(addr, "Syntax: DEVOICE <#chan> <nick>")
            return

        chan_name, target_nick = args[0], args[1]
        info = self.server.chanserv_get(chan_name)
        if not info:
            self._chanserv_notice(addr, f"Channel {chan_name} is not registered.")
            return

        if info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
            self._chanserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
            return

        voicelist = info.get("voicelist", [])
        new_voicelist = [n for n in voicelist if n.lower() != target_nick.lower()]
        if len(new_voicelist) < len(voicelist):
            info["voicelist"] = new_voicelist
            self.server.chanserv_update(chan_name, info)
            self._chanserv_notice(addr, f"{target_nick} removed from {chan_name} voicelist.")
        
        # Revoke mode
        channel = self.server.channel_manager.get_channel(chan_name)
        if channel and channel.has_member(target_nick):
            member = channel.get_member(target_nick)
            if "v" in member["modes"]:
                member["modes"].discard("v")
                prefix = f"ChanServ!ChanServ@{SERVER_NAME}"
                mode_msg = f":{prefix} MODE {chan_name} -v {target_nick}\r\n"
                self.server.broadcast_to_channel(chan_name, mode_msg)

    def _chanserv_ban(self, args, addr):
        """BAN <#chan> <mask>"""
        nick = self._get_nick(addr)
        if len(args) < 1:
            self._chanserv_notice(addr, "Syntax: BAN <#chan> <mask>")
            return

        chan_name = args[0]
        info = self.server.chanserv_get(chan_name)
        if not info:
            self._chanserv_notice(addr, f"Channel {chan_name} is not registered.")
            return

        if len(args) < 2:
            # List bans
            bans = info.get("banlist", [])
            if not bans:
                self._chanserv_notice(addr, f"No bans for {chan_name}.")
            else:
                self._chanserv_notice(addr, f"Bans for {chan_name}:")
                for b in bans:
                    self._chanserv_notice(addr, f"  {b}")
            return

        mask = args[1]
        if info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
            self._chanserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
            return

        banlist = info.setdefault("banlist", [])
        if mask.lower() not in [b.lower() for b in banlist]:
            banlist.append(mask)
            self.server.chanserv_update(chan_name, info)
            self._chanserv_notice(addr, f"Mask {mask} added to {chan_name} banlist.")
            
            # Apply ban immediately if possible
            channel = self.server.channel_manager.get_channel(chan_name)
            if channel:
                channel.ban_list.add(mask)
                # KICK matching users
                for m_nick, m_info in list(channel.members.items()):
                    m_addr = m_info.get("addr")
                    if m_addr:
                        m_reg = self.registration_state.get(m_addr, {})
                        m_user = m_reg.get("user", m_nick)
                        if self._is_banned(channel, m_nick, m_user, SERVER_NAME):
                             self._server_kill(m_nick, f"Banned from {chan_name} by ChanServ")

    def _chanserv_unban(self, args, addr):
        """UNBAN <#chan> <mask>"""
        nick = self._get_nick(addr)
        if len(args) < 2:
            self._chanserv_notice(addr, "Syntax: UNBAN <#chan> <mask>")
            return

        chan_name, mask = args[0], args[1]
        info = self.server.chanserv_get(chan_name)
        if not info:
            self._chanserv_notice(addr, f"Channel {chan_name} is not registered.")
            return

        if info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
            self._chanserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
            return

        banlist = info.get("banlist", [])
        new_banlist = [b for b in banlist if b.lower() != mask.lower()]
        if len(new_banlist) < len(banlist):
            info["banlist"] = new_banlist
            self.server.chanserv_update(chan_name, info)
            self._chanserv_notice(addr, f"Mask {mask} removed from {chan_name} banlist.")
            
            channel = self.server.channel_manager.get_channel(chan_name)
            if channel:
                channel.ban_list.discard(mask)

    def _chanserv_info(self, args, addr):
        """INFO <#chan>"""
        if not args:
            self._chanserv_notice(addr, "Syntax: INFO <#chan>")
            return
        chan_name = args[0]
        info = self.server.chanserv_get(chan_name)
        if not info:
            self._chanserv_notice(addr, f"Channel {chan_name} is not registered.")
            return

        self._chanserv_notice(addr, f"Information for {chan_name}:")
        self._chanserv_notice(addr, f"  Owner: {info['owner']}")
        self._chanserv_notice(addr, f"  Topic: {info.get('topic', 'None')}")
        self._chanserv_notice(addr, f"  Registered: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(info['created_at']))}")
        self._chanserv_notice(addr, f"  Ops: {', '.join(info.get('oplist', []))}")

    def _chanserv_list(self, args, addr):
        """LIST"""
        data = self.server.load_chanserv()
        channels = data.get("channels", {})
        if not channels:
            self._chanserv_notice(addr, "No channels registered.")
            return
        self._chanserv_notice(addr, "Registered channels:")
        for name, info in channels.items():
            self._chanserv_notice(addr, f"  {info['channel']} (Owner: {info['owner']})")

    def _chanserv_notice(self, addr, text):
        """Send a NOTICE from ChanServ to a client."""
        nick = self._get_nick(addr) or "*"
        notice = f":ChanServ!ChanServ@{SERVER_NAME} NOTICE {nick} :{text}\r\n"
        self.server.sock_send(notice.encode(), addr)

    # ======================================================================
    # BotServ
    # ======================================================================

    def _handle_botserv(self, msg, addr):
        """Handle PRIVMSG BotServ :COMMAND args — virtual BotServ service.

        Commands: ADD, DEL, LIST
        """
        text = msg.params[-1].strip()
        parts = text.split()
        if not parts:
            self._botserv_notice(addr, "BotServ commands: ADD <botnick> <#chan> <password>, DEL <botnick> <#chan>, LIST [#chan]")
            return

        subcmd = parts[0].upper()
        args = parts[1:]

        commands = {
            "ADD":    self._botserv_add,
            "DEL":    self._botserv_del,
            "LIST":   self._botserv_list,
            "SETLOG": self._botserv_setlog,
        }

        handler = commands.get(subcmd)
        if handler:
            handler(args, addr)
        else:
            self._botserv_notice(addr, f"Unknown command: {subcmd}. Commands: ADD, DEL, LIST, SETLOG")

    def _botserv_setlog(self, args, addr):
        """SETLOG <botnick> <#chan> <log_file> [enable/disable]"""
        nick = self._get_nick(addr)
        if len(args) < 3:
            self._botserv_notice(addr, "Syntax: SETLOG <botnick> <#chan> <log_file> [enable/disable]")
            return

        botnick, chan_name, log_file = args[0], args[1], args[2]
        enabled_str = args[3].lower() if len(args) > 3 else "enable"
        enabled = enabled_str in ("enable", "on", "true", "1", "yes")

        # Check ChanServ ownership
        chanserv_info = self.server.chanserv_get(chan_name)
        if not chanserv_info:
            self._botserv_notice(addr, f"Channel {chan_name} is not registered.")
            return

        if chanserv_info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
            self._botserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
            return

        # Check if bot registered for this channel
        bot_info = self.server.botserv_get(chan_name, botnick)
        if not bot_info:
            self._botserv_notice(addr, f"Bot {botnick} is not registered for {chan_name}.")
            return

        # Update bot info
        logs = bot_info.setdefault("logs", [])
        if enabled:
            if log_file not in logs:
                logs.append(log_file)
            bot_info["logs_enabled"] = True
        else:
            if log_file in logs:
                logs.remove(log_file)
            if not logs:
                bot_info["logs_enabled"] = False

        # Use a new storage method or update manually
        # I'll use save_botserv directly for now
        data = self.server.load_botserv()
        key = f"{chan_name.lower()}:{botnick.lower()}"
        data["bots"][key] = bot_info
        self.server.save_botserv(data)

        self._botserv_notice(addr, f"Log {log_file} {enabled_str}d for {botnick} on {chan_name}.")
        self.server.log(f"[BOTSERV] {nick} {enabled_str}d log {log_file} for {botnick}")

    def _botserv_add(self, args, addr):
        """ADD <botnick> <#chan> <password>"""
        nick = self._get_nick(addr)
        if not nick:
            self._botserv_notice(addr, "You must be registered to use BotServ.")
            return

        if len(args) < 3:
            self._botserv_notice(addr, "Syntax: ADD <botnick> <#chan> <password>")
            return

        botnick, chan_name, password = args[0], args[1], args[2]

        if not chan_name.startswith("#"):
            self._botserv_notice(addr, f"Invalid channel name '{chan_name}'.")
            return

        # Check ChanServ registration and ownership
        chanserv_info = self.server.chanserv_get(chan_name)
        if not chanserv_info:
            self._botserv_notice(addr, f"Channel {chan_name} is not registered with ChanServ.")
            return

        if chanserv_info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
            self._botserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
            return

        # Validate botnick
        if not NICK_RE.match(botnick) or len(botnick) > 30:
            self._botserv_notice(addr, f"Invalid bot nickname '{botnick}'.")
            return

        # Check if nick in use
        for a, info in list(self.server.clients.items()):
            if info.get("name", "").lower() == botnick.lower():
                self._botserv_notice(addr, f"Nickname {botnick} is already in use.")
                return

        if self.server.botserv_register(chan_name, botnick, nick, password):
            self._botserv_notice(addr, f"Bot {botnick} is now registered for {chan_name}.")
            self.server.log(f"[BOTSERV] {nick} registered bot {botnick} for {chan_name}")
        else:
            self._botserv_notice(addr, f"Bot {botnick} is already registered for {chan_name}.")

    def _botserv_del(self, args, addr):
        """DEL <botnick> <#chan>"""
        nick = self._get_nick(addr)
        if len(args) < 2:
            self._botserv_notice(addr, "Syntax: DEL <botnick> <#chan>")
            return

        botnick, chan_name = args[0], args[1]
        
        # Check ChanServ ownership
        chanserv_info = self.server.chanserv_get(chan_name)
        if not chanserv_info:
            self._botserv_notice(addr, f"Channel {chan_name} is not registered.")
            return

        if chanserv_info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
            self._botserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
            return

        if self.server.botserv_drop(chan_name, botnick):
            self._botserv_notice(addr, f"Bot {botnick} has been unregistered from {chan_name}.")
            self.server.log(f"[BOTSERV] {nick} deleted bot {botnick} for {chan_name}")
        else:
            self._botserv_notice(addr, f"Bot {botnick} is not registered for {chan_name}.")

    def _botserv_list(self, args, addr):
        """LIST [#chan]"""
        data = self.server.load_botserv()
        bots = data.get("bots", {})
        if not bots:
            self._botserv_notice(addr, "No bots registered.")
            return

        chan_filter = args[0] if args else None
        
        self._botserv_notice(addr, "Registered bots:")
        for key, info in bots.items():
            if chan_filter and info["channel"].lower() != chan_filter.lower():
                continue
            self._botserv_notice(addr, f"  {info['botnick']} on {info['channel']} (Owner: {info['owner']})")

    def _botserv_notice(self, addr, text):
        """Send a NOTICE from BotServ to a client."""
        nick = self._get_nick(addr) or "*"
        notice = f":BotServ!BotServ@{SERVER_NAME} NOTICE {nick} :{text}\r\n"
        self.server.sock_send(notice.encode(), addr)

    def _chanserv_notice(self, addr, text):
        """Send a NOTICE from ChanServ to a client."""
        nick = self._get_nick(addr) or "*"
        notice = f":ChanServ!ChanServ@{SERVER_NAME} NOTICE {nick} :{text}\r\n"
        self.server.sock_send(notice.encode(), addr)

    def _nickserv_notice(self, addr, text):
        """Send a NOTICE from NickServ to a client."""
        nick = self._get_nick(addr) or "*"
        notice = f":NickServ!NickServ@{SERVER_NAME} NOTICE {nick} :{text}\r\n"
        self.server.sock_send(notice.encode(), addr)

    def _nickserv_enforce(self, addr, nick):
        """Called by enforcement timer if client hasn't identified. Handles based on enforce_mode."""
        # Check if they identified in time
        if self.server.nickserv_identified.get(addr) == nick:
            return
        # Check if they're still connected with that nick
        current_nick = self._get_nick(addr)
        if current_nick != nick:
            return
        if addr not in self.server.clients:
            return

        settings = self.server.load_settings().get("nickserv", {})
        mode = settings.get("enforce_mode", "disconnect")

        if mode == "warn":
            self._nickserv_notice(addr, f"Reminder: You haven't identified for {nick}. Some features may be restricted.")
            self.server.log(f"[NICKSERV] Enforcement (WARN): {nick} still not identified")
        elif mode == "rename":
            import random
            guest_nick = f"Guest_{random.randint(10000, 99999)}"
            self._nickserv_notice(addr, f"You failed to identify for {nick}. Renaming you to {guest_nick}.")
            self.server.log(f"[NICKSERV] Enforcement (RENAME): {nick} -> {guest_nick}")
            # Execute NICK command internally
            from csc_service.shared.irc import IRCMessage
            nick_msg = IRCMessage(command="NICK", params=[guest_nick])
            self._handle_nick(nick_msg, addr)
        else: # disconnect
            self._nickserv_notice(addr, f"You failed to identify for {nick}. Disconnecting.")
            self._server_kill(nick, f"NickServ enforcement: failed to identify for {nick}")
            self.server.log(f"[NICKSERV] Enforcement (DISCONNECT): {nick} disconnected (failed to identify)")

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
        if nick.lower() in self.server.opers:
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
            self._server_kill(nick, reason)
        else:
            # Unregistered client quitting — just clean up
            self.server.clients.pop(addr, None)
            self.registration_state.pop(addr, None)

    def _handle_cap(self, msg, addr):
        """CAP — capability negotiation (IRCv3). Respond with empty list."""
        if not msg.params:
            return

        subcommand = msg.params[0].upper()

        if subcommand == "LS":
            response = f":{SERVER_NAME} CAP * LS :\r\n"
            self.server.sock_send(response, addr)
        elif subcommand == "REQ":
            caps = msg.params[1] if len(msg.params) > 1 else ""
            response = f":{SERVER_NAME} CAP * NAK :{caps}\r\n"
            self.server.sock_send(response, addr)
        elif subcommand == "END":
            pass
        else:
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

            # Generate server-side keypair using client's p and g
            dh = DHExchange(p=p, g=g)
            
            # Compute shared key
            shared_key = dh.compute_shared_key(client_pub)
            
            # Send reply
            # CRYPTOINIT DHREPLY <pub_hex>
            # We send this as plaintext because the client doesn't have the key yet until it processes this reply.
            reply = dh.format_reply_message()
            self.server.sock_send(reply.encode("utf-8"), addr)

            # Store key for this address AFTER sending reply
            self.server.encryption_keys[addr] = shared_key
            self.server.log(f"[CRYPTO] Established encrypted session with {addr}")

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
        from csc_service.shared.irc import IRCMessage
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
        from csc_service.shared.irc import IRCMessage
        nick_msg = IRCMessage(command="NICK", params=[new_name])
        self._handle_nick(nick_msg, addr)

    # ======================================================================
    # ISOP and WALLOPS
    # ======================================================================

    def _handle_isop(self, msg, addr):
        """ISOP <nick> — returns whether nick is an IRC operator."""
        nick = self._get_nick(addr)
        target = msg.params[0] if msg.params else nick
        is_oper = target.lower() in self.server.opers
        reply = f":{SERVER_NAME} NOTICE {nick} :ISOP {target} {'YES' if is_oper else 'NO'}\r\n"
        self.server.sock_send(reply.encode(), addr)

    def _handle_wallops(self, msg, addr):
        """WALLOPS :<message> — oper only, broadcasts to all opers."""
        nick = self._get_nick(addr)
        if nick.lower() not in self.server.opers:
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
            if client_nick and client_nick.lower() in self.server.opers:
                self.server.sock_send(wallops_msg.encode(), a)
        self.server.log(f"[WALLOPS] {nick}: {text}")

    # ======================================================================
    # Service Command (Transparent on Chatline)
    # ======================================================================


    # ======================================================================
    # Helper Methods
    # ======================================================================

    # ======================================================================
    # Ban Mask Helpers
    # ======================================================================

    @staticmethod
    def _normalize_ban_mask(mask):
        """Normalize a ban mask to nick!user@host format.

        If only a nick is given, expand to nick!*@*.
        If nick!user is given without @host, append @*.
        """
        if "!" not in mask and "@" not in mask:
            return f"{mask}!*@*"
        if "!" not in mask:
            # user@host without nick
            return f"*!{mask}"
        if "@" not in mask:
            # nick!user without host
            return f"{mask}@*"
        return mask

    @staticmethod
    def _match_ban_mask(mask, nick_user_host):
        """Match a ban mask pattern against a nick!user@host string.

        Supports * (any chars) and ? (single char) wildcards.
        Nick portion is matched case-insensitively.

        Args:
            mask: Ban mask pattern like *!*@*.example.com
            nick_user_host: Actual user string like user!user@foo.example.com
        Returns:
            True if the mask matches.
        """
        import fnmatch

        # Split both into nick and user@host parts
        if "!" in mask:
            mask_nick, mask_rest = mask.split("!", 1)
        else:
            mask_nick, mask_rest = "*", mask

        if "!" in nick_user_host:
            actual_nick, actual_rest = nick_user_host.split("!", 1)
        else:
            actual_nick, actual_rest = nick_user_host, "*@*"

        # Nick matching is case-insensitive
        if not fnmatch.fnmatch(actual_nick.lower(), mask_nick.lower()):
            return False

        # user@host matching is case-sensitive for user, case-insensitive for host
        if "@" in mask_rest and "@" in actual_rest:
            mask_user, mask_host = mask_rest.split("@", 1)
            actual_user, actual_host = actual_rest.split("@", 1)
            if not fnmatch.fnmatch(actual_user, mask_user):
                return False
            if not fnmatch.fnmatch(actual_host.lower(), mask_host.lower()):
                return False
            return True

        return fnmatch.fnmatch(actual_rest, mask_rest)

    def _is_banned(self, channel, nick, user, host):
        """Check if a nick!user@host matches any ban in the channel's ban list.

        Args:
            channel: Channel object
            nick: User's nickname
            user: User's username
            host: User's hostname
        Returns:
            True if the user matches any ban mask.
        """
        if not channel.ban_list:
            return False
        nick_user_host = f"{nick}!{user}@{host}"
        for mask in channel.ban_list:
            if self._match_ban_mask(mask, nick_user_host):
                return True
        return False

    def _send_ban_list(self, addr, nick, chan_name, channel):
        """Send RPL_BANLIST (367) entries followed by RPL_ENDOFBANLIST (368)."""
        for ban_mask in sorted(channel.ban_list):
            reply = f":{SERVER_NAME} {RPL_BANLIST} {nick} {chan_name} {ban_mask}\r\n"
            self.server.sock_send(reply.encode(), addr)
        end = f":{SERVER_NAME} {RPL_ENDOFBANLIST} {nick} {chan_name} :End of channel ban list\r\n"
        self.server.sock_send(end.encode(), addr)

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
                self.server.clients[addr] = {"name": name, "last_seen": time.time(), "user_modes": set()}
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

    def _find_client_addr(self, nick):
        """Find the address for a client by nick."""
        # Check registration state
        for addr, reg in list(self.registration_state.items()):
            if reg.get("nick") == nick:
                return addr
        # Check server.clients
        for addr, record in list(self.server.clients.items()):
            if record.get("name") == nick:
                return addr
        return None

    def _send_numeric(self, addr, numeric, target_nick, text):
        """Send a numeric reply to an address."""
        line = f":{SERVER_NAME} {numeric} {target_nick} :{text}\r\n"
        self.server.sock_send(line.encode(), addr)

    def _send_names(self, addr, nick, channel):
        """Send RPL_NAMREPLY + RPL_ENDOFNAMES for a channel."""
        # Check if querier is a member or oper
        is_member = channel.has_member(nick)
        is_oper = nick.lower() in self.server.opers

        # Build names list, filtering invisible users
        names_list = []
        for member_nick_lower, info in list(channel.members.items()):
            # Skip None or empty nicks
            display_nick = info.get("nick")
            if not display_nick:
                continue

            # Check if member is invisible
            member_addr = self._find_client_addr(display_nick)
            if member_addr:
                member_modes = self.server.clients.get(member_addr, {}).get("user_modes", set())
                # Skip invisible users unless querier is in channel or is oper
                if "i" in member_modes and not is_member and not is_oper:
                    continue

            # Add member with appropriate prefix
            member_channel_modes = info.get("modes", set())
            if "o" in member_channel_modes:
                names_list.append(f"@{display_nick}")
            elif "v" in member_channel_modes:
                names_list.append(f"+{display_nick}")
            else:
                names_list.append(display_nick)

        names = " ".join(sorted(names_list))
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

    # ==================================================================
    # Oper Admin Commands
    # ==================================================================

    def _oper_notice(self, addr, text):
        """Send a NOTICE to the requesting oper."""
        nick = self._get_nick(addr)
        msg = f":{SERVER_NAME} NOTICE {nick} :{text}\r\n"
        self.server.sock_send(msg.encode(), addr)

    def _require_oper(self, addr):
        """Return nick if oper, else send ERR_NOPRIVILEGES and return None."""
        nick = self._get_nick(addr)
        if nick.lower() not in self.server.opers:
            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                               "Permission Denied- You're not an IRC operator")
            return None
        return nick

    def _require_admin(self, addr):
        """Return nick if server admin (a/A flag), else deny."""
        nick = self._require_oper(addr)
        if nick and not self.server.is_server_admin(nick):
            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                               "Permission Denied- Server admin flag required")
            return None
        return nick

    def _handle_setmotd(self, msg, addr):
        """SETMOTD :<text>  — set Message of the Day (requires server admin)."""
        nick = self._require_admin(addr)
        if not nick:
            return
        text = " ".join(msg.params).lstrip(":")
        if not text:
            self._oper_notice(addr, "Usage: SETMOTD :<message>")
            return
        self.server.put_data("motd", text)
        self._oper_notice(addr, f"MOTD updated.")
        prefix = f"{SERVER_NAME}!admin@{SERVER_NAME}"
        for channel in self.server.channel_manager.list_channels():
            notice = format_irc_message(prefix, "NOTICE", [channel.name],
                                        f"MOTD updated by {nick}") + "\r\n"
            self.server.broadcast_to_channel(channel.name, notice)
        self.server.send_wallops(f"MOTD updated by {nick}")

    def _handle_trust(self, msg, addr):
        """TRUST <subcommand> [args] — manage o-lines (oper credentials)."""
        nick = self._get_nick(addr)
        if not msg.params:
            self._trust_help(addr)
            return

        sub = msg.params[0].lower()
        args = msg.params[1:]

        if sub == "list":
            # Any oper can list
            if nick.lower() not in self.server.opers:
                self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                                   "Permission Denied- You're not an IRC operator")
                return
            self._trust_list(addr)
        elif sub in ("add", "del", "edit", "addhost", "delhost"):
            if not self._require_admin(addr):
                return
            if sub == "add":
                self._trust_add(addr, args)
            elif sub == "del":
                self._trust_del(addr, args)
            elif sub == "edit":
                self._trust_edit(addr, args)
            elif sub == "addhost":
                self._trust_addhost(addr, args)
            elif sub == "delhost":
                self._trust_delhost(addr, args)
        else:
            self._trust_help(addr)

    def _trust_help(self, addr):
        for line in [
            "TRUST subcommands:",
            "  TRUST list                          - List all o-lines (no passwords)",
            "  TRUST add <acct> <pass> <svrs> <masks> [flags]  - Add o-line",
            "  TRUST del <acct>                    - Remove all o-lines for account",
            "  TRUST edit <acct> <field> <value>   - Edit field: password/flags/servers",
            "  TRUST addhost <acct> <mask>          - Add host mask",
            "  TRUST delhost <acct> <mask>          - Remove host mask",
            "  Flags: o=local oper  O=global oper  a=server admin  A=net admin",
        ]:
            self._oper_notice(addr, line)

    def _trust_list(self, addr):
        data = self.server.load_opers()
        olines = data.get("olines", {})
        remote = data.get("remote_olines", {})
        active_nicks = {e.get("nick", "").lower() for e in data.get("active_opers", [])
                        if isinstance(e, dict)}
        self._oper_notice(addr, "--- O-Lines ---")
        for section, entries_dict, label in [
            (olines, olines, "local"),
            (remote, remote, "remote"),
        ]:
            for acct, entries in entries_dict.items():
                for entry in entries:
                    masks = ",".join(entry.get("host_masks", ["*!*@*"]))
                    servers = ",".join(entry.get("servers", ["*"]))
                    flags = entry.get("flags", "o")
                    comment = entry.get("comment", "")
                    active = " [ACTIVE]" if acct.lower() in active_nicks else ""
                    self._oper_notice(addr,
                        f"  [{label}] {acct}:{flags}:{servers}:{masks}{active}"
                        + (f" # {comment}" if comment else ""))
        self._oper_notice(addr, "--- End O-Lines ---")

    def _trust_add(self, addr, args):
        if len(args) < 4:
            self._oper_notice(addr, "Usage: TRUST add <account> <password> <servers> <masks> [flags]")
            return
        acct, password, servers_str, masks_str = args[0], args[1], args[2], args[3]
        flags = args[4] if len(args) > 4 else "ol"
        servers = [s.strip() for s in servers_str.split(",") if s.strip()]
        masks = [m.strip() for m in masks_str.split(",") if m.strip()]
        data = self.server.load_opers()
        olines = data.setdefault("olines", {})
        olines.setdefault(acct, []).append({
            "user": acct,
            "password": password,
            "servers": servers or ["*"],
            "host_masks": masks or ["*!*@*"],
            "flags": flags,
            "comment": "",
        })
        self.server.save_opers(data)
        self._write_olines_conf(data)
        self._oper_notice(addr, f"O-line added for account '{acct}' (flags: {flags})")
        nick = self._get_nick(addr)
        self.server.send_wallops(f"{nick} added o-line for '{acct}'")

    def _trust_del(self, addr, args):
        if not args:
            self._oper_notice(addr, "Usage: TRUST del <account>")
            return
        acct = args[0]
        data = self.server.load_opers()
        olines = data.get("olines", {})
        if acct not in olines:
            self._oper_notice(addr, f"No o-line found for '{acct}'")
            return
        del olines[acct]
        # Deoper anyone authenticated with this account
        updated_active = []
        for entry in data.get("active_opers", []):
            if isinstance(entry, dict) and entry.get("account") == acct:
                # Strip oper modes from connected client
                for a, info in self.server.clients.items():
                    if info.get("name", "").lower() == entry.get("nick", "").lower():
                        info.get("user_modes", set()).discard("o")
                        info.get("user_modes", set()).discard("O")
                        info.get("user_modes", set()).discard("a")
                        info.get("user_modes", set()).discard("A")
                        mode_msg = f":{SERVER_NAME} MODE {info['name']} -oOaA\r\n"
                        self.server.sock_send(mode_msg.encode(), a)
            else:
                updated_active.append(entry)
        data["active_opers"] = updated_active
        self.server.save_opers(data)
        self._write_olines_conf(data)
        self._oper_notice(addr, f"O-line removed for account '{acct}'")
        nick = self._get_nick(addr)
        self.server.send_wallops(f"{nick} removed o-line for '{acct}'")

    def _trust_edit(self, addr, args):
        if len(args) < 3:
            self._oper_notice(addr, "Usage: TRUST edit <account> <field> <value>")
            self._oper_notice(addr, "  Fields: password, flags, servers")
            return
        acct, field, value = args[0], args[1].lower(), " ".join(args[2:])
        data = self.server.load_opers()
        entries = data.get("olines", {}).get(acct)
        if not entries:
            self._oper_notice(addr, f"No o-line found for '{acct}'")
            return
        for entry in entries:
            if field == "password":
                entry["password"] = value
            elif field == "flags":
                entry["flags"] = value
            elif field == "servers":
                entry["servers"] = [s.strip() for s in value.split(",")]
            else:
                self._oper_notice(addr, f"Unknown field '{field}'. Use: password, flags, servers")
                return
        self.server.save_opers(data)
        self._write_olines_conf(data)
        self._oper_notice(addr, f"Updated '{field}' for account '{acct}'")

    def _trust_addhost(self, addr, args):
        if len(args) < 2:
            self._oper_notice(addr, "Usage: TRUST addhost <account> <nick!user@host>")
            return
        acct, mask = args[0], args[1]
        data = self.server.load_opers()
        entries = data.get("olines", {}).get(acct)
        if not entries:
            self._oper_notice(addr, f"No o-line found for '{acct}'")
            return
        entries[0].setdefault("host_masks", []).append(mask)
        self.server.save_opers(data)
        self._write_olines_conf(data)
        self._oper_notice(addr, f"Added host mask '{mask}' to '{acct}'")

    def _trust_delhost(self, addr, args):
        if len(args) < 2:
            self._oper_notice(addr, "Usage: TRUST delhost <account> <nick!user@host>")
            return
        acct, mask = args[0], args[1]
        data = self.server.load_opers()
        entries = data.get("olines", {}).get(acct)
        if not entries:
            self._oper_notice(addr, f"No o-line found for '{acct}'")
            return
        for entry in entries:
            masks = entry.get("host_masks", [])
            if mask in masks:
                masks.remove(mask)
        self.server.save_opers(data)
        self._write_olines_conf(data)
        self._oper_notice(addr, f"Removed host mask '{mask}' from '{acct}'")

    def _write_olines_conf(self, data):
        """Rewrite olines.conf from current opers.json data (export only)."""
        self.server.write_olines_conf(
            data.get("olines", {}), server_name=self.server.server_name)

    def _handle_stats(self, msg, addr):
        """STATS <letter> — server statistics (oper only)."""
        nick = self._require_oper(addr)
        if not nick:
            return
        letter = msg.params[0].lower() if msg.params else "u"
        RPL_STATSEND = "219"

        if letter == "u":
            import time as _time
            uptime_sec = int(_time.time() - getattr(self.server, "_start_time", _time.time()))
            h, rem = divmod(uptime_sec, 3600)
            m, s = divmod(rem, 60)
            clients = len([i for i in self.server.clients.values() if i.get("name")])
            self._oper_notice(addr, f"Uptime: {h}h {m}m {s}s  |  Connected clients: {clients}")
        elif letter == "o":
            self._trust_list(addr)
            return
        elif letter == "c":
            self._oper_notice(addr, "--- Active Clients ---")
            for a, info in self.server.clients.items():
                n = info.get("name")
                if not n:
                    continue
                channels = self.server.channel_manager.find_channels_for_nick(n)
                chans = ",".join(ch.name for ch in channels) or "(none)"
                flags = self.server.get_oper_flags(n)
                oper_tag = f" [OPER:{flags}]" if flags else ""
                self._oper_notice(addr, f"  {n}{oper_tag} @ {a[0]}:{a[1]}  chans: {chans}")
            self._oper_notice(addr, "--- End Clients ---")
        elif letter == "l":
            if hasattr(self.server, "s2s_network"):
                links = getattr(self.server.s2s_network, "connections", {})
                if links:
                    for sname, conn in links.items():
                        self._oper_notice(addr, f"  Link: {sname} @ {getattr(conn, 'host', '?')}")
                else:
                    self._oper_notice(addr, "No active S2S links.")
            else:
                self._oper_notice(addr, "S2S not active.")
        else:
            self._oper_notice(addr, f"Unknown STATS letter '{letter}'. Use: u c o l")

        end = f":{SERVER_NAME} {RPL_STATSEND} {nick} {letter} :End of /STATS report\r\n"
        self.server.sock_send(end.encode(), addr)

    def _handle_rehash(self, msg, addr):
        """REHASH — no longer supported. opers.json is the sole authority."""
        nick = self._require_admin(addr)
        if not nick:
            return
        self._oper_notice(addr, "REHASH is no longer supported. Edit opers.json directly.")

    def _handle_shutdown(self, msg, addr):
        """SHUTDOWN [reason] — graceful server shutdown (requires server admin)."""
        nick = self._require_admin(addr)
        if not nick:
            return
        reason = " ".join(msg.params) if msg.params else "Server shutting down"
        self.server.send_wallops(f"Server shutting down: {reason} (by {nick})")
        error_msg = f"ERROR :Closing Link: Server shutting down ({reason})\r\n"
        for a in list(self.server.clients.keys()):
            try:
                self.server.sock_send(error_msg.encode(), a)
            except Exception:
                pass
        self.server._running = False
        self.server.log(f"[SHUTDOWN] Initiated by {nick}: {reason}")

    def _handle_link(self, msg, addr):
        """LINK <server> [port] — initiate S2S link."""
        nick = self._require_oper(addr)
        if not nick:
            return
        if not msg.params:
            self._oper_notice(addr, "Usage: LINK <server> [port]")
            return
        server_name = msg.params[0]
        port = int(msg.params[1]) if len(msg.params) > 1 else 9525
        # Delegate to CONNECT handler (already implemented)
        from csc_service.shared.irc import parse_irc_message as _pim
        fake_msg = type("M", (), {"params": [server_name, str(port)]})()
        self._handle_connect(fake_msg, addr)

    def _handle_relink(self, msg, addr):
        """RELINK <server> — reconnect a dropped S2S link."""
        nick = self._require_oper(addr)
        if not nick:
            return
        if not msg.params:
            self._oper_notice(addr, "Usage: RELINK <server>")
            return
        server_name = msg.params[0]
        if hasattr(self.server, "s2s_network"):
            self._oper_notice(addr, f"Attempting to relink {server_name}...")
            try:
                self.server.s2s_network.reconnect(server_name)
                self._oper_notice(addr, f"Relink initiated for {server_name}")
            except Exception as e:
                self._oper_notice(addr, f"Relink failed: {e}")
        else:
            self._oper_notice(addr, "S2S not active.")

    def _handle_delink(self, msg, addr):
        """DELINK <server> [reason] — drop S2S link (alias for SQUIT)."""
        nick = self._require_oper(addr)
        if not nick:
            return
        self._handle_squit_cmd(msg, addr)

    # ==================================================================
    # LOCALCONFIG — server config via IRC (uses Data() get/put_data)
    # ==================================================================

    _CFG_DEFAULTS = {
        "cfg.host":                     "0.0.0.0",
        "cfg.port":                     9525,
        "cfg.timeout":                  120,
        "cfg.max_history":              100,
        "cfg.protect_local_opers":      True,
        "cfg.motd":                     "Welcome to csc-server!",
        "cfg.s2s_cert":                 "/etc/csc/csc-fahu.chain.pem",
        "cfg.s2s_key":                  "/etc/csc/csc-fahu.key",
        "cfg.s2s_ca":                   "/etc/openvpn/easy-rsa/pki/ca.crt",
        "cfg.s2s_crl":                  "/etc/openvpn/easy-rsa/pki/crl.pem",
        "cfg.nickserv_enforce_timeout": 60,
        "cfg.nickserv_enforce_mode":    "disconnect",
    }
    _CFG_RESTART  = {"cfg.host", "cfg.port"}
    _CFG_RELINK   = {"cfg.s2s_cert", "cfg.s2s_key", "cfg.s2s_ca", "cfg.s2s_crl"}

    def _handle_help(self, msg, addr):
        """HELP — show available commands based on caller's oper flags."""
        nick = self._get_nick(addr)
        flags = self.server.get_oper_flags(nick) if nick else ""
        is_oper  = bool(flags)
        is_admin = "a" in flags or "A" in flags
        is_netadmin = "A" in flags

        def ht(text):
            self._send_numeric(addr, "705", nick, text)

        self._send_numeric(addr, "704", nick, "CSC Server Help")

        ht("=== User Commands ===")
        ht("NICK <nick>                     Change your nickname")
        ht("USER <user> 0 * :<realname>     Set username/realname (on connect)")
        ht("JOIN <#channel>                 Join a channel")
        ht("PART <#channel> [reason]        Leave a channel")
        ht("PRIVMSG <target> :<msg>         Send a message to nick or channel")
        ht("NOTICE <target> :<msg>          Send a notice")
        ht("QUIT [reason]                   Disconnect from server")
        ht("WHOIS <nick>                    Show info about a user")
        ht("WHO <#channel|nick>             List users in channel or matching nick")
        ht("LIST                            List all channels")
        ht("TOPIC <#channel> [:<topic>]     Get or set channel topic")
        ht("MODE <target> [modes]           Get or set user/channel modes")
        ht("AWAY [:<message>]               Set or clear away message")
        ht("PING <server>                   Ping the server")
        ht("MOTD                            Show message of the day")
        ht("NAMES <#channel>                List nicks in channel")
        ht("WHOWAS <nick>                   Show last known info for a nick")
        ht("KILL <nick> :<reason>           (Oper) Disconnect a user")
        ht("")
        ht("=== NickServ ===")
        ht("/msg NickServ REGISTER <pass>   Register your nick")
        ht("/msg NickServ IDENTIFY <pass>   Identify with your registered nick")
        ht("/msg NickServ GHOST <nick> <p>  Kill a ghost using your nick")
        ht("/msg NickServ INFO <nick>       Show nick registration info")
        ht("/msg NickServ DROP <pass>       Unregister your nick")

        if is_oper:
            ht("")
            ht("=== Oper Commands (flags: {}) ===".format(flags))
            ht("KILL <nick> :<reason>           Disconnect a user from the server")
            ht("WALLOPS :<message>              Send message to all opers")
            ht("STATS u                         Uptime and connection count")
            ht("STATS o                         Show all o-lines (no passwords)")
            ht("STATS c                         Active clients and IPs")
            ht("STATS l                         Server-to-server links")
            ht("TRUST list                      List all oper accounts")

        if is_admin:
            ht("")
            ht("=== Admin Commands (flags: {}) ===".format(flags))
            ht("SETMOTD :<message>              Set the message of the day")
            ht("REHASH                          Reload olines.conf from disk")
            ht("SHUTDOWN [reason]               Gracefully shut down the server")
            ht("TRUST add <acct> <pass> <svrs> <masks> [flags]")
            ht("                                Add a new oper account")
            ht("TRUST del <account>             Remove an oper account")
            ht("TRUST edit <acct> <field> <val> Edit account field (password/flags/servers)")
            ht("TRUST addhost <acct> <mask>     Add a hostmask to an account")
            ht("TRUST delhost <acct> <mask>     Remove a hostmask from an account")
            ht("LOCALCONFIG show                Show all server config settings")
            ht("LOCALCONFIG get <key>           Get one config value")
            ht("LOCALCONFIG set <key> <val>     Set a config value")
            ht("LOCALCONFIG del <key>           Delete a config value (revert to default)")

        if is_netadmin:
            ht("")
            ht("=== Network Admin Commands (flags: {}) ===".format(flags))
            ht("LINK <server> [port]            Initiate a server-to-server link")
            ht("RELINK <server>                 Reconnect a dropped server link")
            ht("DELINK <server> [reason]        Drop a server link (alias: SQUIT)")

        self._send_numeric(addr, "706", nick, "End of HELP")

    def _handle_localconfig(self, msg, addr):
        """LOCALCONFIG <show|list|get|set|del> [key] [value]"""
        nick = self._get_nick(addr)
        sub = msg.params[0].lower() if msg.params else "show"
        args = msg.params[1:]

        if sub in ("show", "list"):
            if nick.lower() not in self.server.opers:
                self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                                   "Permission Denied- You're not an IRC operator")
                return
            self._oper_notice(addr, "--- Server Config (cfg.*) ---")
            for key, default in sorted(self._CFG_DEFAULTS.items()):
                val = self.server.get_data(key)
                display = val if val is not None else f"{default} (default)"
                tag = " [RESTART]" if key in self._CFG_RESTART else (
                      " [RELINK]"  if key in self._CFG_RELINK  else "")
                self._oper_notice(addr, f"  {key} = {display}{tag}")
            self._oper_notice(addr, "--- End Config ---")

        elif sub == "get":
            if nick.lower() not in self.server.opers:
                self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                                   "Permission Denied- You're not an IRC operator")
                return
            if not args:
                self._oper_notice(addr, "Usage: LOCALCONFIG get <key>")
                return
            key = args[0] if args[0].startswith("cfg.") else f"cfg.{args[0]}"
            val = self.server.get_data(key)
            default = self._CFG_DEFAULTS.get(key, "(no default)")
            display = val if val is not None else f"{default} (default)"
            self._oper_notice(addr, f"{key} = {display}")

        elif sub == "set":
            if not self._require_admin(addr):
                return
            if len(args) < 2:
                self._oper_notice(addr, "Usage: LOCALCONFIG set <key> <value>")
                return
            key = args[0] if args[0].startswith("cfg.") else f"cfg.{args[0]}"
            value = " ".join(args[1:])
            # Type coerce based on default type
            default = self._CFG_DEFAULTS.get(key)
            if isinstance(default, bool):
                value = value.lower() in ("true", "1", "yes", "on")
            elif isinstance(default, int):
                try:
                    value = int(value)
                except ValueError:
                    self._oper_notice(addr, f"Invalid integer value for {key}")
                    return
            self.server.put_data(key, value)
            tag = " — NOTE: requires restart" if key in self._CFG_RESTART else (
                  " — NOTE: requires relink" if key in self._CFG_RELINK else "")
            self._oper_notice(addr, f"Set {key} = {value}{tag}")
            self.server.send_wallops(f"{nick} set config {key} = {value}")

        elif sub == "del":
            if not self._require_admin(addr):
                return
            if not args:
                self._oper_notice(addr, "Usage: LOCALCONFIG del <key>")
                return
            key = args[0] if args[0].startswith("cfg.") else f"cfg.{args[0]}"
            self.server.put_data(key, None)
            default = self._CFG_DEFAULTS.get(key, "(none)")
            self._oper_notice(addr, f"Deleted {key} — will use default: {default}")
            self.server.send_wallops(f"{nick} deleted config {key}")

        else:
            self._oper_notice(addr, "Usage: LOCALCONFIG <show|list|get|set|del> [key] [value]")
