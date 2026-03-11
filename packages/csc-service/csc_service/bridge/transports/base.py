"""Abstract base classes for inbound and outbound transports.

This module defines the transport abstraction layer that decouples the
bridge's core logic from specific network protocols. By programming
against these interfaces, the bridge can bridge any combination of
inbound and outbound transports without knowing the underlying protocol.

Architecture:
    The bridge uses two types of transports:

    InboundTransport — Accepts connections from clients (IRC clients over TCP,
        CSC clients over UDP, etc.) and delivers received data to the bridge
        via a callback. Also provides a method to send data back to a specific
        client.

    OutboundTransport — Manages connections to the upstream CSC server. Creates
        one dedicated upstream handle per client session so the server sees each
        proxied client as a unique (host, port) source.

    This separation means:
    - TCPInbound + UDPOutbound = TCP IRC client → UDP CSC server
    - UDPInbound + UDPOutbound = UDP CSC client → UDP CSC server (encrypted proxy)
    - TCPInbound + TCPOutbound = TCP IRC client → TCP server (future)
    - Any new transport (ICMP, WebSocket, etc.) only needs to implement one interface

Type Aliases:
    ClientID: Transport-specific identifier for a connected client. For UDP this
        is a (host, port) tuple. For TCP this is a TCPClientID object.
    UpstreamHandle: Transport-specific handle for a server connection. For UDP
        this is a UDPUpstreamHandle. For TCP this is a TCPUpstreamHandle.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Optional


# Type aliases for clarity
ClientID = Any       # Transport-specific client identifier
UpstreamHandle = Any # Transport-specific upstream connection handle


class InboundTransport(ABC):
    """Accepts connections/datagrams from clients and delivers data to the bridge.

    Implementations of this interface listen for incoming client connections
    (TCP) or datagrams (UDP) and invoke a callback with the raw data and a
    client identifier. The bridge uses the client identifier to look up
    or create a session, then forwards the data upstream.

    The interface also provides send_to_client() for the reverse path —
    delivering server responses back to the originating client.

    Threading Model:
        Implementations typically run a listener thread (started by start())
        that blocks on accept/recvfrom and invokes on_data from that thread.
        The bridge's callback is thread-safe via its session lock.

    Disconnect Signaling:
        To signal a client disconnect, call on_data(b"", client_id). The
        bridge interprets empty data as a disconnect event and destroys
        the session.
    """

    @abstractmethod
    def start(self, on_data: Callable[[bytes, ClientID], None]) -> None:
        """Start listening for client connections/datagrams.

        Args:
            on_data: Callback invoked for each received message. Parameters are
                (raw_bytes, client_id). Called from the listener thread. Send
                b"" as raw_bytes to signal client disconnect.
        """
        ...

    @abstractmethod
    def send_to_client(self, client_id: ClientID, data: bytes) -> None:
        """Send data back to a specific connected client.

        Args:
            client_id: The transport-specific identifier for the target client,
                as originally passed to on_data.
            data: Raw bytes to send. For TCP transports this is sent via
                sendall(). For UDP this is sent via sendto().
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop listening, close all client connections, and release resources.

        After stop() returns, no further on_data callbacks will be invoked.
        All client sockets/connections are closed.
        """
        ...

    @abstractmethod
    def remove_client(self, client_id: ClientID) -> None:
        """Clean up resources for a specific disconnected client.

        Called by the bridge when a session is destroyed (timeout, error,
        or explicit disconnect). Implementations should close the client's
        socket and remove it from internal tracking.

        Args:
            client_id: The transport-specific identifier for the client to remove.
        """
        ...


class OutboundTransport(ABC):
    """Sends data upstream to the CSC server on behalf of proxied clients.

    Each client session gets its own upstream handle (created by
    create_upstream()) so the CSC server sees a unique (host, port)
    for every proxied client. This is essential because the server
    tracks clients by their source address.

    The bridge spawns a server listener thread per session that
    calls recv() in a loop and forwards responses back to the client.

    Threading Model:
        create_upstream() is called from the bridge's callback thread.
        send() can be called from any thread. recv() blocks up to the
        specified timeout and is called from the per-session listener thread.
        close() is called during session teardown.
    """

    @abstractmethod
    def create_upstream(self, session_id: str) -> UpstreamHandle:
        """Create a new upstream connection/socket for a client session.

        Each call creates an independent connection to the server, bound to
        a unique ephemeral port (UDP) or establishing a new TCP connection.
        The returned handle is stored in the ClientSession and used for all
        subsequent send/recv operations for that client.

        Args:
            session_id: UUID string identifying the session. Used as a key
                for internal handle tracking.

        Returns:
            A transport-specific handle object (UDPUpstreamHandle or
            TCPUpstreamHandle) that encapsulates the upstream socket.

        Raises:
            OSError: If the socket cannot be created or connected.
        """
        ...

    @abstractmethod
    def send(self, handle: UpstreamHandle, data: bytes) -> None:
        """Send data to the CSC server through a session's upstream handle.

        Args:
            handle: The upstream handle returned by create_upstream().
            data: Raw bytes to send (typically IRC wire format).
        """
        ...

    @abstractmethod
    def recv(self, handle: UpstreamHandle, timeout: float = 1.0) -> Optional[bytes]:
        """Receive data from the CSC server on a session's upstream handle.

        Blocks for up to timeout seconds waiting for data. Called in a loop
        by the per-session server listener thread.

        Args:
            handle: The upstream handle returned by create_upstream().
            timeout: Maximum seconds to wait for data.

        Returns:
            Raw bytes received from the server, or None if the timeout
            expired with no data.
        """
        ...

    @abstractmethod
    def close(self, handle: UpstreamHandle) -> None:
        """Close an upstream handle and release its resources.

        Called during session teardown. After close(), the handle must not
        be used for send() or recv().

        Args:
            handle: The upstream handle to close.
        """
        ...
