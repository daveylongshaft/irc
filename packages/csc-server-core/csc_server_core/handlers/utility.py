# Logging policy: Use ASCII-only characters in log messages

"""Utility handlers and helpers: PING, PONG, QUIT, CAP, CRYPTOINIT, legacy compat,
nick/user lookup, numeric sending, authorization checks."""

import time
from csc_server_core.irc import (
    format_irc_message, SERVER_NAME,
    RPL_NAMREPLY, RPL_ENDOFNAMES,
    ERR_NOPRIVILEGES, ERR_UNKNOWNERROR,
)
from csc_server_core.crypto import DHExchange


class UtilityMixin:
    """Utility methods, PING/PONG/QUIT/CAP/CRYPTOINIT, legacy compat, helpers."""

    # ==================================================================
    # Core Helpers
    # ==================================================================

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
        for addr, reg in list(self.registration_state.items()):
            if reg.get("nick") == nick:
                return addr
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
        is_member = channel.has_member(nick)
        is_oper = nick.lower() in self.server.opers

        names_list = []
        for member_nick_lower, info in list(channel.members.items()):
            display_nick = info.get("nick")
            if not display_nick:
                continue

            member_addr = self._find_client_addr(display_nick)
            if member_addr:
                member_modes = self.server.clients.get(member_addr, {}).get("user_modes", set())
                if "i" in member_modes and not is_member and not is_oper:
                    continue

            member_channel_modes = info.get("modes", set())
            if "o" in member_channel_modes:
                names_list.append(f"@{display_nick}")
            elif "v" in member_channel_modes:
                names_list.append(f"+{display_nick}")
            else:
                names_list.append(display_nick)

        # Include remote S2S users who are in this channel
        if hasattr(self.server, 's2s_network'):
            chan_lower = channel.name.lower()
            with self.server.s2s_network._lock:
                for link in self.server.s2s_network._links.values():
                    with link._state_lock:
                        for ru in link.remote_users.values():
                            ru_chans = [c.lower() for c in ru.get("channels", [])]
                            if chan_lower in ru_chans:
                                names_list.append(ru["nick"])

        names = " ".join(sorted(names_list))
        reply = f":{SERVER_NAME} {RPL_NAMREPLY} {nick} = {channel.name} :{names}\r\n"
        self.server.sock_send(reply.encode(), addr)
        end = f":{SERVER_NAME} {RPL_ENDOFNAMES} {nick} {channel.name} :End of /NAMES list\r\n"
        self.server.sock_send(end.encode(), addr)

    def _send_notice(self, addr, text):
        """Helper to send a NOTICE message to a client."""
        nick = self._get_nick(addr) or "*"
        notice = format_irc_message(f":{SERVER_NAME}", "NOTICE", [nick], text) + "\r\n"
        self.server.sock_send(notice.encode(), addr)

    def _is_authorized(self, nick, channel_name=None):
        """Check if a nick is authorized (IRC operator or channel operator)."""
        if not nick:
            return False

        if nick.lower() in self.server.opers:
            return True

        if channel_name:
            channel = self.server.channel_manager.get_channel(channel_name)
            if channel and channel.is_op(nick):
                return True
        else:
            for ch in self.server.channel_manager.find_channels_for_nick(nick):
                if ch.is_op(nick):
                    return True

        return False

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

    # Legacy compatibility for handle_service_command
    def handle_service_command(self, line, addr, client_name):
        """Legacy entry point for service commands."""
        self._handle_service_via_chatline(line, addr, client_name)

    # ==================================================================
    # PING, PONG, QUIT
    # ==================================================================

    def _handle_ping(self, msg, addr):
        """PING :<token> -> PONG :<token>"""
        token = msg.params[0] if msg.params else SERVER_NAME
        pong = f":{SERVER_NAME} PONG {SERVER_NAME} :{token}\r\n"
        self.server.sock_send(pong.encode(), addr)

    def _handle_pong(self, msg, addr):
        """PONG -- just update last_seen."""
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
            self.server.clients.pop(addr, None)
            self.registration_state.pop(addr, None)

    # ==================================================================
    # CAP, CRYPTOINIT
    # ==================================================================

    def _handle_cap(self, msg, addr):
        """CAP -- capability negotiation (IRCv3). Respond with empty list."""
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
        if len(msg.params) < 4 or msg.params[0] != "DH":
            return

        try:
            p = int(msg.params[1], 16)
            g = int(msg.params[2], 16)
            client_pub = int(msg.params[3], 16)

            dh = DHExchange(p=p, g=g)

            shared_key = dh.compute_shared_key(client_pub)

            reply = dh.format_reply_message()
            self.server.sock_send(reply.encode("utf-8"), addr)

            self.server.encryption_keys[addr] = shared_key
            self.server.log(f"[CRYPTO] Established encrypted session with {addr}")

        except Exception as e:
            self.server.log(f"[CRYPTO] Handshake error with {addr}: {e}")

    # ==================================================================
    # Legacy Compatibility
    # ==================================================================

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

        from csc_server_core.irc import IRCMessage
        nick_msg = IRCMessage(command="NICK", params=[name])
        self._handle_nick(nick_msg, addr)

        user_msg = IRCMessage(command="USER", params=[name, "0", "*", name])
        self._handle_user(user_msg, addr)

    def _handle_legacy_rename(self, msg, addr, raw_line):
        """Convert legacy RENAME <old> <new> to NICK change."""
        parts = raw_line.split(maxsplit=2)
        if len(parts) < 3:
            self.server.sock_send(b"[Server] Invalid RENAME command. Usage: RENAME <old> <new>\n", addr)
            return

        new_name = parts[2]
        from csc_server_core.irc import IRCMessage
        nick_msg = IRCMessage(command="NICK", params=[new_name])
        self._handle_nick(nick_msg, addr)
