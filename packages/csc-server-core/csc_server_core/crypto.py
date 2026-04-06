"""Diffie-Hellman key exchange and AES-256-GCM encryption for the CSC translator.

This module provides the cryptographic primitives used by the translator to
establish encrypted sessions between clients and the CSC server. It implements
two layers:

    1. Key Exchange — Diffie-Hellman (RFC 3526 Group 14, 2048-bit MODP) to
       derive a shared secret without transmitting private keys. Each side
       generates an ephemeral private key, computes a public key, exchanges
       public keys via CRYPTOINIT messages, then independently derives the
       same 32-byte AES-256 key using SHA-256.

    2. Symmetric Encryption — AES-256-GCM (Galois/Counter Mode) for
       authenticated encryption of all subsequent traffic. Each message is
       encrypted with a random 12-byte IV, producing ciphertext with a
       16-byte authentication tag appended.

Protocol Flow:
    1. Translator → Server:  CRYPTOINIT DH <p_hex> <g_hex> <pubkey_hex>\\r\\n
    2. Server → Translator:  CRYPTOINIT DHREPLY <pubkey_hex>\\r\\n
    3. Both sides compute:   shared_secret = other_pub ^ private mod p
    4. Both sides derive:    aes_key = SHA-256(shared_secret as 256 bytes)
    5. All subsequent data:  [12-byte IV][AES-GCM ciphertext][16-byte tag]

Wire Format (encrypted messages):
    Bytes 0-11:   Random IV (initialization vector / nonce)
    Bytes 12-N:   AES-GCM ciphertext (same length as plaintext)
    Bytes N-N+16: GCM authentication tag

    Total overhead per message: 28 bytes (12 IV + 16 tag)

Dependencies:
    - hashlib (stdlib) for SHA-256 key derivation
    - os (stdlib) for cryptographically secure random bytes
    - cryptography (pip install cryptography) for AES-GCM — optional at import
      time, required at encrypt/decrypt time. The HAS_CRYPTO flag indicates
      availability.

Module Constants:
    DH_PRIME: The 2048-bit MODP prime from RFC 3526 Group 14. This is a
        well-known safe prime used extensively in TLS and SSH.
    DH_GENERATOR: The generator value (2) for the DH group.
    HAS_CRYPTO: Boolean indicating whether the cryptography library is installed.
"""

import os
import hashlib

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

# RFC 3526 Group 14 — 2048-bit MODP prime
# This is a well-known safe prime (p = 2q + 1 where q is also prime).
# Used in TLS, SSH, and IKE. Provides ~112 bits of security.
DH_PRIME = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AACAA68FFFFFFFFFFFFFFFF", 16
)
DH_GENERATOR = 2


class DHExchange:
    """Diffie-Hellman key exchange using RFC 3526 Group 14 (2048-bit).

    Generates an ephemeral private/public key pair on construction. The public
    key is exchanged with the remote side via CRYPTOINIT messages. Once both
    sides have exchanged public keys, compute_shared_key() derives a 32-byte
    AES-256 key from the shared secret.

    Each DHExchange instance is single-use: create one per session, exchange
    keys, derive the shared key, then discard the instance. The private key
    is never transmitted.

    Attributes:
        private: Random 256-bit integer used as the DH private key. Generated
            from os.urandom(32) for cryptographic security. Never leaves this
            process.
        public: The DH public key (g^private mod p). Transmitted to the remote
            side during key exchange. Safe to expose — recovering the private
            key from the public key requires solving the discrete logarithm
            problem.

    Example:
        >>> alice = DHExchange()
        >>> bob = DHExchange()
        >>> # Exchange public keys (via CRYPTOINIT messages)
        >>> key_a = alice.compute_shared_key(bob.public)
        >>> key_b = bob.compute_shared_key(alice.public)
        >>> assert key_a == key_b  # Both derive the same 32-byte AES key
    """

    def __init__(self, p: int = None, g: int = None):
        """Generate a new ephemeral DH key pair.

        The private key is 256 bits of cryptographically secure randomness.
        The public key is computed as g^private mod p.

        Args:
            p: Optional custom prime. If None, uses RFC 3526 Group 14 prime.
            g: Optional custom generator. If None, uses 2.
        """
        self.p = p if p is not None else DH_PRIME
        self.g = g if g is not None else DH_GENERATOR
        self.private = int.from_bytes(os.urandom(32), "big")
        self.public = pow(self.g, self.private, self.p)

    def compute_shared_key(self, other_public: int) -> bytes:
        """Derive a 32-byte AES-256 key from the other side's public key.

        Computes the DH shared secret (other_public^private mod p), converts
        it to a 256-byte big-endian integer, then hashes with SHA-256 to
        produce a uniform 32-byte key suitable for AES-256.

        Args:
            other_public: The remote side's DH public key as an integer,
                received via CRYPTOINIT DH or CRYPTOINIT DHREPLY message.

        Returns:
            32-byte key (bytes) for use with AES-256-GCM encrypt/decrypt.
        """
        shared_secret = pow(other_public, self.private, self.p)
        secret_bytes = shared_secret.to_bytes(256, "big")
        return hashlib.sha256(secret_bytes).digest()

    def format_init_message(self) -> str:
        """Format the CRYPTOINIT DH message for initiating key exchange.

        Produces an IRC-style command containing the DH parameters (prime,
        generator) and this side's public key, all hex-encoded. Sent by the
        translator to the server as the first message on a new session.

        Returns:
            String in the format: "CRYPTOINIT DH <p_hex> <g_hex> <pubkey_hex>\\r\\n"
        """
        p_hex = format(self.p, "x")
        g_hex = format(self.g, "x")
        pub_hex = format(self.public, "x")
        return f"CRYPTOINIT DH {p_hex} {g_hex} {pub_hex}\r\n"

    def format_reply_message(self) -> str:
        """Format the CRYPTOINIT DHREPLY message for completing key exchange.

        Sent by the server in response to a CRYPTOINIT DH message. Contains
        only the server's public key since both sides already know p and g.

        Returns:
            String in the format: "CRYPTOINIT DHREPLY <pubkey_hex>\\r\\n"
        """
        pub_hex = format(self.public, "x")
        return f"CRYPTOINIT DHREPLY {pub_hex}\r\n"

    @staticmethod
    def parse_init_message(line: str) -> tuple:
        """Parse a CRYPTOINIT DH message into its components.

        Args:
            line: Raw IRC line containing the CRYPTOINIT DH command.

        Returns:
            Tuple of (prime, generator, public_key) as Python integers.

        Raises:
            ValueError: If the line is not a valid CRYPTOINIT DH message
                (wrong prefix, missing fields, or non-hex values).
        """
        parts = line.strip().split()
        if len(parts) < 5 or parts[0] != "CRYPTOINIT" or parts[1] != "DH":
            raise ValueError(f"Invalid CRYPTOINIT DH message: {line}")
        p = int(parts[2], 16)
        g = int(parts[3], 16)
        pubkey = int(parts[4], 16)
        return (p, g, pubkey)

    @staticmethod
    def parse_reply_message(line: str) -> int:
        """Parse a CRYPTOINIT DHREPLY message to extract the public key.

        Args:
            line: Raw IRC line containing the CRYPTOINIT DHREPLY command.

        Returns:
            The remote side's DH public key as a Python integer.

        Raises:
            ValueError: If the line is not a valid CRYPTOINIT DHREPLY message.
        """
        parts = line.strip().split()
        if len(parts) < 3 or parts[0] != "CRYPTOINIT" or parts[1] != "DHREPLY":
            raise ValueError(f"Invalid CRYPTOINIT DHREPLY message: {line}")
        return int(parts[2], 16)


def encrypt(key: bytes, plaintext: bytes) -> bytes:
    """Encrypt plaintext using AES-256-GCM with a random IV.

    Produces authenticated ciphertext that provides both confidentiality and
    integrity. The output format is [12-byte IV][ciphertext][16-byte GCM tag],
    adding 28 bytes of overhead to the plaintext length.

    Args:
        key: 32-byte AES-256 key from DHExchange.compute_shared_key().
        plaintext: Raw bytes to encrypt (typically UTF-8 IRC messages).

    Returns:
        Encrypted bytes in the format [IV][ciphertext][tag]. Pass this
        directly to decrypt() to recover the plaintext.

    Raises:
        RuntimeError: If the cryptography library is not installed.
    """
    if not HAS_CRYPTO:
        raise RuntimeError("cryptography library not installed: pip install cryptography")
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    ciphertext = aesgcm.encrypt(iv, plaintext, None)
    return iv + ciphertext


def decrypt(key: bytes, data: bytes) -> bytes:
    """Decrypt AES-256-GCM data produced by encrypt().

    Verifies the GCM authentication tag before returning plaintext. If the
    data has been tampered with, an InvalidTag exception is raised by the
    cryptography library.

    Args:
        key: 32-byte AES-256 key (must match the key used for encryption).
        data: Encrypted bytes in [12-byte IV][ciphertext][16-byte tag] format.

    Returns:
        Decrypted plaintext bytes.

    Raises:
        RuntimeError: If the cryptography library is not installed.
        ValueError: If data is shorter than 28 bytes (minimum for IV + tag).
        cryptography.exceptions.InvalidTag: If the authentication tag
            verification fails (data corrupted or wrong key).
    """
    if not HAS_CRYPTO:
        raise RuntimeError("cryptography library not installed: pip install cryptography")
    if len(data) < 28:  # 12 IV + 16 tag minimum
        raise ValueError("Data too short to be encrypted")
    aesgcm = AESGCM(key)
    iv = data[:12]
    ciphertext = data[12:]
    return aesgcm.decrypt(iv, ciphertext, None)


def is_encrypted(data: bytes) -> bool:
    """Heuristic to detect whether a datagram contains encrypted or plaintext data.

    Used by the translator to determine whether incoming data needs decryption.
    IRC plaintext always starts with recognizable ASCII patterns (a colon for
    prefixed messages, or an uppercase command like NICK, PRIVMSG, etc.).
    Encrypted data starts with a random 12-byte IV that almost certainly
    contains non-ASCII bytes or fails UTF-8 decoding.

    Detection logic:
        1. If data < 4 bytes, return False (too short to be meaningful)
        2. Try to decode first 32 bytes as UTF-8
        3. If first char is ':' → plaintext IRC → return False
        4. If first word matches a known IRC or S2S command → return False
        5. If UTF-8 decode fails → likely encrypted → return True
        6. If none of the above match → likely encrypted → return True

    Args:
        data: Raw bytes received from a socket.

    Returns:
        True if the data appears to be encrypted, False if it looks like
        plaintext IRC.
    """
    if len(data) < 4:
        return False
    try:
        start = data[:32].decode("utf-8")
        if not start:
            return True
        if start[0] == ":":
            return False
        
        # Check first word against known IRC/S2S commands
        first_word = start.split()[0].upper()
        if first_word in ("NICK", "USER", "PING", "PONG", "QUIT", "PASS",
                         "PRIVMSG", "NOTICE", "JOIN", "PART", "KICK",
                         "MODE", "TOPIC", "NAMES", "LIST", "WHO",
                         "OPER", "WALLOPS", "KILL", "ISOP", "BUFFER",
                         "MOTD", "CAP", "CRYPTOINIT", "SLINK", "SLINKACK",
                         "SYNCUSER", "SYNPART", "SYNCNICK", "SYNCCHAN",
                         "SYNCTOPIC", "SYNCMSG", "SYNCNOTICE", "SYNCMODE",
                         "SYNCLINE", "SYNCKEY", "DESYNC",
                         "SQUIT", "ERROR"):
            return False
    except (UnicodeDecodeError, IndexError):
        return True
    return True
