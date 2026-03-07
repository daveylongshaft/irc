"""
Channel and ChannelManager for IRC-style channel support.

Provides:
  - Channel: tracks name, topic, members, modes, creation time
  - ChannelManager: manages collection of channels with a default channel
"""

import time
from typing import Dict, Optional, Set, List, Tuple, Any


class Channel:
    """Represents a single IRC channel."""

    def __init__(self, name: str):
        """
        Initializes the instance.
        """
        self.name = name
        self.topic = ""
        self.members: Dict[str, Dict[str, Any]] = {}  # nick -> {"addr": tuple, "modes": set}
        self.modes: Set[str] = set()
        self.created = time.time()

    def add_member(self, nick: str, addr: tuple, modes: Optional[Set[str]] = None):
        """Add a member to the channel."""
        self.members[nick] = {
            "addr": addr,
            "modes": modes or set(),
        }

    def remove_member(self, nick: str):
        """Remove a member from the channel."""
        self.members.pop(nick, None)

    def has_member(self, nick: str) -> bool:
        """Check if nick is in this channel."""
        return nick in self.members

    def get_names_list(self) -> str:
        """
        Return space-separated names list with @/+ prefix for ops/voiced.
        Example: "@opnick +voicednick nick3"
        """
        names = []
        for nick, info in list(self.members.items()):
            member_modes = info.get("modes", set())
            if "o" in member_modes:
                names.append(f"@{nick}")
            elif "v" in member_modes:
                names.append(f"+{nick}")
            else:
                names.append(nick)
        return " ".join(sorted(names))

    def member_count(self) -> int:
        """
        Returns the number of members in the channel.
        """
        return len(self.members)

    def is_op(self, nick: str) -> bool:
        """Check if nick has channel operator mode."""
        member = self.members.get(nick)
        if member:
            return "o" in member.get("modes", set())
        return False

    def has_voice(self, nick: str) -> bool:
        """Check if nick has voice (+v) mode."""
        member = self.members.get(nick)
        if member:
            return "v" in member.get("modes", set())
        return False

    def can_speak(self, nick: str) -> bool:
        """
        Check if nick can send messages to this channel.
        Returns True if channel is not +m, or nick has +v or +o.
        """
        if "m" not in self.modes:
            return True
        member = self.members.get(nick)
        if not member:
            return False
        member_modes = member.get("modes", set())
        return "o" in member_modes or "v" in member_modes

    def can_set_topic(self, nick: str) -> bool:
        """
        Check if nick can set the channel topic.
        Returns True if channel is not +t, or nick has +o.
        """
        if "t" not in self.modes:
            return True
        return self.is_op(nick)


class ChannelManager:
    """Manages all channels on the server."""

    DEFAULT_CHANNEL = "#general"

    def __init__(self):
        """
        Initializes the instance.
        """
        self.channels: Dict[str, Channel] = {}
        self.ensure_channel(self.DEFAULT_CHANNEL)

    def ensure_channel(self, name: str) -> Channel:
        """Create channel if it doesn't exist, return it."""
        if name not in self.channels:
            self.channels[name] = Channel(name)
        return self.channels[name]

    def get_channel(self, name: str) -> Optional[Channel]:
        """Get channel by name, or None."""
        return self.channels.get(name)

    def remove_channel(self, name: str) -> bool:
        """Remove a channel. Cannot remove the default channel."""
        if name == self.DEFAULT_CHANNEL:
            return False
        if name in self.channels:
            del self.channels[name]
            return True
        return False

    def list_channels(self) -> List[Channel]:
        """Return all channels."""
        return list(self.channels.values())

    def find_channels_for_nick(self, nick: str) -> List[Channel]:
        """Find all channels a nick is a member of."""
        result = []
        for channel in self.channels.values():
            if channel.has_member(nick):
                result.append(channel)
        return result

    def remove_nick_from_all(self, nick: str) -> List[str]:
        """Remove a nick from all channels. Returns list of channel names they were in."""
        removed_from = []
        for name, channel in list(self.channels.items()):
            if channel.has_member(nick):
                channel.remove_member(nick)
                removed_from.append(name)
                # Clean up empty non-default channels
                if channel.member_count() == 0 and name != self.DEFAULT_CHANNEL:
                    del self.channels[name]
        return removed_from
