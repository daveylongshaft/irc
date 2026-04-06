# Logging policy: Use ASCII-only characters in log messages

"""Messaging handlers: PRIVMSG, NOTICE, wakeword filtering, buffer replay."""

from csc_server_core.irc import (
    format_irc_message, SERVER_NAME,
    ERR_NORECIPIENT, ERR_NOTEXTTOSEND, ERR_NOSUCHCHANNEL,
    ERR_CANNOTSENDTOCHAN, ERR_NOSUCHNICK, ERR_NEEDMOREPARAMS,
    ERR_UNKNOWNERROR, ERR_NOTONCHANNEL,
)


class MessagingMixin:
    """Handles PRIVMSG, NOTICE, wakeword filtering, AI command routing, buffer replay."""

    def _handle_privmsg(self, msg, addr):
        """PRIVMSG <target> :<text>"""
        try:
            nick = self._get_nick(addr)
            if len(msg.params) < 1:
                self._send_numeric(addr, ERR_NORECIPIENT, nick, "No recipient given (PRIVMSG)")
                return
            if len(msg.params) < 2:
                self._send_numeric(addr, ERR_NOTEXTTOSEND, nick, "No text to send")
                return

            target = msg.params[0]
            text = msg.params[-1]  # trailing text

            prefix = f"{nick}!{nick}@{SERVER_NAME}"

            if target.startswith("#"):
                # Channel message
                channel = self.server.channel_manager.get_channel(target)
                if not channel:
                    self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                                       f"{target} :No such channel")
                    return
                if not channel.has_member(nick):
                    self._send_numeric(addr, ERR_CANNOTSENDTOCHAN, nick,
                                       f"{target} :Cannot send to channel")
                    return
                # Check +n (no external messages) -- only members can send
                if "n" in channel.modes and not channel.has_member(nick):
                    self._send_numeric(addr, ERR_CANNOTSENDTOCHAN, nick,
                                       f"{target} :Cannot send to channel (+n)")
                    return
                # Check +m (moderated) -- only ops/voiced/opers can speak
                if not channel.can_speak(nick) and nick.lower() not in self.server.opers:
                    self._send_numeric(addr, ERR_CANNOTSENDTOCHAN, nick,
                                       f"{target} :Cannot send to channel (+m)")
                    return

                # Normalize channel name to lowercase for consistent output (RFC 1459)
                normalized_target = target.lower()
                out = format_irc_message(prefix, "PRIVMSG", [normalized_target], text) + "\r\n"

                # S2S: Relay to federation network BEFORE presenting locally.
                # Remote servers receive and re-relay before presenting, so all
                # channel members across the network see the message at roughly
                # the same time (bounded by slowest relay hop, not split T=0/T=N).
                if hasattr(self.server, 's2s_network'):
                    self.server.s2s_network.route_message(nick, normalized_target, text)

                # Wakeword-filtered broadcast: check each recipient individually
                self._broadcast_privmsg_filtered(channel, out, text, nick, exclude=addr)
                self.server.chat_buffer.append(normalized_target, nick, "PRIVMSG", text)

                # Check for embedded service command (AI ... or <server> AI ...)
                ai_info = self._parse_ai_command(text)
                if ai_info:
                    target_server, ai_text = ai_info
                    local_id = self._get_local_server_id()
                    if target_server is None or target_server.lower() == local_id.lower():
                        self._handle_service_via_chatline(ai_text, addr, nick, normalized_target)
                    else:
                        self._forward_ai_command(target_server, ai_text, nick, normalized_target, addr)
                # Check for embedded file upload start (bare or server-prefixed)
                else:
                    file_info = self._parse_file_command(text)
                    if file_info:
                        target_server, file_text = file_info
                        local_id = self._get_local_server_id()
                        if target_server is None or target_server.lower() == local_id.lower():
                            if not self._is_authorized(nick, normalized_target):
                                self.server.log(f"[SECURITY] [BLOCKED] File upload blocked from unauthorized user {nick}@{addr}")
                                self.server.sock_send(b"[Server] Error: IRC operator or channel operator status required for file uploads.\n", addr)
                                return
                            self.file_handler.start_session(addr, file_text)
            else:
                # Private message to a nick
                self._maybe_replay_pm_buffer(target, nick)
                out = format_irc_message(prefix, "PRIVMSG", [target], text) + "\r\n"
                if not self.server.send_to_nick(target, out):
                    # Try S2S routing for remote users
                    if hasattr(self.server, 's2s_network'):
                        _link, remote_info = self.server.s2s_network.get_user_from_network(target)
                        if remote_info is not None:
                            self.server.s2s_network.route_message(nick, target, text)
                            self.server.chat_buffer.append(target, nick, "PRIVMSG", text)
                            return
                    self._send_numeric(addr, ERR_NOSUCHNICK, nick,
                                       f"{target} :No such nick/channel")
                else:
                    self.server.chat_buffer.append(target, nick, "PRIVMSG", text)
        except (IndexError, ValueError) as e:
            self.server.log(f"[ERROR] PRIVMSG handler ValueError from {addr}: {e}")
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, self._get_nick(addr) or "*", "PRIVMSG :Invalid parameters")
        except Exception as e:
            self.server.log(f"[ERROR] PRIVMSG handler unexpected error from {addr}: {type(e).__name__}: {e}")
            self._send_numeric(addr, ERR_UNKNOWNERROR, self._get_nick(addr) or "*", "Internal server error during PRIVMSG")

    def _handle_notice(self, msg, addr):
        """NOTICE <target> :<text> -- same as PRIVMSG but no auto-reply expected."""
        try:
            nick = self._get_nick(addr)
            if len(msg.params) < 2:
                return  # NOTICE errors are silently dropped per RFC

            target = msg.params[0]
            text = msg.params[-1]
            prefix = f"{nick}!{nick}@{SERVER_NAME}"

            if target.startswith("#"):
                channel = self.server.channel_manager.get_channel(target)
                if channel and channel.has_member(nick):
                    # Normalize channel name to lowercase for consistent output (RFC 1459)
                    normalized_target = target.lower()
                    out = format_irc_message(prefix, "NOTICE", [normalized_target], text) + "\r\n"
                    # Relay to peers before presenting locally (relay-then-present)
                    if hasattr(self.server, 's2s_network'):
                        self.server.s2s_network.route_notice(nick, normalized_target, text)
                    self.server.broadcast_to_channel(normalized_target, out, exclude=addr)
                    self.server.chat_buffer.append(normalized_target, nick, "NOTICE", text)
            else:
                self._maybe_replay_pm_buffer(target, nick)
                out = format_irc_message(prefix, "NOTICE", [target], text) + "\r\n"
                if self.server.send_to_nick(target, out):
                    self.server.chat_buffer.append(target, nick, "NOTICE", text)
        except Exception as e:
            # NOTICE never generates a reply, so just log the error
            self.server.log(f"[ERROR] NOTICE handler unexpected error from {addr}: {type(e).__name__}: {e}")

    # ==================================================================
    # Wakeword Filtering
    # ==================================================================

    def _handle_wakeword(self, msg, addr):
        """WAKEWORD ENABLE|DISABLE - Toggle wakeword-based message filtering for this client."""
        nick = self._get_nick(addr)
        if not msg.params:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick,
                               "WAKEWORD :Not enough parameters. Usage: WAKEWORD ENABLE|DISABLE")
            return

        action = msg.params[0].upper()

        if action == "ENABLE":
            if addr in self.server.clients:
                self.server.clients[addr]["wakeword_enabled"] = True
            self._send_notice(addr, "Wakeword filtering ENABLED. Only matching messages will be forwarded.")
            self.server.log(f"[WAKEWORD] {nick} enabled wakeword filtering")
        elif action == "DISABLE":
            if addr in self.server.clients:
                self.server.clients[addr]["wakeword_enabled"] = False
            self._send_notice(addr, "Wakeword filtering DISABLED. All messages will be forwarded.")
            self.server.log(f"[WAKEWORD] {nick} disabled wakeword filtering")
        else:
            self._send_notice(addr, "Usage: WAKEWORD ENABLE|DISABLE")

    def _should_forward_to_client(self, recipient_addr, message_text, sender_nick):
        """Check whether a PRIVMSG should be forwarded to a specific recipient."""
        client_info = self.server.clients.get(recipient_addr)
        if not client_info:
            return True  # Unknown client, forward by default

        # If wakeword filtering is not enabled, forward everything
        if not client_info.get("wakeword_enabled", False):
            return True

        recipient_nick = client_info.get("name", "")
        msg_lower = message_text.lower()

        # Check 1: Nick match - message mentions the recipient's nick
        if recipient_nick and recipient_nick.lower() in msg_lower:
            return True

        # Check 2: AI command token - message starts with "AI " or "<server> AI "
        if message_text.upper().startswith("AI "):
            return True
        if self._parse_ai_command(message_text) is not None:
            return True

        # Check 3: Wakeword match - message contains any wakeword
        wakewords = self.server.wakewords
        if wakewords:
            for word in wakewords:
                if word in msg_lower:
                    return True

        # No match - suppress this message for the AI client
        return False

    def _broadcast_privmsg_filtered(self, channel, out_msg, message_text, sender_nick, exclude=None):
        """Broadcast a PRIVMSG to channel members with wakeword filtering."""
        msg_bytes = out_msg.encode("utf-8") if isinstance(out_msg, str) else out_msg
        for member_nick, info in list(channel.members.items()):
            member_addr = info.get("addr")
            if not member_addr or member_addr == exclude:
                continue

            if not self._should_forward_to_client(member_addr, message_text, sender_nick):
                self.server.log(
                    f"[WAKEWORD] Filtered message from {sender_nick} to {member_nick} "
                    f"(no nick/token/wakeword match)"
                )
                continue

            try:
                self.server.sock_send(msg_bytes, member_addr)
            except Exception as e:
                self.server.log(f"[BROADCAST_FILTERED] Error sending to {member_nick}@{member_addr}: {e}")

    def _get_local_server_id(self):
        """Return the local server's S2S identity (e.g. 'haven.4346')."""
        if hasattr(self.server, 's2s_network'):
            return self.server.s2s_network.server_id
        return SERVER_NAME

    def _parse_ai_command(self, text):
        """Detect AI command with optional server prefix.

        Delegates to Service.parse_service_command() from the service base layer.
        Returns:
            (target_server, ai_text) if AI command detected, else None.
        """
        from csc_services import Service
        parsed = Service.parse_service_command(text)
        if parsed is None:
            return None
        # Return in legacy format: (target, full_text_without_target)
        if parsed["target"] is None:
            return (None, text)
        # Strip the target prefix: return remaining text starting at keyword
        parts = text.split(None, 1)
        return (parsed["target"], parts[1] if len(parts) > 1 else text)

    def _parse_file_command(self, text):
        """Detect file upload command with optional server prefix.

        Returns:
            (target_server, file_text) if file command detected, else None.
            target_server is None for unprefixed commands.
        """
        if text.startswith("<begin file=") or text.startswith("<append file="):
            return (None, text)
        parts = text.split(None, 1)
        if len(parts) == 2:
            rest = parts[1]
            if rest.startswith("<begin file=") or rest.startswith("<append file="):
                return (parts[0], rest)
        return None

    def _forward_ai_command(self, target_server, ai_text, nick, channel, addr):
        """Forward an AI command to a remote server via SYNCCMD."""
        if not hasattr(self.server, 's2s_network'):
            self._send_notice(addr, f"S2S not available, cannot reach {target_server}")
            return
        link = self.server.s2s_network.get_link(target_server)
        if link is None:
            self._send_notice(addr, f"Server {target_server} is not linked")
            return
        target_param = channel or "*"
        line = f"SYNCCMD {nick} {target_param} {target_server} :{ai_text}"
        link.send_raw(line)
        self.server.log(f"[S2S] Forwarded AI command to {target_server}: {ai_text}")

    def _handle_service_via_chatline(self, raw_line, addr, nick, channel=None):
        """Handle service commands received via chatline (e.g., AI 1 agent assign...)."""
        self.server.log(f"[DEBUG] _handle_service_via_chatline entered for {nick}@{addr}: {raw_line}")

        # Strip "AI " prefix if present for handle_command
        cmd_text = raw_line
        if raw_line.upper().startswith("AI "):
            cmd_text = raw_line[3:].strip()

        parts = cmd_text.split()
        if not parts:
            return

        token = parts[0]

        if len(parts) < 2:
            self._send_notice(addr, f"{token} AI : UPDATED Usage: AI <token> <service> [<method>] [args...]")
            return

        class_name = parts[1]
        method_name = parts[2] if len(parts) > 2 else "help"  # Default to "help" if no method specified
        method_args = parts[3:] if len(parts) > 3 else []

        # Execute via server.handle_command (Service.handle_command signature)
        result = self.server.handle_command(class_name, method_name, method_args, nick, addr)

        if token == "0":
            return # Fire and forget

        # Send result back -- prefix every line with the token
        for line in str(result).splitlines():
            prefixed = f"{token} AI : {line}"
            if channel:
                prefix = f"ServiceBot!service@{SERVER_NAME}"
                msg = format_irc_message(prefix, "PRIVMSG", [channel], prefixed) + "\r\n"
                self.server.broadcast_to_channel(channel, msg)
                # Relay ServiceBot response to all linked servers
                if hasattr(self.server, 's2s_network'):
                    self.server.s2s_network.route_message("ServiceBot", channel, prefixed)
            else:
                self._send_notice(addr, prefixed)
        self.server.log(f"[SERVICE] '{cmd_text}' from {nick}@{addr}: OK")

    # ==================================================================
    # Buffer Replay
    # ==================================================================

    def _handle_buffer(self, msg, addr):
        """BUFFER <target> [full] -- replay the chat buffer for a channel or PM target."""
        nick = self._get_nick(addr)
        if len(msg.params) < 1:
            self._send_numeric(addr, ERR_NEEDMOREPARAMS, nick, "BUFFER :Not enough parameters")
            return

        target = msg.params[0]
        full_history = False
        if len(msg.params) > 1:
            arg = msg.params[1].lower()
            if arg in ("full", "all") or (arg.isdigit() and int(arg) > 1024):
                full_history = True

        if target.startswith("#"):
            channel = self.server.channel_manager.get_channel(target)
            if not channel:
                self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                                   f"{target} :No such channel")
                return
            if not channel.has_member(nick):
                self._send_numeric(addr, ERR_NOTONCHANNEL, nick,
                                   f"{target} :You're not on that channel")
                return

        self._send_buffer_replay(addr, nick, target, full_history=full_history)

    def _send_buffer_replay(self, addr, nick, target, full_history=False):
        """Read the buffer for *target* and send each line as a NOTICE to *addr*."""
        limit = None if full_history else 1024
        lines = self.server.chat_buffer.read(target, sender_nick=nick, limit_bytes=limit)
        count = len(lines)

        prefix = f":{SERVER_NAME} NOTICE {nick} :[BUFFER]"

        # Start marker
        mode_str = "FULL" if full_history else "PARTIAL (1KB)"
        start = f"{prefix} -- Start of buffer replay for {target} ({count} lines, {mode_str}) --\r\n"
        self.server.sock_send(start.encode(), addr)

        for line in lines:
            stripped = line.rstrip("\n\r")
            replay = f"{prefix} {stripped}\r\n"
            self.server.sock_send(replay.encode(), addr)

        # End marker
        end = f"{prefix} -- End of buffer replay for {target} --\r\n"
        self.server.sock_send(end.encode(), addr)

    def _maybe_replay_pm_buffer(self, recipient_nick, sender_nick):
        """On first PM to *recipient_nick* from *sender_nick* in this session,
        auto-replay the PM buffer to the recipient so they see prior history."""
        # Find recipient address
        recipient_addr = None
        for a, info in list(self.server.clients.items()):
            if info.get("name") == recipient_nick:
                recipient_addr = a
                break
        if not recipient_addr:
            return

        # Canonical PM key: sorted lowercase nicks
        pm_key = tuple(sorted([sender_nick.lower(), recipient_nick.lower()]))
        track_key = (recipient_addr, pm_key)

        if track_key in self._pm_buffer_replayed:
            return  # already replayed this session

        # Check if there's actually any history to replay
        lines = self.server.chat_buffer.read(recipient_nick, sender_nick=sender_nick)
        if not lines:
            self._pm_buffer_replayed.add(track_key)
            return

        self._pm_buffer_replayed.add(track_key)
        self._send_buffer_replay(recipient_addr, recipient_nick, sender_nick, full_history=False)
