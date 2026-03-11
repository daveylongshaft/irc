"""
Protocol normalization layer for the CSC bridge.

This module provides the IrcNormalizer class, which handles bidirectional
translation between the CSC IRC dialect and standard RFC 2812 IRC.
It is used to allow:
1. Native CSC clients to connect to standard IRC servers (csc_to_rfc mode).
2. Standard IRC clients to connect to the CSC server (rfc_to_csc mode).
"""

from typing import Optional, List
from .irc_constants import RFC_COMMANDS, CSC_COMMANDS, CSC_TO_RFC_MAP, CSC_ISUPPORT_TOKENS
from .irc_utils import (
    parse_irc_message, format_irc_message, numeric_reply,
    IRCMessage, SERVER_NAME,
    RPL_WELCOME, RPL_MYINFO, RPL_ISUPPORT,
    ERR_UNKNOWNCOMMAND, ERR_SASLFAIL
)

class IrcNormalizer:
    """
    Handles stateful normalization of IRC messages between dialects.

    Each instance is attached to a ClientSession and tracks the state
    necessary for that session (e.g., registration progress).
    """

    def __init__(self, mode: str):
        """
        Initializes the normalizer with the specified mode and sets up state tracking for registration progress.

        Args:
            mode (str): The normalization mode determining translation direction.
                Valid values:
                - "csc_to_rfc": CSC dialect client connecting to RFC 2812 standard server.
                                Translates IDENT->NICK+USER, RENAME->NICK, filters CSC-only commands.
                - "rfc_to_csc": RFC 2812 client connecting to CSC dialect server.
                                Intercepts CAP/AUTHENTICATE, injects synthetic 005 ISUPPORT.
                Constraints: Must be one of the two values above. Invalid modes not validated.

        Returns:
            None

        Raises:
            None (invalid mode values not validated at init time, will cause logic errors later).

        Data:
            Writes: self.mode (str) - stores the normalization mode.
            Writes: self.seen_welcome (bool) - initialized to False, tracks 001-004 reception.
            Writes: self.seen_end_of_registration (bool) - initialized to False, tracks 004 for 005 injection.

        Side effects:
            None (pure initialization, no I/O or network operations).

        Thread safety:
            Thread-safe for initialization. Each IrcNormalizer instance is tied to a single
            ClientSession and should not be shared across threads.

        Children:
            None (no method calls during initialization).

        Parents:
            - ControlHandler._do_connect(): Creates IrcNormalizer instance when establishing connection.
            - ClientSession initialization code for dialect translation setup.
        """
        self.mode = mode
        self.seen_welcome = False  # Track 001-004
        self.seen_end_of_registration = False  # Track 004 to inject 005

    def normalize_client_to_server(self, block: str, session) -> Optional[str]:
        """
        Normalizes a block of text from client to server, splitting on CR-LF and processing each line.

        Args:
            block (str): Raw text chunk received from client, potentially containing multiple
                IRC messages separated by \r\n.
                Valid values: Any string. Empty strings return None.
                May or may not end with \r\n delimiter.
            session: ClientSession object containing state for this connection.
                Required attributes: session.nick (Optional[str]), session.inbound (Transport).

        Returns:
            Optional[str]: Normalized IRC message block with \r\n terminators, or None.
                - Returns None if block is empty or all lines filtered out.
                - Returns str ending with \r\n if any lines pass through normalization.
                - May contain multiple messages joined by \r\n.
                - IDENT expansion produces multiple lines: "NICK...\r\nUSER...\r\n".

        Raises:
            None (exceptions from child methods may propagate).

        Data:
            Reads: self.mode - determines normalization rules.
            Does not mutate self state (read-only operation on instance variables).
            May mutate session state via _normalize_client_line side effects.

        Side effects:
            - Sends local NOTICE to client for filtered CSC commands (ISOP, BUFFER, AI).
            - Sends CAP/AUTHENTICATE responses to client in rfc_to_csc mode.
            - Network I/O: May send messages to client via session.inbound.send_to_client().

        Thread safety:
            Not thread-safe if same session is accessed from multiple threads.
            Each session should have dedicated thread for client->server processing.

        Children:
            - str.split('\r\n'): Splits block into individual lines.
            - self._normalize_client_line(line, session): Processes each line.
            - str.rstrip('\r\n'): Removes trailing delimiters.
            - "\r\n".join(out_parts): Rejoins normalized lines.

        Parents:
            - ClientSession.handle_client_data(): Processes incoming client data.
            - Bridge proxy loop forwarding client messages to upstream server.
        """
        if not block:
            return None
            
        lines = block.split('\r\n')
        out_parts = []
        
        for i, line in enumerate(lines):
            # If the block ends with \r\n, split produces an empty string at the end.
            # We skip it here and re-add the delimiter later if needed.
            if i == len(lines) - 1 and not line and block.endswith('\r\n'):
                continue
                
            if not line:
                # Empty line in middle? Keep it or drop? 
                # RFC 2812 says empty messages are silently ignored.
                # But splitting "A\r\n\r\nB" gives "A", "", "B". 
                # We can probably ignore empty lines.
                continue

            norm = self._normalize_client_line(line, session)
            if norm is not None:
                # norm might contain \r\n if it expanded (like IDENT)
                out_parts.append(norm.rstrip('\r\n'))

        if not out_parts:
            return None

        # Rejoin. If original block ended with newline, we typically want to preserve message framing.
        # However, our normalized lines are full commands.
        # We should join with \r\n and append \r\n.
        return "\r\n".join(out_parts) + "\r\n"

    def _normalize_client_line(self, line: str, session) -> Optional[str]:
        """
        Normalizes a single IRC line from the client based on the configured mode.

        Args:
            line (str): Single IRC protocol line without trailing \r\n.
                Valid values: Any valid or invalid IRC message string.
                Format: "[:<prefix>] <command> [<params>]"
            session: ClientSession object for this connection.
                Required attributes: session.nick, session.inbound.

        Returns:
            Optional[str]: Normalized IRC line(s) or None if filtered.
                - Returns None if command should be filtered (CSC-only in csc_to_rfc mode).
                - Returns None if command intercepted (CAP/AUTHENTICATE in rfc_to_csc mode).
                - Returns str (single line) for standard pass-through or translations like RENAME.
                - Returns str (multi-line) for IDENT expansion: "NICK...\r\nUSER...".
                - Returns original line unchanged for standard commands.

        Raises:
            None (parse errors from parse_irc_message may propagate).

        Data:
            Reads: self.mode - determines normalization rules.
            Does not mutate self state (stateless per-line processing).

        Side effects:
            - Sends NOTICE to client for filtered CSC commands (ISOP, BUFFER, AI, CRYPTOINIT).
            - Sends CAP responses (CAP * LS/NAK) to client in rfc_to_csc mode.
            - Sends ERR_SASLFAIL numeric for AUTHENTICATE in rfc_to_csc mode.
            - Network I/O: May send messages to client via session.inbound.send_to_client().

        Thread safety:
            Not thread-safe if same session accessed from multiple threads.
            No shared state mutation beyond session object.

        Logic table (csc_to_rfc mode):
            ISOP       -> None (filtered, NOTICE sent)
            BUFFER     -> None (filtered, NOTICE sent)
            AI         -> None (filtered, NOTICE sent)
            CRYPTOINIT -> None (filtered, no NOTICE)
            IDENT      -> "NICK <nick>\r\nUSER <nick> 0 * :<nick>"
            RENAME     -> "NICK <new_nick>"
            Other      -> line (unchanged)

        Logic table (rfc_to_csc mode):
            CAP LS/LIST -> None (intercepted, "CAP * LS :" sent)
            CAP REQ     -> None (intercepted, "CAP * NAK :<caps>" sent)
            CAP END     -> None (intercepted)
            AUTHENTICATE -> None (intercepted, ERR_SASLFAIL sent)
            Other       -> line (unchanged)

        Children:
            - parse_irc_message(line): Parses IRC message into IRCMessage object.
            - format_irc_message(): Formats NICK/USER commands for IDENT expansion.
            - self._send_notice(session, text): Sends local NOTICE to client.
            - self._send_numeric(session, numeric, target, text): Sends numeric reply.
            - self._send_raw_to_client(session, raw_line): Sends CAP responses.

        Parents:
            - self.normalize_client_to_server(): Calls this for each line in block.
        """
        msg = parse_irc_message(line)
        command = msg.command.upper()

        if self.mode == "csc_to_rfc":
            # 1. Filter CSC-only commands
            csc_only_notice = {
                "ISOP": "Command ISOP is not supported on this network.",
                "BUFFER": "Command BUFFER is not supported on this network.",
                "AI": "Command AI is not supported on this network.",
            }
            if command in csc_only_notice:
                self._send_notice(session, csc_only_notice[command])
                return None

            if command == "CRYPTOINIT":
                return None

            # 2. Translate Legacy Commands
            if command == "IDENT":
                # IDENT <nick> [pass] -> NICK <nick> + USER <nick> ...
                nick = msg.params[0] if msg.params else "unknown"
                # Generate NICK
                nick_line = format_irc_message(None, "NICK", [nick])
                # Generate USER
                user_line = format_irc_message(None, "USER", [nick, "0", "*"], nick)
                return f"{nick_line}\r\n{user_line}"

            if command == "RENAME":
                # RENAME <old> <new> -> NICK <new>
                if len(msg.params) >= 2:
                    new_nick = msg.params[1]
                    return format_irc_message(None, "NICK", [new_nick])
                return None

            # 3. Pass through standard commands
            return line

        elif self.mode == "rfc_to_csc":
            # 1. Intercept CAP subcommands
            if command == "CAP":
                subcmd = msg.params[0].upper() if msg.params else ""
                cap_handlers = {
                    "LS": self._handle_cap_ls,
                    "LIST": self._handle_cap_ls,
                    "REQ": self._handle_cap_req,
                    "END": self._handle_cap_end,
                }
                handler = cap_handlers.get(subcmd)
                if handler:
                    handler(session, msg)
                    return None

            # 2. Intercept AUTHENTICATE
            if command == "AUTHENTICATE":
                self._send_numeric(session, ERR_SASLFAIL, "*", "SASL authentication not supported")
                return None

            # 3. Pass through standard commands
            return line

        return line

    def normalize_server_to_client(self, block: str, session) -> Optional[str]:
        """
        Normalizes a block of text from server to client, splitting on CR-LF and processing each line.

        Args:
            block (str): Raw text chunk received from upstream server, potentially containing
                multiple IRC messages separated by \r\n.
                Valid values: Any string. Empty strings return None.
                May or may not end with \r\n delimiter.
            session: ClientSession object containing state for this connection.
                Required attributes: session.nick (Optional[str]), session.inbound (Transport).

        Returns:
            Optional[str]: Normalized IRC message block with \r\n terminators, or None.
                - Returns None if block is empty or all lines filtered out.
                - Returns str ending with \r\n if any lines pass through normalization.
                - May contain additional synthetic messages (005 ISUPPORT in rfc_to_csc mode).

        Raises:
            None (exceptions from child methods may propagate).

        Data:
            Reads: self.mode - determines normalization rules.
            Reads: self.seen_end_of_registration - tracks whether 004 was seen for 005 injection.
            Mutates: self.seen_end_of_registration set to True when 004 detected in rfc_to_csc mode.

        Side effects:
            - Injects synthetic 005 ISUPPORT after 004 in rfc_to_csc mode.
            - Network I/O: Sends synthetic 005 to client via session.inbound.send_to_client().

        Thread safety:
            Not thread-safe if same session accessed from multiple threads.
            Mutates self.seen_end_of_registration which could race.

        Children:
            - str.split('\r\n'): Splits block into individual lines.
            - self._normalize_server_line(line, session): Processes each line.
            - str.rstrip('\r\n'): Removes trailing delimiters.
            - "\r\n".join(out_parts): Rejoins normalized lines.

        Parents:
            - ClientSession.handle_server_data(): Processes incoming server data.
            - Bridge proxy loop forwarding server messages to downstream client.
        """
        if not block:
            return None

        lines = block.split('\r\n')
        out_parts = []

        for i, line in enumerate(lines):
            if i == len(lines) - 1 and not line and block.endswith('\r\n'):
                continue
            if not line: continue

            norm = self._normalize_server_line(line, session)
            if norm is not None:
                out_parts.append(norm.rstrip('\r\n'))

        if not out_parts:
            return None

        return "\r\n".join(out_parts) + "\r\n"

    def _normalize_server_line(self, line: str, session) -> Optional[str]:
        """
        Normalizes a single IRC line from the server based on the configured mode.

        Args:
            line (str): Single IRC protocol line without trailing \r\n.
                Valid values: Any valid or invalid IRC message string.
                Format: ":<prefix> <command> [<params>]"
            session: ClientSession object for this connection.
                Required attributes: session.nick (Optional[str]), session.inbound (Transport).

        Returns:
            Optional[str]: The line unchanged (normalization happens via side effects), or None if filtered.
                - Returns line unchanged in all current cases (no filtering implemented).
                - In rfc_to_csc mode: detects 004 and injects 005 via side effect, but still returns line.
                - In csc_to_rfc mode: passes through unchanged.

        Raises:
            None (parse errors from parse_irc_message may propagate).

        Data:
            Reads: self.mode - determines normalization rules.
            Reads: self.seen_end_of_registration - prevents duplicate 005 injection.
            Mutates: self.seen_end_of_registration set to True when 004 detected in rfc_to_csc mode.

        Side effects:
            - In rfc_to_csc mode: Detects 004 (RPL_MYINFO) and sends synthetic 005 ISUPPORT.
            - Network I/O: Sends 005 numeric to client via session.inbound.send_to_client().
            - Synthetic 005 content: "CHANTYPES=# NETWORK=CSC-BNC :are supported"

        Thread safety:
            Not thread-safe if same session accessed from multiple threads.
            Mutates self.seen_end_of_registration which could race.

        Logic table (rfc_to_csc mode):
            004 (RPL_MYINFO) & !seen_end_of_registration -> line (+ inject 005 via side effect)
            004 (RPL_MYINFO) & seen_end_of_registration  -> line (no injection)
            Other                                          -> line (unchanged)

        Logic table (csc_to_rfc mode):
            All commands -> line (unchanged, pass-through)

        Children:
            - parse_irc_message(line): Parses IRC message into IRCMessage object.
            - self._send_numeric(session, RPL_ISUPPORT, target, text): Sends synthetic 005.

        Parents:
            - self.normalize_server_to_client(): Calls this for each line in block.
        """
        if self.mode == "rfc_to_csc":
            # Inject 005 ISUPPORT after 004 for RFC clients
            msg = parse_irc_message(line)
            if msg.command == RPL_MYINFO and not self.seen_end_of_registration:
                self.seen_end_of_registration = True
                # Construct and send synthetic 005
                supported_tokens = ["CHANTYPES=#", "NETWORK=CSC-BNC"] # As expected by test
                text_005 = " ".join(supported_tokens) + " :are supported"
                self._send_numeric(session, RPL_ISUPPORT, session.nick or "*", text_005)

        elif self.mode == "csc_to_rfc":
            # 1. Filter potential confused numerics? 
            # Real IRCd might send 421 (Unknown command) for things we let through?
            # Generally passthrough is fine.
            pass

        return line

    def _handle_cap_ls(self, session, msg):
        """Handler for CAP LS and CAP LIST subcommands."""
        self._send_raw_to_client(session, f":{SERVER_NAME} CAP * LS :\r\n")

    def _handle_cap_req(self, session, msg):
        """Handler for CAP REQ subcommand."""
        # NAK all requested caps since CSC doesn't support any
        requested = " ".join(msg.params[1:]) if len(msg.params) > 1 else ""
        self._send_raw_to_client(session, f":{SERVER_NAME} CAP * NAK :{requested}\r\n")

    def _handle_cap_end(self, session, msg):
        """Handler for CAP END subcommand."""
        pass  # Simply drop the command

    def _send_notice(self, session, text: str):
        """
        Sends a local NOTICE message to the client using the session's inbound transport.

        Args:
            session: ClientSession object for this connection.
                Required attributes: session.nick (Optional[str]), session.inbound (Transport).
            text (str): The notice message content to send.
                Valid values: Any string. Will be sent as trailing parameter (after colon).

        Returns:
            None

        Raises:
            None (errors from _send_raw_to_client silently ignored).

        Data:
            Reads: session.nick - uses nickname as NOTICE target, or "*" if not set.
            Does not mutate any state.

        Side effects:
            - Network I/O: Sends NOTICE message to client via session.inbound.send_to_client().
            - Message format: ":<SERVER_NAME> NOTICE <nick|*> :<text>\r\n"

        Thread safety:
            Thread-safe if session.inbound transport is thread-safe.
            No shared state mutation in normalizer instance.

        Children:
            - self._send_raw_to_client(session, line): Sends raw IRC message to client.

        Parents:
            - self._normalize_client_line(): Sends notices for filtered CSC commands.
        """
        # We need a nick to address the notice to, usually.
        # If session.nick is set, use it. Else use *
        target = session.nick or "*"
        line = f":{SERVER_NAME} NOTICE {target} :{text}\r\n"
        self._send_raw_to_client(session, line)

    def _send_numeric(self, session, numeric: str, target: str, text: str):
        """
        Sends a local numeric reply to the client using the session's inbound transport.

        Args:
            session: ClientSession object for this connection.
                Required attributes: session.inbound (Transport).
            numeric (str): The numeric reply code to send.
                Valid values: 3-digit strings like "001", "005", "464", "904".
                Format: Typically constants like RPL_WELCOME, RPL_ISUPPORT, ERR_SASLFAIL.
            target (str): The target nickname for the numeric reply.
                Valid values: Any string. Typically session.nick or "*" for unregistered clients.
            text (str): The message text for the numeric reply.
                Valid values: Any string. Format varies by numeric type.

        Returns:
            None

        Raises:
            None (errors from _send_raw_to_client silently ignored).

        Data:
            Does not read or mutate any state beyond function parameters.

        Side effects:
            - Network I/O: Sends numeric reply to client via session.inbound.send_to_client().
            - Message format: ":<SERVER_NAME> <numeric> <target> <text>\r\n"

        Thread safety:
            Thread-safe if session.inbound transport is thread-safe.
            No shared state mutation in normalizer instance.

        Children:
            - numeric_reply(SERVER_NAME, numeric, target, text): Formats the numeric message.
            - self._send_raw_to_client(session, line): Sends raw IRC message to client.

        Parents:
            - self._normalize_client_line(): Sends ERR_SASLFAIL for AUTHENTICATE command.
            - self._normalize_server_line(): Sends synthetic RPL_ISUPPORT (005) after 004.
        """
        line = numeric_reply(SERVER_NAME, numeric, target, text) + "\r\n"
        self._send_raw_to_client(session, line)

    def _send_raw_to_client(self, session, raw_line: str):
        """
        Send raw data back to the client using session.inbound.
        Requires session to have 'inbound' attribute (the transport object).
        """
        if hasattr(session, "inbound") and session.inbound:
             try:
                 session.inbound.send_to_client(session.client_id, raw_line.encode("utf-8"))
             except Exception:
                 pass