# Logging policy: Use ASCII-only characters in log messages

"""NickServ handlers: REGISTER, IDENTIFY, GHOST, INFO, DROP, enforcement."""

import threading
from csc_service.shared.irc import SERVER_NAME


class NickServMixin:
    """Handles NickServ commands and nick enforcement."""

    def _handle_nickserv(self, msg, addr):
        """Handle PRIVMSG NickServ :COMMAND args -- virtual NickServ service."""
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
        """REGISTER <password> -- register your current nick with NickServ."""
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

        existing = self.server.nickserv_get(nick)
        if existing:
            self._nickserv_notice(addr, f"Nick {nick} is already registered.")
            return

        reg_info = self.registration_state.get(addr, {})
        registered_by = f"{reg_info.get('user', nick)}@{SERVER_NAME}"

        if self.server.nickserv_register(nick, password, registered_by):
            self.server.nickserv_identified[addr] = nick
            self._nickserv_notice(addr, f"Nick {nick} has been registered. You are now identified.")
            self.server.log(f"[NICKSERV] {nick} registered their nick")
        else:
            self._nickserv_notice(addr, "Registration failed. Nick may already be registered.")

    def _nickserv_identify(self, args, addr):
        """IDENTIFY <password> -- identify as the owner of your current nick."""
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

            timer_key = f"_nickserv_enforce_{addr}"
            timer = getattr(self, timer_key, None)
            if timer:
                timer.cancel()
                delattr(self, timer_key)
        else:
            self._nickserv_notice(addr, "Invalid password.")
            self.server.log(f"[NICKSERV] Failed IDENTIFY for {nick} from {addr}")

    def _nickserv_ghost(self, args, addr):
        """GHOST <nickname> <password> -- kill a ghost session to reclaim a nick."""
        if len(args) < 2:
            self._nickserv_notice(addr, "Syntax: GHOST <nickname> <password>")
            return

        target_nick = args[0]
        password = args[1]

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
        """INFO <nickname> -- show registration info for a nick."""
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
        """DROP <password> -- unregister your current nick."""
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

    def _nickserv_enforce(self, addr, nick):
        """Called by enforcement timer if client hasn't identified."""
        if self.server.nickserv_identified.get(addr) == nick:
            return
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
            from csc_service.shared.irc import IRCMessage
            nick_msg = IRCMessage(command="NICK", params=[guest_nick])
            self._handle_nick(nick_msg, addr)
        else: # disconnect
            self._nickserv_notice(addr, f"You failed to identify for {nick}. Disconnecting.")
            self._server_kill(nick, f"NickServ enforcement: failed to identify for {nick}")
            self.server.log(f"[NICKSERV] Enforcement (DISCONNECT): {nick} disconnected (failed to identify)")
