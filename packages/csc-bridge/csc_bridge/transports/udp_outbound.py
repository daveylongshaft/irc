"""UDP outbound transport -- sends data upstream to the CSC server.

This module implements the UDP variant of the OutboundTransport interface,
allowing the bridge to forward client traffic to the CSC server over UDP.
Each client session gets its own dedicated UDP socket bound to an ephemeral
port, ensuring the server sees a unique (host, port) source per proxied client.

Architecture:
    UDPOutbound acts as a factory for UDPUpstreamHandle objects. When the
    bridge creates a session for a new client, it calls create_upstream()
    which allocates a fresh UDP socket, binds it to an OS-assigned ephemeral
    port, and returns a handle wrapping the socket and the server address.

    The bridge then uses send() and recv() on the handle to forward
    traffic bidirectionally between the client and the CSC server. A dedicated
    server listener thread per session calls recv() in a loop.

Dependencies:
    - transports.base.OutboundTransport: Abstract base class this implements.
    - transports.base.UpstreamHandle: Type alias for transport-specific handles.

Threading:
    send() can be called from any thread (the inbound transport's listener
    thread via the bridge callback). recv() is called from per-session
    server listener threads. create_upstream() is called from the bridge's
    callback thread under its session lock. close() is called during session
    teardown.

    The _handles dict is modified by create_upstream() and close(). Since
    these are called from different threads, and dict comprehension in close()
    creates a new dict, there is a potential race. In practice this is
    acceptable because close() only runs during session teardown and the GIL
    protects dict assignment.

Related Modules:
    - transports.udp_inbound: The inbound counterpart for UDP clients.
    - transports.tcp_outbound: The TCP variant of this interface.
    - bridge.Bridge: Consumes this transport for upstream forwarding.
"""

import socket
from typing import Dict, Optional
from .base import OutboundTransport, UpstreamHandle


class UDPUpstreamHandle:
    """Wraps a single UDP socket dedicated to one client session.

    Each UDPUpstreamHandle encapsulates a UDP socket bound to an ephemeral
    local port, paired with the target CSC server address. This ensures
    the server sees a unique source (host, port) for each proxied client,
    which is critical because the CSC server identifies clients by their
    source address.

    Attributes:
        sock: The UDP socket bound to an ephemeral local port, used for
            both sending to and receiving from the CSC server.
        server_addr: Tuple of (host, port) identifying the target CSC server.

    Threading Safety:
        The socket is used by send() (from the bridge callback thread)
        and recv() (from the per-session server listener thread) concurrently.
        UDP sendto() and recvfrom() are atomic at the OS level for individual
        datagrams, so no locking is required.
    """

    def __init__(self, sock: socket.socket, server_addr: tuple):
        """Initialize the upstream handle with a socket and server address.

        Args:
            sock: A UDP socket already bound to an ephemeral local port.
            server_addr: The (host, port) tuple of the target CSC server.
        """
        self.sock = sock
        self.server_addr = server_addr

    def close(self):
        """Close the underlying UDP socket.

        Suppresses OSError in case the socket is already closed or in an
        error state. After calling close(), this handle must not be used
        for any further send or receive operations.
        """
        try:
            self.sock.close()
        except OSError:
            pass


class UDPOutbound(OutboundTransport):
    """Creates per-session UDP sockets for forwarding traffic to the CSC server.

    UDPOutbound manages the upstream side of the bridge's UDP path. For
    each client session, it creates a dedicated UDP socket bound to an
    ephemeral port, so the CSC server sees each proxied client as a distinct
    source address. This is essential because the server uses source (host, port)
    as the client identifier.

    Attributes:
        server_addr: Tuple of (host, port) for the target CSC server that all
            upstream sockets will send to.
        _handles: Dictionary mapping session_id strings to their corresponding
            UDPUpstreamHandle objects. Used for tracking and cleanup.

    Threading Safety:
        create_upstream() and close() modify _handles and may be called from
        different threads. The GIL protects dict assignment in CPython. send()
        and recv() operate on individual handles and are safe for concurrent
        use on different handles.
    """

    def __init__(self, server_host: str = "127.0.0.1", server_port: int = 9525):
        """Initialize the UDP outbound transport with the target server address.

        Args:
            server_host: IP address or hostname of the CSC server. Defaults to
                "127.0.0.1" for local server connections.
            server_port: UDP port number of the CSC server. Defaults to 9525,
                the standard CSC server port.
        """
        self.server_addr = (server_host, server_port)
        self._handles: Dict[str, UDPUpstreamHandle] = {}

    def create_upstream(self, session_id: str) -> UDPUpstreamHandle:
        """Create a new UDP upstream socket for a client session.

        Allocates a fresh UDP socket, binds it to 0.0.0.0:0 (which the OS
        resolves to an available ephemeral port), wraps it in a
        UDPUpstreamHandle, and registers it in the internal tracking dict.

        Args:
            session_id: UUID string identifying the session. Used as the key
                in _handles for tracking and cleanup.

        Returns:
            A UDPUpstreamHandle wrapping the new socket and the server address.

        Raises:
            OSError: If the socket cannot be created or bound (e.g., ephemeral
                port exhaustion).
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        # Bind to ephemeral port so server sees unique (host, port)
        sock.bind(("0.0.0.0", 0))
        handle = UDPUpstreamHandle(sock, self.server_addr)
        self._handles[session_id] = handle
        return handle

    def send(self, handle: UDPUpstreamHandle, data: bytes) -> None:
        """Send a datagram to the CSC server through a session's upstream socket.

        Uses sendto() to deliver the data to the server address stored in the
        handle. OSError exceptions are silently suppressed since UDP delivery
        is best-effort and the session will eventually time out if the server
        is unreachable.

        Args:
            handle: The UDPUpstreamHandle returned by create_upstream().
            data: Raw bytes to send (typically IRC wire format or encrypted
                CSC payload).
        """
        try:
            handle.sock.sendto(data, handle.server_addr)
        except OSError:
            pass

    def recv(self, handle: UDPUpstreamHandle, timeout: float = 1.0) -> Optional[bytes]:
        """Receive a datagram from the CSC server on a session's upstream socket.

        Blocks for up to ``timeout`` seconds waiting for a response from the
        server. Called in a loop by the per-session server listener thread in
        the bridge.

        Args:
            handle: The UDPUpstreamHandle returned by create_upstream().
            timeout: Maximum seconds to wait for data. The socket's timeout is
                set to this value before each recvfrom() call. Defaults to 1.0.

        Returns:
            The raw bytes of the received datagram, or None if the timeout
            expired or an OSError occurred (e.g., socket closed).
        """
        handle.sock.settimeout(timeout)
        try:
            data, _ = handle.sock.recvfrom(65500)
            return data
        except socket.timeout:
            return None
        except OSError:
            return None

    def close(self, handle: UDPUpstreamHandle) -> None:
        """Close an upstream handle and remove it from internal tracking.

        Closes the handle's UDP socket and rebuilds the _handles dict to
        exclude the closed handle. Called during session teardown by the
        bridge's _destroy_session() method.

        Args:
            handle: The UDPUpstreamHandle to close. Must not be used for
                send() or recv() after this call.
        """
        handle.close()
        # Remove from tracking
        self._handles = {k: v for k, v in self._handles.items() if v is not handle}
