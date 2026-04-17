"""
Control Plane for the Bridge Daemon.

Handles client authentication and acts as a mock IRC server in the LOBBY state.
"""

import hashlib
import threading
import time
from typing import Optional
from .irc_utils import parse_irc_message, numeric_reply, format_irc_message, SERVER_NAME
from .transports.tcp_outbound import TCPOutbound
from .transports.udp_outbound import UDPOutbound
from .irc_normalizer import IrcNormalizer

# Mock IRCd Constants
RPL_WELCOME = "001"
RPL_YOURHOST = "002"
RPL_CREATED = "003"
RPL_MYINFO = "004"
RPL_ISUPPORT = "005"
RPL_MOTDSTART = "375"
RPL_MOTD = "372"
RPL_ENDOFMOTD = "376"
ERR_PASSWDMISMATCH = "464"
ERR_NICKNAMEINUSE = "433"

MOTD_TEXT = """
Welcome to the CSC Bridge Daemon!
---------------------------------------
You are in the LOBBY. You are not connected to any server yet.

Commands:
  /trans connect <proto:enc:dialect:host:port>
  /trans history
  /trans fav <alias>
  /trans menu

Type '/trans menu' for more details.
"""

class ControlHandler:
    """
    Handles IRC protocol logic for clients in the LOBBY state.

    Responsibilities:
    - Initial Handshake (PASS/NICK/USER)
    - Authentication against BridgeData
    - Sending Mock 001-004 + MOTD
    - Handling PING/PONG while in Lobby
    - Handling /trans commands to initiate connections
    """

    def __init__(self, session, bridge):
        """
        Initializes the control handler, storing references to session and bridge, and setting up authentication state.

        Args:
            session: ClientSession object representing the client connection.
                Required attributes: session.session_id, session.client_id, session.inbound, session.nick.
            bridge: Bridge instance (daemon main object).
                Required attributes: bridge.data (BridgeData), bridge.get_lobby_sessions(),
                bridge._server_listener().

        Returns:
            None

        Raises:
            None

        Data:
            Writes: self.session - reference to ClientSession object.
            Writes: self.bridge - reference to Bridge daemon instance.
            Writes: self.buffer (str) - initialized to "" for buffering incomplete lines.
            Writes: self.username (Optional[str]) - initialized to None, set by USER command.
            Writes: self.password (Optional[str]) - initialized to None, set by PASS command.
            Writes: self.nick (Optional[str]) - initialized to None, set by NICK command.
            Writes: self.authenticated (bool) - initialized to False, set True after successful auth.

        Side effects:
            None (pure initialization, no I/O or network operations).

        Thread safety:
            Thread-safe for initialization. Each ControlHandler instance is tied to a single
            ClientSession and should not be shared across threads.

        Children:
            None (no method calls during initialization).

        Parents:
            - Bridge.handle_new_client(): Creates ControlHandler when client connects to lobby.
            - ClientSession initialization for LOBBY state.
        """
        self.session = session
        self.bridge = bridge
        self.buffer = ""
        self.username = None
        self.password = None
        self.nick = None
        self.authenticated = False

    def handle_line(self, line: bytes):
        """
        Processes a raw line from the client, handling authentication, keepalive, and control commands.

        Args:
            line (bytes): Raw IRC protocol line from client, including trailing \r\n.
                Valid values: Any byte sequence. Decoded as UTF-8 with error replacement.
                Format: IRC message like "NICK alice\r\n" or "PRIVMSG #lobby :hello\r\n"

        Returns:
            None

        Raises:
            None (decoding errors and parse errors handled gracefully).

        Data:
            Reads: self.authenticated - determines if /trans commands are allowed.
            Mutates: self.password - set by PASS command.
            Mutates: self.nick - set by NICK command.
            Mutates: self.username - set by USER command.
            Mutates: session.nick - updated when NICK command received.
            Does not mutate self.buffer (currently unused).

        Side effects:
            - Calls _try_auth() which may authenticate user and send welcome sequence.
            - Calls _handle_command() for /trans commands which may:
              - Query/display history and favorites.
              - Initiate upstream connections (network I/O).
              - Start listener threads.
            - Broadcasts PRIVMSG to lobby clients via _broadcast_lobby_message().
            - Sends PONG responses for PING keepalive.
            - Network I/O: Sends IRC messages to client via session.inbound.send_to_client().

        Thread safety:
            Not thread-safe if same session accessed from multiple threads.
            Each client should have dedicated thread calling handle_line().

        Logic table:
            Command         | Authenticated | Action
            ----------------|---------------|--------------------------------------------------
            PASS            | Any           | Store password, no immediate action
            NICK            | Any           | Store nick, update session.nick, try auth
            USER            | Any           | Store username, try auth
            PING            | Any           | Send PONG response
            QUIT            | Any           | No action (handled by disconnect handler)
            PRIVMSG /trans  | True          | Parse and execute /trans command
            PRIVMSG (other) | True          | Broadcast to other lobby clients
            PRIVMSG         | False         | Ignored (not authenticated)
            Other           | Any           | Ignored

        Children:
            - line.decode("utf-8", errors="ignore"): Decodes byte line to string.
            - parse_irc_message(text): Parses IRC message into IRCMessage object.
            - self._try_auth(): Attempts authentication if nick and username present.
            - self._handle_command(command_text): Processes /trans commands.
            - self._broadcast_lobby_message(message): Sends PRIVMSG to lobby clients.
            - self._send_raw(line): Sends raw IRC message to client (PONG responses).

        Parents:
            - Bridge.handle_lobby_client_data(): Calls this for each line from LOBBY client.
            - ClientSession event loop for LOBBY state.
        """
        try:
            text = line.decode("utf-8", errors="ignore")
        except (UnicodeDecodeError, AttributeError):
            return

        msg = parse_irc_message(text)
        cmd = msg.command.upper()

        # Check for /trans command if authenticated
        if self.authenticated:
            # Handle PRIVMSG to a service bot or just raw commands
            # Accept "/trans" in text, or just "trans" command if valid IRC?
            # Standard clients send "/trans" as "PRIVMSG <target> :/trans ..." usually.
            # Raw clients might just send "trans ...".

            command_text = None
            if cmd == "PRIVMSG":
                trailing = msg.params[-1] if len(msg.params) > 1 else ""
                if trailing.startswith("/trans ") or trailing.startswith("trans "):
                    command_text = trailing.lstrip("/").lstrip()
                else:
                    # Non-command PRIVMSG in lobby - broadcast to other lobby clients
                    self._broadcast_lobby_message(trailing)
                    return
            elif cmd == "TRANS": # Raw command
                # Reconstruct full line minus command
                # msg.params are split.
                command_text = "trans " + " ".join(msg.params)

            if command_text:
                self._handle_command(command_text)
                return

        if cmd == "PASS":
            self.password = msg.params[0] if msg.params else None

        elif cmd == "NICK":
            self.nick = msg.params[0] if msg.params else None
            self.session.nick = self.nick # Update session nick
            self._try_auth()

        elif cmd == "USER":
            self.username = msg.params[0] if msg.params else None
            self._try_auth()

        elif cmd == "PING":
            token = msg.params[0] if msg.params else ""
            self._send_raw(f"PONG :{token}\r\n")

        elif cmd == "QUIT":
            # Client disconnect
            pass # handled by disconnect handler

    def _handle_command(self, text):
        """
        Parses and executes /trans commands including connect, history, fav (favorite), and menu.

        Args:
            text (str): Full command text including the command name.
                Valid values: Strings starting with "trans " or "/trans ".
                Format: "trans <subcommand> [args...]"
                Examples: "trans connect tcp:none:rfc:irc.example.com:6667"
                          "trans history"
                          "trans fav myserver"
                          "trans menu"

        Returns:
            None

        Raises:
            None (errors handled gracefully by sending notices to client).

        Data:
            Reads: self.username - for querying history/favorites.
            Reads: self.bridge.data - for retrieving history and favorites.
            Mutates: self.session state when executing connect command:
                - session.outbound (Transport)
                - session.upstream_handle
                - session.normalizer (IrcNormalizer)
                - session.state (changed to "CONNECTED")

        Side effects:
            - Sends NOTICE messages to client for all command responses.
            - Network I/O for "connect" subcommand:
              - Creates TCP or UDP outbound connection to upstream server.
              - Starts listener thread for upstream data.
            - Disk I/O for "connect" subcommand:
              - Saves connection string to user's history via bridge.data.add_history().
            - Thread creation: Spawns daemon thread for upstream listener.

        Thread safety:
            Not thread-safe if same session accessed from multiple threads.
            Creates new thread for server listener which accesses session.

        Logic table (subcommands):
            Subcommand | Args                        | Action
            -----------|-----------------------------|-----------------------------------------
            connect    | proto:enc:dialect:host:port | Parse conn string, create transport, switch to CONNECTED
            history    | (none)                      | Display user's connection history (max 25 items)
            fav        | <alias>                     | Look up and connect to saved favorite
            menu       | (none)                      | Display MOTD_TEXT with available commands
            (unknown)  | (any)                       | Send error notice

        Children:
            - text.split(): Splits command into parts.
            - self.send_notice(message): Sends NOTICE to client.
            - self.bridge.data.get_history(username): Retrieves connection history.
            - self.bridge.data.get_favorite(username, alias): Retrieves favorite connection.
            - self._do_connect(conn_str): Establishes upstream connection.

        Parents:
            - self.handle_line(): Calls this when /trans command detected in PRIVMSG.
        """
        parts = text.split()
        if len(parts) < 2:
            self.send_notice("Usage: /trans <command> [args]")
            return

        subcmd = parts[1].lower()
        args = parts[2:]

        # Dispatch table for subcommands
        handlers = {
            "connect": self._subcmd_connect,
            "history": self._subcmd_history,
            "fav": self._subcmd_fav,
            "menu": self._subcmd_menu,
        }

        handler = handlers.get(subcmd)
        if handler:
            handler(args)
        else:
            self.send_notice(f"Unknown command: {subcmd}")

    def _subcmd_connect(self, args):
        """Handler for 'connect' subcommand."""
        if not args:
            self.send_notice("Usage: /trans connect <proto:enc:dialect:host:port>")
            return
        self._do_connect(args[0])

    def _subcmd_history(self, args):
        """Handler for 'history' subcommand."""
        hist = self.bridge.data.get_history(self.username)
        if not hist:
            self.send_notice("No history.")
        else:
            self.send_notice("-- History --")
            for i, item in enumerate(hist):
                self.send_notice(f"[{i+1}] {item}")

    def _subcmd_fav(self, args):
        """Handler for 'fav' subcommand."""
        if not args:
            self.send_notice("Usage: /trans fav <alias>")
            return
        conn_str = self.bridge.data.get_favorite(self.username, args[0])
        if conn_str:
            self._do_connect(conn_str)
        else:
            self.send_notice(f"Favorite '{args[0]}' not found.")

    def _subcmd_menu(self, args):
        """Handler for 'menu' subcommand."""
        for line in MOTD_TEXT.strip().split("\n"):
            self.send_notice(line)

    def _do_connect(self, conn_str):
        """
        Parse connection string and establish upstream connection.
        Format: proto:enc:dialect:host:port
        Example: udp:dh-aes:csc:127.0.0.1:9525
        """
        try:
            parts = conn_str.split(":")
            if len(parts) != 5:
                raise ValueError("Invalid format. Expected proto:enc:dialect:host:port")

            proto, enc, dialect, host, port = parts
            port = int(port)

            self.send_notice(f"Connecting to {host}:{port} ({proto.upper()})...")

            # 1. Create Outbound Transport using dispatch table
            transports = {
                "tcp": TCPOutbound,
                "udp": UDPOutbound,
            }
            transport_class = transports.get(proto.lower())
            if not transport_class:
                raise ValueError(f"Unknown protocol: {proto}")
            outbound = transport_class(host, port)

            # 2. Configure Normalizer using dispatch table
            dialect_modes = {
                "csc": "rfc_to_csc",
                "rfc": None,
            }
            norm_mode = dialect_modes.get(dialect.lower())
            if norm_mode is None and dialect.lower() not in dialect_modes:
                raise ValueError(f"Unknown dialect: {dialect}")

            # 3. Update Session
            self.session.outbound = outbound
            self.session.upstream_handle = outbound.create_upstream(self.session.session_id)

            if norm_mode:
                self.session.normalizer = IrcNormalizer(norm_mode)
            else:
                self.session.normalizer = None

            # 4. Save to History
            self.bridge.data.add_history(self.username, conn_str)

            # 5. Start listener thread FIRST (must receive DHREPLY)
            threading.Thread(
                target=self.bridge._server_listener,
                args=(self.session,),
                daemon=True,
                name=f"upstream-{self.session.session_id[:8]}",
            ).start()

            # 6. Apply encryption based on enc parameter
            enc_lower = enc.lower()
            if enc_lower in ("dh-aes", "dh", "rsa"):
                dh = self.session.crypto.start_dh()
                init_msg = dh.format_init_message().encode("utf-8")
                self.session.outbound.send(self.session.upstream_handle, init_msg)
                self.send_notice("Negotiating encryption...")
                if not self.session.crypto.wait_until_ready(timeout=5.0):
                    self.send_notice("Encryption handshake timed out")
                    return
                self.send_notice("Encryption established.")
            elif enc_lower.startswith("psk"):
                psk_parts = enc.split("-", 1)
                if len(psk_parts) == 2 and psk_parts[1]:
                    self.session.crypto.set_key(
                        hashlib.sha256(psk_parts[1].encode()).digest()
                    )
                else:
                    self.send_notice("PSK mode requires a key: psk-<key>")
                    return
            # "none" = no encryption, crypto stays NONE

            # 7. Switch state AFTER crypto is ready
            self.session.state = "CONNECTED"
            self.send_notice("Connected! Switching to proxy mode.")

        except Exception as e:
            self.send_notice(f"Connection failed: {e}")
            # If we created outbound but failed to connect, clean up?
            # Outbound create_upstream raises exception on fail usually.

    def _try_auth(self):
        """
        Attempts authentication once both nick and username are provided, validating against BridgeData.

        Args:
            None (operates on instance state: self.nick, self.username, self.password)

        Returns:
            None

        Raises:
            None (authentication failures handled by sending ERR_PASSWDMISMATCH).

        Data:
            Reads: self.nick - nickname provided by NICK command.
            Reads: self.username - username provided by USER command.
            Reads: self.password - password provided by PASS command (or None).
            Reads: self.bridge.data.get_data("users") - checks if user database is empty.
            Mutates: self.authenticated - set to True on successful authentication.
            Mutates: self.bridge.data - may create "admin" user if database is empty.

        Side effects:
            - Validates credentials via bridge.data.validate_user().
            - Auto-creates "admin" user if database is empty and username is "admin".
            - Sends welcome sequence (001-005 + MOTD) on successful authentication.
            - Sends ERR_PASSWDMISMATCH (464) on failed authentication.
            - Network I/O: Sends IRC messages to client via session.inbound.send_to_client().

        Thread safety:
            Not thread-safe. The auto-creation of "admin" user has a race condition:
            multiple concurrent connections could all see empty DB and try to create admin.
            Expected to be called during initial handshake before concurrent access.

        Logic table:
            Condition                                        | Action
            -------------------------------------------------|----------------------------------
            nick or username not set                         | Return immediately (wait for both)
            Valid credentials in database                    | Authenticate, send welcome
            Invalid credentials, non-empty database          | Send ERR_PASSWDMISMATCH
            Invalid credentials, empty DB, username="admin"  | Create admin, authenticate, send welcome
            Invalid credentials, empty DB, username!="admin" | Send ERR_PASSWDMISMATCH

        Children:
            - self.bridge.data.validate_user(username, password): Validates credentials.
            - self.bridge.data.get_data("users"): Checks if user database is empty.
            - self.bridge.data.create_user("admin", password): Auto-creates admin user.
            - self._send_welcome(): Sends IRC welcome sequence.
            - self._send_numeric(ERR_PASSWDMISMATCH, text): Sends password error.

        Parents:
            - self.handle_line(): Calls this after NICK or USER command received.
        """
        if not (self.nick and self.username):
            return
        
        # If no password provided yet, wait (some clients send NICK/USER then PASS?)
        # Actually standard is PASS then NICK/USER.
        # If we have NICK and USER, we proceed.

        # Check against BridgeData
        # Using self.username as the login handle
        
        if self.bridge.data.validate_user(self.username, self.password or ""):
            self.authenticated = True
            self._send_welcome()
        else:
            # For now, if no users exist, maybe auto-create first user?
            # Or just fail.
            # Let's implement a "default" bypass for now if DB is empty?
            # No, strict auth.
            
            # Allow "admin" / "admin" if DB is empty for bootstrapping?
            users = self.bridge.data.get_data("users")
            if not users and self.username == "admin":
                self.bridge.data.create_user("admin", self.password or "admin")
                self.authenticated = True
                self._send_welcome()
                return

            self._send_numeric(ERR_PASSWDMISMATCH, "Password incorrect")
            # Close connection?
            # self.session.inbound.remove_client(self.session.client_id)

    def _send_welcome(self):
        """
        Sends the full IRC welcome sequence including 001-005 and MOTD to the authenticated client.

        Args:
            None (operates on instance state: self.nick)

        Returns:
            None

        Raises:
            None (errors from transport layer may propagate).

        Data:
            Reads: self.nick - used as target for numeric replies and in welcome message.
            Does not mutate any state.

        Side effects:
            - Network I/O: Sends multiple IRC numeric replies to client via session.inbound.send_to_client().
            - Message sequence sent:
              001 (RPL_WELCOME): "Welcome to CSC Bridge Daemon <nick>"
              002 (RPL_YOURHOST): "Your host is <SERVER_NAME>, running csc-bridge"
              003 (RPL_CREATED): "This server was created today"
              004 (RPL_MYINFO): "<SERVER_NAME> csc-trans o o"
              005 (RPL_ISUPPORT): "CHANTYPES=# NETWORK=CSC-BNC :are supported"
              375 (RPL_MOTDSTART): "- <SERVER_NAME> Message of the Day -"
              372 (RPL_MOTD): "- <line>" (for each line in MOTD_TEXT)
              376 (RPL_ENDOFMOTD): "End of /MOTD command"

        Thread safety:
            Thread-safe if session.inbound transport is thread-safe.
            No shared state mutation in handler instance.

        Children:
            - self._send_numeric(numeric, text): Sends each numeric reply.
            - MOTD_TEXT.strip().split("\n"): Splits MOTD into lines for iteration.

        Parents:
            - self._try_auth(): Calls this after successful authentication.
        """
        nick = self.nick
        self._send_numeric(RPL_WELCOME, f"Welcome to CSC Bridge Daemon {nick}")
        self._send_numeric(RPL_YOURHOST, f"Your host is {SERVER_NAME}, running csc-bridge")
        self._send_numeric(RPL_CREATED, "This server was created today")
        self._send_numeric(RPL_MYINFO, f"{SERVER_NAME} csc-trans o o")
        self._send_numeric(RPL_ISUPPORT, "CHANTYPES=# NETWORK=CSC-BNC :are supported")

        self._send_numeric(RPL_MOTDSTART, f"- {SERVER_NAME} Message of the Day -")
        for line in MOTD_TEXT.strip().split("\n"):
            self._send_numeric(RPL_MOTD, f"- {line}")
        self._send_numeric(RPL_ENDOFMOTD, "End of /MOTD command")

    def _send_numeric(self, numeric, text):
        """
        Send a numeric IRC reply to the current client.

        Args:
            numeric (str): Three-digit IRC numeric code (e.g. "001", "375", "422").
            text (str): The trailing text for the numeric reply.

        Returns:
            None

        Data:
            Reads self.nick (str|None), falls back to "*" if unset.

        Side effects:
            Sends encoded bytes to client via _send_raw().

        Children:
            numeric_reply(), self._send_raw()

        Parents:
            Called by _send_welcome() for the welcome/MOTD sequence.
        """
        target = self.nick or "*"
        line = numeric_reply(SERVER_NAME, numeric, target, text) + "\r\n"
        self._send_raw(line)

    def send_notice(self, text):
        """
        Send an IRC NOTICE message to the current client.

        Args:
            text (str): The notice text to send.

        Returns:
            None

        Data:
            Reads self.nick (str|None), falls back to "*" if unset.

        Side effects:
            Sends encoded bytes to client via _send_raw().

        Children:
            self._send_raw()

        Parents:
            Called by handle_line(), _handle_command(), _try_auth(),
            and bridge.py for user-facing status messages.
        """
        target = self.nick or "*"
        line = f":{SERVER_NAME} NOTICE {target} :{text}\r\n"
        self._send_raw(line)

    def _send_raw(self, line):
        """
        Send a raw IRC line to the client over the inbound transport.

        Args:
            line (str): Complete IRC line including trailing CRLF.
                Will be UTF-8 encoded before sending.

        Returns:
            None

        Data:
            Reads self.session.inbound (transport instance),
            self.session.client_id (transport-specific client identifier).

        Side effects:
            Sends UTF-8 encoded bytes via session.inbound.send_to_client().
            No-op if session.inbound is None (disconnected client).

        Children:
            self.session.inbound.send_to_client()

        Parents:
            Called by _send_numeric(), send_notice().
        """
        if self.session.inbound:
            self.session.inbound.send_to_client(self.session.client_id, line.encode("utf-8"))

    def _broadcast_lobby_message(self, message: str):
        """
        Broadcast a chat message to all other clients in the lobby.

        Args:
            message: The chat message text (without command prefix).
        """
        if not message.strip():
            # Ignore empty messages
            return

        sender_nick = self.nick or self.username or "Unknown"
        formatted_msg = f"<{sender_nick}> {message}"

        # Get all lobby sessions from the bridge
        lobby_sessions = self.bridge.get_lobby_sessions()

        for session in lobby_sessions:
            # Don't send back to sender
            if session.session_id == self.session.session_id:
                continue

            # Send as PRIVMSG from the bridge server
            privmsg_line = f":{SERVER_NAME} PRIVMSG {session.nick or '*'} :{formatted_msg}\r\n"
            if session.inbound:
                try:
                    session.inbound.send_to_client(session.client_id, privmsg_line.encode("utf-8"))
                except OSError:
                    # Silently ignore send errors
                    pass
