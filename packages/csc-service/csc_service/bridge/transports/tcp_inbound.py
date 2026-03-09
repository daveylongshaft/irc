"""TCP inbound transport -- listens for standard IRC clients over TCP.

This module implements the TCP variant of the InboundTransport interface,
allowing the bridge to accept connections from standard IRC clients that
communicate over TCP with CRLF-delimited lines. This enables any off-the-shelf
IRC client (mIRC, HexChat, irssi, etc.) to connect through the bridge to
a CSC server.

Architecture:
    TCPInbound runs a TCP server socket that accepts incoming connections. Each
    accepted connection is handled by a dedicated reader thread that line-buffers
    on \\r\\n (the IRC line terminator). Complete lines are delivered to the
    bridge via the on_data callback, using a TCPClientID object as the
    client identifier.

    Unlike UDPInbound, TCP is connection-oriented, so each client has its own
    socket that must be individually tracked and cleaned up. The _clients dict
    maps connection IDs to TCPClientID objects, protected by a threading lock.

Dependencies:
    - transports.base.InboundTransport: Abstract base class this implements.
    - transports.base.ClientID: Type alias (here, a TCPClientID object).

Threading:
    - One accept thread ("tcp-accept") runs the _accept_loop, calling accept()
      in a loop to receive new connections.
    - One reader thread per client ("tcp-client-N") runs _handle_client, reading
      and line-buffering data from that client's socket.
    - The on_data callback is invoked from each client's reader thread.
    - _clients dict access is protected by self._lock.
    - send_to_client() can be called from any thread; sendall() is thread-safe
      at the OS level for a given socket.

Disconnect Signaling:
    When a client's TCP connection is closed (recv returns empty bytes or a
    connection error occurs), _handle_client sends an empty b"" via on_data
    to signal disconnect to the bridge, then calls _cleanup_client().

Related Modules:
    - transports.tcp_outbound: The outbound counterpart for TCP upstream.
    - transports.udp_inbound: The UDP variant of this interface.
    - bridge.Bridge: Consumes this transport and manages sessions.
"""

import socket
import threading
from typing import Callable, Dict, Optional
from .base import InboundTransport, ClientID


class TCPClientID:
    """Identifier for a TCP client connection.

    Wraps a TCP socket, its remote address, and a monotonically increasing
    connection ID into a hashable, equality-comparable object suitable for
    use as a dictionary key. The bridge uses TCPClientID as the ClientID
    for TCP sessions.

    The connection ID (conn_id) is used for hashing and equality rather than
    the socket object or address, because a client could reconnect from the
    same address but should be treated as a new session.

    Attributes:
        conn: The TCP socket for this client connection. Used by
            send_to_client() and _handle_client() for I/O.
        addr: The remote (host, port) tuple from accept(). Used for logging.
        conn_id: Monotonically increasing integer assigned by TCPInbound.
            Used for hashing, equality, and thread naming.

    Threading Safety:
        TCPClientID is created under _lock in _accept_loop and may be accessed
        from multiple threads (the client's reader thread, the bridge's
        forwarding path, and cleanup). The conn socket is used for recv() from
        the reader thread and sendall() from the bridge's forwarding path;
        these are safe for concurrent use at the OS level.
    """

    def __init__(self, conn: socket.socket, addr: tuple, conn_id: int):
        """Initialize a TCP client identifier.

        Args:
            conn: The accepted TCP socket for this client.
            addr: The remote (host, port) tuple from socket.accept().
            conn_id: Unique integer assigned by TCPInbound's connection counter.
        """
        self.conn = conn
        self.addr = addr
        self.conn_id = conn_id

    def __hash__(self):
        """Hash based on connection ID for use as dictionary key.

        Returns:
            Integer hash combining the "tcp" prefix with the conn_id.
        """
        return hash(("tcp", self.conn_id))

    def __eq__(self, other):
        """Compare equality based on connection ID.

        Args:
            other: Object to compare against. Must be a TCPClientID with the
                same conn_id to be considered equal.

        Returns:
            True if other is a TCPClientID with the same conn_id, False otherwise.
        """
        if isinstance(other, TCPClientID):
            return self.conn_id == other.conn_id
        return False

    def __repr__(self):
        """Return a human-readable representation for logging.

        Returns:
            String in the format "TCPClient((host, port), id=N)".
        """
        return f"TCPClient({self.addr}, id={self.conn_id})"


class TCPInbound(InboundTransport):
    """Accepts TCP connections from IRC clients, line-buffers on \\r\\n.

    TCPInbound runs a TCP server that accepts connections from standard IRC
    clients. Each connection gets a dedicated reader thread that buffers
    incoming data and splits it on \\r\\n (the IRC line terminator). Complete
    lines (including the trailing \\r\\n) are delivered to the bridge
    via the on_data callback.

    This enables any standard IRC client to connect through the bridge
    to a CSC server, even though the CSC server may use UDP natively.

    Attributes:
        host: The local IP address to bind to (e.g., "127.0.0.1" or "0.0.0.0").
        port: The local TCP port to listen on (e.g., 6667 for standard IRC).
        server_sock: The listening TCP server socket.
        _running: Boolean flag controlling the accept and reader loop lifecycles.
        _accept_thread: Reference to the daemon accept thread, or None if not started.
        _on_data: The callback function registered by start().
        _conn_counter: Monotonically increasing integer for assigning unique
            connection IDs to new clients.
        _clients: Dictionary mapping conn_id integers to TCPClientID objects.
            Protected by _lock.
        _lock: Threading lock protecting _clients and _conn_counter mutations.

    Threading Safety:
        All mutations to _clients and _conn_counter are performed under _lock.
        The accept loop, each client reader thread, send_to_client(), and
        stop() all acquire _lock before modifying shared state.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 6667):
        """Initialize the TCP inbound transport.

        Creates the TCP server socket with SO_REUSEADDR and a 1-second accept
        timeout. The socket is not bound or listening until start() is called.

        Args:
            host: Local IP address to bind to. Defaults to "127.0.0.1"
                (localhost only). Use "0.0.0.0" to accept from all interfaces.
            port: Local TCP port to listen on. Defaults to 6667, the standard
                IRC port.
        """
        self.host = host
        self.port = port
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.settimeout(1.0)
        self._running = False
        self._accept_thread = None
        self._on_data = None
        self._conn_counter = 0
        self._clients: Dict[int, TCPClientID] = {}
        self._lock = threading.Lock()

    def start(self, on_data: Callable[[bytes, ClientID], None]) -> None:
        """Bind the server socket, start listening, and launch the accept thread.

        Binds the TCP server socket to (self.host, self.port), starts listening
        with a backlog of 5, and spawns the daemon accept thread that runs
        _accept_loop().

        Args:
            on_data: Callback invoked for each complete IRC line received from
                a client, or with b"" to signal disconnect. Called as
                on_data(line_bytes, tcp_client_id) from the client's reader
                thread.

        Raises:
            OSError: If the socket cannot be bound (e.g., port already in use
                or insufficient permissions).
        """
        self._on_data = on_data
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(5)
        self._running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, daemon=True, name="tcp-accept"
        )
        self._accept_thread.start()

    def _accept_loop(self):
        """Accept loop running on the accept thread.

        Continuously calls accept() with a 1-second timeout. For each accepted
        connection, assigns a unique conn_id under _lock, creates a TCPClientID,
        registers it in _clients, and spawns a dedicated reader thread for that
        client.

        The loop exits when _running is set to False (by stop()) or on an
        unrecoverable OSError while _running is False.
        """
        while self._running:
            try:
                conn, addr = self.server_sock.accept()
                with self._lock:
                    self._conn_counter += 1
                    client_id = TCPClientID(conn, addr, self._conn_counter)
                    self._clients[client_id.conn_id] = client_id
                threading.Thread(
                    target=self._handle_client,
                    args=(client_id,),
                    daemon=True,
                    name=f"tcp-client-{client_id.conn_id}",
                ).start()
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    continue
                break

    def _handle_client(self, client_id: TCPClientID):
        """Read IRC lines from a TCP client, delivering each complete line.

        Runs on a dedicated thread per client. Reads data into a buffer and
        splits on \\r\\n boundaries. Each complete line (including the \\r\\n
        terminator) is delivered to the bridge via the on_data callback.

        When the connection is closed (recv returns b""), reset by the peer,
        or encounters an error, the method sends an empty b"" via on_data
        to signal disconnect to the bridge, then calls _cleanup_client()
        to close the socket and remove the client from tracking.

        Args:
            client_id: The TCPClientID for the client connection to handle.
                Contains the socket, remote address, and connection ID.
        """
        buf = b""
        try:
            # Note: Removed pre-registration NOTICE as it can confuse some IRC clients (mIRC).
            # Standard IRC doesn't send any unsolicited messages before registration.
            # The server will send welcome messages once NICK/USER is received.

            while self._running:
                try:
                    data = client_id.conn.recv(4096)
                    if not data:
                        break
                    buf += data
                    # Split on \n to handle both \r\n (RFC) and \n (some clients like mIRC)
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.rstrip(b"\r")  # Strip \r if present
                        irc_line = line + b"\r\n"  # Normalize to CRLF for server
                        if self._on_data:
                            self._on_data(irc_line, client_id)
                except socket.timeout:
                    continue
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                    break
                except OSError:
                    break
        finally:
            # Notify bridge of disconnect via empty data
            if self._on_data:
                self._on_data(b"", client_id)
            self._cleanup_client(client_id)

    def send_to_client(self, client_id: ClientID, data: bytes) -> None:
        """Send data to a specific connected TCP client.

        Uses sendall() to ensure the complete payload is delivered over the
        TCP stream. If the send fails (broken pipe, connection reset, etc.),
        the client is cleaned up automatically.

        Args:
            client_id: The TCPClientID for the target client. If not a
                TCPClientID instance, the call is silently ignored (allowing
                safe calls when the transport type is unknown).
            data: Raw bytes to send (typically IRC wire format with \\r\\n
                line terminators).
        """
        if not isinstance(client_id, TCPClientID):
            return
        try:
            client_id.conn.sendall(data)
        except (OSError, BrokenPipeError):
            self._cleanup_client(client_id)

    def remove_client(self, client_id: ClientID) -> None:
        """Remove a client connection and close its socket.

        Called by the bridge when a session is destroyed. Delegates to
        _cleanup_client() after verifying the client_id type.

        Args:
            client_id: The TCPClientID for the client to remove. If not a
                TCPClientID instance, the call is silently ignored.
        """
        if isinstance(client_id, TCPClientID):
            self._cleanup_client(client_id)

    def _cleanup_client(self, client_id: TCPClientID):
        """Remove a client from tracking and close its socket.

        Acquires _lock to safely remove the client from the _clients dict,
        then closes the TCP socket. OSError on close is suppressed since
        the socket may already be closed.

        This method is safe to call multiple times for the same client --
        the dict pop uses a default of None, and socket close is idempotent
        in practice.

        Args:
            client_id: The TCPClientID to clean up.
        """
        with self._lock:
            self._clients.pop(client_id.conn_id, None)
        try:
            client_id.conn.close()
        except OSError:
            pass

    def stop(self) -> None:
        """Stop accepting connections, close all clients, and shut down.

        Sets _running to False to signal all loops to exit, closes every
        active client connection under _lock, closes the server socket,
        and joins the accept thread with a 3-second timeout. After this
        method returns, no further on_data callbacks will be invoked.

        Client reader threads will exit on their own when they detect
        _running is False or when their socket is closed.
        """
        self._running = False
        # Close all client connections
        with self._lock:
            for client_id in list(self._clients.values()):
                try:
                    client_id.conn.close()
                except OSError:
                    pass
            self._clients.clear()
        try:
            self.server_sock.close()
        except OSError:
            pass
        if self._accept_thread:
            self._accept_thread.join(timeout=3)
