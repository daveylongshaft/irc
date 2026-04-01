"""
Channel and ChannelManager for IRC-style channel support.

Provides:
  - Channel: tracks name, topic, members, modes, creation time
  - ChannelManager: manages collection of channels with a default channel

All nick lookups are case-insensitive. Members are stored keyed by
lowercase nick, with the display nick preserved in the value dict.
"""

import time
import threading
from typing import Dict, Optional, Set, List, Tuple, Any


def _nk(nick: str) -> str:
    """Normalize nick to lowercase for case-insensitive lookups."""
    return nick.lower() if nick else ""


class Channel:
    """Represents a single IRC channel with members, modes, bans, and topic.

    Tracks membership (with per-member modes like op/voice), channel-wide modes,
    ban lists, invite lists, and topic. All nick lookups are case-insensitive
    via _nk() normalization; display nicks are preserved in member dicts.

    Attributes:
        name (str): Channel name as provided (e.g. "#general"), case preserved.
        topic (str): Current channel topic, empty string if unset.
        members (Dict[str, Dict[str, Any]]): Members keyed by lowercase nick.
            Values: {"addr": tuple, "modes": set[str], "nick": str (display case)}.
        modes (Set[str]): Active channel mode characters (e.g. {"n", "t", "i"}).
        mode_params (Dict[str, Any]): Parameters for modes that require them
            (e.g. {"l": 50, "k": "secret"}).
        invite_list (Set[str]): Lowercase nicks invited to this channel (for +i mode).
        ban_list (Set[str]): Ban masks (e.g. "nick!user@host" patterns).
        created (float): Unix timestamp of channel creation.
    """

    def __init__(self, name: str):
        """Initialize a new IRC channel.

        Args:
            name: Channel name (str), typically starting with '#'. Case is preserved
                for display. No validation is performed on the name format.

        Returns:
            None

        Raises:
            None

        Data:
            Writes:
                - self.name (str): The channel name as provided
                - self.topic (str): Empty string, can be set later
                - self.members (Dict[str, Dict[str, Any]]): Empty dict mapping
                  lowercase nick -> {"addr": tuple, "modes": set, "nick": str}
                - self.modes (Set[str]): Empty set of channel mode characters
                - self.mode_params (Dict[str, Any]): Empty dict for mode parameters
                - self.invite_list (Set[str]): Empty set of lowercase nicks
                - self.ban_list (Set[str]): Empty set of ban masks
                - self.created (float): Current Unix timestamp from time.time()

        Side effects:
            - Calls time.time() to set creation timestamp

        Thread safety:
            Not thread-safe. Caller must synchronize access to Channel instances.

        Children:
            - time.time(): Gets current Unix timestamp

        Parents:
            - ChannelManager.__init__(): Creates default channel
            - ChannelManager.ensure_channel(): Creates channels on demand
        """
        self.name = name
        self.topic = ""
        self.members: Dict[str, Dict[str, Any]] = {}  # lower(nick) -> {"addr": tuple, "modes": set, "nick": display_nick}
        self.modes: Set[str] = set()
        self.mode_params: Dict[str, Any] = {}
        self.invite_list: Set[str] = set()    # stored lowercase
        self.ban_list: Set[str] = set()
        self.created = time.time()

    def add_member(self, nick: str, addr: tuple, modes: Optional[Set[str]] = None):
        """Add a member to the channel or replace existing member info.

        Args:
            nick: The user's nickname (str). Case-insensitive for lookup but display
                case is preserved. Can be any non-empty string.
            addr: The user's address (tuple), typically (host, port) or similar
                connection info. No validation is performed.
            modes: Optional set of mode characters (Set[str]) to assign to this
                member (e.g., {'o', 'v'} for operator and voice). If None or omitted,
                defaults to empty set.

        Returns:
            None

        Raises:
            None

        Data:
            Writes:
                - self.members[lowercase(nick)] (Dict[str, Any]): Creates or replaces
                  entry with {"addr": addr, "modes": modes_set, "nick": nick}

        Side effects:
            None

        Thread safety:
            Not thread-safe. Caller must synchronize access to self.members.

        Children:
            - _nk(): Normalizes nick to lowercase

        Parents:
            - IRC JOIN handlers
            - User registration code
            - Channel mode change handlers
        """
        self.members[_nk(nick)] = {
            "addr": addr,
            "modes": modes or set(),
            "nick": nick,  # preserve display case
        }

    def remove_member(self, nick: str):
        """Remove a member from the channel if they exist.

        Args:
            nick: The user's nickname (str). Case-insensitive lookup. Can be any
                string value.

        Returns:
            None

        Raises:
            None

        Data:
            Writes:
                - self.members (Dict[str, Dict[str, Any]]): Removes entry for
                  lowercase(nick) if it exists. No-op if nick not in channel.

        Side effects:
            None

        Thread safety:
            Not thread-safe. Caller must synchronize access to self.members.

        Children:
            - _nk(): Normalizes nick to lowercase

        Parents:
            - IRC PART handlers
            - IRC KICK handlers
            - IRC QUIT handlers
            - ChannelManager.remove_nick_from_all()
        """
        self.members.pop(_nk(nick), None)

    def has_member(self, nick: str) -> bool:
        """Check if a nick is a member of this channel.

        Args:
            nick: The user's nickname (str). Case-insensitive lookup. Can be any
                string value including empty string.

        Returns:
            bool: True if nick is a member of this channel, False otherwise.

        Raises:
            None

        Data:
            Reads:
                - self.members (Dict[str, Dict[str, Any]]): Checks if lowercase(nick)
                  exists as a key

        Side effects:
            None

        Thread safety:
            Not thread-safe. Caller must synchronize access to self.members.

        Children:
            - _nk(): Normalizes nick to lowercase

        Parents:
            - self.can_speak(): Checks membership before evaluating modes
            - ChannelManager.find_channels_for_nick(): Iterates all channels
            - ChannelManager.remove_nick_from_all(): Checks before removing
            - IRC command handlers (JOIN, PART, PRIVMSG, etc.)
        """
        return _nk(nick) in self.members

    def get_member(self, nick: str) -> Optional[Dict[str, Any]]:
        """Get member information dictionary for a given nick.

        Args:
            nick: The user's nickname (str). Case-insensitive lookup. Can be any
                string value.

        Returns:
            Optional[Dict[str, Any]]: Member info dict with keys:
                - "addr" (tuple): Connection address
                - "modes" (Set[str]): Set of mode characters like {'o', 'v'}
                - "nick" (str): Display-case preserved nickname
            Returns None if nick is not a member of this channel.

        Raises:
            None

        Data:
            Reads:
                - self.members (Dict[str, Dict[str, Any]]): Looks up lowercase(nick)

        Side effects:
            None

        Thread safety:
            Not thread-safe. Caller must synchronize access to self.members.
            Returned dict is a direct reference to internal data structure.

        Children:
            - _nk(): Normalizes nick to lowercase

        Parents:
            - self.get_display_nick(): Retrieves member info to get display nick
            - self.is_op(): Checks member modes
            - self.has_voice(): Checks member modes
            - self.can_speak(): Checks member modes
        """
        return self.members.get(_nk(nick))

    def get_display_nick(self, nick: str) -> str:
        """Get the display-case preserved nickname for a member.

        Args:
            nick: The user's nickname (str). Case-insensitive lookup. Can be any
                string value.

        Returns:
            str: The display-case nickname if the user is a member of this channel,
                otherwise returns the input nick as-is (preserving its case).

        Raises:
            None

        Data:
            Reads:
                - self.members (Dict[str, Dict[str, Any]]): Looks up lowercase(nick)
                  and retrieves the "nick" field from the member info dict

        Side effects:
            None

        Thread safety:
            Not thread-safe. Caller must synchronize access to self.members.

        Children:
            - self.get_member(): Retrieves member info dict (inlined here)
            - _nk(): Normalizes nick to lowercase

        Parents:
            - IRC reply handlers that need to preserve proper nick capitalization
            - NAMES list generation
        """
        info = self.members.get(_nk(nick))
        return info["nick"] if info else nick

    def get_names_list(self) -> str:
        """
        Return space-separated names list with @/+ prefix for ops/voiced.
        Example: "@opnick +voicednick nick3"
        """
        names = []
        for key, info in list(self.members.items()):
            display = info.get("nick", key)
            member_modes = info.get("modes", set())
            if "o" in member_modes:
                names.append(f"@{display}")
            elif "v" in member_modes:
                names.append(f"+{display}")
            else:
                names.append(display)
        return " ".join(sorted(names))

    def member_count(self) -> int:
        """Get the number of members in this channel.

        Args:
            None

        Returns:
            int: The count of members currently in the channel. Returns 0 if empty.

        Raises:
            None

        Data:
            Reads:
                - self.members (Dict[str, Dict[str, Any]]): The members dictionary

        Side effects:
            None

        Thread safety:
            Not thread-safe. Caller must synchronize access to self.members.

        Children:
            - len(): Built-in function to get dictionary size

        Parents:
            - ChannelManager.remove_nick_from_all(): Checks if channel is empty
        """
        return len(self.members)

    def is_op(self, nick: str) -> bool:
        """Check if a nick has channel operator (+o) mode.

        Args:
            nick: The user's nickname (str). Case-insensitive lookup. Can be any
                string value.

        Returns:
            bool: True if the nick is a member of this channel and has "o" in their
                modes set. False if nick is not a member or lacks operator mode.

        Raises:
            None

        Data:
            Reads:
                - self.members (Dict[str, Dict[str, Any]]): Looks up lowercase(nick)
                  and checks if "o" is in the member's "modes" set

        Side effects:
            None

        Thread safety:
            Not thread-safe. Caller must synchronize access to self.members.

        Children:
            - _nk(): Normalizes nick to lowercase

        Parents:
            - self.can_set_topic(): Checks operator status for topic restriction
            - IRC MODE command handlers
            - IRC KICK command handlers
            - Permission checking code
        """
        member = self.members.get(_nk(nick))
        if member:
            return "o" in member.get("modes", set())
        return False

    def has_voice(self, nick: str) -> bool:
        """Check if a nick has voice (+v) mode.

        Args:
            nick: The user's nickname (str). Case-insensitive lookup. Can be any
                string value.

        Returns:
            bool: True if the nick is a member of this channel and has "v" in their
                modes set. False if nick is not a member or lacks voice mode.

        Raises:
            None

        Data:
            Reads:
                - self.members (Dict[str, Dict[str, Any]]): Looks up lowercase(nick)
                  and checks if "v" is in the member's "modes" set

        Side effects:
            None

        Thread safety:
            Not thread-safe. Caller must synchronize access to self.members.

        Children:
            - _nk(): Normalizes nick to lowercase

        Parents:
            - IRC MODE command handlers
            - Permission checking code
            - get_names_list(): For displaying voice prefix
        """
        member = self.members.get(_nk(nick))
        if member:
            return "v" in member.get("modes", set())
        return False

    def can_speak(self, nick: str) -> bool:
        """Check if a nick can send messages to this channel.

        Implements moderated channel logic: if channel has +m mode, only members
        with +v (voice) or +o (operator) can speak. If +m is not set, anyone can speak.

        Args:
            nick: The user's nickname (str). Case-insensitive lookup. Can be any
                string value.

        Returns:
            bool: True in these cases:
                - Channel does not have "m" in self.modes (not moderated)
                - Nick is a member with "o" in their modes (operator)
                - Nick is a member with "v" in their modes (voice)
            False if:
                - Channel has "m" mode and nick is not a member
                - Channel has "m" mode and member lacks both "o" and "v" modes

        Raises:
            None

        Data:
            Reads:
                - self.modes (Set[str]): Checks if "m" (moderated) is present
                - self.members (Dict[str, Dict[str, Any]]): Looks up lowercase(nick)
                  and checks member's "modes" set for "o" or "v"

        Side effects:
            None

        Thread safety:
            Not thread-safe. Caller must synchronize access to self.modes and
            self.members.

        Children:
            - _nk(): Normalizes nick to lowercase

        Parents:
            - IRC PRIVMSG handlers
            - IRC NOTICE handlers
            - Message permission validators
        """
        if "m" not in self.modes:
            return True
        member = self.members.get(_nk(nick))
        if not member:
            return False
        member_modes = member.get("modes", set())
        return "o" in member_modes or "v" in member_modes

    def can_set_topic(self, nick: str) -> bool:
        """Check if a nick can set the channel topic.

        Implements topic protection logic: if channel has +t mode, only operators
        can set the topic. If +t is not set, anyone can set the topic.

        Args:
            nick: The user's nickname (str). Case-insensitive lookup. Can be any
                string value.

        Returns:
            bool: True in these cases:
                - Channel does not have "t" in self.modes (topic unrestricted)
                - Nick is a channel operator (has "o" mode)
            False if:
                - Channel has "t" mode and nick is not an operator

        Raises:
            None

        Data:
            Reads:
                - self.modes (Set[str]): Checks if "t" (topic restricted) is present
                - self.members (Dict[str, Dict[str, Any]]): Via is_op(), checks if
                  nick has "o" mode

        Side effects:
            None

        Thread safety:
            Not thread-safe. Caller must synchronize access to self.modes and
            self.members.

        Children:
            - self.is_op(): Checks if nick has operator mode

        Parents:
            - IRC TOPIC command handlers
            - Topic permission validators
        """
        if "t" not in self.modes:
            return True
        return self.is_op(nick)


class ChannelManager:
    """Manages all channels on the server. Thread-safe.

    Maintains a dict of Channel instances keyed by lowercase channel name.
    Provides create/get/remove/list operations and cross-channel nick lookups.
    Automatically creates a default channel ("#general") on initialization.
    All public methods are protected by a reentrant lock to ensure thread safety.

    Attributes:
        channels (Dict[str, Channel]): All channels, keyed by lowercase name.
        DEFAULT_CHANNEL (str): Class constant "#general" — created on init.
    """

    DEFAULT_CHANNEL = "#general"

    def __init__(self):
        """Initialize the channel manager with an empty channel list and default channel.

        Args:
            None

        Returns:
            None

        Raises:
            None

        Data:
            Writes:
                - self.channels (Dict[str, Channel]): Empty dict mapping lowercase
                  channel name to Channel instances
                - self._lock (threading.RLock): Reentrant lock for thread safety
            Reads:
                - self.DEFAULT_CHANNEL (str): Class constant "#general"

        Side effects:
            - Creates the default channel "#general" via ensure_channel()

        Thread safety:
            This constructor is thread-safe.

        Children:
            - self.ensure_channel(): Creates the default channel

        Parents:
            - Server initialization code or other application-level setup
        """
        self.channels: Dict[str, Channel] = {}
        self._lock = threading.RLock()
        self.ensure_channel(self.DEFAULT_CHANNEL)

    def ensure_channel(self, name: str) -> Channel:
        """Get an existing channel or create it if it doesn't exist. Thread-safe.

        Args:
            name: Channel name (str), typically starting with '#'. Case-insensitive
                for lookup but display case is preserved in the Channel object. Can
                be any string value.

        Returns:
            Channel: The existing or newly created Channel object for this name.
                Never returns None.

        Raises:
            None

        Data:
            Reads:
                - self.channels (Dict[str, Channel]): Checks if lowercase(name) exists
            Writes:
                - self.channels[lowercase(name)] (Channel): Creates new Channel if
                  key doesn't exist

        Side effects:
            - Creates new Channel instance if channel doesn't exist
            - Channel.__init__ calls time.time()

        Thread safety:
            This method is thread-safe, using a lock to protect access to the
            internal channels dictionary.

        Children:
            - Channel.__init__(): Creates new channel if needed

        Parents:
            - self.__init__(): Creates default channel
            - IRC JOIN handlers
            - Channel creation commands
        """
        with self._lock:
            key = name.lower()
            if key not in self.channels:
                self.channels[key] = Channel(name)
            return self.channels[key]

    def get_channel(self, name: str) -> Optional[Channel]:
        """Get an existing channel by name. Thread-safe.

        Args:
            name: Channel name (str). Case-insensitive lookup. Can be any string value.

        Returns:
            Optional[Channel]: The Channel object if it exists, None if the channel
                has not been created.

        Raises:
            None

        Data:
            Reads:
                - self.channels (Dict[str, Channel]): Looks up lowercase(name)

        Side effects:
            None

        Thread safety:
            This method is thread-safe, using a lock to protect access to the
            internal channels dictionary.

        Children:
            None

        Parents:
            - IRC command handlers (PART, PRIVMSG, TOPIC, MODE, etc.)
            - Channel lookup operations
        """
        with self._lock:
            return self.channels.get(name.lower())

    def remove_channel(self, name: str) -> bool:
        """Remove a channel from the manager. Thread-safe.

        The default channel (DEFAULT_CHANNEL = "#general") cannot be removed.

        Args:
            name: Channel name (str). Case-insensitive lookup. Can be any string value.

        Returns:
            bool: True if the channel existed and was removed. False if:
                - The channel name matches DEFAULT_CHANNEL (case-insensitive)
                - The channel doesn't exist

        Raises:
            None

        Data:
            Reads:
                - self.DEFAULT_CHANNEL (str): Class constant "#general"
                - self.channels (Dict[str, Channel]): Checks if lowercase(name) exists
            Writes:
                - self.channels (Dict[str, Channel]): Deletes entry for lowercase(name)
                  if it exists and is not the default channel

        Side effects:
            None

        Thread safety:
            This method is thread-safe, using a lock to protect access to the
            internal channels dictionary.

        Children:
            None

        Parents:
            - Channel cleanup code
            - Administrative channel removal commands
        """
        with self._lock:
            key = name.lower()
            if key == self.DEFAULT_CHANNEL.lower():
                return False
            if key in self.channels:
                del self.channels[key]
                return True
            return False

    def list_channels(self) -> List[Channel]:
        """Get a list of all channels. Thread-safe.

        Args:
            None

        Returns:
            List[Channel]: A list containing all Channel objects managed by this
                ChannelManager. Returns empty list if no channels exist (though
                normally at least DEFAULT_CHANNEL exists). Order is not guaranteed.
                This returns a copy of the list of channels.

        Raises:
            None

        Data:
            Reads:
                - self.channels (Dict[str, Channel]): Retrieves all values

        Side effects:
            None

        Thread safety:
            This method is thread-safe. It returns a new list containing the
            channel objects, preventing modification of the internal list.

        Children:
            None

        Parents:
            - IRC LIST command handlers
            - Server status queries
            - Administrative tools
        """
        with self._lock:
            return list(self.channels.values())

    def find_channels_for_nick(self, nick: str) -> List[Channel]:
        """Find all channels a nick is a member of (case-insensitive). Thread-safe."""
        with self._lock:
            result = []
            for channel in self.channels.values():
                if channel.has_member(nick):
                    result.append(channel)
            return result

    def remove_nick_from_all(self, nick: str) -> List[str]:
        """Remove a nick from all channels. Returns list of channel names they were in. Thread-safe."""
        with self._lock:
            removed_from = []
            # Create a copy of items to avoid modification during iteration
            for name, channel in list(self.channels.items()):
                if channel.has_member(nick):
                    channel.remove_member(nick)
                    removed_from.append(channel.name)
                    # Clean up empty non-default channels
                    if channel.member_count() == 0 and name != self.DEFAULT_CHANNEL.lower():
                        del self.channels[name]
            return removed_from
