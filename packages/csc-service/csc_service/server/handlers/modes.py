# Logging policy: Use ASCII-only characters in log messages

"""Mode handlers: user modes and channel modes."""

import time
from csc_service.shared.irc import (
    format_irc_message, SERVER_NAME,
    RPL_UMODEIS, ERR_UMODEUNKNOWNFLAG, ERR_USERSDONTMATCH,
    ERR_NOSUCHCHANNEL, ERR_NEEDMOREPARAMS, ERR_CHANOPRIVSNEEDED,
    ERR_NOPRIVILEGES, ERR_UNKNOWNMODE, ERR_USERNOTINCHANNEL,
    ERR_NOSUCHNICK, ERR_UNKNOWNERROR,
    RPL_BANLIST, RPL_ENDOFBANLIST, ERR_BANLISTFULL,
)


class ModeMixin:
    """Handles MODE command for users and channels, ban mask helpers."""

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
        """MODE <target> <modestring> [param1] [param2] ..."""
        try:
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
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] MODE handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, self._get_nick(addr) or "*", "MODE :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] MODE handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during MODE")

    def _handle_user_mode(self, msg, addr, nick, target_nick):
        """Handle user MODE commands."""
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
                    if adding:
                        if char not in current_modes:
                            current_modes.add(char)
                            changes_made = True
                    else:
                        if char in current_modes:
                            current_modes.discard(char)
                            changes_made = True

                elif handler_type == "oper":
                    if adding:
                        if not is_oper:
                            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                                             ":Permission Denied- You're not an IRC operator")
                            return
                        if target_nick.lower() not in self.server.opers:
                            self.server.add_active_oper(target_nick.lower())
                            current_modes.add("o")
                            changes_made = True
                    else:
                        if not is_oper:
                            self._send_numeric(addr, ERR_NOPRIVILEGES, nick,
                                             ":Permission Denied- You're not an IRC operator")
                            return
                        if target_nick.lower() in self.server.opers:
                            self.server.remove_active_oper(target_nick.lower())
                            current_modes.discard("o")
                            changes_made = True

                elif handler_type == "noop":
                    pass

            else:
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

    # ==================================================================
    # Ban Mask Helpers
    # ==================================================================

    @staticmethod
    def _normalize_ban_mask(mask):
        """Normalize a ban mask to nick!user@host format."""
        if "!" not in mask and "@" not in mask:
            return f"{mask}!*@*"
        if "!" not in mask:
            return f"*!{mask}"
        if "@" not in mask:
            return f"{mask}@*"
        return mask

    @staticmethod
    def _match_ban_mask(mask, nick_user_host):
        """Match a ban mask pattern against a nick!user@host string."""
        import fnmatch

        if "!" in mask:
            mask_nick, mask_rest = mask.split("!", 1)
        else:
            mask_nick, mask_rest = "*", mask

        if "!" in nick_user_host:
            actual_nick, actual_rest = nick_user_host.split("!", 1)
        else:
            actual_nick, actual_rest = nick_user_host, "*@*"

        if not fnmatch.fnmatch(actual_nick.lower(), mask_nick.lower()):
            return False

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
        """Check if a nick!user@host matches any ban in the channel's ban list."""
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
