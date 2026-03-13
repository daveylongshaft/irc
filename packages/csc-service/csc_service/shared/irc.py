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

# Server identity — generated once per install from hostname+MAC, persisted in server_name file
def _load_server_name() -> str:
    try:
        from csc_service.shared.platform import Platform
        return Platform.get_server_shortname()
    except Exception:
        return "csc-server"

SERVER_NAME = _load_server_name()

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
ERR_UNKNOWNERROR = "400"
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
# CTCP / DCC Constants
# ---------------------------------------------------------------------------
CTCP_DELIM = "\x01"


# ---------------------------------------------------------------------------
# IRCMessage dataclass
# ---------------------------------------------------------------------------

@dataclass
class IRCMessage:
    """
    Parsed IRC message structure representing a single IRC protocol message.

    Conforms to RFC 1459/2812 message format: [:prefix] COMMAND [params...] [:trailing]

    Args:
        None (dataclass - fields are set directly)

    Attributes:
        prefix (Optional[str]): Message prefix, typically server name or nick!user@host.
            None if no prefix present. Default: None.
        command (str): IRC command in uppercase (e.g., 'PRIVMSG', 'JOIN', '001').
            Empty string for malformed messages. Default: "".
        params (List[str]): List of space-separated parameters. If trailing is set,
            it will be the last element. Default: empty list.
        trailing (Optional[str]): The trailing parameter (content after ' :').
            None if no trailing parameter present. Default: None.
        raw (str): Original wire-format line with CRLF stripped. Default: "".

    Data structures:
        - Immutable dataclass, should not be modified after creation
        - params is a mutable list but should be treated as read-only

    Thread safety:
        - Read-only after creation, safe for concurrent access

    Parents:
        - Created by parse_irc_message()
        - Used throughout csc-server message handlers

    Children:
        - None (data container only)

    Examples:
        >>> msg = IRCMessage(prefix="nick!user@host", command="PRIVMSG",
        ...                  params=["#channel", "hello"], trailing="hello", raw="...")
        >>> msg.command
        'PRIVMSG'
    """
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

    Handles the full RFC 1459/2812 message format including optional prefix,
    command, space-separated parameters, and trailing parameter.

    Args:
        line (str): Raw IRC message line from socket, may include trailing \\r\\n.
            Can be empty string. No length limit enforced.

    Returns:
        IRCMessage: Parsed message structure with the following guarantees:
            - raw field always contains the input line with \\r\\n stripped
            - Empty input returns IRCMessage with only raw field set
            - Malformed input (prefix-only, no command) returns partial parse
            - command is always uppercase when present
            - trailing parameter is included as last element of params list
            - All fields are populated or None/empty as appropriate

    Raises:
        None: Never raises exceptions, returns best-effort parse

    Data structures:
        Read: None (operates on string input only)
        Write: Creates new IRCMessage dataclass instance
        Mutates: None

    Side effects:
        None: Pure function with no I/O or global state

    Thread safety:
        Thread-safe: No shared state, operates only on local variables

    Parents:
        - Called by server message handlers throughout csc-server
        - Called by client message processing
        - Used in all IRC protocol layer parsing

    Children:
        - IRCMessage constructor (dataclass)
        - str.rstrip(), str.startswith(), str.find(), str.lstrip()
        - str.split(), str.upper()

    Logic table (key cases):
        Input                          | prefix | command | params      | trailing
        -------------------------------|--------|---------|-------------|----------
        ""                             | None   | ""      | []          | None
        "PING"                         | None   | "PING"  | []          | None
        ":srv 001 nick :Welcome"       | "srv"  | "001"   | ["nick","Welcome"] | "Welcome"
        "JOIN #chan"                   | None   | "JOIN"  | ["#chan"]   | None
        ":nick!user@host PRIVMSG #c :hi" | "nick!user@host" | "PRIVMSG" | ["#c","hi"] | "hi"
        ":prefix"                      | "prefix" | ""    | []          | None
        "CMD p1 p2 :trail text"        | None   | "CMD"   | ["p1","p2","trail text"] | "trail text"

    Examples:
        >>> parse_irc_message("PING :server\\r\\n")
        IRCMessage(prefix=None, command='PING', params=['server'], trailing='server', raw='PING :server')
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

    Constructs a properly formatted IRC protocol message according to RFC 1459/2812
    with intelligent handling of the trailing parameter syntax.

    Args:
        prefix (Optional[str]): Message prefix (server name or nick!user@host).
            If provided and non-empty, formatted as ":prefix" at start.
            Can be None or empty string (both treated as no prefix).
        command (str): IRC command in any case (caller's responsibility to uppercase if needed).
            Required, should not be empty. Examples: "PRIVMSG", "JOIN", "001".
        params (Optional[List[str]]): List of message parameters. Can be None or empty list.
            Elements should not contain spaces except the last one if trailing is None.
            Default: None (treated as empty list).
        trailing (Optional[str]): Trailing parameter to be prefixed with " :".
            If provided, becomes the final parameter after all params.
            If None, the last param gets ":" prefix only if it contains spaces or starts with ":".
            Default: None.

    Returns:
        str: Space-joined wire-format message WITHOUT \\r\\n terminator.
            Format: [:prefix] command [param1 param2 ...] [:trailing]
            Examples:
                ":server 001 nick :Welcome" (with prefix and trailing)
                "JOIN #channel" (no prefix, no trailing)
                "PRIVMSG #chan :hello world" (trailing with spaces)

    Raises:
        None: Never raises exceptions (will produce malformed IRC if inputs invalid)

    Data structures:
        Read: None (operates on parameters only)
        Write: None (pure function)
        Mutates: None (params list is read but not modified)

    Side effects:
        None: Pure function with no I/O or global state

    Thread safety:
        Thread-safe: No shared state, operates only on local variables

    Parents:
        - Called by server broadcast functions
        - Called by numeric_reply()
        - Called by message formatting throughout csc-server

    Children:
        - str.join(), list.append()
        - Python string formatting (f-strings)

    Logic table:
        trailing | last param | Result for last param
        ---------|------------|----------------------
        Not None | Any        | All params as-is, then ":trailing"
        None     | Has space  | Prefixed with ":"
        None     | Starts ":" | Prefixed with ":"
        None     | Normal     | Not prefixed
        None     | (no params)| (nothing added)

    Examples:
        >>> format_irc_message(None, "PING", trailing="server1")
        'PING :server1'
        >>> format_irc_message(":server", "001", ["nick"], "Welcome to IRC")
        ':server 001 nick :Welcome to IRC'
        >>> format_irc_message(None, "JOIN", ["#channel"])
        'JOIN #channel'
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
    Build a numeric reply line for IRC server responses.

    Convenience function for creating RFC 2812 numeric reply messages with
    consistent formatting. Always includes trailing parameter syntax.

    Args:
        server_name (str): Server hostname to use as prefix. Should not include
            leading colon. Examples: "csc-server", "irc.example.com".
            Required, should not be empty.
        numeric (str): Three-digit numeric code as string. Examples: "001", "433", "353".
            Should be exactly 3 characters but not enforced. Use constants from this
            module (RPL_WELCOME, ERR_NICKNAMEINUSE, etc.) for correctness.
        target_nick (str): Target nickname (usually the recipient). Required, should
            not be empty. Typically the client's current or attempted nickname.
        *text_parts (str): Variable number of text parts to join with spaces and use
            as the trailing parameter. Can be empty (produces ":") or multiple parts
            that will be space-separated.

    Returns:
        str: Formatted numeric reply WITHOUT \\r\\n terminator.
            Format: ":{server_name} {numeric} {target_nick} :{text}"
            where text is all text_parts joined by spaces.
            Examples:
                ":csc-server 001 alice :Welcome to csc-server"
                ":csc-server 433 * bob :Nickname is already in use"

    Raises:
        None: Never raises exceptions (will produce malformed IRC if inputs invalid)

    Data structures:
        Read: None (operates on parameters only)
        Write: None (pure function)
        Mutates: None

    Side effects:
        None: Pure function with no I/O or global state

    Thread safety:
        Thread-safe: No shared state, operates only on local variables

    Parents:
        - Called throughout csc-server handlers for all numeric responses
        - Called by welcome sequence, error handlers, info replies

    Children:
        - str.join()
        - Python f-string formatting

    Examples:
        >>> numeric_reply("csc-server", "001", "alice", "Welcome to", "the network")
        ':csc-server 001 alice :Welcome to the network'
        >>> numeric_reply("csc-server", RPL_WELCOME, "bob", "Welcome to csc-server")
        ':csc-server 001 bob :Welcome to csc-server'
        >>> numeric_reply("csc-server", "433", "*", "Nickname is already in use")
        ':csc-server 433 * :Nickname is already in use'
    """
    text = " ".join(text_parts)
    return f":{server_name} {numeric} {target_nick} :{text}"
