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

import re
import time
import threading
from csc_server_core.irc import (
    parse_irc_message, format_irc_message, SERVER_NAME,
)
from csc_server_core.handlers import (
    RegistrationMixin,
    ChannelMixin,
    MessagingMixin,
    ModeMixin,
    OperMixin,
    InfoMixin,
    NickServMixin,
    ChanServMixin,
    BotServMixin,
    UtilityMixin,
    FTPMixin,
    VFSMixin,
)

# Valid IRC nick: letter or special first char, then letters/digits/specials
NICK_RE = re.compile(r'^[A-Za-z\[\]\\`_^{|}][A-Za-z0-9\[\]\\`_^{|}\-]*$')


class MessageHandler(
    RegistrationMixin,
    ChannelMixin,
    MessagingMixin,
    ModeMixin,
    OperMixin,
    InfoMixin,
    NickServMixin,
    ChanServMixin,
    BotServMixin,
    UtilityMixin,
    FTPMixin,
    VFSMixin,
):
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
        # Set of (addr, canonical_pm_key) tuples -- prevents duplicate replay.
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

        # NickServ interception -- allowed even before registration
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
            from csc_server_core.irc import ERR_NOTREGISTERED
            # Fallback: treat as plain text from unregistered client
            if not command or command not in (
                "JOIN", "PART", "PRIVMSG", "NOTICE", "TOPIC", "NAMES",
                "LIST", "WHO", "OPER", "KICK", "MODE", "MOTD", "KILL",
            ):
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
            "FTP":         self._handle_ftp,
            "VFS":         self._handle_vfs,
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
