"""
IRC message parser, formatter, and constants for RFC 1459/2812 compliance.

Provides:
  - IRCMessage dataclass for parsed messages
  - parse_irc_message() to parse wire-format lines
  - format_irc_message() to build wire-format lines
  - numeric_reply() helper for server numeric responses
  - All RFC 2812 numeric constants used by csc-server
"""

from dataclasses import dataclass, field
from typing import List, Optional

# Server identity
SERVER_NAME = "csc-server"

# ---------------------------------------------------------------------------
# RFC 2812 Numeric Reply Constants
# ---------------------------------------------------------------------------

# Welcome burst (001-004)
RPL_WELCOME = "001"
RPL_YOURHOST = "002"
RPL_CREATED = "003"
RPL_MYINFO = "004"

# Channel list (322-323)
RPL_LIST = "322"
RPL_LISTEND = "323"

# Topic (331-332)
RPL_NOTOPIC = "331"
RPL_TOPIC = "332"

# Names (353, 366)
RPL_NAMREPLY = "353"
RPL_ENDOFNAMES = "366"

# WHOIS (311-313, 318)
RPL_WHOISUSER = "311"
RPL_WHOISSERVER = "312"
RPL_WHOISOPERATOR = "313"
RPL_ENDOFWHOIS = "318"

# WHOWAS (314, 369, 406)
RPL_WHOWASUSER = "314"
RPL_ENDOFWHOWAS = "369"
ERR_WASNOSUCHNICK = "406"

# MOTD (372, 375, 376)
RPL_MOTDSTART = "375"
RPL_MOTD = "372"
RPL_ENDOFMOTD = "376"

# Oper (381)
RPL_YOUREOPER = "381"

# User modes (221)
RPL_UMODEIS = "221"

# Away (301, 305, 306)
RPL_AWAY = "301"
RPL_UNAWAY = "305"
RPL_NOWAWAY = "306"

# Error numerics
ERR_NOSUCHNICK = "401"
ERR_NOSUCHCHANNEL = "403"
ERR_CANNOTSENDTOCHAN = "404"
ERR_NORECIPIENT = "411"
ERR_NOTEXTTOSEND = "412"
ERR_NONICKNAMEGIVEN = "431"
ERR_ERRONEUSNICKNAME = "432"
ERR_NICKNAMEINUSE = "433"
ERR_USERNOTINCHANNEL = "441"
ERR_NOTONCHANNEL = "442"
ERR_NOTREGISTERED = "451"
ERR_NEEDMOREPARAMS = "461"
ERR_ALREADYREGISTRED = "462"
ERR_PASSWDMISMATCH = "464"
ERR_NOPRIVILEGES = "481"
ERR_CHANOPRIVSNEEDED = "482"

# User mode errors (501-502)
ERR_UMODEUNKNOWNFLAG = "501"
ERR_USERSDONTMATCH = "502"

# Channel errors (471-475)
ERR_CHANNELISFULL = "471"
ERR_UNKNOWNMODE = "472" # Re-using for invalid limit parameter
ERR_INVITEONLYCHAN = "473"
ERR_BADCHANNELKEY = "475"

# INVITE (341)
RPL_INVITING = "341"

# WHOIS Channels (319)
RPL_WHOISCHANNELS = "319"

# Ban list (367-368)
RPL_BANLIST = "367"
RPL_ENDOFBANLIST = "368"

# Ban errors (474, 478)
ERR_BANNEDFROMCHAN = "474"
ERR_BANLISTFULL = "478"



# ---------------------------------------------------------------------------
# IRCMessage dataclass
# ---------------------------------------------------------------------------

@dataclass
class IRCMessage:
    """Parsed IRC message."""
    prefix: Optional[str] = None
    command: str = ""
    params: List[str] = field(default_factory=list)
    trailing: Optional[str] = None
    raw: str = ""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_irc_message(line: str) -> IRCMessage:
    """
    Parse an IRC wire-format line into an IRCMessage.

    Format: [:prefix] COMMAND [params...] [:trailing]
    """
    raw = line.rstrip("\r\n")
    if not raw:
        return IRCMessage(raw=raw)

    rest = raw
    prefix = None
    trailing = None

    # Extract prefix
    if rest.startswith(":"):
        space_idx = rest.find(" ")
        if space_idx == -1:
            return IRCMessage(prefix=rest[1:], raw=raw)
        prefix = rest[1:space_idx]
        rest = rest[space_idx + 1:].lstrip()

    # Extract trailing (everything after " :")
    trailing_idx = rest.find(" :")
    if trailing_idx != -1:
        trailing = rest[trailing_idx + 2:]
        rest = rest[:trailing_idx]

    # Split remaining into command + params
    parts = rest.split()
    if not parts:
        return IRCMessage(prefix=prefix, trailing=trailing, raw=raw)

    command = parts[0].upper()
    params = parts[1:]

    # Trailing is the last param in IRC
    if trailing is not None:
        params.append(trailing)

    return IRCMessage(
        prefix=prefix,
        command=command,
        params=params,
        trailing=trailing,
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

def format_irc_message(prefix: Optional[str], command: str,
                       params: Optional[List[str]] = None,
                       trailing: Optional[str] = None) -> str:
    """
    Build an IRC wire-format string (without trailing \\r\\n).

    If trailing is provided, it becomes the final :param.
    If trailing is None but params has items, the last param is NOT
    auto-prefixed with ':' unless it contains spaces.
    """
    parts = []
    if prefix:
        parts.append(f":{prefix}")
    parts.append(command)

    if params is None:
        params = []

    if trailing is not None:
        # All non-trailing params first
        for p in params:
            parts.append(p)
        parts.append(f":{trailing}")
    else:
        for i, p in enumerate(params):
            if i == len(params) - 1 and (" " in p or p.startswith(":")):
                parts.append(f":{p}")
            else:
                parts.append(p)

    return " ".join(parts)


def numeric_reply(server_name: str, numeric: str, target_nick: str,
                  *text_parts: str) -> str:
    """
    Build a numeric reply line.

    Example: :csc-server 001 nick :Welcome to csc-server
    """
    text = " ".join(text_parts)
    return f":{server_name} {numeric} {target_nick} :{text}"
