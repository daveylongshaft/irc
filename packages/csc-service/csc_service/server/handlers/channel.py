# Logging policy: Use ASCII-only characters in log messages

"""Channel handlers: JOIN, PART, TOPIC, INVITE, NAMES, LIST."""

import time
from csc_service.shared.irc import (
    format_irc_message, SERVER_NAME,
    RPL_LIST, RPL_LISTEND, RPL_NOTOPIC, RPL_TOPIC, RPL_INVITING,
    ERR_NOSUCHCHANNEL, ERR_NOTONCHANNEL, ERR_NEEDMOREPARAMS,
    ERR_INVITEONLYCHAN, ERR_CHANNELISFULL, ERR_BADCHANNELKEY,
    ERR_BANNEDFROMCHAN, ERR_NOSUCHNICK, ERR_CHANOPRIVSNEEDED,
    ERR_UNKNOWNERROR, ERR_NOTREGISTERED,
)


class ChannelMixin:
    """Handles JOIN, PART, TOPIC, INVITE, NAMES, LIST commands."""

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

                # Persist BEFORE broadcast to prevent sync_from_disk race:
                # broadcast_to_channel calls sync_from_disk which reloads from
                # channels.json -- if we haven't persisted yet, the reload
                # removes the just-added member.
                self.server._persist_session_data()

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
                # Set topic -- check +t mode and ChanServ enforcement
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
        """LIST -- list all channels."""
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
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during LIST")
