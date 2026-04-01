"""
IRC protocol constants for CSC/RFC normalization.

This module defines sets of standard and custom commands, and mappings
for translating between CSC dialect and standard RFC 2812 IRC.
"""

# Standard RFC 2812 Commands (Subset)
RFC_COMMANDS = {
    "NICK", "USER", "PASS", "OPER", "QUIT",
    "JOIN", "PART", "MODE", "TOPIC", "NAMES", "LIST", "INVITE", "KICK",
    "PRIVMSG", "NOTICE", "MOTD", "LUSERS", "VERSION", "STATS", "LINKS",
    "TIME", "CONNECT", "TRACE", "ADMIN", "INFO", "SERVLIST", "SQUERY",
    "WHO", "WHOIS", "WHOWAS", "KILL", "PING", "PONG", "ERROR",
    "AWAY", "REHASH", "DIE", "RESTART", "SUMMON", "USERS", "WALLOPS",
    "USERHOST", "ISON", "CAP", "AUTHENTICATE"
}

# CSC-Specific Commands
CSC_COMMANDS = {
    "ISOP",     # Check oper status
    "BUFFER",   # Request chat buffer replay
    "AI",       # Service command
    "IDENT",    # Legacy registration (pre-NICK/USER)
    "RENAME",   # Legacy nick change
    "CRYPTOINIT" # Encryption handshake (handled by transport layer)
}

# Mapping: CSC Legacy -> RFC Equivalent
CSC_TO_RFC_MAP = {
    "IDENT": "NICK",   # Requires synthetic USER generation
    "RENAME": "NICK",
}

# Synthetic 005 (RPL_ISUPPORT) tokens for CSC Server
# CSC server supports:
# - Channel types: # (standard)
# - Prefix: @ (op) + (voice) -> (ov)@+
# - Chanmodes: b,k,l,imnpst (standard set supported by server_message_handler)
CSC_ISUPPORT_TOKENS = [
    "CHANTYPES=#",
    "PREFIX=(ov)@+",
    "CHANMODES=b,k,l,imnpst",
    "NETWORK=CSC-Network",
    "CASEMAPPING=rfc1459",
]
