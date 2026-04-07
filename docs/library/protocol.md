[← Back to README](../README.md)

# Shared Library & Protocol Documentation

The `csc-shared` package provides the foundational modules used by all components of the CSC ecosystem. It implements the core IRC protocol logic, UDP networking stack, and security primitives.

---

## 📦 The `csc-shared` Package

All CSC components depend on this library. It provides:
- **`irc`**: Message parsing, formatting, and RFC 2812 constants.
- **`network`**: The underlying UDP transport and keepalive system.
- **`data`**: Atomic, file-based JSON persistence.
- **`crypto`**: Diffie-Hellman and AES-256-GCM implementation.
- **`channel` & `chat_buffer`**: IRC-style channel management and message logging.
- **`version`**: Sequential file versioning and rollback.

---

## 📡 The IRC-over-UDP Protocol

CSC uses a specialized implementation of **IRC (RFC 2812) over UDP**.

### Why UDP?
- **Lower Latency**: Essential for real-time AI response streams.
- **Statelessness**: Allows for easier recovery from network disruptions or component crashes.
- **Simplicity**: No complex TCP handshake for every connection.

### Message Format
The system uses the standard IRC wire format:
`[:prefix] COMMAND [params...] [:trailing]\r\n`

**The `IRCMessage` Class**:
The `irc.py` module parses raw lines into a structured dataclass:
- `prefix`: The sender (e.g., `Nick!user@host`).
- `command`: The IRC command or numeric reply (e.g., `PRIVMSG` or `001`).
- `params`: A list of space-separated parameters.
- `trailing`: The final parameter, often the message text, prefixed with `:`.

**Example Parse**:
Input: `:Alice PRIVMSG #general :Hello World`
Parsed: `prefix="Alice", command="PRIVMSG", params=["#general"], trailing="Hello World"`

---

## 🏗️ Core Data Structures

### Channels (`channel.py`)
Channels are managed by the `ChannelManager`. Each `Channel` object tracks:
- **Members**: A dictionary of `nick -> {addr, modes, display_nick}`.
- **Modes**: A set of active channel modes (e.g., `+n`, `+t`).
- **Topic**: The current channel topic and its metadata.
- **Bans**: A set of hostmasks or nicks forbidden from the channel.

### Users
Users are tracked by the server's `MessageHandler`.
- **Registration**: Requires both a `NICK` and `USER` command.
- **Modes**: Persistent user-level modes like `+i` (Invisible) and `+o` (Operator).

---

## 🛜 Network Transport (`network.py`)

The `Network` class provides the UDP interface:
- **Default Port**: `9525`
- **MTU & Chunking**: The system uses a 65,500-byte buffer. Messages larger than this are automatically chunked with a 10ms delay between datagrams.
- **Keepalives**: Clients send `PING :keepalive` every 60-120 seconds to maintain presence on the server.
- **Queue Management**: Incoming datagrams are placed in a thread-safe `queue.Queue` to be processed by application-level handlers.

---

## 🔐 Cryptography (`crypto.py`)

For secure communication, CSC implements a "Zero-Trust" transport layer.

### Diffie-Hellman Key Exchange
- **Group**: RFC 3526 Group 14 (2048-bit MODP).
- **Process**:
  1.  Server sends `CRYPTOINIT DH` with prime `p`, generator `g`, and its public key.
  2.  Client replies with `CRYPTOINIT DHREPLY` and its public key.
  3.  Both derive a 32-byte shared secret.

### AES-256-GCM Encryption
Once a key is established:
- **IV**: 12-byte random Initialization Vector per packet.
- **Tag**: 16-byte GCM authentication tag for integrity verification.
- **Heuristic Detection**: The `is_encrypted()` function uses a UTF-8 decoding check to automatically distinguish between plaintext IRC and encrypted blocks.

---

## 💾 Persistent Storage (Source of Truth)

Persistence is handled by the `Data` class and the server's `PersistentStorageManager`.
- **Disk as Source of Truth**: The server re-reads its state from disk if it detects a change in the JSON files, allowing for real-time external configuration.
- **Atomic Renaming**: Writes follow the `tmp -> fsync -> rename` pattern to prevent data corruption.
- **JSON Format**: All data (channels, users, history) is stored in human-readable JSON files.
- **Auto-Sync**: The server triggers a disk sync after every state-changing IRC command (JOIN, PART, NICK, etc.).

---
*The CSC protocol bridges the simplicity of 1980s IRC with the power of modern AI autonomy.*

[Prev: Client Terminal](client.md) | [Next: Setup & Deployment](setup.md)
