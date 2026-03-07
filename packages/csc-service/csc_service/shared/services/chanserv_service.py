"""
ChanServ Service - Channel registration and management.

Commands (via /msg ChanServ):
  REGISTER <#chan> <topic> - Register a channel
  OP <#chan> <nick>        - Add a nick to the oplist
  DEOP <#chan> <nick>      - Remove a nick from the oplist
  VOICE <#chan> <nick>     - Add a nick to the voicelist
  DEVOICE <#chan> <nick>   - Remove a nick from the voicelist
  BAN <#chan> <mask>       - Add a mask to the banlist
  UNBAN <#chan> <mask>     - Remove a mask from the banlist
  LIST                     - List registered channels
  INFO <#chan>             - Show registration info

Data storage: managed by PersistentStorageManager (chanserv.json)
"""

import time
from csc_service.server.service import Service

class Chanserv(Service):
    """
    ChanServ service for channel registration and access control.
    """

    def __init__(self, server_instance):
        """Initialize the ChanServ service."""
        super().__init__(server_instance)
        self.name = "chanserv"
        self.log("ChanServ service initialized.")

    def register(self, *args) -> str:
        """REGISTER <#chan> <topic>"""
        if len(args) < 2:
            return "Error: REGISTER requires channel and topic. Usage: REGISTER <#chan> <topic>"
        return "Error: ChanServ REGISTER must be called via PRIVMSG from the IRC server integration."

    def op(self, *args) -> str:
        """OP <#chan> <nick>"""
        if len(args) < 2:
            return "Error: OP requires channel and nick. Usage: OP <#chan> <nick>"
        return "Error: ChanServ OP must be called via PRIVMSG from the IRC server integration."

    def voice(self, *args) -> str:
        """VOICE <#chan> <nick>"""
        if len(args) < 2:
            return "Error: VOICE requires channel and nick. Usage: VOICE <#chan> <nick>"
        return "Error: ChanServ VOICE must be called via PRIVMSG from the IRC server integration."

    def ban(self, *args) -> str:
        """BAN <#chan> [mask]"""
        if len(args) < 1:
            return "Error: BAN requires channel. Usage: BAN <#chan> [mask]"
        return "Error: ChanServ BAN must be called via PRIVMSG from the IRC server integration."

    # Internal methods for server integration

    def apply_channel_state(self, channel_obj):
        """
        Apply registered state (topic, modes, ops, voice, bans) to a channel object.
        Called by the server when a channel is loaded or a user joins.
        """
        info = self.server.storage.chanserv_get(channel_obj.name)
        if not info:
            return

        # Apply topic
        if info.get("topic"):
            channel_obj.topic = info["topic"]

        # Apply oplist
        oplist = info.get("oplist", [])
        for nick in list(channel_obj.members.keys()):
            if nick.lower() in oplist:
                channel_obj.members[nick]["modes"].add("o")

        # Apply voicelist
        voicelist = info.get("voicelist", [])
        for nick in list(channel_obj.members.keys()):
            if nick.lower() in voicelist:
                channel_obj.members[nick]["modes"].add("v")

        # Apply banlist
        banlist = info.get("banlist", [])
        for mask in banlist:
            channel_obj.ban_list.add(mask)

        # Enforce bans: kick users who are currently in the channel but should be banned
        # (This is more complex because we need to know who matches the mask)
        # For now, we'll let the message handler handle it during JOIN.

    def default(self, *args) -> str:
        """Show available ChanServ commands."""
        return (
            "ChanServ - Channel Registration Service
"
            "Available commands:
"
            "  /msg ChanServ REGISTER <#chan> <topic>  - Register a channel
"
            "  /msg ChanServ OP <#chan> <nick>         - Add a nick to oplist
"
            "  /msg ChanServ VOICE <#chan> <nick>      - Add a nick to voicelist
"
            "  /msg ChanServ BAN <#chan> [<mask>]      - Add a mask to banlist
"
            "  /msg ChanServ INFO <#chan>              - Show channel info"
        )
