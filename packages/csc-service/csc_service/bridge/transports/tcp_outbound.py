"""TCP outbound transport -- sends data upstream to the CSC server via TCP.

This module implements the TCP variant of the OutboundTransport interface,
allowing the bridge to forward client traffic to a CSC server (or any
IRC-compatible server) over persistent TCP connections. Each client session
gets its own dedicated TCP connection, so the server sees each proxied client
as a distinct connection.

Architecture:
    TCPOutbound acts as a factory for TCPUpstreamHandle objects. When the
    bridge creates a session for a new client, it calls create_upstream()
    which establishes a new TCP connection to the server and returns a handle
    wrapping the connected socket.

    Unlike UDPOutbound where datagrams are naturally framed, TCP is a byte
    stream. The recv() method returns whatever data is available (up to 65500
    bytes) without line buffering -- the bridge or downstream consumer is
    responsible for framing if needed.

Dependencies:
    - transports.base.OutboundTransport: Abstract base class this implements.
    - transports.base.UpstreamHandle: Type alias for transport-specific handles.

Threading:
    send() can be called from any thread (the inbound transport's listener
    thread via the bridge callback). recv() is called from per-session
    server listener threads. create_upstream() is called from the bridge's
    callback context. close() is called during session teardown.

    TCPUpstreamHandle includes a _lock for future use in buffered receive
    scenarios, though the current recv() implementation does not require it
    since each session has its own socket and listener thread.

Related Modules:
    - transports.tcp_inbound: The inbound counterpart for TCP clients.
    - transports.udp_outbound: The UDP variant of this interface.
    - bridge.Bridge: Consumes this transport for upstream forwarding.
"""

import socket
import threading
from typing import Dict, Optional
from .base import OutboundTransport, UpstreamHandle


class TCPUpstreamHandle:
    """Wraps a single TCP connection dedicated to one client session.

    Each TCPUpstreamHandle encapsulates a persistent TCP connection to the
    CSC server. Unlike UDP handles, TCP connections must be explicitly
    established (via connect()) and maintain connection state. The handle
    also includes a receive buffer and lock for potential future line-buffered
    receive operations.

    Attributes:
        sock: The connected TCP socket for communicating with the CSC server.
        server_addr: Tuple of (host, port) identifying the target CSC server.
            Stored for reference; the socket is already connected to this address.
        _recv_buf: Byte buffer for accumulating partial receives. Reserved for
            future line-buffered receive support.
        _lock: Threading lock protecting _recv_buf for future concurrent access.
            Currently unused since each session has a dedicated listener thread.

    Threading Safety:
        The socket is used by send() (from the bridge callback thread, via
        sendall()) and recv() (from the per-session server listener thread).
        Concurrent sendall() and recv() on the same TCP socket are safe at the
        OS level. The _lock is provided for future buffered receive patterns.
    """

    def __init__(self, sock: socket.socket, server_addr: tuple):
        """Initialize the upstream handle with a connected socket.

        Args:
            sock: A TCP socket already connected to the CSC server.
            server_addr: The (host, port) tuple of the server this socket is
                connected to. Stored for reference and logging.
        """
        self.sock = sock
        self.server_addr = server_addr
        self._recv_buf = b""
        self._lock = threading.Lock()

    def close(self):
        """Close the underlying TCP connection.

        Suppresses OSError in case the socket is already closed or in an
        error state. After calling close(), this handle must not be used
        for any further send or receive operations.
        """
        try:
            self.sock.close()
        except OSError:
            pass


class TCPOutbound(OutboundTransport):
    """Creates per-session TCP connections for forwarding traffic to the CSC server.

    TCPOutbound manages the upstream side of the bridge's TCP path. For
    each client session, it establishes a new TCP connection to the server,
    wraps it in a TCPUpstreamHandle, and provides send/recv/close operations.

    Because TCP connections are stateful and persistent, connection failures
    during create_upstream() will raise OSError (e.g., connection refused).
    The bridge's _create_session() method catches these and logs the error.

    Attributes:
        server_addr: Tuple of (host, port) for the target CSC server that all
            upstream connections will connect to.
        _handles: Dictionary mapping session_id strings to their corresponding
            TCPUpstreamHandle objects. Used for tracking and cleanup.

    Threading Safety:
        create_upstream() and close() modify _handles and may be called from
        different threads. The GIL protects dict assignment in CPython. send()
        and recv() operate on individual handles and are safe for concurrent
        use on different handles.
    """

    def __init__(self, server_host: str = "127.0.0.1", server_port: int = 9525):
        """Initialize the TCP outbound transport with the target server address.

        Args:
            server_host: IP address or hostname of the CSC server. Defaults to
                "127.0.0.1" for local server connections.
            server_port: TCP port number of the CSC server. Defaults to 9525.
        """
        self.server_addr = (server_host, server_port)
        self._handles: Dict[str, TCPUpstreamHandle] = {}

    def create_upstream(self, session_id: str) -> TCPUpstreamHandle:
        """Establish a new TCP connection to the server for a client session.

        Creates a new TCP socket, connects it to the server with a 5-second
        connect timeout, then switches to a 1-second recv timeout for normal
        operation. The socket is wrapped in a TCPUpstreamHandle and registered
        in _handles.

        Args:
            session_id: UUID string identifying the session. Used as the key
                in _handles for tracking and cleanup.

        Returns:
            A TCPUpstreamHandle wrapping the connected socket and server address.

        Raises:
            OSError: If the connection cannot be established (e.g., server not
                running, connection refused, or connect timeout exceeded).
            socket.timeout: If the 5-second connect timeout expires.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(self.server_addr)
        sock.settimeout(1.0)
        handle = TCPUpstreamHandle(sock, self.server_addr)
        self._handles[session_id] = handle
        return handle

    def send(self, handle: TCPUpstreamHandle, data: bytes) -> None:
        """Send data to the CSC server through a session's TCP connection.

        Uses sendall() to ensure the complete payload is delivered over the
        TCP stream. OSError exceptions are silently suppressed; the session
        will be cleaned up when the server listener thread detects the
        connection failure.

        Args:
            handle: The TCPUpstreamHandle returned by create_upstream().
            data: Raw bytes to send (typically IRC wire format with \\r\\n
                line terminators).
        """
        try:
            handle.sock.sendall(data)
        except OSError:
            pass

    def recv(self, handle: TCPUpstreamHandle, timeout: float = 1.0) -> Optional[bytes]:
        """Receive data from the CSC server on a session's TCP connection.

        Receives up to 65500 bytes of data from the server. Unlike UDP, TCP
        is a byte stream, so the returned data may contain partial lines or
        multiple lines. The caller is responsible for any framing.

        Returns None on timeout, connection close (recv returns b""), or
        OSError. A return of None due to connection close (as opposed to
        timeout) is indistinguishable at this level -- the caller should
        treat both as "no data available" and rely on subsequent failures
        to detect a dead connection.

        Args:
            handle: The TCPUpstreamHandle returned by create_upstream().
            timeout: Maximum seconds to wait for data. The socket's timeout
                is set to this value before each recv() call. Defaults to 1.0.

        Returns:
            Raw bytes received from the server, or None if the timeout expired,
            the connection was closed, or an error occurred.
        """
        handle.sock.settimeout(timeout)
        try:
            data = handle.sock.recv(65500)
            if not data:
                return None
            return data
        except socket.timeout:
            return None
        except OSError:
            return None

    def close(self, handle: TCPUpstreamHandle) -> None:
        """Close an upstream TCP connection and remove it from tracking.

        Closes the handle's TCP socket and rebuilds the _handles dict to
        exclude the closed handle. Called during session teardown by the
        bridge's _destroy_session() method.

        Args:
            handle: The TCPUpstreamHandle to close. Must not be used for
                send() or recv() after this call.
        """
        handle.close()
        self._handles = {k: v for k, v in self._handles.items() if v is not handle}
