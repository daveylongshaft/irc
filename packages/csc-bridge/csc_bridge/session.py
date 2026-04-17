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

from csc_crypto.crypto_state import CryptoState


@dataclass
class ClientSession:
    """Tracks state for a single proxied client connection.

    Each ClientSession represents one client connected through the bridge.
    The session binds together:
        - The client's identity on the inbound side (client_id)
        - The dedicated upstream connection to the CSC server (upstream_handle)
        - Encryption state for this specific client's traffic

    Crypto state is delegated to self.crypto (a CryptoState from csc-crypto).
    This is the same state machine that Connection uses on the server side.

    Attributes:
        session_id: Unique UUID string identifying this session.
        client_id: Transport-specific identifier for the client.
        inbound_name: Class name of the inbound transport.
        upstream_handle: Transport-specific handle for the outbound connection.
        nick: The client's IRC nickname, sniffed from NICK commands.
        created_at: Unix timestamp when the session was created.
        last_activity: Unix timestamp of the last data sent or received.
        crypto: CryptoState managing DH exchange, AES key, and encrypt/decrypt.
    """
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    client_id: Any = None
    inbound_name: str = ""
    upstream_handle: Any = None
    nick: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    crypto: CryptoState = field(default_factory=CryptoState)
    normalizer: Any = None  # Optional[IrcNormalizer]
    control_handler: Any = None # Optional[ControlHandler]
    registration_complete: bool = False
    inbound: Any = None  # InboundTransport object
    outbound: Any = None  # OutboundTransport object
    state: str = "CONNECTED"  # LOBBY, CONNECTING, CONNECTED

    @property
    def encrypted(self) -> bool:
        """Compat: True when crypto is ready."""
        return self.crypto.is_ready

    @property
    def aes_key(self) -> bytes | None:
        """Compat: AES key from crypto state."""
        return self.crypto.aes_key

    @property
    def dh_exchange(self):
        """Compat: pending DH exchange from crypto state."""
        return self.crypto._dh

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
