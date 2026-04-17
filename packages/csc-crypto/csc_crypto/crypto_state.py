"""Crypto state machine for a single peer relationship.

CryptoState owns everything about the encryption lifecycle of one
connection: DH exchange, AES key derivation, key_hash computation,
and encrypt/decrypt operations.

Both Connection (server-side) and ClientSession (bridge-side) compose
a CryptoState.  This keeps the crypto state machine in the crypto layer
where it belongs, reusable across server and bridge.

State machine::

    NONE  -->  DH_PENDING  -->  READY
                ^                  |
                |     (reset)      |
                +------------------+

Thread safety: All state transitions are guarded by _lock.  The
_ready_event allows callers to block until encryption is established
(used by bridge; server does not need to block).
"""
import hashlib
import threading
import time

from csc_crypto.crypto import DHExchange, encrypt, decrypt


CRYPTO_NONE = "NONE"
CRYPTO_DH_PENDING = "DH_PENDING"
CRYPTO_READY = "READY"


class CryptoState:
    """Crypto state machine for one peer."""

    __slots__ = (
        "_state",
        "_dh",
        "_aes_key",
        "_key_hash",
        "_ready_event",
        "_lock",
        "_dh_initiated_at",
    )

    def __init__(self):
        self._state: str = CRYPTO_NONE
        self._dh: DHExchange | None = None
        self._aes_key: bytes | None = None
        self._key_hash: bytes | None = None
        self._ready_event: threading.Event = threading.Event()
        self._lock: threading.Lock = threading.Lock()
        self._dh_initiated_at: float = 0.0

    # ------------------------------------------------------------------
    # Read-only access for external integration
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_ready(self) -> bool:
        return self._state == CRYPTO_READY

    @property
    def is_pending(self) -> bool:
        return self._state == CRYPTO_DH_PENDING

    @property
    def is_none(self) -> bool:
        return self._state == CRYPTO_NONE

    @property
    def key_hash(self) -> bytes | None:
        """16-byte key_hash for O(1) lookup.  None if no key set."""
        return self._key_hash

    @property
    def aes_key(self) -> bytes | None:
        """32-byte AES key.  None if no key set."""
        return self._aes_key

    @property
    def dh_initiated_at(self) -> float:
        return self._dh_initiated_at

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def start_dh(self) -> DHExchange:
        """Create a new DH exchange and transition to DH_PENDING.

        Returns the DHExchange so the caller can format and send the
        CRYPTOINIT message via whatever transport it owns.
        """
        with self._lock:
            self._dh = DHExchange()
            self._dh_initiated_at = time.time()
            self._aes_key = None
            self._key_hash = None
            self._ready_event.clear()
            self._state = CRYPTO_DH_PENDING
        return self._dh

    def complete_dh(self, other_public: int) -> bytes:
        """Finish DH with the peer's public key.  Computes shared key,
        sets AES key + key_hash.  Transitions to READY.  Returns key."""
        with self._lock:
            if self._dh is None:
                raise RuntimeError("complete_dh called with no pending DH")
            key = self._dh.compute_shared_key(other_public)
            self._set_key_locked(key)
            self._dh = None
            return key

    def set_key(self, key: bytes) -> None:
        """Set AES key directly (PSK mode or server-side DH completion).
        Transitions to READY."""
        with self._lock:
            self._set_key_locked(key)

    def clear(self) -> None:
        """Clear all crypto state.  Transitions to NONE."""
        with self._lock:
            self._state = CRYPTO_NONE
            self._dh = None
            self._aes_key = None
            self._key_hash = None
            self._dh_initiated_at = 0.0
            self._ready_event.clear()

    # ------------------------------------------------------------------
    # Data operations
    # ------------------------------------------------------------------

    def wrap(self, data: bytes) -> bytes:
        """Encrypt data + prepend 16-byte key_hash header.
        Only works in READY state."""
        if self._state != CRYPTO_READY or self._aes_key is None:
            raise RuntimeError(f"Cannot encrypt: state is {self._state}")
        return self._key_hash + encrypt(self._aes_key, data)

    def unwrap(self, data: bytes) -> bytes:
        """Decrypt data.  Strips key_hash header if present.
        Only works in READY state."""
        if self._state != CRYPTO_READY or self._aes_key is None:
            raise RuntimeError(f"Cannot decrypt: state is {self._state}")
        if len(data) >= 16 and data[:16] == self._key_hash:
            data = data[16:]
        return decrypt(self._aes_key, data)

    def matches_key_hash(self, hash_bytes: bytes) -> bool:
        """Does this CryptoState own the given key_hash?"""
        return self._key_hash is not None and self._key_hash == hash_bytes

    # ------------------------------------------------------------------
    # Blocking wait (bridge uses this; server does not)
    # ------------------------------------------------------------------

    def wait_until_ready(self, timeout: float = 5.0) -> bool:
        """Block until READY or timeout.  Returns True if ready."""
        return self._ready_event.wait(timeout=timeout)

    def dh_timed_out(self, timeout_secs: float = 10.0) -> bool:
        """True if DH is pending and has exceeded timeout."""
        if self._dh is None:
            return False
        return (time.time() - self._dh_initiated_at) > timeout_secs

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _set_key_locked(self, key: bytes) -> None:
        """Set key + hash + state.  Must hold _lock."""
        self._aes_key = key
        self._key_hash = hashlib.sha256(key).digest()[:16]
        self._state = CRYPTO_READY
        self._ready_event.set()
