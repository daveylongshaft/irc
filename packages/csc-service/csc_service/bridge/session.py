"""Client session tracking for the bridge proxy.

This module defines the ClientSession dataclass, which represents a single
proxied client connection passing through the bridge. Each session maps
one inbound client (identified by a transport-specific ClientID) to one
outbound upstream handle (a dedicated socket to the CSC server).

The bridge creates one session per connecting client. Sessions track:
    - Which inbound transport the client arrived on (TCP or UDP)
    - The upstream handle used to communicate with the CSC server
    - The client's IRC nick (sniffed from NICK commands in passthrough traffic)
    - Encryption state (DH exchange progress and AES session key)
    - Activity timestamps for keepalive and timeout management

Lifecycle:
    1. Client sends first packet → bridge calls _create_session()
    2. Session gets a dedicated upstream socket via outbound.create_upstream()
    3. A server listener thread is spawned for this session
    4. Traffic flows bidirectionally through the session
    5. On disconnect or timeout, _destroy_session() sends QUIT and closes upstream
"""

import uuid
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ClientSession:
    """Tracks state for a single proxied client connection.

    Each ClientSession represents one client connected through the bridge.
    The session binds together:
        - The client's identity on the inbound side (client_id)
        - The dedicated upstream connection to the CSC server (upstream_handle)
        - Encryption state for this specific client's traffic

    Attributes:
        session_id: Unique UUID string identifying this session. Used as the key
            in the bridge's session tracking dicts and to name the upstream
            listener thread.
        client_id: Transport-specific identifier for the client. For UDP this is
            a (host, port) tuple. For TCP this is a TCPClientID object containing
            the socket, address, and connection counter.
        inbound_name: Class name of the inbound transport that accepted this client
            (e.g., "UDPInbound" or "TCPInbound"). Used to route server responses
            back to the correct transport's send_to_client() method.
        upstream_handle: Transport-specific handle for the outbound connection to
            the CSC server. For UDP this is a UDPUpstreamHandle (dedicated socket
            bound to an ephemeral port). For TCP this is a TCPUpstreamHandle
            (dedicated TCP connection).
        nick: The client's IRC nickname, extracted by sniffing NICK commands as
            they pass through the bridge. Used for logging and the status
            display. None until the first NICK command is observed.
        created_at: Unix timestamp when the session was created. Used by age().
        last_activity: Unix timestamp of the last data sent or received. Updated
            by touch(). Used by idle() and the cleanup loop to detect timeouts.
        aes_key: 32-byte AES-256 key derived from the DH exchange. None until
            encryption is negotiated. When set, all traffic through this session
            is encrypted/decrypted using AES-256-GCM.
        dh_exchange: DHExchange object holding the private key during the DH
            handshake. Set to None after key derivation completes.
        encrypted: Boolean flag indicating whether encryption is active for this
            session. True after successful DH exchange and key derivation.
    """
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    client_id: Any = None
    inbound_name: str = ""
    upstream_handle: Any = None
    nick: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    aes_key: Optional[bytes] = None
    dh_exchange: Any = None
    encrypted: bool = False
    normalizer: Any = None  # Optional[IrcNormalizer]
    control_handler: Any = None # Optional[ControlHandler]
    registration_complete: bool = False
    inbound: Any = None  # InboundTransport object
    outbound: Any = None  # OutboundTransport object
    state: str = "CONNECTED"  # LOBBY, CONNECTING, CONNECTED

    def touch(self):
        """Update last_activity to the current time.

        Called by the bridge whenever data passes through this session
        in either direction (client→server or server→client). The cleanup
        loop uses idle() to detect sessions that haven't had any traffic
        for longer than the session_timeout.
        """
        self.last_activity = time.time()

    def age(self) -> float:
        """Return the number of seconds since this session was created.

        Returns:
            Float representing seconds elapsed since created_at.
        """
        return time.time() - self.created_at

    def idle(self) -> float:
        """Return the number of seconds since the last activity on this session.

        Activity includes any data forwarded in either direction, or keepalive
        pings sent by the bridge. The cleanup loop compares this value
        against session_timeout to decide when to destroy idle sessions.

        Returns:
            Float representing seconds elapsed since last_activity.
        """
        return time.time() - self.last_activity
