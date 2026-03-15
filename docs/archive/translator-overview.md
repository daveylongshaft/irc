# CSC Translator -- Architecture Overview

## What the Translator Does

The CSC Translator is a **transport bridge and encryption proxy** that sits between IRC/CSC clients and the CSC server. It solves two core problems:

1. **Protocol bridging**: Standard IRC clients speak TCP, but the CSC server speaks UDP. The translator accepts TCP connections from IRC clients, converts the stream into UDP datagrams, and forwards them to the CSC server -- and vice versa for server responses.

2. **Encryption proxying**: CSC clients that connect over UDP can negotiate end-to-end encryption via a Diffie-Hellman key exchange. The translator manages per-session AES-256-GCM encryption state, transparently encrypting and decrypting traffic as it passes through.

The translator is fully transparent to both sides: the IRC client sees a standard IRC server on TCP port 6667, and the CSC server sees individual UDP clients on unique ephemeral ports.

---

## The 3-Layer Design

The CSC system uses a layered communication architecture. The translator operates at the boundary between layers 2 and 3:

```
Layer 1: Command Language (IRC)
    IRC commands (NICK, PRIVMSG, JOIN, etc.) form the application protocol.
    Both standard IRC clients and CSC-aware clients speak this language.
            |
            v
Layer 2: Communication Protocol (IRC Wire Format)
    Messages are encoded as RFC 1459/2812 wire format:
        [:prefix] COMMAND [params...] [:trailing]\r\n
    TCP transports deliver these as a byte stream (line-buffered on \r\n).
    UDP transports deliver these as individual datagrams.
            |
            v
Layer 3: Encrypted Transport (Translator)
    The translator sits here, performing:
      - Transport conversion (TCP stream <-> UDP datagrams)
      - Per-session encryption (AES-256-GCM after DH key exchange)
      - Session multiplexing (one upstream socket per client)
      - Keepalive management and session timeout cleanup
```

---

## Data Flow

### TCP-to-UDP Bridging (IRC Client to CSC Server)

This is the primary use case: an unmodified IRC client (mIRC, HexChat, irssi, etc.) connects to the translator over TCP, and the translator relays traffic to the CSC server over UDP.

```
IRC Client (TCP)                  Translator                     CSC Server (UDP)
     |                               |                                |
     |--- TCP connect to :6667 ----->|                                |
     |                               |-- create session S1            |
     |                               |-- bind ephemeral UDP port P1   |
     |                               |-- spawn upstream listener      |
     |                               |                                |
     |--- NICK alice\r\n ----------->|                                |
     |                               |-- sniff nick "alice"           |
     |                               |-- UDP sendto(:9525) from P1 -->|
     |                               |                                |
     |                               |<-- UDP response from :9525 ----|
     |<-- :csc-server 001 alice -----|                                |
     |                               |                                |
     |--- PRIVMSG #ch :hello\r\n --->|                                |
     |                               |-- UDP sendto(:9525) from P1 -->|
     |                               |                                |
     |--- TCP disconnect ----------->|                                |
     |                               |-- QUIT :Translator closed ---->|
     |                               |-- close UDP socket P1          |
     |                               |-- destroy session S1           |
```

### UDP-to-UDP Proxying (CSC Client to CSC Server)

A CSC-native client connects over UDP. The translator acts as an encryption proxy, adding a DH key exchange and AES-256-GCM encryption layer. Even without encryption enabled, the proxy isolates client addresses from the server.

```
CSC Client (UDP)                  Translator                     CSC Server (UDP)
     |                               |                                |
     |--- UDP datagram to :9526 ---->|                                |
     |                               |-- create session S2            |
     |                               |-- bind ephemeral UDP port P2   |
     |                               |-- spawn upstream listener      |
     |                               |                                |
     |--- NICK bob\r\n ------------->|                                |
     |                               |-- sniff nick "bob"             |
     |                               |-- UDP sendto(:9525) from P2 -->|
     |                               |                                |
     |                               |<-- UDP response from :9525 ----|
     |<-- :csc-server 001 bob ------|                                |
     |                               |                                |
```

### Encryption Negotiation Flow (Future / Planned)

When encryption is enabled, the translator initiates a CRYPTOINIT handshake with the CSC client before forwarding traffic:

```
CSC Client                        Translator
     |                               |
     |--- first datagram ----------->|
     |                               |-- create DH keypair
     |<-- CRYPTOINIT DH p g pub -----|
     |                               |
     |--- CRYPTOINIT DHREPLY pub' -->|
     |                               |-- compute shared_secret
     |                               |-- derive AES-256 key = SHA256(shared_secret)
     |                               |-- session.encrypted = True
     |                               |
     |=== all subsequent traffic is AES-256-GCM encrypted ===|
```

The CRYPTOINIT protocol uses:
- **DH parameters**: RFC 3526 Group 14 (2048-bit MODP prime), generator g=2
- **Key derivation**: SHA-256 hash of the raw DH shared secret (256-byte big-endian integer)
- **Encryption**: AES-256-GCM with 12-byte random IV, 16-byte authentication tag
- **Wire format**: `[12-byte IV][ciphertext + 16-byte GCM tag]`

The `is_encrypted()` heuristic distinguishes encrypted packets from plaintext IRC by checking whether the first bytes are valid ASCII/UTF-8 IRC command prefixes.

## Gateway Mode

The translator can act as a protocol gateway to bridge dialect differences between CSC and standard RFC 2812 IRC. This is controlled by the `--gateway-mode` CLI argument.

### Mode A: CSC Client -> Standard IRC Server (`csc-to-irc`)

A native CSC client connects to the translator, which forwards to a standard IRC network (e.g., Libera. Chat, Undernet).

**Normalization:**
- **Filters** CSC-only commands (`ISOP`, `BUFFER`, `AI`) and sends a local `NOTICE` to the client.
- **Translates** legacy `IDENT` and `RENAME` commands into standard `NICK`/`USER` sequences.
- **Passthrough** for all standard IRC commands.

### Mode B: Standard IRC Client -> CSC Server (`irc-to-csc`)

A standard IRC client (HexChat, irssi) connects to the translator, which forwards to the CSC server.

**Normalization:**
- **Injects** `RPL_ISUPPORT` (005) after the welcome burst (004) so the client knows the server's features.
- **Intercepts** `CAP` negotiation and replies with `NAK` locally (since CSC server doesn't support CAP).
- **Intercepts** `AUTHENTICATE` and replies with error locally.
- **Passthrough** for all other commands.

## Daemon Mode (BNC)

The translator can run as a standalone **Bouncer (BNC)**, allowing multiple clients to connect, authenticate, and manage their own upstream connections dynamically.

### Architecture

1.  **Lobby State**: Clients connect to the daemon port (e.g., 9520) and authenticate. They are placed in a "Lobby" where they interact with the translator itself (acting as a mock IRC server) via `/trans` commands.
2.  **Dynamic Connection**: Users issue commands like `/trans connect udp:rsa:csc:1.2.3.4:9525` to establish an upstream connection.
3.  **Proxy State**: Once connected, the session transitions to "Proxy" mode, forwarding traffic bidirectionally.
4.  **Control**: Users can manage history and favorites.

### Command Syntax

- `/trans connect <proto>:<enc>:<dialect>:<host>:<port>`
  - `proto`: `tcp` or `udp`
  - `enc`: `plain` (future: `rsa`)
  - `dialect`: `csc` or `rfc`
- `/trans history`
- `/trans fav <alias>`
- `/trans menu`

---

## Threading Model

The translator uses a multi-threaded architecture. All threads are daemon threads, so they terminate automatically when the main process exits.

```
Main Thread
  |
  |-- console input loop (status, quit, help commands)
  |
  +-- [per inbound transport]
  |     |
  |     +-- TCPInbound
  |     |     |-- tcp-accept thread (accepts new TCP connections)
  |     |     +-- tcp-client-N thread (one per TCP client, reads lines)
  |     |
  |     +-- UDPInbound
  |           |-- udp-inbound thread (recvfrom loop)
  |
  +-- keepalive thread
  |     (every 30s, sends PING :keepalive to sessions idle > 45s)
  |
  +-- cleanup thread
  |     (every 15s, destroys sessions idle > session_timeout)
  |
  +-- [per session]
        |-- upstream-XXXXXXXX thread (recv loop from CSC server)
```

### Thread Inventory

| Thread Name | Created By | Purpose | Lifetime |
|---|---|---|---|
| `tcp-accept` | `TCPInbound.start()` | Accept new TCP connections | Transport lifetime |
| `tcp-client-N` | `TCPInbound._accept_loop()` | Read IRC lines from one TCP client | Client connection lifetime |
| `udp-inbound` | `UDPInbound.start()` | Receive UDP datagrams from all UDP clients | Transport lifetime |
| `upstream-XXXXXXXX` | `Translator._create_session()` | Receive responses from CSC server for one session | Session lifetime |
| `keepalive` | `Translator.start()` | Send keepalive PINGs to idle sessions | Translator lifetime |
| `cleanup` | `Translator.start()` | Destroy timed-out sessions | Translator lifetime |
| Main thread | Process start | Console I/O, signal handling | Process lifetime |

### Thread Safety

The `Translator` class uses a single `threading.Lock` (`_lock`) to protect:
- `_sessions` dict (session_id -> ClientSession)
- `_client_to_session` dict (client_id -> ClientSession)

The `TCPInbound` class uses its own `threading.Lock` (`_lock`) to protect:
- `_clients` dict (conn_id -> TCPClientID)
- `_conn_counter` integer

Individual `ClientSession` fields (nick, last_activity, aes_key, etc.) are updated without locks from their owning threads. The `touch()` method performs a simple float assignment which is atomic in CPython.

---

## Session Lifecycle

```
                     +------------------+
                     |   Client sends   |
                     |  first packet    |
                     +--------+---------+
                              |
                              v
                     +------------------+
                     | _create_session  |
                     | - assign UUID    |
                     | - create upstream|
                     |   socket (bind   |
                     |   ephemeral port)|
                     | - spawn upstream |
                     |   listener thread|
                     +--------+---------+
                              |
                              v
                     +------------------+
                     |  Active Traffic  |
                     | - client->server |
                     |   via _forward_  |
                     |   to_server()    |
                     | - server->client |
                     |   via _forward_  |
                     |   to_client()    |
                     | - nick sniffed   |
                     |   from NICK cmds |
                     | - touch() on     |
                     |   every packet   |
                     +--------+---------+
                              |
              +---------------+----------------+
              |               |                |
              v               v                v
     +--------+------+ +-----+------+ +-------+--------+
     | TCP disconnect | | idle >     | | upstream error |
     | (empty data)   | | timeout    | | (recv fails)   |
     +--------+------+ +-----+------+ +-------+--------+
              |               |                |
              v               v                v
                     +------------------+
                     | _destroy_session |
                     | - send QUIT to   |
                     |   CSC server     |
                     | - close upstream |
                     |   socket         |
                     | - remove from    |
                     |   session dicts  |
                     | - remove_client  |
                     |   on inbound     |
                     |   transport      |
                     +------------------+
```

### Session States

1. **Created**: `_create_session()` allocates the session, creates the upstream handle, and spawns the listener. The session is immediately added to tracking dicts.

2. **Active**: Data flows bidirectionally. Every packet in either direction calls `touch()` to reset the idle timer. The `_sniff_nick()` method passively extracts the IRC NICK from passthrough traffic for logging and status display.

3. **Destroyed**: Triggered by TCP disconnect (empty data callback), session timeout (cleanup loop), or upstream recv failure. `_destroy_session()` sends `QUIT :Translator session closed\r\n` to the server and closes the upstream socket.

### Timeout Configuration

- **Keepalive interval**: 30 seconds between checks; sends `PING :keepalive` to sessions idle for more than 45 seconds
- **Cleanup interval**: 15 seconds between sweeps
- **Session timeout**: Configurable (default 300 seconds / 5 minutes); sessions with `idle() > session_timeout` are destroyed

---

## How Encryption Works

Encryption in the translator is designed but not yet fully wired into the forwarding path (the `_forward_to_server` and `_forward_to_client` methods contain TODO comments for encryption/decryption). The cryptographic primitives are fully implemented in `crypto.py`.

### Diffie-Hellman Key Exchange

1. The translator creates a `DHExchange` object, which generates a private key (256-bit random) and computes the public key: `public = g^private mod p`.

2. The translator sends a `CRYPTOINIT DH` message containing the prime `p`, generator `g`, and its public key (all hex-encoded).

3. The client responds with `CRYPTOINIT DHREPLY` containing its own public key.

4. Both sides compute the shared secret: `shared = other_public^private mod p`.

5. The 32-byte AES-256 key is derived: `key = SHA-256(shared_secret_as_256_bytes)`.

6. The `DHExchange` object is discarded (set to `None`) and only the `aes_key` is retained on the session.

### DH Parameters

- **Group**: RFC 3526 Group 14 (2048-bit MODP)
- **Prime**: Standard 2048-bit prime from RFC 3526
- **Generator**: 2
- **Private key**: 256 bits of `os.urandom()`

### AES-256-GCM Encryption

Once the key is established:

- **encrypt(key, plaintext)**: Generates a 12-byte random IV, encrypts with AES-256-GCM (no AAD), returns `IV || ciphertext || tag` (IV is 12 bytes, tag is 16 bytes appended to ciphertext by the AESGCM library).

- **decrypt(key, data)**: Splits the first 12 bytes as IV, decrypts the remainder with AES-256-GCM. Raises `ValueError` if data is shorter than 28 bytes (12 IV + 16 tag minimum).

- **is_encrypted(data)**: Heuristic detection -- attempts to decode the first 20 bytes as UTF-8 and checks if they look like a valid IRC command prefix (`:` for server prefix, or uppercase IRC command name). If they do, the data is plaintext; otherwise, it is assumed to be encrypted.

### Dependency

Encryption requires the `cryptography` Python package (`pip install cryptography`). If not installed, `HAS_CRYPTO` is set to `False` and `encrypt()`/`decrypt()` raise `RuntimeError`.
