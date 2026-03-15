# Translator App Implementation Plan

## Overview

A standalone proxy/bridge between clients and the CSC server, providing:
- **Transport bridging**: Accept on TCP and/or UDP, forward on TCP and/or UDP (any combination)
- **Encryption**: DH key exchange → AES-256-GCM for all forwarded traffic
- **Protocol bridging**: Standard IRC clients (TCP) can reach the UDP-only CSC server
- **CLI-configurable**: All ports and transports specified via command-line args

## Architecture

```
                         ┌─────────────────────────────┐
IRC Client (TCP) ──────> │                             │
CSC Client (UDP) ──────> │  TRANSLATOR                 │ ──> UDP to CSC Server
                         │                             │ ──> TCP (future servers)
                         │  in: tcp/udp + port         │
                         │  out: tcp/udp + port        │
                         │  DH + AES-256-GCM           │
                         └─────────────────────────────┘
```

Each connected client gets its own upstream socket so the CSC server sees unique (host, port) per client.

## Command-Line Interface

```
python main.py --intcp 6667 --inudp 9526 --outudp 127.0.0.1:9525
python main.py --intcp 6667 --outudp 192.168.1.10:9525
python main.py --intcp 6667 --inudp 9526 --outtcp 10.0.0.5:9525 --outudp 127.0.0.1:9525
```

Args:
- `--intcp [host:]port` — Listen for TCP IRC clients (default host: 127.0.0.1)
- `--inudp [host:]port` — Listen for UDP CSC clients (default host: 127.0.0.1)
- `--outtcp host:port` — Forward to server via TCP
- `--outudp host:port` — Forward to server via UDP
- `--no-encrypt` — Disable encryption (plaintext passthrough, for dev/debug)
- `--config path` — Config file (overridden by CLI args)

At least one `--in*` and one `--out*` is required.

## File Structure

```
client-server-commander/
  translator/
    __init__.py              # Path setup
    main.py                  # Entry point, argparse, launch
    translator.py            # Core orchestrator, session management
    transports/
      __init__.py
      base.py                # Abstract InboundTransport / OutboundTransport
      tcp_inbound.py         # TCP listener, per-connection line buffering
      udp_inbound.py         # UDP listener
      tcp_outbound.py        # TCP sender
      udp_outbound.py        # UDP sender (per-session ephemeral socket)
    crypto.py                # DH exchange + AES-256-GCM encrypt/decrypt
    session.py               # ClientSession dataclass
    translator_config.json   # Default config
    # Copied shared modules:
    root.py
    log.py
    data.py
    irc.py
    version.py
    network.py
```

## Transport Abstraction

```python
class InboundTransport(ABC):
    def start(self, on_data: Callable[[bytes, ClientID], None]) -> None: ...
    def send_to_client(self, client_id: ClientID, data: bytes) -> None: ...
    def stop(self) -> None: ...

class OutboundTransport(ABC):
    def create_upstream(self, session_id: str) -> UpstreamHandle: ...
    def send(self, handle: UpstreamHandle, data: bytes) -> None: ...
    def recv(self, handle: UpstreamHandle, timeout: float) -> Optional[bytes]: ...
    def close(self, handle: UpstreamHandle) -> None: ...
```

Any inbound talks to any outbound without knowing the transport.

## Session Model

```python
@dataclass
class ClientSession:
    session_id: str              # UUID
    client_id: Any               # Transport-specific client identifier
    inbound_transport: str       # "tcp" or "udp"
    upstream_handle: Any         # Outbound transport handle
    nick: Optional[str]          # Sniffed from NICK command
    created_at: float
    last_activity: float
    aes_key: Optional[bytes]     # 32-byte AES-256 key after DH
    dh_exchange: Optional[Any]   # During negotiation
    encrypted: bool              # Whether encryption is active
```

## DH Key Exchange Protocol

Happens immediately on new connection, before NICK/USER:

```
1. Translator -> Server:  CRYPTOINIT DH <p_hex> <g_hex> <pubkey_hex>\r\n
2. Server -> Translator:  CRYPTOINIT DHREPLY <pubkey_hex>\r\n
3. Both derive:           aes_key = SHA-256(shared_secret)
4. All subsequent traffic: [12-byte IV][AES-GCM ciphertext][16-byte tag]
```

- DH Group: RFC 3526 Group 14 (2048-bit MODP)
- Key derivation: SHA-256 of raw shared secret → 32-byte AES-256 key
- AES mode: GCM (authenticated, no padding needed)
- IV: 12 bytes random per message, prepended to ciphertext
- Tag: 16 bytes, appended by GCM

If `--no-encrypt`, skip DH and pass through plaintext. Phase 1 uses `--no-encrypt` since the server doesn't support CRYPTOINIT yet.

## Threading Model

```
Main Thread: argparse, config, launch transports, admin console

Per inbound transport:
  - TCP: accept thread + 1 reader thread per connection
  - UDP: 1 listener thread

Per session:
  - 1 upstream listener thread (receives server responses, relays to client)

Background:
  - Keepalive thread (PING on all sessions every 30s)
  - Cleanup thread (removes sessions idle > timeout)
```

## Config File (translator_config.json)

```json
{
    "server_host": "127.0.0.1",
    "server_port": 9525,
    "tcp_listen_host": "127.0.0.1",
    "tcp_listen_port": 6667,
    "udp_listen_host": "127.0.0.1",
    "udp_listen_port": 9526,
    "encryption_enabled": true,
    "session_timeout": 300,
    "log_file": "Translator.log"
}
```

CLI args override config file values.

## Implementation Order

### Phase 1: Core proxy with TCP/UDP bridging (no encryption)
1. Copy shared modules into `translator/`
2. `session.py` — ClientSession dataclass
3. `transports/base.py` — Abstract transport interfaces
4. `transports/udp_inbound.py` — UDP client listener
5. `transports/udp_outbound.py` — UDP sender (per-session sockets)
6. `transports/tcp_inbound.py` — TCP IRC listener with line buffering
7. `transports/tcp_outbound.py` — TCP sender
8. `translator.py` — Orchestrator wiring transports + sessions
9. `main.py` — Argparse + entry point
10. `translator_config.json` — Default config

### Phase 2: Encryption
11. `crypto.py` — DHExchange class, AES-GCM encrypt/decrypt
12. Wire DH negotiation into translator session setup
13. Add `CRYPTOINIT` handler to server's `server_message_handler.py`

### Phase 3: Tests
14. `tests/test_translator.py` — Unit tests for session, transports
15. `tests/test_translator_crypto.py` — DH + AES round-trip tests
16. `tests/test_translator_integration.py` — Full stack with real server

## Verification

1. Start CSC server: `cd server && python main.py`
2. Start translator: `python translator/main.py --intcp 6667 --inudp 9526 --outudp 127.0.0.1:9525`
3. Connect CSC client pointed at localhost:9526 — verify normal operation
4. Connect HexChat/irssi to localhost:6667 — verify IRC works through TCP bridge
5. Run test suite: `python -m pytest tests/test_translator*.py`

## Critical Files to Create

| File | Purpose |
|------|---------|
| `translator/main.py` | Entry point with argparse |
| `translator/translator.py` | Core orchestrator |
| `translator/session.py` | Session tracking |
| `translator/crypto.py` | DH + AES-256-GCM |
| `translator/transports/base.py` | Abstract interfaces |
| `translator/transports/tcp_inbound.py` | TCP listener |
| `translator/transports/udp_inbound.py` | UDP listener |
| `translator/transports/tcp_outbound.py` | TCP sender |
| `translator/transports/udp_outbound.py` | UDP sender |
| `translator/translator_config.json` | Default config |
