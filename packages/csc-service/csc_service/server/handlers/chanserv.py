# Logging policy: Use ASCII-only characters in log messages

"""ChanServ handlers: REGISTER, SET, OP, DEOP, VOICE, DEVOICE, BAN, UNBAN, INFO, LIST."""

import time
from csc_service.shared.irc import format_irc_message, SERVER_NAME


class ChanServMixin:
    """Handles ChanServ commands."""

    def _handle_chanserv(self, msg, addr):
        """Handle PRIVMSG ChanServ :COMMAND args -- virtual ChanServ service."""
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

        if not self._is_authorized(nick, chan_name):
            self._chanserv_notice(addr, f"You must be a channel operator of {chan_name} to register it.")
            return

        if self.server.chanserv_register(chan_name, nick, topic):
            self._chanserv_notice(addr, f"Channel {chan_name} is now registered to {nick}.")
            self.server.log(f"[CHANSERV] {nick} registered channel {chan_name}")
            if topic:
                channel.topic = topic
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

        if info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
            self._chanserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
            return

        oplist = info.setdefault("oplist", [])
        if target_nick.lower() not in [n.lower() for n in oplist]:
            oplist.append(target_nick)
            self.server.chanserv_update(chan_name, info)
            self._chanserv_notice(addr, f"{target_nick} added to {chan_name} oplist.")

        channel = self.server.channel_manager.get_channel(chan_name)
        if channel and channel.has_member(target_nick):
            member = channel.get_member(target_nick)
            if "o" not in member["modes"]:
                member["modes"].add("o")
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

            channel = self.server.channel_manager.get_channel(chan_name)
            if channel:
                channel.ban_list.add(mask)
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
