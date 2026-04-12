"""Cryptographic layer and primitives for CSC transports."""

import hashlib
import os

from csc_network import Network

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


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
    "15728E5A8AACAA68FFFFFFFFFFFFFFFF",
    16,
)
DH_GENERATOR = 2


class Crypto(Network):
    """Layer class inserted between Network and Service."""


class DHExchange:
    """Diffie-Hellman key exchange using RFC 3526 Group 14."""

    def __init__(self, p: int = None, g: int = None):
        self.p = p if p is not None else DH_PRIME
        self.g = g if g is not None else DH_GENERATOR
        self.private = int.from_bytes(os.urandom(32), "big")
        self.public = pow(self.g, self.private, self.p)

    def compute_shared_key(self, other_public: int) -> bytes:
        shared_secret = pow(other_public, self.private, self.p)
        secret_bytes = shared_secret.to_bytes(256, "big")
        return hashlib.sha256(secret_bytes).digest()

    def format_init_message(self) -> str:
        return (
            f"CRYPTOINIT DH {format(self.p, 'x')} "
            f"{format(self.g, 'x')} {format(self.public, 'x')}\r\n"
        )

    def format_reply_message(self) -> str:
        return f"CRYPTOINIT DHREPLY {format(self.public, 'x')}\r\n"

    @staticmethod
    def parse_init_message(line: str) -> tuple[int, int, int]:
        parts = line.strip().split()
        if len(parts) < 5 or parts[0] != "CRYPTOINIT" or parts[1] != "DH":
            raise ValueError(f"Invalid CRYPTOINIT DH message: {line}")
        return (int(parts[2], 16), int(parts[3], 16), int(parts[4], 16))

    @staticmethod
    def parse_reply_message(line: str) -> int:
        parts = line.strip().split()
        if len(parts) < 3 or parts[0] != "CRYPTOINIT" or parts[1] != "DHREPLY":
            raise ValueError(f"Invalid CRYPTOINIT DHREPLY message: {line}")
        return int(parts[2], 16)


def encrypt(key: bytes, plaintext: bytes) -> bytes:
    if not HAS_CRYPTO:
        raise RuntimeError("cryptography library not installed: pip install cryptography")
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    ciphertext = aesgcm.encrypt(iv, plaintext, None)
    return b"\xe0" + iv + ciphertext


def decrypt(key: bytes, data: bytes) -> bytes:
    if not HAS_CRYPTO:
        raise RuntimeError("cryptography library not installed: pip install cryptography")
    if len(data) < 29:
        raise ValueError("Data too short to be encrypted")
    if data[0:1] == b"\xe0":
        data = data[1:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(data[:12], data[12:], None)


def is_encrypted(data: bytes) -> bool:
    if len(data) >= 1 and data[0] == 0xE0:
        return True
    if len(data) < 4:
        return False
    try:
        start = data[:32].decode("utf-8")
        if not start:
            return True
        if start[0] == ":":
            return False
        first_word = start.split()[0].upper()
        if first_word in (
            "NICK",
            "USER",
            "PING",
            "PONG",
            "QUIT",
            "PASS",
            "PRIVMSG",
            "NOTICE",
            "JOIN",
            "PART",
            "KICK",
            "MODE",
            "TOPIC",
            "NAMES",
            "LIST",
            "WHO",
            "OPER",
            "WALLOPS",
            "KILL",
            "ISOP",
            "BUFFER",
            "MOTD",
            "CAP",
            "CRYPTOINIT",
            "SLINK",
            "SLINKACK",
            "SYNCUSER",
            "SYNPART",
            "SYNCNICK",
            "SYNCCHAN",
            "SYNCTOPIC",
            "SYNCMSG",
            "SYNCNOTICE",
            "SYNCMODE",
            "SYNCLINE",
            "SYNCKEY",
            "DESYNC",
            "SQUIT",
            "ERROR",
        ):
            return False
    except (UnicodeDecodeError, IndexError):
        return True
    return True
