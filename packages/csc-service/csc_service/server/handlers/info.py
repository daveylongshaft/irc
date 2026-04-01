# Logging policy: Use ASCII-only characters in log messages

"""Info/query handlers: WHO, WHOIS, WHOWAS, MOTD, HELP, LOCALCONFIG, ISOP."""

import time
from csc_service.shared.irc import (
    format_irc_message, SERVER_NAME,
    RPL_WHOISUSER, RPL_WHOISSERVER, RPL_WHOISOPERATOR, RPL_ENDOFWHOIS,
    RPL_WHOWASUSER, RPL_ENDOFWHOWAS, ERR_WASNOSUCHNICK,
    RPL_MOTDSTART, RPL_MOTD, RPL_ENDOFMOTD,
    RPL_AWAY, RPL_WHOISCHANNELS,
    ERR_NOSUCHNICK, ERR_NONICKNAMEGIVEN, ERR_NOSUCHCHANNEL,
    ERR_UNKNOWNERROR, ERR_NOPRIVILEGES,
)


class InfoMixin:
    """Handles WHO, WHOIS, WHOWAS, MOTD, HELP, LOCALCONFIG, ISOP."""

    def _handle_who(self, msg, addr):
        """WHO <channel> -- basic WHO reply."""
        try:
            nick = self._get_nick(addr)
            if not msg.params:
                return
            chan_name = msg.params[0]
            channel = self.server.channel_manager.get_channel(chan_name)
            if channel:
                if "p" in channel.modes and not channel.has_member(nick):
                    self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                                       f"{chan_name} :No such channel")
                    return

                is_oper = nick.lower() in self.server.opers
                is_member = channel.has_member(nick)

                for member_nick in channel.members:
                    member_addr = self._find_client_addr(member_nick)
                    if member_addr:
                        member_modes = self.server.clients.get(member_addr, {}).get("user_modes", set())
                        if "i" in member_modes and not is_member and not is_oper:
                            continue

                    line = f":{SERVER_NAME} 352 {nick} {chan_name} {member_nick} {SERVER_NAME} {SERVER_NAME} {member_nick} H :0 {member_nick}\r\n"
                    self.server.sock_send(line.encode(), addr)
            end = f":{SERVER_NAME} 315 {nick} {chan_name} :End of /WHO list\r\n"
            self.server.sock_send(end.encode(), addr)
        except Exception as e:
            self.server.log(f"[ERROR] WHO handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during WHO")

    def _handle_whois(self, msg, addr):
        """WHOIS <nick> -- return information about a user per RFC 2812."""
        try:
            nick = self._get_nick(addr)
            if not msg.params:
                self._send_numeric(addr, ERR_NONICKNAMEGIVEN, nick, "No nickname given")
                return

            target_nick = msg.params[-1]

            target_addr = None
            actual_target_nick = None

            for a, info in list(self.server.clients.items()):
                client_nick = info.get("name", "")
                if client_nick.lower() == target_nick.lower():
                    target_addr = a
                    actual_target_nick = client_nick
                    break

            if not target_addr:
                if hasattr(self.server, 's2s_network') and self.server.s2s_network:
                    link, remote_info = self.server.s2s_network.get_user_from_network(target_nick)
                    if link and remote_info and link.is_connected():
                        whoisuser = f":{SERVER_NAME} {RPL_WHOISUSER} {nick} {remote_info['nick']} {remote_info['nick']} {remote_info['server_id']} * :{remote_info['nick']}\r\n"
                        self.server.sock_send(whoisuser.encode(), addr)
                        whoisserver = f":{SERVER_NAME} {RPL_WHOISSERVER} {nick} {remote_info['nick']} {remote_info['server_id']} :Federated CSC Server\r\n"
                        self.server.sock_send(whoisserver.encode(), addr)
                        endwhois = f":{SERVER_NAME} {RPL_ENDOFWHOIS} {nick} {remote_info['nick']} :End of WHOIS list\r\n"
                        self.server.sock_send(endwhois.encode(), addr)
                        return

                self._send_numeric(addr, ERR_NOSUCHNICK, nick,
                                   f"{target_nick} :No such nick/channel")
                return

            target_reg = self.registration_state.get(target_addr, {})
            target_user = target_reg.get("user", target_nick)
            target_realname = target_reg.get("realname", target_nick)

            whoisuser = f":{SERVER_NAME} {RPL_WHOISUSER} {nick} {target_nick} {target_user} {SERVER_NAME} * :{target_realname}\r\n"
            self.server.sock_send(whoisuser.encode(), addr)

            whoisserver = f":{SERVER_NAME} {RPL_WHOISSERVER} {nick} {target_nick} {SERVER_NAME} :CSC IRC Server\r\n"
            self.server.sock_send(whoisserver.encode(), addr)

            target_client = self.server.clients.get(target_addr, {})
            away_message = target_client.get("away_message")
            if away_message:
                away_reply = f":{SERVER_NAME} {RPL_AWAY} {nick} {target_nick} :{away_message}\r\n"
                self.server.sock_send(away_reply.encode(), addr)

            if actual_target_nick and actual_target_nick.lower() in self.server.opers:
                whoisoper = f":{SERVER_NAME} {RPL_WHOISOPERATOR} {nick} {target_nick} :is an IRC operator\r\n"
                self.server.sock_send(whoisoper.encode(), addr)

            target_channels = self.server.channel_manager.find_channels_for_nick(actual_target_nick)
            visible_channels = []
            for channel in target_channels:
                if ("s" in channel.modes or "p" in channel.modes) and not channel.has_member(nick):
                    continue
                visible_channels.append(channel.name)
            if visible_channels:
                channels_str = " ".join(visible_channels)
                whoischannels = f":{SERVER_NAME} {RPL_WHOISCHANNELS} {nick} {target_nick} :{channels_str}\r\n"
                self.server.sock_send(whoischannels.encode(), addr)

            endofwhois = f":{SERVER_NAME} {RPL_ENDOFWHOIS} {nick} {target_nick} :End of /WHOIS list\r\n"
            self.server.sock_send(endofwhois.encode(), addr)

            self.server.log(f"[WHOIS] {nick} queried information for {target_nick}")
        except Exception as e:
            self.server.log(f"[ERROR] WHOIS handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during WHOIS")

    def _handle_whowas(self, msg, addr):
        """WHOWAS <nick> -- return information about a disconnected user."""
        try:
            nick = self._get_nick(addr)
            if not msg.params:
                self._send_numeric(addr, ERR_NONICKNAMEGIVEN, nick, "No nickname given")
                return

            target_nick = msg.params[-1]

            if target_nick in self.server.disconnected_clients:
                disc_info = self.server.disconnected_clients[target_nick]
                target_user = disc_info.get("user", target_nick)
                target_realname = disc_info.get("realname", target_nick)
                target_host = disc_info.get("host", SERVER_NAME)
                quit_time = disc_info.get("quit_time", "Unknown")
                quit_reason = disc_info.get("quit_reason", "")

                whowasuser = f":{SERVER_NAME} {RPL_WHOWASUSER} {nick} {target_nick} {target_user} {target_host} * :{target_realname}\r\n"
                self.server.sock_send(whowasuser.encode(), addr)

                quit_info = f":{SERVER_NAME} {RPL_WHOISSERVER} {nick} {target_nick} {SERVER_NAME} :Disconnected at {quit_time} ({quit_reason})\r\n"
                self.server.sock_send(quit_info.encode(), addr)

                endofwhowas = f":{SERVER_NAME} {RPL_ENDOFWHOWAS} {nick} {target_nick} :End of WHOWAS\r\n"
                self.server.sock_send(endofwhowas.encode(), addr)

                self.server.log(f"[WHOWAS] {nick} queried information for disconnected user {target_nick}")
            else:
                self._send_numeric(addr, ERR_WASNOSUCHNICK, nick,
                                   f"{target_nick} :There was no such nickname")
        except Exception as e:
            self.server.log(f"[ERROR] WHOWAS handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during WHOWAS")

    def _handle_motd(self, msg, addr):
        """MOTD -- send the message of the day."""
        nick = self._get_nick(addr)
        self._send_motd(addr, nick)

    def _send_motd(self, addr, nick):
        """Send MOTD as 375/372/376 numerics."""
        motd = self.server.get_data("motd") or "Welcome to csc-server!"
        self._send_numeric(addr, RPL_MOTDSTART, nick, f"- {SERVER_NAME} Message of the Day -")
        for line in motd.split("\n"):
            self._send_numeric(addr, RPL_MOTD, nick, f"- {line}")
        self._send_numeric(addr, RPL_ENDOFMOTD, nick, "End of /MOTD command")

    def _handle_isop(self, msg, addr):
        """ISOP <nick> -- returns whether nick is an IRC operator."""
        nick = self._get_nick(addr)
        target = msg.params[0] if msg.params else nick
        is_oper = target.lower() in self.server.opers
        reply = f":{SERVER_NAME} NOTICE {nick} :ISOP {target} {'YES' if is_oper else 'NO'}\r\n"
        self.server.sock_send(reply.encode(), addr)

    # ==================================================================
    # HELP
    # ==================================================================

    def _handle_help(self, msg, addr):
        """HELP -- show available commands based on caller's oper flags."""
        nick = self._get_nick(addr)
        flags = self.server.get_oper_flags(nick) if nick else ""
        is_oper = bool(flags)
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

    # ==================================================================
    # LOCALCONFIG (active version)
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
    _CFG_RESTART = {"cfg.host", "cfg.port"}
    _CFG_RELINK  = {"cfg.s2s_cert", "cfg.s2s_key", "cfg.s2s_ca", "cfg.s2s_crl"}

    def _handle_localconfig(self, msg, addr):
        """LOCALCONFIG <show|list|get|set|del> [key] [value]"""
        try:
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
                tag = " -- NOTE: requires restart" if key in self._CFG_RESTART else (
                      " -- NOTE: requires relink" if key in self._CFG_RELINK else "")
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
                self._oper_notice(addr, f"Deleted {key} -- will use default: {default}")
                self.server.send_wallops(f"{nick} deleted config {key}")

            else:
                self._oper_notice(addr, "Usage: LOCALCONFIG <show|list|get|set|del> [key] [value]")
        except Exception as e:
            self.server.log(f"[ERROR] LOCALCONFIG handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during LOCALCONFIG")
