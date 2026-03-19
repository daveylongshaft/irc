"""QueueProcessor: single consumer thread for unified S2S event delivery."""

import json
import threading
import traceback as tb_mod

from .queue_record import QueueRecord
from .message_queue import MessageQueue


def _nick_from_prefix(prefix):
    """Extract nick from a nick!user@host prefix."""
    return prefix.split("!")[0] if "!" in prefix else prefix


class QueueProcessor:
    """Consumes QueueRecords from the MessageQueue.

    For origin_local=True events:
        - Replicates to linked S2S peers via QMSG.
    For origin_local=False events:
        - Delivers to local clients (broadcast, send_to_nick).
        - Mutates local state (add/remove virtual members, update topics).
        - Forwards to other linked peers (chain relay), excluding via_link.
    """

    def __init__(self, server, event_queue: MessageQueue):
        self._server = server
        self._queue = event_queue
        self._running = False
        self._thread = None
        self._deliver_dispatch = {
            "PRIVMSG": self._deliver_message,
            "NOTICE":  self._deliver_message,
            "JOIN":    self._deliver_join,
            "PART":    self._deliver_part,
            "QUIT":    self._deliver_quit,
            "KICK":    self._deliver_kick,
            "TOPIC":   self._deliver_topic,
            "MODE":    self._deliver_mode,
            "NICK":    self._deliver_nick,
            "INVITE":  self._deliver_invite,
            "AWAY":    self._deliver_away,
            "WALLOPS": self._deliver_wallops,
            "CHINFO":  self._deliver_chinfo,
            "OPER_SYNC": self._deliver_oper_sync,
        }

    def start(self):
        """Start the consumer thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Signal the consumer thread to stop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self):
        """Main consumer loop."""
        while self._running:
            record = self._queue.dequeue(timeout=0.5)
            if record is None:
                continue
            try:
                if record.origin_local:
                    # Local event: replicate to all peers
                    self._send_to_peers(record)
                else:
                    # Remote event: deliver locally, then forward to other peers
                    self._deliver_local(record)
                    self._send_to_peers(record)
            except Exception as e:
                self._server.log(
                    f"[QUEUE] Error processing {record.command} "
                    f"for {record.target}: {e}\n{tb_mod.format_exc()}"
                )

    # ------------------------------------------------------------------
    # S2S replication + chain relay
    # ------------------------------------------------------------------

    def _send_to_peers(self, record):
        """Send QMSG to linked peers, excluding via_link to prevent echo.

        For local events (via_link=""), broadcasts to all peers.
        For remote events (via_link=some_server), forwards to all peers
        except the one that sent it (chain relay).
        """
        s2s = getattr(self._server, 's2s_network', None)
        if not s2s:
            return

        # CHINFO and OPER_SYNC are sync-only metadata, don't chain-relay
        if record.command.upper() in ("CHINFO", "OPER_SYNC"):
            return

        payload = json.dumps({
            "ss": record.source_server,
            "sc": record.source_client,
            "cmd": record.command,
            "tgt": record.target,
            "cnt": record.content,
        }, separators=(',', ':'))

        cmd = record.command.upper()
        target = record.target
        exclude = record.via_link or None

        # PM/NOTICE/INVITE to a nick -> route to the specific peer that owns it
        if cmd in ("PRIVMSG", "NOTICE", "INVITE") and not target.startswith("#"):
            remote_info = s2s.get_user_from_network(target)
            if remote_info:
                via = remote_info.get("via_link", remote_info.get("server_id"))
                if via and via != exclude:
                    link = s2s.get_link(via)
                    if link and link.is_connected():
                        link.send_raw(f"QMSG {payload}")
            return

        # Channel/global events -> broadcast to all peers except via_link
        s2s.broadcast_to_network("QMSG", payload, exclude_server=exclude)

    # ------------------------------------------------------------------
    # Local delivery (remote events -> local clients + state mutation)
    # ------------------------------------------------------------------

    def _deliver_local(self, record):
        """Deliver a remote event to local clients and mutate state."""
        cmd = record.command.upper()
        handler = self._deliver_dispatch.get(cmd)
        if handler:
            handler(record)
        else:
            self._server.log(f"[QUEUE] Unknown command in remote record: {cmd}")

    def _deliver_message(self, r):
        """Deliver remote PRIVMSG or NOTICE to local clients."""
        cmd = r.command.upper()
        msg = f":{r.source_client} {cmd} {r.target} :{r.content}\r\n"
        if r.target.startswith("#"):
            self._server.broadcast_to_channel(r.target, msg)
        else:
            self._server.send_to_nick(r.target, msg)

    def _deliver_join(self, r):
        """Add virtual member and broadcast JOIN to local channel members."""
        nick = _nick_from_prefix(r.source_client)
        # Extract user ident from nick!user@host prefix
        user = r.source_client.split("!")[1].split("@")[0] if "!" in r.source_client else nick
        chan_name = r.target
        channel = self._server.channel_manager.ensure_channel(chan_name)

        # Add as virtual member (no addr, tagged with remote server + via_link)
        if not channel.has_member(nick):
            channel.add_member(nick, addr=None, modes=set())
            member = channel.get_member(nick)
            if member:
                member["remote_server"] = r.source_server
                member["via_link"] = r.via_link or r.source_server

        # Track in s2s remote_users (with via_link for chain split awareness)
        s2s = getattr(self._server, 's2s_network', None)
        if s2s:
            with s2s._lock:
                nick_lower = nick.lower()
                if nick_lower not in s2s.remote_users:
                    s2s.remote_users[nick_lower] = {
                        "nick": nick,
                        "user": user,
                        "server_id": r.source_server,
                        "via_link": r.via_link or r.source_server,
                        "channels": set(),
                    }
                info = s2s.remote_users.get(nick_lower)
                if info:
                    info.setdefault("channels", set()).add(chan_name.lower())

        # Broadcast JOIN to local members
        join_msg = f":{r.source_client} JOIN {chan_name}\r\n"
        self._server.broadcast_to_channel(chan_name, join_msg)

        self._server._persist_session_data()

    def _deliver_part(self, r):
        """Remove virtual member and broadcast PART."""
        nick = _nick_from_prefix(r.source_client)
        chan_name = r.target

        part_msg = f":{r.source_client} PART {chan_name} :{r.content}\r\n"
        self._server.broadcast_to_channel(chan_name, part_msg)

        channel = self._server.channel_manager.get_channel(chan_name)
        if channel:
            channel.remove_member(nick)

        # Update remote_users tracking
        s2s = getattr(self._server, 's2s_network', None)
        if s2s:
            with s2s._lock:
                info = s2s.remote_users.get(nick.lower())
                if info:
                    info.get("channels", set()).discard(chan_name.lower())
                    if not info.get("channels"):
                        s2s.remote_users.pop(nick.lower(), None)

        self._server._persist_session_data()

    def _deliver_quit(self, r):
        """Remove remote user from all channels and broadcast QUIT."""
        nick = _nick_from_prefix(r.source_client)

        quit_msg = f":{r.source_client} QUIT :{r.content}\r\n"
        channels = self._server.channel_manager.find_channels_for_nick(nick)
        notified = set()
        for ch in channels:
            for m_nick, m_info in list(ch.members.items()):
                m_addr = m_info.get("addr")
                if m_addr and m_addr not in notified:
                    self._server.sock_send(quit_msg.encode(), m_addr)
                    notified.add(m_addr)

        self._server.channel_manager.remove_nick_from_all(nick)

        # Remove remote oper status if they had it
        if nick.lower() in self._server.opers:
            self._server.remove_active_oper(nick.lower())

        # Clean remote user tracking
        s2s = getattr(self._server, 's2s_network', None)
        if s2s:
            with s2s._lock:
                s2s.remote_users.pop(nick.lower(), None)

        self._server._persist_session_data()

    def _deliver_kick(self, r):
        """Remove target from channel and broadcast KICK."""
        # content format: "<target_nick> <reason>"
        parts = r.content.split(" ", 1)
        target_nick = parts[0] if parts else ""
        reason = parts[1] if len(parts) > 1 else _nick_from_prefix(r.source_client)
        chan_name = r.target

        kick_msg = f":{r.source_client} KICK {chan_name} {target_nick} :{reason}\r\n"
        self._server.broadcast_to_channel(chan_name, kick_msg)

        channel = self._server.channel_manager.get_channel(chan_name)
        if channel:
            channel.remove_member(target_nick)

        self._server._persist_session_data()

    def _deliver_topic(self, r):
        """Update channel topic and broadcast TOPIC."""
        chan_name = r.target
        new_topic = r.content

        channel = self._server.channel_manager.get_channel(chan_name)
        if channel:
            channel.topic = new_topic

        topic_msg = f":{r.source_client} TOPIC {chan_name} :{new_topic}\r\n"
        self._server.broadcast_to_channel(chan_name, topic_msg)

        self._server._persist_session_data()

    def _deliver_mode(self, r):
        """Apply mode changes to channel state and broadcast MODE."""
        chan_name = r.target
        mode_str = r.content  # e.g. "+o nick" or "+nt"

        # Apply mode delta to local channel state
        channel = self._server.channel_manager.get_channel(chan_name)
        if channel:
            self._apply_mode_delta(channel, mode_str)

        mode_msg = f":{r.source_client} MODE {chan_name} {mode_str}\r\n"
        self._server.broadcast_to_channel(chan_name, mode_msg)

        self._server._persist_session_data()

    @staticmethod
    def _apply_mode_delta(channel, mode_str):
        """Parse and apply a mode delta string to a channel object."""
        parts = mode_str.split()
        flags = parts[0] if parts else ""
        params = parts[1:] if len(parts) > 1 else []

        NICK_MODES = frozenset(("o", "v"))
        FLAG_MODES = frozenset(("m", "t", "n", "i", "s", "p", "Q"))
        PARAM_MODES = frozenset(("k", "l"))
        LIST_MODES = frozenset(("b",))

        param_idx = 0
        adding = True

        for ch in flags:
            if ch == "+":
                adding = True
            elif ch == "-":
                adding = False
            elif ch in FLAG_MODES:
                if adding:
                    channel.modes.add(ch)
                else:
                    channel.modes.discard(ch)
            elif ch in PARAM_MODES:
                if adding and param_idx < len(params):
                    param = params[param_idx]
                    param_idx += 1
                    if ch == "l":
                        try:
                            channel.mode_params[ch] = int(param)
                        except ValueError:
                            pass
                    else:
                        channel.mode_params[ch] = param
                    channel.modes.add(ch)
                elif not adding:
                    channel.modes.discard(ch)
                    channel.mode_params.pop(ch, None)
                    if param_idx < len(params):
                        param_idx += 1
            elif ch in NICK_MODES:
                if param_idx < len(params):
                    target_nick = params[param_idx]
                    param_idx += 1
                    member = channel.get_member(target_nick)
                    if member:
                        modes = member.get("modes", set())
                        if adding:
                            modes.add(ch)
                        else:
                            modes.discard(ch)
            elif ch in LIST_MODES:
                if param_idx < len(params):
                    mask = params[param_idx]
                    param_idx += 1
                    if adding:
                        channel.ban_list.add(mask)
                    else:
                        to_remove = None
                        for existing in channel.ban_list:
                            if existing.lower() == mask.lower():
                                to_remove = existing
                                break
                        if to_remove:
                            channel.ban_list.discard(to_remove)

    def _deliver_nick(self, r):
        """Update nick in channel member lists and broadcast NICK."""
        old_nick = _nick_from_prefix(r.source_client)
        new_nick = r.content

        nick_msg = f":{r.source_client} NICK {new_nick}\r\n"

        # Update channel memberships and broadcast
        channels = self._server.channel_manager.find_channels_for_nick(old_nick)
        notified = set()
        for ch in channels:
            old_lower = old_nick.lower()
            if old_lower in ch.members:
                member_info = ch.members.pop(old_lower)
                member_info["nick"] = new_nick
                ch.members[new_nick.lower()] = member_info

            for m_nick, m_info in list(ch.members.items()):
                m_addr = m_info.get("addr")
                if m_addr and m_addr not in notified:
                    self._server.sock_send(nick_msg.encode(), m_addr)
                    notified.add(m_addr)

        # Update remote user tracking
        s2s = getattr(self._server, 's2s_network', None)
        if s2s:
            with s2s._lock:
                info = s2s.remote_users.pop(old_nick.lower(), None)
                if info:
                    info["nick"] = new_nick
                    s2s.remote_users[new_nick.lower()] = info

        self._server._persist_session_data()

    def _deliver_invite(self, r):
        """Add to invite list and send INVITE to local target."""
        chan_name = r.content  # channel name stored in content for INVITE
        target_nick = r.target

        channel = self._server.channel_manager.get_channel(chan_name)
        if channel:
            channel.invite_list.add(target_nick.lower())

        invite_msg = f":{r.source_client} INVITE {target_nick} {chan_name}\r\n"
        self._server.send_to_nick(target_nick, invite_msg)

    def _deliver_away(self, r):
        """Update remote user away status (informational, no broadcast)."""
        s2s = getattr(self._server, 's2s_network', None)
        if not s2s:
            return
        nick = _nick_from_prefix(r.source_client)
        with s2s._lock:
            info = s2s.remote_users.get(nick.lower())
            if info:
                if r.content:
                    info["away_message"] = r.content
                else:
                    info.pop("away_message", None)

    def _deliver_wallops(self, r):
        """Send WALLOPS to all local opers."""
        wallops_msg = f":{r.source_client} WALLOPS :{r.content}\r\n"
        for addr, info in list(self._server.clients.items()):
            nick = info.get("name")
            if nick and nick.lower() in self._server.opers:
                try:
                    self._server.sock_send(wallops_msg.encode(), addr)
                except Exception as e:
                    self._server.log(f"[QUEUE] WALLOPS send error to {nick}: {e}")

    def _deliver_chinfo(self, r):
        """Apply channel metadata from remote server (created time)."""
        chan_name = r.target
        channel = self._server.channel_manager.ensure_channel(chan_name)
        try:
            meta = json.loads(r.content)
        except (json.JSONDecodeError, ValueError):
            return

        # Keep the EARLIEST created time (channel existed first on whichever server)
        remote_created = meta.get("created", 0)
        if remote_created and remote_created < channel.created:
            channel.created = remote_created

    def _deliver_oper_sync(self, r):
        """Register remote oper as local oper (network-wide oper status)."""
        nick = _nick_from_prefix(r.source_client)
        try:
            meta = json.loads(r.content)
        except (json.JSONDecodeError, ValueError):
            return
        flags = meta.get("flags", "o")
        account = meta.get("account", nick.lower())
        remote_account = f"remote:{r.source_server}:{account}"
        self._server.add_active_oper(nick.lower(), remote_account, flags)
        self._server.log(
            f"[S2S] Remote oper synced: {nick} flags={flags} from {r.source_server}"
        )
