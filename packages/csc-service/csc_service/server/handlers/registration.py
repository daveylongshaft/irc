# Logging policy: Use ASCII-only characters in log messages

"""Registration handlers: PASS, NICK, USER, and registration completion."""

import re
import time
import threading
from csc_service.shared.irc import (
    format_irc_message, SERVER_NAME,
    RPL_WELCOME, RPL_YOURHOST, RPL_CREATED, RPL_MYINFO,
    ERR_ALREADYREGISTRED, ERR_NEEDMOREPARAMS, ERR_NONICKNAMEGIVEN,
    ERR_ERRONEUSNICKNAME, ERR_NICKNAMEINUSE, ERR_UNKNOWNERROR,
)

# Valid IRC nick: letter or special first char, then letters/digits/specials
NICK_RE = re.compile(r'^[A-Za-z\[\]\\`_^{|}][A-Za-z0-9\[\]\\`_^{|}\-]*$')


class RegistrationMixin:
    """Handles PASS, NICK, USER commands and registration completion."""

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
                    _link, remote_info = self.server.s2s_network.get_user_from_network(new_nick)
                    if remote_info is not None:
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

        # S2S: Announce nick to network immediately (before welcome burst)
        # so other servers can detect collisions before the client gets a welcome
        if hasattr(self.server, 's2s_network'):
            host = f"{addr[0]}:{addr[1]}" if isinstance(addr, tuple) else str(addr)
            self.server.s2s_network.sync_user_join(nick, host, "+")

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
