# Logging policy: Use ASCII-only characters in log messages

"""BotServ handlers: ADD, DEL, LIST, SETLOG."""

import re
from csc_service.shared.irc import SERVER_NAME

# Valid IRC nick: letter or special first char, then letters/digits/specials
NICK_RE = re.compile(r'^[A-Za-z\[\]\\`_^{|}][A-Za-z0-9\[\]\\`_^{|}\-]*$')


class BotServMixin:
    """Handles BotServ commands."""

    def _handle_botserv(self, msg, addr):
        """Handle PRIVMSG BotServ :COMMAND args -- virtual BotServ service."""
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

        chanserv_info = self.server.chanserv_get(chan_name)
        if not chanserv_info:
            self._botserv_notice(addr, f"Channel {chan_name} is not registered.")
            return

        if chanserv_info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
            self._botserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
            return

        bot_info = self.server.botserv_get(chan_name, botnick)
        if not bot_info:
            self._botserv_notice(addr, f"Bot {botnick} is not registered for {chan_name}.")
            return

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

        chanserv_info = self.server.chanserv_get(chan_name)
        if not chanserv_info:
            self._botserv_notice(addr, f"Channel {chan_name} is not registered with ChanServ.")
            return

        if chanserv_info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
            self._botserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
            return

        if not NICK_RE.match(botnick) or len(botnick) > 30:
            self._botserv_notice(addr, f"Invalid bot nickname '{botnick}'.")
            return

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
