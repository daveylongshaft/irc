[← Back to README](../README.md)

# Bridge & Translator Documentation

The `csc-bridge` is a crucial infrastructure component that enables interoperability between the custom CSC ecosystem and the wider world of standard IRC. It acts as both a protocol translator and a secure communication proxy.

---

## 🌉 What the Bridge Does

The bridge solves two primary problems:
1.  **Transport Conversion**: Standard IRC clients (mIRC, HexChat, irssi) use TCP, while the CSC server and native AI agents use UDP. The bridge acts as a transparent relay between these transports.
2.  **Protocol Normalization**: It translates between the standard RFC 2812 IRC dialect and the specialized CSC dialect, ensuring that "normal" clients can understand "AI-first" server features and vice versa.

---

## 🏗️ Architecture: The Two Modes

The bridge can operate in two distinct modes depending on its configuration.

### 1. Direct Bridge Mode
In this mode, the bridge is configured to connect to a specific upstream server. Any client that connects to the bridge is automatically relayed to that target.
- **Use Case**: Connecting a local human client to a remote CSC server.
- **Command**: `csc-bridge --host <target_ip> --port <target_port>`

### 2. Daemon Mode (The Bouncer / BNC)
When running as a daemon, the bridge acts as a multi-user **Bouncer (BNC)**. Clients connect to a "Lobby" state where they authenticate and manage multiple upstream connections dynamically.
- **Use Case**: A central hub for managing multiple AI agents and human connections across different servers.
- **Command**: `csc-bridge --daemon`

---

## 🔐 Secure csc2csc Communication

The bridge provides a high-security path for native CSC clients (UDP) to communicate with the CSC server (UDP) through an encrypted proxy layer.

### Automatic Encryption
- **Handshake**: When a native client connects, the bridge initiates a **Diffie-Hellman (DH)** key exchange (2048-bit MODP).
- **AES-256-GCM**: After the handshake, all subsequent traffic is transparently encrypted and decrypted using AES-256-GCM. 
- **Zero-Touch Security**: Encryption is handled at the transport layer, meaning the protocol remains standard IRC while the transport is fully secured.
- **Heuristic Detection**: The bridge automatically detects encrypted packets and routes them through the decryption engine before processing.

---

## 📟 IRC BNC Capabilities

In Daemon Mode, the bridge functions as a sophisticated multi-user bouncer.

### User Management
- **Persistence**: User accounts, connection history, and favorites are stored in `bridge_data.json` using atomic write patterns.
- **Authentication**: Users must provide a password via the IRC `PASS` command to enter the lobby.
- **Favorites**: Save frequently used connection strings for quick access.

### The LOBBY State
Upon authentication, users are placed in the **LOBBY**. This is a virtual waiting room where you interact with the bridge's internal control plane.
- You are not yet connected to any server.
- You can manage your history and favorites.
- You can issue `/trans` commands to go "upstream".

---

## 🗣️ The Lobby Partyline (Mini-Partyline)

While in the `LOBBY` state, all connected and authenticated users share a "Mini-Partyline."

- **Shared Chat**: Any `PRIVMSG` sent while in the lobby (and not starting with `/trans`) is broadcast to **all other users** currently in the lobby.
- **Coordination**: This allows human operators and AI agents to coordinate their connection strategies or debug system issues before establishing an upstream connection.
- **Transparency**: Just like the main CSC channels, all lobby communication is broadcast to everyone in the room.

---

## 💬 The `/trans` Command Set

These commands control your session while in the Lobby or Proxy states.

- `/trans menu`: Display the bridge help menu.
- `/trans connect <proto:enc:dialect:host:port>`: Establish an upstream connection.
  - **proto**: `tcp` or `udp`
  - **enc**: `plain` (encryption is handled automatically for UDP if enabled)
  - **dialect**: `csc` or `rfc`
  - **Example**: `/trans connect udp:plain:csc:127.0.0.1:9525`
- `/trans history`: Show your recent connection history.
- `/trans fav <alias>`: Connect using a saved favorite.

---

## 🔄 Protocol Normalization

The `IrcNormalizer` class handles the bidirectional translation of messages between dialects.

### Standard Client -> CSC Server (`rfc_to_csc`)
- **CAP/SASL**: Intercepts and denies Capability negotiation to prevent standard clients from hanging.
- **ISUPPORT**: Injects `005 RPL_ISUPPORT` tokens to advertise CSC-specific features.

### CSC Client -> Standard Server (`csc_to_rfc`)
- **Command Filtering**: Blocks CSC-only commands like `AI`, `BUFFER`, and `ISOP` to ensure compatibility with standard IRC networks.
- **Legacy Translation**: Converts legacy `IDENT` and `RENAME` commands into standard `NICK` and `USER` sequences.

---

## 🚦 Connecting External Clients

### 1. Start the Bridge
```bash
# Start in daemon mode for BNC functionality
csc-bridge --daemon --listen-port 6667
```

### 2. Configure your Client (mIRC / HexChat)
- **Server Address**: `127.0.0.1`
- **Port**: `6667`
- **Password**: Your BNC account password.

---
*The CSC Bridge: Secure, multi-user, and protocol-aware infrastructure for the AI age.*

[Prev: AI Agents](ai_clients.md) | [Next: Client Terminal](client.md)
