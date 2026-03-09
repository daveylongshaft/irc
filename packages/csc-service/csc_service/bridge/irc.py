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
    """
    Represents a parsed IRC message conforming to RFC 1459/2812 wire format.

    This dataclass holds the components of an IRC protocol message after parsing
    from the wire format, or before serialization to wire format. The structure
    separates the optional prefix (server/nick!user@host), command (verb or numeric),
    middle parameters, and trailing parameter.

    Args:
        prefix: Optional[str] = None
            The message prefix (source identifier). Format depends on source:
            - Server messages: "servername" (e.g., "csc-server")
            - User messages: "nick!user@host" (e.g., "alice!~alice@host.com")
            - None if no prefix present (typical for client-to-server commands)
            Constraints: Must not contain spaces if present.

        command: str = ""
            The IRC command or numeric reply code.
            - Commands: Uppercase strings (e.g., "PRIVMSG", "JOIN", "NICK")
            - Numerics: Three-digit strings (e.g., "001", "332", "401")
            Valid values: Any RFC 1459/2812 command or numeric, or empty string for
            malformed messages.
            Constraints: Converted to uppercase by parse_irc_message().

        params: List[str] = field(default_factory=list)
            List of all parameters including the trailing parameter (if present).
            - Middle params appear as-is from the wire format
            - Trailing param (text after " :") is appended as the last element
            - Empty list if no parameters
            Examples:
                "PRIVMSG #channel :Hello world" -> ["#channel", "Hello world"]
                "MODE alice +i" -> ["alice", "+i"]
            Constraints: Each param must not contain spaces unless it's the trailing param.

        trailing: Optional[str] = None
            The trailing parameter (text after " :" in wire format), if present.
            This is duplicated from params[-1] for convenience when formatting.
            - None if message has no trailing parameter
            - May contain spaces, colons, and any other characters
            Examples:
                "PRIVMSG #chan :Hello world" -> "Hello world"
                "JOIN #channel" -> None

        raw: str = ""
            The original unparsed wire-format line with \r\n stripped.
            Preserved for logging, debugging, and reference.
            Empty string for newly constructed messages or blank input lines.

    Returns:
        IRCMessage instance with the specified field values.

    Raises:
        No exceptions raised. Dataclass instantiation always succeeds.

    Data:
        Reads: None (dataclass has no methods that read external state)
        Writes: None
        Mutates: Instance fields are mutable (list and string fields can be changed)

    Side effects:
        None. Pure data container with no I/O, logging, or state changes.

    Thread safety:
        Not thread-safe. Concurrent mutations to params list require external
        synchronization.

    Children:
        field(default_factory=list) - Creates empty list for params field

    Parents:
        parse_irc_message() - Constructs instances from wire format
        format_irc_message() - May read fields to serialize to wire format
        IRC protocol handlers throughout csc-bridge and csc-server
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
    Parses an IRC wire-format line into structured IRCMessage components.

    Implements RFC 1459/2812 message parsing: extracts prefix, command, middle
    parameters, and trailing parameter from a raw IRC protocol line. The parser
    handles all standard IRC message formats including server-to-client numerics
    and client-to-server commands.

    Args:
        line: str
            Raw IRC protocol line from the wire.
            Format: [:<prefix> ]<command>[ <middle params>][ :<trailing>][\r\n]
            - May include \r\n line terminator (will be stripped)
            - May be empty string or whitespace-only
            - Prefix (optional): Starts with ":", ends at first space
            - Command: First token after prefix (or first token if no prefix)
            - Middle params: Space-separated tokens
            - Trailing: Everything after " :" delimiter
            Examples:
                ":server 001 nick :Welcome message\r\n"
                "PRIVMSG #channel :Hello world"
                "JOIN #test"
                ""
            Constraints: No length limit enforced, but IRC spec suggests 512 bytes max.

    Returns:
        IRCMessage
            Parsed message with populated fields:
            - Empty line: IRCMessage(prefix=None, command="", params=[], trailing=None, raw="")
            - Prefix-only line (:prefix): IRCMessage(prefix="prefix", command="", params=[], trailing=None, raw=":prefix")
            - Normal message: IRCMessage with all applicable fields populated
            - command is always uppercased
            - params list includes trailing as last element if trailing is not None
            - raw field contains input with \r\n stripped
            Always returns IRCMessage; never returns None.

    Raises:
        No exceptions raised. Malformed input results in partially-populated
        IRCMessage (e.g., blank command for invalid messages).

    Data:
        Reads:
            - line parameter (immutable string, no external state)
        Writes: None
        Mutates: None (creates new objects only)

    Side effects:
        None. Pure function with no I/O, logging, or state modifications.

    Thread safety:
        Thread-safe. No shared state or mutations.

    Children:
        str.rstrip() - Removes \r\n line terminators
        str.startswith() - Checks for prefix indicator ":"
        str.find() - Locates space and trailing delimiter " :"
        str.lstrip() - Removes leading whitespace after prefix
        str.split() - Tokenizes command and middle params
        str.upper() - Uppercases command
        IRCMessage() - Constructs result dataclass

    Parents:
        IRC message handlers in csc-bridge
        IRC client/server protocol processing loops
        Unit tests for IRC parsing

    Logic table (input patterns -> output):
        "" -> IRCMessage(command="", params=[], raw="")
        "CMD" -> IRCMessage(command="CMD", params=[], raw="CMD")
        "CMD p1 p2" -> IRCMessage(command="CMD", params=["p1", "p2"], raw=...)
        "CMD :trailing" -> IRCMessage(command="CMD", params=["trailing"], trailing="trailing", raw=...)
        "CMD p1 :trailing" -> IRCMessage(command="CMD", params=["p1", "trailing"], trailing="trailing", raw=...)
        ":prefix CMD" -> IRCMessage(prefix="prefix", command="CMD", params=[], raw=...)
        ":prefix CMD :trailing" -> IRCMessage(prefix="prefix", command="CMD", params=["trailing"], trailing="trailing", raw=...)
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
    Builds an IRC wire-format string from message components.

    Serializes IRC message parts into RFC 1459/2812 compliant wire format. Handles
    prefix formatting, trailing parameter delimiter insertion, and automatic
    detection of when parameters need ":" prefix (parameters with spaces or
    leading colons).

    Args:
        prefix: Optional[str] = None
            Message source prefix to prepend.
            - None: No prefix in output (typical for client commands)
            - Non-None: Formatted as ":<prefix> " at start of message
            Examples:
                "csc-server" -> ":csc-server "
                "alice!~alice@host" -> ":alice!~alice@host "
            Constraints: Should not contain spaces (not enforced but will break protocol).

        command: str
            IRC command or numeric code.
            - Commands: Usually uppercase (e.g., "PRIVMSG", "JOIN")
            - Numerics: Three digits (e.g., "001", "332")
            Constraints: Required, must not be empty for valid IRC messages.
            Case is preserved (not modified by this function).

        params: Optional[List[str]] = None
            Middle parameters (not including trailing).
            - None: No parameters (treated as empty list)
            - Empty list: No parameters
            - Non-empty: Each param joined with spaces
            If trailing is None and params is provided, the last param gets ":"
            prefix automatically if it contains spaces or starts with ":".
            Examples:
                ["#channel"] -> "#channel"
                ["alice", "+i"] -> "alice +i"
            Constraints: Middle params should not contain spaces (will be auto-prefixed
            with ":" if last param and no trailing specified).

        trailing: Optional[str] = None
            Trailing parameter (free-form text after " :").
            - None: No explicit trailing (last param may be auto-prefixed)
            - Non-None: Appended as " :<trailing>" after all params
            May contain spaces, colons, any characters.
            Examples:
                "Hello world" -> " :Hello world"
                "" -> " :"
            Constraints: None.

    Returns:
        str
            RFC-compliant IRC wire-format message without \r\n terminator.
            Format: [:<prefix> ]<command>[ <params>][ :<trailing>]
            Examples:
                prefix=None, command="JOIN", params=["#test"], trailing=None
                    -> "JOIN #test"
                prefix="alice!a@h", command="PRIVMSG", params=["#chan"], trailing="hi"
                    -> ":alice!a@h PRIVMSG #chan :hi"
                prefix="server", command="001", params=["nick"], trailing="Welcome"
                    -> ":server 001 nick :Welcome"
                prefix=None, command="MODE", params=["alice", "+i"], trailing=None
                    -> "MODE alice +i"
            Never returns None. Returns command alone if all params are None/empty.

    Raises:
        No exceptions raised. All inputs accepted (even invalid ones).

    Data:
        Reads:
            - Function parameters (no external state)
        Writes: None
        Mutates: None (creates new strings only)

    Side effects:
        None. Pure function with no I/O, logging, or state modifications.

    Thread safety:
        Thread-safe. No shared state.

    Children:
        str.append() / list.append() - Builds parts list
        " ".join() - Joins parts into final message
        f-string formatting - Constructs prefix and trailing strings
        str.startswith() - Checks if param starts with ":"
        "in" operator - Checks if param contains space
        len() - Determines last param index
        enumerate() - Iterates params with index

    Parents:
        IRC message senders in csc-bridge
        numeric_reply() - Uses this to build numeric responses
        IRC server message formatting code
        Protocol handlers constructing outbound messages

    Logic table (trailing handling):
        trailing=None, params=None -> no params section
        trailing=None, params=[] -> no params section
        trailing=None, params=["p1"] -> " p1" (no colon unless p1 has space/colon)
        trailing=None, params=["p1 p2"] -> " :p1 p2" (auto-colon for space)
        trailing=None, params=["p1", "p2"] -> " p1 p2" (no colon if p2 no space)
        trailing="text", params=None -> " :text"
        trailing="text", params=[] -> " :text"
        trailing="text", params=["p1"] -> " p1 :text"
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
    Builds an IRC server numeric reply in standard format.

    Convenience function for constructing RFC 1459/2812 numeric replies sent from
    server to client. Formats as ":<server> <numeric> <nick> :<text>" where text
    is composed of multiple parts joined with spaces.

    Args:
        server_name: str
            Server hostname to use as message prefix.
            Examples:
                "csc-server"
                "irc.example.com"
            Constraints: Should be valid hostname, no spaces.

        numeric: str
            Three-digit RFC 2812 numeric reply code.
            Examples:
                "001" (RPL_WELCOME)
                "332" (RPL_TOPIC)
                "401" (ERR_NOSUCHNICK)
            Valid values: Any three-digit string from "000" to "999", typically
            from RFC 2812 numeric constants defined in this module.
            Constraints: Should be three digits for protocol compliance.

        target_nick: str
            Target user nickname (recipient of the numeric).
            Examples:
                "alice"
                "bob_123"
                "*" (for pre-registration numerics)
            Constraints: Should be valid IRC nickname or "*" for unregistered clients.

        *text_parts: str (variadic)
            Zero or more text fragments to join with spaces as the trailing parameter.
            - Zero parts: Empty trailing " :"
            - One part: That string as trailing
            - Multiple parts: Joined with single spaces
            Examples:
                ("Welcome to the network") -> ":Welcome to the network"
                ("Welcome", "to", "the", "network") -> ":Welcome to the network"
                () -> ":"
            Constraints: None. Any strings accepted.

    Returns:
        str
            Formatted IRC numeric reply without \r\n terminator.
            Format: ":<server_name> <numeric> <target_nick> :<joined_text>"
            Examples:
                server_name="csc-server", numeric="001", target_nick="alice",
                text_parts=("Welcome", "to", "IRC")
                    -> ":csc-server 001 alice :Welcome to IRC"
                server_name="csc-server", numeric="332", target_nick="bob",
                text_parts=("#test", "Channel topic here")
                    -> ":csc-server 332 bob :#test Channel topic here"
                server_name="csc-server", numeric="401", target_nick="alice",
                text_parts=()
                    -> ":csc-server 401 alice :"
            Never returns None.

    Raises:
        No exceptions raised. All inputs accepted.

    Data:
        Reads:
            - Function parameters only (no external state)
        Writes: None
        Mutates: None

    Side effects:
        None. Pure function with no I/O or state changes.

    Thread safety:
        Thread-safe. No shared state.

    Children:
        " ".join() - Joins text_parts into single string
        f-string formatting - Constructs final message

    Parents:
        IRC server numeric reply handlers
        Welcome sequence (001-004 replies)
        Error handlers (4xx/5xx replies)
        Query responses (WHOIS, LIST, NAMES, etc.)
        Any code sending RFC 2812 numeric replies to clients

    Logic table:
        text_parts=() -> ":<server> <num> <nick> :"
        text_parts=("a") -> ":<server> <num> <nick> :a"
        text_parts=("a", "b") -> ":<server> <num> <nick> :a b"
        text_parts=("a", "b", "c") -> ":<server> <num> <nick> :a b c"
    """
    text = " ".join(text_parts)
    return f":{server_name} {numeric} {target_nick} :{text}"
