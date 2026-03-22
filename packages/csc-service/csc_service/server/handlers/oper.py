# Logging policy: Use ASCII-only characters in log messages

"""Oper/admin handlers: OPER, AWAY, KICK, KILL, CONNECT, SQUIT, TRUST,
SETMOTD, STATS, REHASH, SHUTDOWN, LINK, RELINK, DELINK, WALLOPS, _server_kill."""

import time
import threading
from csc_service.shared.irc import (
    format_irc_message, SERVER_NAME,
    RPL_YOUREOPER, RPL_AWAY, RPL_UNAWAY, RPL_NOWAWAY,
    ERR_NOPRIVILEGES, ERR_NEEDMOREPARAMS, ERR_PASSWDMISMATCH,
    ERR_NOSUCHNICK, ERR_NOSUCHCHANNEL, ERR_CHANOPRIVSNEEDED,
    ERR_USERNOTINCHANNEL, ERR_UNKNOWNERROR,
)


class OperMixin:
    """Handles oper authentication, admin commands, and server kill logic."""

    def _handle_oper(self, msg, addr):
        """OPER <account> <password>"""
        try:
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
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] OPER handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, self._get_nick(addr) or "*", "OPER :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] OPER handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during OPER")

    def _handle_away(self, msg, addr):
        """AWAY [:<message>]"""
        try:
            nick = self._get_nick(addr)

            if addr not in self.server.clients:
                self.server.clients[addr] = {"name": nick, "last_seen": time.time(), "user_modes": set()}

            user_modes = self.server.clients[addr].setdefault("user_modes", set())

            if msg.params and msg.params[0]:
                away_message = msg.params[0]
                self.server.clients[addr]["away_message"] = away_message
                user_modes.add("a")
                self._send_numeric(addr, RPL_NOWAWAY, nick, "You have been marked as being away")
                self.server.log(f"[AWAY] {nick} set away: {away_message}")
            else:
                if "away_message" in self.server.clients[addr]:
                    del self.server.clients[addr]["away_message"]
                user_modes.discard("a")
                self._send_numeric(addr, RPL_UNAWAY, nick, "You are no longer marked as being away")
                self.server.log(f"[AWAY] {nick} removed away status")

            self.server._persist_session_data()
        except Exception as e:
            self.server.log(f"[ERROR] AWAY handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during AWAY")

    def _handle_kick(self, msg, addr):
        """KICK <channel> <nick> [:<reason>]"""
        try:
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

            if nick.lower() not in self.server.opers and not channel.is_op(nick):
                self._send_numeric(addr, ERR_CHANOPRIVSNEEDED, nick,
                                   f"{chan_name} :You're not channel operator")
                return

            if not channel.has_member(target_nick):
                self._send_numeric(addr, ERR_USERNOTINCHANNEL, nick,
                                   f"{target_nick} {chan_name} :They aren't on that channel")
                return

            prefix = f"{nick}!{nick}@{SERVER_NAME}"
            kick_msg = format_irc_message(prefix, "KICK", [chan_name, target_nick], reason) + "\r\n"
            for m_nick, m_info in list(channel.members.items()):
                m_addr = m_info.get("addr")
                if m_addr:
                    self.server.sock_send(kick_msg.encode(), m_addr)

            channel.remove_member(target_nick)
            self.server.send_wallops(f"{nick} kicked {target_nick} from {chan_name}: {reason}")

            if hasattr(self.server, 's2s_network'):
                self.server.s2s_network.sync_channel_state(chan_name)

            self.server._persist_session_data()
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] KICK handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, self._get_nick(addr) or "*", "KICK :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] KICK handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during KICK")

    def _handle_kill(self, msg, addr):
        """KILL <nick> [:<reason>] -- requires oper 'kill' flag."""
        try:
            nick = self._get_nick(addr)
            if not self.server.oper_has_flag(nick, "k"):
                self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                                   "KILL :Permission Denied- You do not have the kill flag")
                return

            if len(msg.params) < 1:
                self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "KILL :Not enough parameters")
                return

            target_nick = msg.params[0]
            reason = msg.params[1] if len(msg.params) > 1 else "Killed by operator"

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
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] KILL handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, self._get_nick(addr) or "*", "KILL :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] KILL handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during KILL")

    def _handle_connect(self, msg, addr):
        """CONNECT <host> <port> [password] -- Initiate S2S link."""
        try:
            nick = self._get_nick(addr)
            if not self.server.oper_has_flag(nick, "c"):
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

            def do_link():
                success = self.server.s2s_network.link_to(host, port, password)
                if success:
                    self._send_notice(addr, f"Successfully linked to {host}:{port}.")
                else:
                    self._send_notice(addr, f"Failed to link to {host}:{port}. Check logs for details.")

            threading.Thread(target=do_link, daemon=True).start()
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] CONNECT handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, self._get_nick(addr) or "*", "CONNECT :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] CONNECT handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during CONNECT")

    def _handle_squit_cmd(self, msg, addr):
        """SQUIT <server_id> [:<reason>] -- Drop an S2S link."""
        try:
            nick = self._get_nick(addr)
            if not self.server.oper_has_flag(nick, "q"):
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
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] SQUIT handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, self._get_nick(addr) or "*", "SQUIT :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] SQUIT handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during SQUIT")

    # ==================================================================
    # Server Kill -- core disconnect logic
    # ==================================================================

    def _server_kill(self, target_nick, reason="Disconnected"):
        """Disconnect a client by nick. Cleans up channels, clients, registration,
        NickServ state, PM buffers, persists to disk. Returns the killed nick if found, else False."""
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

        prefix = f"{nick}!{nick}@{SERVER_NAME}"
        quit_msg = format_irc_message(prefix, "QUIT", [], reason) + "\r\n"

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

        self.server.channel_manager.remove_nick_from_all(nick)

        error_msg = f"ERROR :Closing Link: {nick} ({reason})\r\n"
        self.server.sock_send(error_msg.encode(), target_addr)

        target_reg = self.registration_state.get(target_addr, {})
        target_user = target_reg.get("user", nick)
        target_realname = target_reg.get("realname", nick)

        if nick.lower() in self.server.opers:
            self.server.remove_active_oper(nick.lower())

        self.server.clients.pop(target_addr, None)
        self.registration_state.pop(target_addr, None)
        self.server.nickserv_identified.pop(target_addr, None)
        self._pm_buffer_replayed = {k for k in self._pm_buffer_replayed if k[0] != target_addr}

        try:
            self.server.add_disconnection(
                nick=nick, user=target_user, realname=target_realname,
                host=SERVER_NAME, quit_reason=reason,
            )
        except Exception as e:
            self.server.log(f"[STORAGE ERROR] Failed to persist disconnection for {nick}: {e}")

        self.server._persist_session_data()
        return nick

    # ==================================================================
    # TRUST -- o-line management (active version)
    # ==================================================================

    def _handle_trust(self, msg, addr):
        """TRUST <subcommand> [args] -- manage o-lines (oper credentials)."""
        nick = self._get_nick(addr)
        if not msg.params:
            self._trust_help(addr)
            return

        sub = msg.params[0].lower()
        args = msg.params[1:]

        if sub == "list":
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
        updated_active = []
        for entry in data.get("active_opers", []):
            if isinstance(entry, dict) and entry.get("account") == acct:
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

    # ==================================================================
    # STATS (active version)
    # ==================================================================

    def _handle_stats(self, msg, addr):
        """STATS <letter> -- server statistics (oper only)."""
        try:
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
        except Exception as e:
            self.server.log(f"[ERROR] STATS handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during STATS")

    # ==================================================================
    # SETMOTD (active version)
    # ==================================================================

    def _handle_setmotd(self, msg, addr):
        """SETMOTD :<text> -- set Message of the Day (requires server admin)."""
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

    # ==================================================================
    # REHASH (active version)
    # ==================================================================

    def _handle_rehash(self, msg, addr):
        """REHASH -- no longer supported. opers.json is the sole authority."""
        try:
            nick = self._require_admin(addr)
            if not nick:
                return
            self._oper_notice(addr, "REHASH is no longer supported. Edit opers.json directly.")
        except Exception as e:
            self.server.log(f"[ERROR] REHASH handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during REHASH")

    # ==================================================================
    # SHUTDOWN (active version)
    # ==================================================================

    def _handle_shutdown(self, msg, addr):
        """SHUTDOWN [reason] -- graceful server shutdown (requires server admin)."""
        try:
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
        except Exception as e:
            self.server.log(f"[ERROR] SHUTDOWN handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self.server._running = False

    # ==================================================================
    # WALLOPS
    # ==================================================================

    def _handle_wallops(self, msg, addr):
        """WALLOPS :<message> -- oper only, broadcasts to all opers."""
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

    # ==================================================================
    # LINK, RELINK, DELINK
    # ==================================================================

    def _handle_link(self, msg, addr):
        """LINK <server> [port] -- initiate S2S link."""
        nick = self._require_oper(addr)
        if not nick:
            return
        if not msg.params:
            self._oper_notice(addr, "Usage: LINK <server> [port]")
            return
        server_name = msg.params[0]
        port = int(msg.params[1]) if len(msg.params) > 1 else 9525
        fake_msg = type("M", (), {"params": [server_name, str(port)]})()
        self._handle_connect(fake_msg, addr)

    def _handle_relink(self, msg, addr):
        """RELINK <server> -- reconnect a dropped S2S link."""
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
        """DELINK <server> [reason] -- drop S2S link (alias for SQUIT)."""
        nick = self._require_oper(addr)
        if not nick:
            return
        self._handle_squit_cmd(msg, addr)
