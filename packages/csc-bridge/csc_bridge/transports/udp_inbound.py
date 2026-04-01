"""UDP inbound transport -- listens for CSC client datagrams.

This module implements the UDP variant of the InboundTransport interface,
allowing the bridge to accept datagrams from CSC clients that communicate
using the native UDP-based CSC protocol.

Architecture:
    UDPInbound binds a single UDP socket and runs a background listener thread
    that calls recvfrom() in a loop. Each incoming datagram is delivered to the
    bridge via the on_data callback, using the sender's (host, port) tuple
    as the ClientID. Because UDP is connectionless, there is no per-client
    socket -- the single bound socket handles both receiving from and sending
    to all clients.

    Unlike TCPInbound, UDP datagrams are delivered as-is without line buffering,
    since the CSC protocol already frames messages within individual datagrams.

Dependencies:
    - transports.base.InboundTransport: Abstract base class this implements.
    - transports.base.ClientID: Type alias (here, a (host, port) tuple).

Threading:
    The listener runs on a single daemon thread named "udp-inbound". The
    on_data callback is invoked directly from this thread. send_to_client()
    can be called from any thread since UDP sendto() is inherently atomic
    for datagrams under the OS MTU.

Related Modules:
    - transports.udp_outbound: The outbound counterpart for UDP upstream.
    - transports.tcp_inbound: The TCP variant of this interface.
    - bridge.Bridge: Consumes this transport and manages sessions.
"""

import socket
import threading
from typing import Callable, Dict
from .base import InboundTransport, ClientID


class UDPInbound(InboundTransport):
    """Accepts UDP datagrams from CSC clients on a single bound socket.

    UDPInbound listens on a configured host:port for incoming UDP datagrams.
    Each datagram's sender address (host, port) serves as the ClientID, which
    the bridge uses to map the traffic to a session. Responses are sent
    back through the same socket via sendto().

    Attributes:
        host: The local IP address to bind to (e.g., "127.0.0.1" or "0.0.0.0").
        port: The local UDP port to bind to (e.g., 9526).
        sock: The bound UDP socket used for both receiving and sending.
        _running: Boolean flag controlling the listener loop lifecycle.
        _thread: Reference to the daemon listener thread, or None if not started.
        _on_data: The callback function registered by start(), invoked for each
            received datagram.
        _clients: Dictionary tracking known client addresses. Keys are (host, port)
            tuples; values are True. Used for bookkeeping of active clients.

    Threading Safety:
        The _clients dict is only mutated from the listener thread (additions)
        and from remove_client() which may be called from the bridge's lock
        context. Since dict operations on disjoint keys are safe in CPython
        (GIL-protected), no additional lock is used. If porting to a non-GIL
        runtime, a lock would be needed.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9526):
        """Initialize the UDP inbound transport.

        Creates the UDP socket and configures it with SO_REUSEADDR and a
        1-second receive timeout. The socket is not bound until start() is
        called.

        Args:
            host: Local IP address to bind to. Defaults to "127.0.0.1"
                (localhost only). Use "0.0.0.0" to accept from all interfaces.
            port: Local UDP port number to bind to. Defaults to 9526, the
                standard CSC client port.
        """
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.settimeout(1.0)
        self._running = False
        self._thread = None
        self._on_data = None
        # Track known client addresses
        self._clients: Dict[tuple, bool] = {}

    def start(self, on_data: Callable[[bytes, ClientID], None]) -> None:
        """Bind the socket and start the background listener thread.

        Binds the UDP socket to (self.host, self.port), sets the running flag,
        and spawns the daemon listener thread that calls _listen_loop().

        Args:
            on_data: Callback invoked for each received datagram. Called as
                on_data(raw_bytes, (host, port)) from the listener thread.
                The bridge registers its _on_client_data method here.

        Raises:
            OSError: If the socket cannot be bound (e.g., port already in use
                or insufficient permissions).
        """
        self._on_data = on_data
        self.sock.bind((self.host, self.port))
        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="udp-inbound"
        )
        self._thread.start()

    def _listen_loop(self):
        """Main receive loop running on the listener thread.

        Continuously calls recvfrom() with a 1-second timeout. For each
        received datagram, records the sender address in _clients and invokes
        the on_data callback. Empty datagrams are silently discarded.

        The loop exits when _running is set to False (by stop()) or when an
        unrecoverable OSError occurs while _running is False (indicating the
        socket was closed intentionally).

        Socket timeout exceptions are caught and cause the loop to re-check
        the _running flag, enabling clean shutdown within 1 second of stop()
        being called.
        """
        while self._running:
            if hasattr(self, "check_shutdown") and self.check_shutdown():
                if hasattr(self, "log_shutdown"): self.log_shutdown()
                break
            try:
                data, addr = self.sock.recvfrom(65500)
                if not data:
                    continue
                self._clients[addr] = True
                if self._on_data:
                    self._on_data(data, addr)
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    continue
                break

    def send_to_client(self, client_id: ClientID, data: bytes) -> None:
        """Send a datagram back to a specific CSC client.

        Uses sendto() on the bound socket to deliver data to the client's
        address. OSError exceptions (e.g., client unreachable) are silently
        suppressed since UDP delivery is best-effort.

        Args:
            client_id: The client's (host, port) tuple as originally received
                by recvfrom() and passed to the on_data callback.
            data: Raw bytes to send to the client (typically IRC wire format
                or encrypted CSC payload).
        """
        try:
            self.sock.sendto(data, client_id)
        except OSError:
            pass

    def remove_client(self, client_id: ClientID) -> None:
        """Remove a client from internal tracking.

        Called by the bridge when a session is destroyed (timeout or
        explicit disconnect). Since UDP is connectionless, there is no socket
        to close -- this only removes the address from the _clients dict.

        Args:
            client_id: The client's (host, port) tuple to remove from tracking.
        """
        self._clients.pop(client_id, None)

    def stop(self) -> None:
        """Stop the listener thread and close the UDP socket.

        Sets _running to False, closes the socket (which unblocks any pending
        recvfrom()), and joins the listener thread with a 3-second timeout.
        After this method returns, no further on_data callbacks will be invoked.
        """
        self._running = False
        try:
            self.sock.close()
        except OSError:
            pass
        if self._thread:
            self._thread.join(timeout=3)
