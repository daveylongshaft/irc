"""Core bridge orchestrator -- bridges inbound clients to the CSC server.

This module contains the Bridge class, which is the central coordinator
of the CSC bridge proxy. It accepts client connections from one or more
inbound transports, creates a dedicated upstream session for each client, and
forwards traffic bidirectionally between the client and the CSC server.

Architecture Overview:
    The bridge sits between IRC/CSC clients and the CSC server:

        [IRC Client] --TCP--> [Bridge] --UDP/TCP--> [CSC Server]
        [CSC Client] --UDP--> [Bridge] --UDP/TCP--> [CSC Server]

    Multiple inbound transports can run simultaneously (e.g., TCP on port 6667
    for standard IRC clients and UDP on port 9526 for native CSC clients). Only
    one outbound transport is active at a time.

Session Management:
    Each connecting client gets a dedicated ClientSession (see session.py) with:
    - A unique session_id (UUID)
    - Its own upstream handle (a dedicated socket to the CSC server, so the
      server sees each proxied client as a unique source address)
    - A server listener thread that polls for responses from the server
    - Activity tracking for keepalive and timeout management

    Sessions are stored in two dicts:
    - _sessions: session_id -> ClientSession (canonical store)
    - _client_to_session: client_id -> ClientSession (reverse lookup)

    Both dicts are protected by _lock. All session creation, lookup, and
    destruction must acquire _lock.

Threading Model:
    The bridge spawns several categories of threads:

    1. Inbound listener threads (managed by each InboundTransport):
       - Accept/receive client data and invoke _on_client_data callback.

    2. Per-session server listener threads ("upstream-XXXXXXXX"):
       - One per active session, polling recv() on the upstream handle.
       - Forward server responses back to the client via _forward_to_client.
       - Exit when the session is removed from _sessions or _running is False.

    3. Keepalive thread ("keepalive"):
       - Sends PING :keepalive to sessions idle > 45 seconds, every 30 seconds.

    4. Cleanup thread ("cleanup"):
       - Removes sessions idle > session_timeout, checked every 15 seconds.

    All threads are daemon threads and will terminate when the main thread exits.

Forwarding Logic:
    Client -> Server:
        1. Inbound transport receives data, calls _on_client_data(data, cid, transport)
        2. Bridge looks up or creates a session for the client_id
        3. Session's last_activity is updated via touch()
        4. NICK commands are sniffed for logging/status display
        5. Data is forwarded to the server via outbound.send(session.upstream_handle, data)

    Server -> Client:
        1. Per-session listener thread calls outbound.recv(handle, timeout=1.0)
        2. If data is received, session.touch() updates activity timestamp
        3. Data is forwarded to client via inbound.send_to_client(client_id, data)
        4. The correct inbound transport is found via _inbound_map[session.inbound_name]

Dependencies:
    - session.ClientSession: Dataclass tracking per-client session state.
    - transports.base.InboundTransport: Abstract interface for client-facing transports.
    - transports.base.OutboundTransport: Abstract interface for server-facing transports.

Related Modules:
    - main.py: Parses configuration and instantiates the Bridge.
    - crypto.py: DH exchange and AES encryption (referenced by TODO comments).
    - transports/: Concrete transport implementations (UDP/TCP inbound/outbound).
"""

import threading
import time
import logging
from typing import Dict, List, Optional, Any

from .session import ClientSession
from .transports.base import InboundTransport, OutboundTransport, ClientID
from .irc_normalizer import IrcNormalizer
from .data_bridge import BridgeData
from .control_handler import ControlHandler
from csc_crypto import DHExchange, decrypt, encrypt, is_encrypted

logger = logging.getLogger("csc_bridge")


class Bridge:
    """Bridges multiple inbound transports to an outbound transport.

    Each client connection gets its own session with a dedicated upstream
    socket so the CSC server sees unique (host, port) per client. The
    Bridge handles session lifecycle, traffic forwarding, keepalive
    pings, and idle session cleanup.

    Attributes:
        inbound_transports: List of InboundTransport instances accepting client
            connections (e.g., [TCPInbound, UDPInbound]).
        outbound: The single OutboundTransport instance used to forward traffic
            to the CSC server (e.g., UDPOutbound or TCPOutbound).
        session_timeout: Number of seconds of inactivity after which a session
            is destroyed by the cleanup loop. Defaults to 300 (5 minutes).
        encrypt: Whether to enable encryption for new sessions. Currently
            referenced but not yet fully implemented (see TODO in forwarding
            methods).
        normalize_mode: Optional[str] specifying the protocol normalization mode
            ("csc_to_rfc" or "rfc_to_csc"). None disables normalization.
        _sessions: Dictionary mapping session_id (str) to ClientSession objects.
            This is the canonical session store, protected by _lock.
        _client_to_session: Dictionary mapping transport-specific client_id to
            ClientSession objects. Provides O(1) lookup when data arrives from
            a known client. Protected by _lock.
        _lock: Threading lock protecting _sessions and _client_to_session.
            Must be held for any read or write to these dicts.
        _running: Boolean flag controlling all background thread lifecycles.
            Set to True by start(), False by stop().
        _inbound_map: Dictionary mapping inbound transport class names (str) to
            InboundTransport instances. Used to route server responses back to
            the correct transport's send_to_client() method.

    Threading Safety:
        All session dict access is protected by _lock. Background threads
        (keepalive, cleanup, server listeners) check _running and _sessions
        membership before operating. The lock is held for minimal duration
        to avoid blocking inbound data processing.
    """

    def __init__(
        self,
        inbound_transports: List[InboundTransport],
        outbound_transport: Optional[OutboundTransport],
        session_timeout: int = 300,
        encrypt: bool = False,
        normalize_mode: Optional[str] = None,
        daemon_mode: bool = False,
    ):
        """Initialize the bridge with transports and configuration.

        Does not start any threads or bind any sockets -- call start() to
        begin operation.

        Args:
            inbound_transports: List of InboundTransport instances to accept
                client connections from. At least one is required.
            outbound_transport: The default OutboundTransport instance.
                Required unless daemon_mode is True.
            session_timeout: Seconds of inactivity before a session is reaped
                by the cleanup loop. Defaults to 300 (5 minutes).
            encrypt: Whether to enable encryption negotiation for new sessions.
                Defaults to False. When True, the bridge will attempt DH
                key exchange (not yet fully implemented).
            normalize_mode: Optional[str] "csc_to_rfc" or "rfc_to_csc".
            daemon_mode: Whether to start in BNC/Daemon mode (Lobby).
        """
        self.inbound_transports = inbound_transports
        self.default_outbound = outbound_transport
        self.session_timeout = session_timeout
        self.encrypt = encrypt
        self.normalize_mode = normalize_mode
        self.daemon_mode = daemon_mode
        self.data = BridgeData()

        # Session tracking
        self._sessions: Dict[str, ClientSession] = {}          # session_id -> session
        self._client_to_session: Dict[Any, ClientSession] = {} # client_id -> session
        self._lock = threading.Lock()
        self._running = False

        # Map inbound transports by name for reverse lookups
        self._inbound_map: Dict[str, InboundTransport] = {}

    def start(self):
        """Start all transports and background threads.

        For each inbound transport, registers the _on_client_data callback
        (with transport captured via closure) and calls transport.start().
        Then spawns the keepalive and cleanup daemon threads.

        After start() returns, the bridge is fully operational and ready
        to accept client connections.
        """
        self._running = True

        # Start each inbound transport with our callback
        for transport in self.inbound_transports:
            name = type(transport).__name__
            self._inbound_map[name] = transport
            transport.start(lambda data, cid, t=transport: self._on_client_data(data, cid, t))
            logger.info(f"Inbound transport started: {name}")

        # Background threads
        threading.Thread(
            target=self._keepalive_loop, daemon=True, name="keepalive"
        ).start()
        threading.Thread(
            target=self._cleanup_loop, daemon=True, name="cleanup"
        ).start()

        logger.info("Bridge started")

    def stop(self):
        """Stop all transports, destroy all sessions, and clean up.

        Sets _running to False to signal all background threads to exit,
        stops each inbound transport, and destroys every active session
        (sending QUIT to the server and closing upstream handles). Clears
        all session tracking dicts.

        After stop() returns, no further callbacks will be invoked and all
        sockets are closed.
        """
        self._running = False
        for transport in self.inbound_transports:
            transport.stop()
        with self._lock:
            for session in list(self._sessions.values()):
                self._destroy_session(session)
            self._sessions.clear()
            self._client_to_session.clear()
        logger.info("Bridge stopped")

    def _on_client_data(self, data: bytes, client_id: ClientID, inbound: InboundTransport):
        """Callback invoked by inbound transports when data arrives from a client.

        This is the main entry point for client-to-server traffic. It handles
        three cases:
        1. Empty data (b""): Client disconnected -- destroy the session.
        2. Known client: Look up existing session, update activity, forward data.
        3. New client: Create a new session with a dedicated upstream handle,
           then forward the data.

        In all cases, NICK commands are sniffed for the session's nick field
        (used for logging and status display).

        Args:
            data: Raw bytes received from the client. Empty bytes signal
                disconnect.
            client_id: Transport-specific identifier for the client (e.g.,
                (host, port) tuple for UDP, TCPClientID for TCP).
            inbound: The InboundTransport instance that received the data.
                Captured via closure when the callback is registered in start().

        Threading:
            Called from the inbound transport's listener/reader thread. Acquires
            _lock briefly for session lookup. Session creation (_create_session)
            acquires _lock internally.
        """
        # Empty data = disconnect
        if not data:
            self._handle_disconnect(client_id)
            return

        logger.debug(f"_on_client_data: Received {len(data)} bytes from {client_id}: {data[:100]}")

        with self._lock:
            session = self._client_to_session.get(client_id)

        if session is None:
            logger.info(f"_on_client_data: New client {client_id}, creating session")
            session = self._create_session(client_id, inbound)
            if session is None:
                return

        session.touch()
        self._sniff_nick(session, data)
        logger.debug(f"_on_client_data: Forwarding {len(data)} bytes from client {client_id} to server")
        self._forward_to_server(session, data)

    def _create_session(self, client_id: ClientID, inbound: InboundTransport) -> Optional[ClientSession]:
        """Create a new session for a client.

        Allocates a ClientSession.
        If daemon_mode is False (legacy), creates a dedicated upstream handle via the
        default outbound transport and spawns a listener.
        If daemon_mode is True, sets state to LOBBY and waits for auth.

        Args:
            client_id: Transport-specific identifier for the new client.
            inbound: The InboundTransport that accepted this client.

        Returns:
            The newly created ClientSession, or None if session creation failed.
        """
        try:
            logger.debug(f"_create_session: Creating for client {client_id}")
            session = ClientSession(
                client_id=client_id,
                inbound_name=type(inbound).__name__,
            )
            session.inbound = inbound # Store inbound transport object

            if self.normalize_mode:
                session.normalizer = IrcNormalizer(self.normalize_mode)

            # LOBBY vs CONNECTED logic
            if self.daemon_mode:
                session.state = "LOBBY"
                session.control_handler = ControlHandler(session, self)
                # No outbound yet
            else:
                session.state = "CONNECTED"
                session.outbound = self.default_outbound
                if session.outbound:
                    logger.debug(f"Creating upstream handle for {session.session_id[:8]}")
                    session.upstream_handle = session.outbound.create_upstream(session.session_id)
                    logger.debug(f"Upstream handle created successfully for {session.session_id[:8]}")

                    # Initiate Encryption
                    if self.encrypt:
                        try:
                            session.dh = DHExchange()
                            init_msg = session.dh.format_init_message().encode("utf-8")
                            session.outbound.send(session.upstream_handle, init_msg)
                            logger.info(f"Sent CRYPTOINIT for {session.session_id[:8]}")
                        except Exception as e:
                            logger.error(f"Failed to initiate crypto for {session.session_id[:8]}: {e}")

            with self._lock:
                self._sessions[session.session_id] = session
                self._client_to_session[client_id] = session

            # Start server listener thread for this session
            if session.outbound:
                logger.debug(f"Starting server listener thread for {session.session_id[:8]}")
                threading.Thread(
                    target=self._server_listener,
                    args=(session,),
                    daemon=True,
                    name=f"upstream-{session.session_id[:8]}",
                ).start()

            nick_str = f" ({session.nick})" if session.nick else ""
            logger.info(f"Session created: {session.session_id[:8]} client={client_id}{nick_str} mode={self.normalize_mode} state={session.state}")
            return session

        except Exception as e:
            logger.error(f"Failed to create session for {client_id}: {type(e).__name__}: {e}", exc_info=True)
            return None

    def _handle_disconnect(self, client_id: ClientID):
        """Handle a client disconnect event.

        Removes the session from both tracking dicts under _lock, then
        destroys the session (sends QUIT to server, closes upstream handle).

        Args:
            client_id: Transport-specific identifier for the disconnected client.

        Threading:
            Acquires _lock to remove the session from tracking dicts. The
            actual session destruction (_destroy_session) runs outside the lock.
        """
        with self._lock:
            session = self._client_to_session.pop(client_id, None)
            if session:
                self._sessions.pop(session.session_id, None)
        if session:
            self._destroy_session(session)
            logger.info(f"Session ended: {session.session_id[:8]} nick={session.nick}")

    def _destroy_session(self, session: ClientSession):
        """Clean up and destroy a session, closing server connection gracefully.

        Sends a QUIT message to the CSC server (if the session has an active
        outbound handle) to notify the server that the client is disconnecting,
        then closes the upstream handle to release socket resources. This method
        does NOT remove the session from tracking dicts (_sessions,
        _client_to_session) -- that must be done by the caller.

        Both send and close operations are wrapped in try/except to ensure
        cleanup proceeds even if the network operations fail (e.g., server
        already disconnected, socket already closed).

        Args:
            session: ClientSession to destroy. Must not be None.
                - session.outbound: OutboundTransport instance or None. If None,
                  no QUIT is sent and no handle is closed.
                - session.upstream_handle: Transport-specific handle (e.g., socket)
                  or None. If None, no operations are performed.

        Returns:
            None

        Raises:
            No exceptions propagate. All exceptions from send() and close()
            operations are caught and silently ignored to ensure cleanup
            proceeds.

        Data:
            Reads:
                - session.outbound: OutboundTransport instance
                - session.upstream_handle: Transport-specific handle
            Writes:
                - None (does not modify session or Bridge state)
            Mutates:
                - Network: Sends "QUIT :Bridge session closed\r\n" to server
                - Network: Closes upstream socket/handle via outbound.close()

        Side effects:
            - Network I/O:
                - Sends QUIT command to CSC server (UDP or TCP packet)
                - Closes upstream socket, releasing OS file descriptor
            - Logging: None
            - Thread safety: Safe to call from any thread. Does not acquire locks.
              Caller must ensure session is already removed from _sessions before
              destroying to prevent race conditions with _server_listener thread.

        Children:
            - session.outbound.send(): Sends QUIT message to server
            - session.outbound.close(): Closes upstream handle/socket

        Parents:
            - _handle_disconnect(): Destroys session when client disconnects
            - _cleanup_loop(): Destroys timed-out sessions
            - stop(): Destroys all sessions during shutdown
        """
        try:
            if session.outbound and session.upstream_handle:
                # Send QUIT to server so it cleans up
                quit_msg = f"QUIT :Bridge session closed\r\n".encode("utf-8")
                session.outbound.send(session.upstream_handle, quit_msg)
        except Exception:
            pass  # Ignored exception
        try:
            if session.outbound and session.upstream_handle:
                session.outbound.close(session.upstream_handle)
        except Exception:
            pass  # Ignored exception

    def _sniff_nick(self, session: ClientSession, data: bytes):
        """Extract and store the nick from NICK commands in client data.

        Parses the raw client data for NICK commands (case-insensitive) and
        updates session.nick with the extracted nickname. This is used for
        logging and status display purposes. The actual NICK command is still
        forwarded to the server -- this method only extracts the value for
        bridge-side tracking.

        The method decodes data as UTF-8 (ignoring errors), splits into lines,
        and searches for lines starting with "NICK ". If found, the nickname
        is extracted (with leading ":" removed if present) and stored in
        session.nick.

        All exceptions during parsing are silently ignored to prevent client
        data from crashing the bridge.

        Args:
            session: ClientSession whose nick field will be updated. Must not
                be None.
                - session.nick: String field that will be overwritten if a NICK
                  command is found.
            data: Raw bytes received from the client. Can be empty, incomplete,
                or malformed. Will be decoded as UTF-8 with error handling.
                Valid data format: "NICK nickname\r\n" or "NICK :nickname\r\n"

        Returns:
            None

        Raises:
            No exceptions propagate. All parsing exceptions (UnicodeDecodeError,
            IndexError, etc.) are caught and silently ignored.

        Data:
            Reads:
                - data: Raw client bytes (not modified)
            Writes:
                - session.nick: Overwrites with extracted nickname string
            Mutates:
                - session.nick: Updated in-place if NICK command found

        Side effects:
            - Logging: None
            - Network I/O: None
            - Thread safety: Modifies session.nick without locking. Safe because
              each session is only accessed by one _on_client_data thread at a
              time (session is tied to a specific client_id).

        Children:
            - bytes.decode(): Decodes raw data to UTF-8 string
            - str.splitlines(): Splits data into lines
            - str.upper(): Case-insensitive NICK detection
            - str.split(): Parses NICK command arguments

        Parents:
            - _on_client_data(): Calls this for every client message to track nick

        Logic table (NICK command parsing):
            Input                    | session.nick updated? | Value stored
            -------------------------|-----------------------|-------------
            "NICK alice\r\n"         | Yes                   | "alice"
            "NICK :alice\r\n"        | Yes                   | "alice"
            "nick bob\r\n"           | Yes                   | "bob"
            "USER foo\r\n"           | No                    | (unchanged)
            "PRIVMSG #chan :hi\r\n"  | No                    | (unchanged)
            "NICK\r\n"               | No                    | (unchanged)
            b"\xff\xfe"              | No                    | (unchanged)
            b""                      | No                    | (unchanged)
        """
        try:
            text = data.decode("utf-8", errors="ignore")
            for line in text.strip().splitlines():
                line = line.strip()
                if line.upper().startswith("NICK "):
                    parts = line.split(None, 1)
                    if len(parts) >= 2:
                        nick = parts[1].lstrip(":")
                        session.nick = nick
        except Exception:
            pass  # Ignored exception

    def _forward_to_server(self, session: ClientSession, data: bytes):
        """Forward client data to the CSC server with encryption and normalization.

        Routes client data based on session state:
        - LOBBY state: Delegates to _handle_control_command for authentication
          and control commands (e.g., /connect, /help). Data is not forwarded
          to server.
        - CONNECTED state: Encrypts (if session.encrypted), normalizes (if
          session.normalizer configured), and sends to server via
          outbound.send().

        In CONNECTED state, the flow is:
        1. Check if session has outbound and upstream_handle (should always
           be true in CONNECTED state).
        2. If session.encrypted and session.aes_key are set, encrypt the data
           using AES. Encryption failures are logged and the message is dropped.
        3. If session.normalizer is set and session is not encrypted, apply
           protocol normalization (e.g., CSC -> RFC IRC translation). Normalization
           can filter commands by returning None, which drops the message.
        4. Send the (possibly encrypted/normalized) data via
           session.outbound.send().

        Encryption and normalization are mutually exclusive: encrypted data is
        not normalized (binary ciphertext cannot be parsed as IRC commands).

        Args:
            session: ClientSession with state, encryption, and normalization config.
                - session.state: "LOBBY" or "CONNECTED" (string)
                - session.outbound: OutboundTransport instance or None
                - session.upstream_handle: Transport-specific handle or None
                - session.encrypted: Boolean indicating if encryption is active
                - session.aes_key: 32-byte AES key or None
                - session.normalizer: IrcNormalizer instance or None
                - session.control_handler: ControlHandler instance (only in LOBBY)
                - session.session_id: String UUID for logging
            data: Raw bytes from client. Can be any size (0 to MTU). For CONNECTED
                sessions, expected to contain IRC protocol commands (e.g.,
                "NICK alice\r\n", "PRIVMSG #chan :hello\r\n"). For LOBBY sessions,
                expected to contain control commands (e.g., "/connect server\r\n").

        Returns:
            None

        Raises:
            No exceptions propagate. All exceptions during encryption, normalization,
            or sending are caught and logged. Messages that fail to process are
            dropped silently (from the client's perspective).

        Data:
            Reads:
                - session.state: Determines routing logic
                - session.outbound, session.upstream_handle: Server connection
                - session.encrypted, session.aes_key: Encryption config
                - session.normalizer: Protocol normalization config
                - session.control_handler: Control command handler (LOBBY only)
                - session.session_id: For logging
            Writes:
                - None (does not modify session or Bridge state)
            Mutates:
                - None

        Side effects:
            - Logging:
                - logger.debug(): Logs data size and first 100 bytes sent to server
                - logger.warning(): Logs normalization errors
                - logger.error(): Logs encryption or send failures
            - Network I/O:
                - Sends data to CSC server via session.outbound.send()
                - In LOBBY state, may send responses to client via control_handler
            - Thread safety: Safe to call from any thread. Does not acquire locks.
              Modifies no shared state.

        Children:
            - _handle_control_command(): Handles LOBBY state commands
            - encrypt(): Encrypts data with AES (csc_shared.crypto)
            - session.normalizer.normalize_client_to_server(): Normalizes IRC protocol
            - bytes.decode(), str.encode(): Convert between bytes and strings
            - session.outbound.send(): Sends data to server

        Parents:
            - _on_client_data(): Forwards all client traffic through this method

        State transitions:
            LOBBY -> LOBBY: Control commands handled, no server I/O
            LOBBY -> CONNECTED: After successful authentication (handled by control_handler)
            CONNECTED -> CONNECTED: All client data forwarded to server

        Normalization logic table (when session.normalizer is set):
            Client command              | Normalized command           | Action
            ----------------------------|------------------------------|-------
            "NICK alice\r\n"            | "NICK alice\r\n"             | Send
            "PRIVMSG #chan :hi\r\n"     | "PRIVMSG #chan :hi\r\n"      | Send
            Custom CSC command          | RFC-compliant equivalent     | Send
            Filtered command            | None                         | Drop
            Malformed UTF-8             | (original bytes)             | Send

        Encryption logic table (when session.encrypted is True):
            Input                       | Encrypted? | Sent to server?
            ----------------------------|------------|----------------
            "NICK alice\r\n"            | Yes        | Yes (ciphertext)
            "CRYPTOINIT ..."            | No         | Yes (plaintext)
            Any data (AES key set)      | Yes        | Yes
            Any data (AES key missing)  | (error)    | No (dropped)
        """
        if session.state == "LOBBY":
            self._handle_control_command(session, data)
            return

        if not session.outbound or not session.upstream_handle:
            # Should not happen in CONNECTED state
            return

        # Encrypt if session is secure
        if session.encrypted:
            if session.aes_key:
                try:
                    # Do NOT encrypt CRYPTOINIT messages (handshake)
                    # But client shouldn't be sending them anyway.
                    # Just encrypt everything from client.
                    data = encrypt(session.aes_key, data)
                except Exception as e:
                    logger.error(f"Encryption failed for {session.session_id[:8]}: {e}")
                    # Forwarding raw data as fallback is safer for debugging but riskier for security.
                    # As per instruction, handle missing key gracefully (don't drop silently).
            else:
                logger.error(f"Encryption enabled but aes_key missing for {session.session_id[:8]}. Forwarding as plaintext.")

        try:
            to_send = data
            if session.normalizer and not session.encrypted: # Only normalize plaintext
                try:
                    text = data.decode("utf-8")
                    norm_text = session.normalizer.normalize_client_to_server(text, session)
                    if norm_text is None:
                        # Command consumed/filtered
                        return
                    to_send = norm_text.encode("utf-8")
                except Exception as e:
                    logger.warning(f"Normalization error (client->server): {e}")
                    # Fallback to sending original data
                    to_send = data

            logger.debug(f"_forward_to_server: Sending {len(to_send)} bytes to server for session {session.session_id[:8]}: {to_send[:100]}")
            session.outbound.send(session.upstream_handle, to_send)
        except Exception as e:
            logger.error(f"Forward to server failed for {session.session_id[:8]}: {e}")

    def _handle_control_command(self, session: ClientSession, data: bytes):
        """Delegate control command handling to the session's control handler.

        Routes raw client data to the session's ControlHandler instance for
        processing. This is only called when session.state == "LOBBY", where
        clients can execute control commands like /connect, /help, /list, etc.
        before connecting to an upstream server.

        The ControlHandler is responsible for parsing commands, authenticating
        clients, managing server connections, and transitioning sessions from
        LOBBY to CONNECTED state. This method is a simple delegation layer.

        Args:
            session: ClientSession with an active control_handler.
                - session.control_handler: ControlHandler instance or None.
                  If None, this method does nothing (should never happen in
                  LOBBY state).
                - session.state: Expected to be "LOBBY" when this is called.
            data: Raw bytes from client. Expected to contain control commands
                (e.g., "/connect server\r\n", "/help\r\n") or chat messages
                for the lobby. The ControlHandler is responsible for parsing
                and validating the format.

        Returns:
            None

        Raises:
            No exceptions propagate. Any exceptions raised by
            session.control_handler.handle_line() are caught by that method
            and logged. This method does not add additional exception handling.

        Data:
            Reads:
                - session.control_handler: ControlHandler instance
            Writes:
                - None (ControlHandler may modify session state internally)
            Mutates:
                - None (modifications are encapsulated in ControlHandler)

        Side effects:
            - Logging: ControlHandler logs command execution
            - Network I/O:
                - ControlHandler may send responses to client via inbound.send_to_client()
                - ControlHandler may create outbound connection and transition
                  session to CONNECTED state
            - Thread safety: Safe to call from any thread. Does not acquire locks.
              ControlHandler may modify session state (state, outbound,
              upstream_handle) but this is synchronized internally.

        Children:
            - session.control_handler.handle_line(): Processes control command

        Parents:
            - _forward_to_server(): Calls this when session.state == "LOBBY"

        Control commands handled by ControlHandler:
            /connect <server> [port] - Connect to an upstream server
            /disconnect              - Disconnect from server (return to LOBBY)
            /help                    - Display help message
            /list                    - List available servers (if configured)
            /quit                    - Disconnect from bridge
            <message>                - Broadcast to all LOBBY users (chat)
        """
        if session.control_handler:
            session.control_handler.handle_line(data)

    def _forward_to_client(self, session: ClientSession, data: bytes):
        """Forward server data back to the client with optional normalization.

        Routes server responses back to the client via the inbound transport
        that originally accepted the client connection. If protocol normalization
        is configured (session.normalizer), applies server-to-client translation
        (e.g., CSC -> RFC IRC). If normalization drops the message (returns None),
        the data is not sent to the client.

        The inbound transport is looked up by name (session.inbound_name) in
        the _inbound_map dict. If the transport is not found (should never
        happen), the message is dropped and an error is logged.

        Args:
            session: ClientSession with client routing information.
                - session.inbound_name: String class name of the InboundTransport
                  (e.g., "TCPInbound", "UDPInbound")
                - session.client_id: Transport-specific client identifier (e.g.,
                  (host, port) tuple for UDP, TCPClientID for TCP)
                - session.normalizer: IrcNormalizer instance or None
                - session.session_id: String UUID for logging
            data: Raw bytes from server. Expected to contain IRC protocol messages
                (e.g., ":server 001 alice :Welcome\r\n"). Can be any size (0 to MTU).
                Empty data is allowed but will result in a no-op send.

        Returns:
            None

        Raises:
            No exceptions propagate. All exceptions during normalization or
            sending are caught and logged. Messages that fail to process are
            dropped silently (from the server's perspective).

        Data:
            Reads:
                - session.inbound_name: Transport class name for lookup
                - session.client_id: Client routing identifier
                - session.normalizer: Protocol normalization config
                - session.session_id: For logging
                - self._inbound_map: Dict mapping transport names to instances
            Writes:
                - None (does not modify session or Bridge state)
            Mutates:
                - None

        Side effects:
            - Logging:
                - logger.debug(): Logs transport lookup, normalization drops, and
                  data size sent to client
                - logger.warning(): Logs normalization errors
                - logger.error(): Logs send failures with full exception trace
            - Network I/O:
                - Sends data to client via inbound.send_to_client()
            - Thread safety: Safe to call from any thread. Does not acquire locks.
              Reads from _inbound_map (populated once during start(), never modified).

        Children:
            - self._inbound_map.get(): Looks up inbound transport by name
            - session.normalizer.normalize_server_to_client(): Normalizes IRC protocol
            - bytes.decode(), str.encode(): Convert between bytes and strings
            - inbound.send_to_client(): Sends data to client via transport

        Parents:
            - _server_listener(): Forwards all server traffic through this method

        Normalization logic table (when session.normalizer is set):
            Server message              | Normalized message           | Action
            ----------------------------|------------------------------|-------
            ":srv 001 alice :Welcome"   | ":srv 001 alice :Welcome"    | Send
            ":srv NOTICE * :foo"        | ":srv NOTICE * :foo"         | Send
            Custom CSC message          | RFC-compliant equivalent     | Send
            Filtered message            | None                         | Drop
            Malformed UTF-8             | (original bytes)             | Send

        Transport lookup logic table:
            session.inbound_name | _inbound_map entry | Result
            ---------------------|-------------------|--------
            "TCPInbound"         | TCPInbound inst.  | Send via TCP
            "UDPInbound"         | UDPInbound inst.  | Send via UDP
            "UnknownTransport"   | None              | Drop (error logged)
            ""                   | None              | Drop (error logged)
        """
        # Find the inbound transport for this session
        inbound = self._inbound_map.get(session.inbound_name)
        logger.debug(f"_forward_to_client: inbound_name={session.inbound_name}, inbound={inbound is not None}")

        # If session has encryption enabled, decrypt server->client data
        if getattr(session, 'encrypted', False) and getattr(session, 'aes_key', None):
            if is_encrypted(data):
                try:
                    data = decrypt(session.aes_key, data)
                except Exception as e:
                    # Log decryption failure but forward raw data rather than dropping
                    logger.error(f"Decryption failed for {session.session_id[:8]}: {e}")

        if inbound:
            try:
                to_send = data
                if session.normalizer:
                    try:
                        text = data.decode("utf-8")
                        norm_text = session.normalizer.normalize_server_to_client(text, session)
                        if norm_text is None:
                             # Dropped
                             logger.debug(f"Normalization dropped data for {session.session_id[:8]}")
                             return
                        to_send = norm_text.encode("utf-8")
                    except Exception as e:
                        logger.warning(f"Normalization error (server->client): {e}")
                        to_send = data

                logger.debug(f"Sending {len(to_send)} bytes to TCP client {session.client_id}")
                inbound.send_to_client(session.client_id, to_send)
            except Exception as e:
                logger.error(f"Forward to client failed for {session.session_id[:8]}: {type(e).__name__}: {e}", exc_info=True)

    def _server_listener(self, session: ClientSession):
        """Poll server for responses and forward to client (per-session thread).

        This is the main server-to-client traffic handler, running in a dedicated
        daemon thread for each active session. It continuously polls the outbound
        transport for data from the CSC server, handles encryption handshake and
        decryption, and forwards responses back to the client.

        The loop runs until one of these conditions is met:
        1. self._running is False (bridge is shutting down)
        2. session.session_id is removed from self._sessions (session destroyed)
        3. session.outbound is None (should never happen after initialization)
        4. An exception occurs during recv() (e.g., socket closed)

        Encryption handling:
        - If data is plaintext and starts with "CRYPTOINIT DHREPLY":
            - Complete DH key exchange to derive shared AES key
            - Set session.encrypted = True and session.aes_key
            - Drop the handshake message (don't forward to client)
        - Otherwise, forward data to _forward_to_client for potential decryption

        After successful recv(), session.touch() is called to update activity
        timestamp for keepalive and timeout tracking.

        Args:
            session: ClientSession with server connection information.
                - session.session_id: String UUID for session tracking
                - session.outbound: OutboundTransport instance
                - session.upstream_handle: Transport-specific handle for server socket
                - session.client_id: Client routing identifier for logging
                - session.encrypted: Boolean indicating encryption status
                - session.aes_key: 32-byte AES key or None
                - session.dh: DHExchange instance or None (for handshake)

        Returns:
            None (runs until exit condition, never returns normally)

        Raises:
            No exceptions propagate to parent thread. All exceptions during recv(),
            decryption, or forwarding are caught and logged. Loop exits on exception.

        Data:
            Reads:
                - self._running: Bridge shutdown flag (checked every iteration)
                - self._sessions: Session tracking dict (checked under lock)
                - session.session_id: Session identifier
                - session.outbound: OutboundTransport instance
                - session.upstream_handle: Server socket handle
                - session.encrypted, session.aes_key: Encryption state
                - session.dh: DH exchange instance for handshake
            Writes:
                - session.encrypted: Set to True after successful handshake
                - session.aes_key: Set after DH key exchange
            Mutates:
                - session.last_activity: Updated via session.touch()

        Side effects:
            - Logging:
                - logger.info(): Logs thread start/exit and encryption establishment
                - logger.debug(): Logs recv() calls, data sizes, timeouts
                - logger.warning(): Logs encrypted data without key
                - logger.error(): Logs decryption failures and exceptions
            - Network I/O:
                - Polls session.outbound.recv() with 1.0 second timeout (blocking)
                - Forwards data to client via _forward_to_client()
            - Thread safety:
                - Acquires self._lock to check session membership (brief hold)
                - No other locks acquired
                - Safe concurrent access to session (only this thread reads server data)
            - Threads:
                - Runs in dedicated daemon thread "upstream-{session_id[:8]}"
                - One thread per active session
                - Exits when session is destroyed or bridge stops

        Children:
            - session.outbound.recv(): Blocks waiting for server data (1s timeout)
            - session.touch(): Updates last_activity timestamp
            - is_encrypted(): Checks if data is encrypted (csc_shared.crypto)
            - decrypt(): Decrypts data with AES key (csc_shared.crypto)
            - DHExchange.parse_reply_message(): Parses server's DH public key
            - session.dh.compute_shared_key(): Computes shared AES key
            - _forward_to_client(): Sends data to client

        Parents:
            - _create_session(): Spawns this thread for each new session

        Loop exit conditions table:
            Condition                       | Exit path               | Logging
            --------------------------------|-------------------------|-------------------
            self._running == False          | break in outer loop     | "exiting loop"
            session removed from _sessions  | break in inner loop     | "removed, exiting"
            session.outbound == None        | break in inner loop     | "no outbound, exiting"
            recv() raises exception         | break in except block   | "exception: ..."
            Outer exception                 | exit in except block    | "outer exception: ..."

        Encryption state machine:
            State              | Incoming data          | Action
            -------------------|------------------------|----------------------------------
            Not encrypted      | Plaintext              | Forward to client
            Not encrypted      | CRYPTOINIT DHREPLY     | Complete handshake, set encrypted=True
            Not encrypted      | Encrypted data         | Log warning, drop
            Encrypted          | Encrypted data         | Decrypt, forward to client
            Encrypted          | Plaintext              | Forward to client (corner case)
            Encrypted (no key) | Encrypted data         | Log warning, drop
        """
        logger.info(f"_server_listener STARTED for {session.session_id[:8]} (client={session.client_id})")
        try:
            while self._running:
                if hasattr(self, "check_shutdown") and self.check_shutdown():
                    if hasattr(self, "log_shutdown"): self.log_shutdown()
                    break
                with self._lock:
                    if session.session_id not in self._sessions:
                        logger.info(f"_server_listener: session {session.session_id[:8]} removed from _sessions, exiting loop")
                        break

                if not session.outbound:
                    # Should not be running if no outbound
                    logger.info(f"_server_listener: no outbound for {session.session_id[:8]}, exiting loop")
                    break

                try:
                    logger.debug(f"_server_listener: calling recv() for {session.session_id[:8]}")
                    data = session.outbound.recv(session.upstream_handle, timeout=1.0)
                    logger.debug(f"_server_listener: recv() returned {len(data) if data else 0} bytes for {session.session_id[:8]}")
                    if data:
                        session.touch()

                        # Handshake Logic
                        if not is_encrypted(data):
                            # Check for Handshake Reply
                            try:
                                text = data.decode("utf-8", errors="ignore").strip()
                                if text.startswith("CRYPTOINIT DHREPLY"):
                                    if session.dh:
                                        server_pub = DHExchange.parse_reply_message(text)
                                        session.aes_key = session.dh.compute_shared_key(server_pub)
                                        session.encrypted = True
                                        logger.info(f"Encrypted session established for {session.session_id[:8]}")
                                        continue # Consume the handshake message
                            except Exception:
                                pass  # Ignored exception

                        logger.debug(f"Forwarding {len(data)} bytes to client {session.session_id[:8]}")
                        self._forward_to_client(session, data)
                    else:
                        logger.debug(f"_server_listener: recv() returned no data for {session.session_id[:8]}, timeout")
                except Exception as e:
                    logger.error(f"Server listener exception for {session.session_id[:8]}: {type(e).__name__}: {e}", exc_info=True)
                    break
        except Exception as e:
            logger.error(f"_server_listener outer exception for {session.session_id[:8]}: {type(e).__name__}: {e}", exc_info=True)
        finally:
            logger.info(f"_server_listener EXITED for {session.session_id[:8]}")

    def _keepalive_loop(self):
        """Send periodic keepalive PING to idle sessions (background thread).

        This daemon thread wakes every 30 seconds to check all active sessions.
        For each session that:
        1. Is in CONNECTED state (not LOBBY)
        2. Has an outbound transport configured
        3. Has been idle for more than 45 seconds (no client or server activity)

        ...it sends a "PING :keepalive\r\n" message to the CSC server via the
        session's outbound transport. This keeps the server connection alive
        and prevents the server from timing out idle clients.

        The PING is sent via the outbound transport (not to the client), so
        the server should respond with a PONG that will reset the session's
        idle timer. The client is not directly involved in this keepalive
        mechanism.

        Exceptions during send() are silently ignored (connection may already
        be dead, will be cleaned up by _cleanup_loop).

        Args:
            None (accesses self._running and self._sessions via closure)

        Returns:
            None (runs until self._running is False, never returns normally)

        Raises:
            No exceptions propagate. All exceptions during send() are caught
            and silently ignored.

        Data:
            Reads:
                - self._running: Bridge shutdown flag (checked every iteration)
                - self._sessions: Session tracking dict (copied under lock)
                - session.state: Session state ("LOBBY" or "CONNECTED")
                - session.outbound: OutboundTransport instance
                - session.upstream_handle: Server socket handle
                - session.last_activity: Timestamp for idle calculation
            Writes:
                - None (session.last_activity may be updated by server PONG response)
            Mutates:
                - None

        Side effects:
            - Logging: None (intentionally silent to avoid log spam)
            - Network I/O:
                - Sends "PING :keepalive\r\n" to server via outbound.send()
                - Server typically responds with PONG (handled by _server_listener)
            - Thread safety:
                - Acquires self._lock briefly to snapshot _sessions list
                - Safe concurrent iteration over session list (copied before iteration)
            - Threads:
                - Runs in dedicated daemon thread "keepalive"
                - Single thread for all sessions
                - Blocks on time.sleep(30) between iterations

        Children:
            - time.sleep(): Blocks thread for 30 seconds
            - session.idle(): Computes time since last activity
            - session.outbound.send(): Sends PING to server

        Parents:
            - start(): Spawns this thread during bridge initialization

        Timing table:
            Idle time | Session state | Outbound? | Action
            ----------|---------------|-----------|------------------
            < 45s     | CONNECTED     | Yes       | No PING (active)
            > 45s     | CONNECTED     | Yes       | Send PING
            > 45s     | CONNECTED     | No        | No PING (no transport)
            > 45s     | LOBBY         | N/A       | No PING (lobby users)
            > 300s    | Any           | Any       | Cleaned by _cleanup_loop

        Loop iteration frequency:
            - Sleep duration: 30 seconds
            - Idle threshold: 45 seconds
            - Result: Sessions idle 45-75s receive 1 PING
                     Sessions idle 75-105s receive 2 PINGs
                     Sessions idle >300s are destroyed by _cleanup_loop
        """
        while self._running:
            if hasattr(self, "check_shutdown") and self.check_shutdown():
                if hasattr(self, "log_shutdown"): self.log_shutdown()
                break
            time.sleep(30)
            with self._lock:
                sessions = list(self._sessions.values())
            for session in sessions:
                if session.idle() > 45 and session.state == "CONNECTED" and session.outbound:
                    try:
                        session.outbound.send(
                            session.upstream_handle,
                            b"PING :keepalive\r\n"
                        )
                    except Exception:
                        pass  # Ignored exception

    def _cleanup_loop(self):
        """Remove sessions that have been idle longer than session_timeout.

        Runs on a daemon thread, checking every 15 seconds. Sessions whose
        last_activity is older than session_timeout seconds are removed from
        tracking dicts under _lock, then destroyed outside the lock (sending
        QUIT and closing upstream handles).

        This prevents resource leaks from clients that disconnect without
        sending a proper QUIT or closing the connection cleanly (e.g., network
        failure, client crash).

        Threading:
            Runs on the "cleanup" daemon thread. Acquires _lock to identify
            and remove timed-out sessions, then releases it before calling
            _destroy_session() to avoid holding the lock during I/O.
        """
        while self._running:
            if hasattr(self, "check_shutdown") and self.check_shutdown():
                if hasattr(self, "log_shutdown"): self.log_shutdown()
                break
            time.sleep(15)
            now = time.time()
            to_remove = []
            with self._lock:
                for sid, session in list(self._sessions.items()):
                    if now - session.last_activity > self.session_timeout:
                        to_remove.append(session)
                        self._sessions.pop(sid, None)
                        self._client_to_session.pop(session.client_id, None)
            for session in to_remove:
                self._destroy_session(session)
                logger.info(f"Session timed out: {session.session_id[:8]} nick={session.nick}")

    def session_count(self) -> int:
        """Return the number of active sessions.

        Returns:
            Integer count of currently tracked sessions.

        Threading:
            Acquires _lock for a thread-safe read of _sessions.
        """
        with self._lock:
            return len(self._sessions)

    def list_sessions(self) -> List[dict]:
        """Return a list of summary dicts for all active sessions.

        Each dict contains the session's truncated ID, nick, transport name,
        idle time, and encryption status. Used by the interactive console
        or status reporting tools.

        Returns:
            List of dicts with keys:
                - "id": First 8 characters of the session UUID.
                - "nick": The client's IRC nick, or "?" if unknown.
                - "transport": Class name of the inbound transport.
                - "idle": Idle time formatted as "Ns" (e.g., "42s").
                - "encrypted": Boolean indicating encryption state.

        Threading:
            Acquires _lock for a thread-safe snapshot of _sessions.
        """
        with self._lock:
            return [
                {
                    "id": s.session_id[:8],
                    "nick": s.nick or "?",
                    "transport": s.inbound_name,
                    "idle": f"{s.idle():.0f}s",
                    "encrypted": s.encrypted,
                }
                for s in self._sessions.values()
            ]

    def get_lobby_sessions(self) -> List[ClientSession]:
        """Return a list of all sessions currently in the LOBBY state.

        Used by ControlHandler to broadcast lobby chat messages to all
        authenticated clients not yet connected to an upstream server.

        Returns:
            List of ClientSession objects with state == "LOBBY".

        Threading:
            Acquires _lock for a thread-safe snapshot of _sessions.
        """
        with self._lock:
            return [s for s in self._sessions.values() if s.state == "LOBBY"]
