# CSC Translator -- API Reference

Complete reference for every module, class, and function in the translator package.

---

## Table of Contents

- [session.py -- ClientSession](#sessionpy----clientsession)
- [transports/base.py -- Abstract Base Classes](#transportsbasepy----abstract-base-classes)
- [transports/udp_inbound.py -- UDPInbound](#transportsudp_inboundpy----udpinbound)
- [transports/udp_outbound.py -- UDPOutbound](#transportsudp_outboundpy----udpoutbound)
- [transports/tcp_inbound.py -- TCPInbound](#transportstcp_inboundpy----tcpinbound)
- [transports/tcp_outbound.py -- TCPOutbound](#transportstcp_outboundpy----tcpoutbound)
- [translator.py -- Translator](#translatorpy----translator)
- [crypto.py -- Encryption and Key Exchange](#cryptopy----encryption-and-key-exchange)
- [main.py -- Entry Point and CLI](#mainpy----entry-point-and-cli)
- [Supporting Modules](#supporting-modules)

---

## session.py -- ClientSession

**File**: `translator/session.py`

### `class ClientSession`

A `@dataclass` that tracks state for a single proxied client connection through the translator. Each session binds together a client identity, a dedicated upstream connection, and encryption state.

#### Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `session_id` | `str` | `uuid.uuid4()` | Unique UUID identifying this session. Used as the key in the translator's session tracking dicts and to name the upstream listener thread. |
| `client_id` | `Any` | `None` | Transport-specific client identifier. For UDP: `(host, port)` tuple. For TCP: `TCPClientID` object. |
| `inbound_name` | `str` | `""` | Class name of the inbound transport (e.g., `"UDPInbound"` or `"TCPInbound"`). Used to route server responses back to the correct transport. |
| `upstream_handle` | `Any` | `None` | Transport-specific handle for the outbound connection. For UDP: `UDPUpstreamHandle`. For TCP: `TCPUpstreamHandle`. |
| `nick` | `Optional[str]` | `None` | The client's IRC nickname, extracted by sniffing `NICK` commands in passthrough traffic. `None` until the first `NICK` command is observed. |
| `created_at` | `float` | `time.time()` | Unix timestamp when the session was created. |
| `last_activity` | `float` | `time.time()` | Unix timestamp of the last data sent or received. Updated by `touch()`. |
| `aes_key` | `Optional[bytes]` | `None` | 32-byte AES-256 key derived from DH exchange. `None` until encryption is negotiated. |
| `dh_exchange` | `Any` | `None` | `DHExchange` object holding the private key during the DH handshake. Set to `None` after key derivation completes. |
| `encrypted` | `bool` | `False` | Whether encryption is active for this session. `True` after successful DH exchange and key derivation. |
| `normalizer` | `Any` | `None` | Optional `IrcNormalizer` instance for protocol translation. |
| `inbound` | `Any` | `None` | The `InboundTransport` instance that accepted this client. |

#### Methods

##### `touch() -> None`

Update `last_activity` to the current time.

- **Called by**: The translator whenever data passes through the session in either direction.
- **Threading**: Safe to call from any thread (float assignment is atomic in CPython).

##### `age() -> float`

Return the number of seconds since this session was created.

- **Returns**: `float` -- seconds elapsed since `created_at`.

##### `idle() -> float`

Return the number of seconds since the last activity on this session.

- **Returns**: `float` -- seconds elapsed since `last_activity`.
- **Used by**: The cleanup loop to determine if a session should be destroyed.

---

## transports/base.py -- Abstract Base Classes

**File**: `translator/transports/base.py`

### Type Aliases

```python
ClientID = Any       # Transport-specific client identifier
UpstreamHandle = Any # Transport-specific upstream connection handle
```

### `class InboundTransport(ABC)`

Abstract base class for transports that accept connections/datagrams from clients and deliver data to the translator.

#### `start(on_data: Callable[[bytes, ClientID], None]) -> None` (abstract)

Start listening for client connections or datagrams.

- **Args**:
  - `on_data`: Callback invoked for each received message. Parameters are `(raw_bytes, client_id)`. Send `b""` as `raw_bytes` to signal client disconnect.
- **Threading**: Implementations typically spawn a listener thread that invokes `on_data` from that thread.

#### `send_to_client(client_id: ClientID, data: bytes) -> None` (abstract)

Send data back to a specific connected client.

- **Args**:
  - `client_id`: The transport-specific identifier for the target client.
  - `data`: Raw bytes to send.

#### `stop() -> None` (abstract)

Stop listening, close all client connections, and release resources. After `stop()` returns, no further `on_data` callbacks will be invoked.

#### `remove_client(client_id: ClientID) -> None` (abstract)

Clean up resources for a specific disconnected client. Called by the translator when a session is destroyed.

- **Args**:
  - `client_id`: The transport-specific identifier for the client to remove.

---

### `class OutboundTransport(ABC)`

Abstract base class for transports that send data upstream to the CSC server on behalf of proxied clients.

#### `create_upstream(session_id: str) -> UpstreamHandle` (abstract)

Create a new upstream connection/socket for a client session.

- **Args**:
  - `session_id`: UUID string identifying the session.
- **Returns**: A transport-specific handle object.
- **Raises**: `OSError` if the socket cannot be created or connected.

#### `send(handle: UpstreamHandle, data: bytes) -> None` (abstract)

Send data to the CSC server through a session's upstream handle.

- **Args**:
  - `handle`: The upstream handle returned by `create_upstream()`.
  - `data`: Raw bytes to send (typically IRC wire format).

#### `recv(handle: UpstreamHandle, timeout: float = 1.0) -> Optional[bytes]` (abstract)

Receive data from the CSC server on a session's upstream handle. Blocks for up to `timeout` seconds.

- **Args**:
  - `handle`: The upstream handle returned by `create_upstream()`.
  - `timeout`: Maximum seconds to wait for data.
- **Returns**: Raw bytes received, or `None` if the timeout expired.

#### `close(handle: UpstreamHandle) -> None` (abstract)

Close an upstream handle and release its resources.

- **Args**:
  - `handle`: The upstream handle to close.

---

## transports/udp_inbound.py -- UDPInbound

**File**: `translator/transports/udp_inbound.py`

### `class UDPInbound(InboundTransport)`

Accepts UDP datagrams from CSC clients. Client identity is the `(host, port)` tuple of the sending address.

#### Constructor

```python
UDPInbound(host: str = "127.0.0.1", port: int = 9526)
```

- **Args**:
  - `host`: Address to bind the listening socket to.
  - `port`: Port to listen on.
- Creates a `SOCK_DGRAM` socket with `SO_REUSEADDR` and a 1-second timeout.

#### Fields

| Field | Type | Description |
|---|---|---|
| `host` | `str` | Bind address. |
| `port` | `int` | Bind port. |
| `sock` | `socket.socket` | The UDP listening socket. |
| `_running` | `bool` | Flag to control the listen loop. |
| `_thread` | `Optional[Thread]` | The `udp-inbound` listener thread. |
| `_on_data` | `Optional[Callable]` | The translator's data callback. |
| `_clients` | `Dict[tuple, bool]` | Set of known client `(host, port)` addresses. |

#### `start(on_data: Callable[[bytes, ClientID], None]) -> None`

Bind the socket and start the `udp-inbound` daemon thread.

- **Args**: `on_data` -- callback for received datagrams.
- **Threading**: Spawns one daemon thread named `"udp-inbound"`.

#### `_listen_loop() -> None` (private)

Blocking loop that calls `recvfrom(65500)` and invokes `_on_data(data, addr)` for each datagram. Silently continues on `socket.timeout` and `OSError` (while running).

- **Threading**: Runs on the `udp-inbound` thread.

#### `send_to_client(client_id: ClientID, data: bytes) -> None`

Send a datagram back to a UDP client via `sendto()`. Silently ignores `OSError`.

- **Args**:
  - `client_id`: `(host, port)` tuple.
  - `data`: Raw bytes to send.

#### `remove_client(client_id: ClientID) -> None`

Remove a client from the `_clients` tracking dict.

#### `stop() -> None`

Set `_running = False`, close the socket, join the listener thread (3s timeout).

---

## transports/udp_outbound.py -- UDPOutbound

**File**: `translator/transports/udp_outbound.py`

### `class UDPUpstreamHandle`

Encapsulates a single UDP socket dedicated to one session's communication with the server.

#### Constructor

```python
UDPUpstreamHandle(sock: socket.socket, server_addr: tuple)
```

#### Fields

| Field | Type | Description |
|---|---|---|
| `sock` | `socket.socket` | The dedicated UDP socket bound to an ephemeral port. |
| `server_addr` | `tuple` | `(host, port)` of the CSC server. |

#### `close() -> None`

Close the socket. Silently ignores `OSError`.

---

### `class UDPOutbound(OutboundTransport)`

Creates per-session UDP sockets to the CSC server. Each session gets a unique ephemeral source port so the server sees unique `(host, port)` per client.

#### Constructor

```python
UDPOutbound(server_host: str = "127.0.0.1", server_port: int = 9525)
```

- **Args**:
  - `server_host`: CSC server address.
  - `server_port`: CSC server port.

#### Fields

| Field | Type | Description |
|---|---|---|
| `server_addr` | `tuple` | `(server_host, server_port)`. |
| `_handles` | `Dict[str, UDPUpstreamHandle]` | Session ID to handle mapping. |

#### `create_upstream(session_id: str) -> UDPUpstreamHandle`

Create a new `SOCK_DGRAM` socket, bind to `("0.0.0.0", 0)` (ephemeral port), set 1-second timeout, wrap in `UDPUpstreamHandle`, and store in `_handles`.

- **Returns**: `UDPUpstreamHandle`.
- **Raises**: `OSError` on socket creation failure.

#### `send(handle: UDPUpstreamHandle, data: bytes) -> None`

Send datagram to `handle.server_addr` via `sendto()`. Silently ignores `OSError`.

#### `recv(handle: UDPUpstreamHandle, timeout: float = 1.0) -> Optional[bytes]`

Set socket timeout and call `recvfrom(65500)`.

- **Returns**: Received bytes, or `None` on timeout/error.

#### `close(handle: UDPUpstreamHandle) -> None`

Close the handle's socket and remove it from `_handles`.

---

## transports/tcp_inbound.py -- TCPInbound

**File**: `translator/transports/tcp_inbound.py`

### `class TCPClientID`

Identifier for a TCP client connection. Hashable and comparable by `conn_id`.

#### Constructor

```python
TCPClientID(conn: socket.socket, addr: tuple, conn_id: int)
```

#### Fields

| Field | Type | Description |
|---|---|---|
| `conn` | `socket.socket` | The accepted TCP socket for this client. |
| `addr` | `tuple` | `(host, port)` of the remote client. |
| `conn_id` | `int` | Monotonically increasing connection counter. Used for hashing and equality. |

#### `__hash__() -> int`

Returns `hash(("tcp", self.conn_id))`.

#### `__eq__(other) -> bool`

Compares `conn_id` values. Returns `False` for non-`TCPClientID` objects.

#### `__repr__() -> str`

Returns `TCPClient((host, port), id=N)`.

---

### `class TCPInbound(InboundTransport)`

Accepts TCP connections from IRC clients. Line-buffers incoming data on `\r\n` boundaries per RFC 1459 and delivers complete IRC lines to the translator.

#### Constructor

```python
TCPInbound(host: str = "127.0.0.1", port: int = 6667)
```

- Creates a `SOCK_STREAM` socket with `SO_REUSEADDR`, 1-second timeout, and `listen(5)` backlog.

#### Fields

| Field | Type | Description |
|---|---|---|
| `host` | `str` | Bind address. |
| `port` | `int` | Bind port (default 6667, standard IRC). |
| `server_sock` | `socket.socket` | The listening TCP socket. |
| `_running` | `bool` | Flag to control accept and read loops. |
| `_accept_thread` | `Optional[Thread]` | The `tcp-accept` thread. |
| `_on_data` | `Optional[Callable]` | The translator's data callback. |
| `_conn_counter` | `int` | Monotonically increasing counter for `TCPClientID.conn_id`. |
| `_clients` | `Dict[int, TCPClientID]` | Active client connections indexed by `conn_id`. |
| `_lock` | `threading.Lock` | Protects `_clients` and `_conn_counter`. |

#### `start(on_data: Callable[[bytes, ClientID], None]) -> None`

Bind, listen, and start the `tcp-accept` daemon thread.

- **Threading**: Spawns one daemon thread named `"tcp-accept"`.

#### `_accept_loop() -> None` (private)

Blocking loop that accepts new TCP connections. For each accepted connection:
1. Increments `_conn_counter` under lock
2. Creates a `TCPClientID`
3. Adds to `_clients` under lock
4. Spawns a `tcp-client-N` daemon thread running `_handle_client()`

- **Threading**: Runs on the `tcp-accept` thread. Spawns one thread per client.

#### `_handle_client(client_id: TCPClientID) -> None` (private)

Per-client read loop. Buffers incoming TCP data and splits on `\r\n` boundaries. For each complete line (including the trailing `\r\n`), calls `_on_data(line_bytes, client_id)`.

On disconnect (recv returns empty, connection reset, broken pipe, or OSError):
1. Calls `_on_data(b"", client_id)` to signal disconnect
2. Calls `_cleanup_client(client_id)`

- **Threading**: Runs on a `tcp-client-N` daemon thread.

#### `send_to_client(client_id: ClientID, data: bytes) -> None`

Send data to a TCP client via `sendall()`. On failure, calls `_cleanup_client()`.

- **Args**:
  - `client_id`: Must be a `TCPClientID`. Non-`TCPClientID` values are silently ignored.
  - `data`: Raw bytes to send.

#### `remove_client(client_id: ClientID) -> None`

Delegates to `_cleanup_client()` for `TCPClientID` instances.

#### `_cleanup_client(client_id: TCPClientID) -> None` (private)

Remove from `_clients` under lock and close the client socket. Silently ignores `OSError`.

#### `stop() -> None`

Set `_running = False`, close all client sockets under lock, clear `_clients`, close the server socket, join the accept thread (3s timeout).

---

## transports/tcp_outbound.py -- TCPOutbound

**File**: `translator/transports/tcp_outbound.py`

### `class TCPUpstreamHandle`

Encapsulates a single TCP connection dedicated to one session's communication with the server.

#### Constructor

```python
TCPUpstreamHandle(sock: socket.socket, server_addr: tuple)
```

#### Fields

| Field | Type | Description |
|---|---|---|
| `sock` | `socket.socket` | The dedicated TCP socket connected to the server. |
| `server_addr` | `tuple` | `(host, port)` of the server. |
| `_recv_buf` | `bytes` | Receive buffer (reserved for future line-buffering). |
| `_lock` | `threading.Lock` | Lock for thread-safe buffer access (reserved for future use). |

#### `close() -> None`

Close the socket. Silently ignores `OSError`.

---

### `class TCPOutbound(OutboundTransport)`

Creates per-session TCP connections to the server.

#### Constructor

```python
TCPOutbound(server_host: str = "127.0.0.1", server_port: int = 9525)
```

#### Fields

| Field | Type | Description |
|---|---|---|
| `server_addr` | `tuple` | `(server_host, server_port)`. |
| `_handles` | `Dict[str, TCPUpstreamHandle]` | Session ID to handle mapping. |

#### `create_upstream(session_id: str) -> TCPUpstreamHandle`

Create a new `SOCK_STREAM` socket, connect to the server with a 5-second timeout, then set 1-second timeout for ongoing operations. Wrap in `TCPUpstreamHandle` and store in `_handles`.

- **Returns**: `TCPUpstreamHandle`.
- **Raises**: `OSError` or `socket.timeout` on connection failure.

#### `send(handle: TCPUpstreamHandle, data: bytes) -> None`

Send data via `sendall()`. Silently ignores `OSError`.

#### `recv(handle: TCPUpstreamHandle, timeout: float = 1.0) -> Optional[bytes]`

Set socket timeout and call `recv(65500)`.

- **Returns**: Received bytes, or `None` on timeout/error/disconnect (empty recv returns `None`).

#### `close(handle: TCPUpstreamHandle) -> None`

Close the handle's socket and remove it from `_handles`.

---

## translator.py -- Translator

**File**: `translator/translator.py`

### `class Translator`

The core orchestrator that bridges multiple inbound transports to a single outbound transport. Manages session lifecycle, keepalive, and cleanup.

#### Constructor

```python
Translator(
    inbound_transports: List[InboundTransport],
    outbound_transport: OutboundTransport,
    session_timeout: int = 300,
    encrypt: bool = False,
)
```

- **Args**:
  - `inbound_transports`: List of inbound transport instances (TCP and/or UDP).
  - `outbound_transport`: Single outbound transport instance.
  - `session_timeout`: Seconds of inactivity before a session is destroyed (default 300).
  - `encrypt`: Whether to enable encryption negotiation (default `False`).

#### Fields

| Field | Type | Description |
|---|---|---|
| `inbound_transports` | `List[InboundTransport]` | All configured inbound transports. |
| `outbound` | `OutboundTransport` | The outbound transport to the CSC server. |
| `session_timeout` | `int` | Idle seconds before session destruction. |
| `encrypt` | `bool` | Whether encryption is enabled. |
| `_sessions` | `Dict[str, ClientSession]` | Session ID to session mapping. |
| `_client_to_session` | `Dict[Any, ClientSession]` | Client ID to session mapping. |
| `_lock` | `threading.Lock` | Protects `_sessions` and `_client_to_session`. |
| `_running` | `bool` | Flag controlling all background loops. |
| `_inbound_map` | `Dict[str, InboundTransport]` | Transport class name to instance mapping. |

---

#### `start() -> None`

Start all inbound transports and background threads.

1. Sets `_running = True`
2. Iterates `inbound_transports`, registers each in `_inbound_map` by class name
3. Calls `transport.start()` with a lambda callback that captures the transport reference
4. Spawns the `keepalive` daemon thread
5. Spawns the `cleanup` daemon thread

- **Threading**: Spawns 2 daemon threads. Each inbound transport spawns its own threads via `start()`.

#### `stop() -> None`

Stop all transports and clean up all sessions.

1. Sets `_running = False`
2. Calls `stop()` on each inbound transport
3. Under lock: calls `_destroy_session()` on every session, clears both dicts

#### `_on_client_data(data: bytes, client_id: ClientID, inbound: InboundTransport) -> None` (private)

Callback invoked by inbound transports when data arrives from a client.

- **Empty data** (`b""`): Interpreted as a disconnect signal, delegates to `_handle_disconnect()`.
- **First packet from a new client**: Calls `_create_session()`.
- **Subsequent packets**: Looks up session, calls `touch()`, `_sniff_nick()`, and `_forward_to_server()`.

- **Threading**: Called from inbound transport listener threads. Uses `_lock` for session lookups.

#### `_create_session(client_id: ClientID, inbound: InboundTransport) -> Optional[ClientSession]` (private)

Create a new session for a client with a dedicated upstream handle.

1. Creates a `ClientSession` with the client_id and inbound class name
2. Calls `outbound.create_upstream(session_id)` to get an upstream handle
3. Under lock: adds session to both tracking dicts
4. Spawns an `upstream-XXXXXXXX` daemon thread running `_server_listener(session)`

- **Returns**: The new `ClientSession`, or `None` on failure.
- **Threading**: Called from inbound transport threads. Spawns one daemon thread per session.

#### `_handle_disconnect(client_id: ClientID) -> None` (private)

Handle a client disconnect.

1. Under lock: removes session from both tracking dicts
2. Calls `_destroy_session()` on the removed session

#### `_destroy_session(session: ClientSession) -> None` (private)

Clean up a session's upstream resources.

1. Sends `QUIT :Translator session closed\r\n` to the server via the upstream handle
2. Closes the upstream handle

- **Note**: Does NOT remove from tracking dicts (caller is responsible). Does NOT call `remove_client()` on the inbound transport.

#### `_sniff_nick(session: ClientSession, data: bytes) -> None` (private)

Extract the IRC nickname from `NICK` commands passing through the translator.

- Decodes data as UTF-8 (ignoring errors)
- Scans each line for lines starting with `NICK ` (case-insensitive)
- Extracts the nick parameter (stripping leading `:`)
- Stores in `session.nick`

#### `_forward_to_server(session: ClientSession, data: bytes) -> None` (private)

Forward client data to the CSC server via the outbound transport.

- Contains a TODO comment for future encryption support.
- Calls `outbound.send(session.upstream_handle, data)`.
- Logs errors on failure.

#### `_forward_to_client(session: ClientSession, data: bytes) -> None` (private)

Forward server data back to the client via the appropriate inbound transport.

- Contains a TODO comment for future decryption support.
- Looks up the inbound transport by `session.inbound_name` from `_inbound_map`.
- Calls `inbound.send_to_client(session.client_id, data)`.
- Logs errors on failure.

#### `_server_listener(session: ClientSession) -> None` (private)

Per-session loop that receives data from the upstream server and forwards it to the client.

1. While `_running` and session exists in `_sessions`:
2. Calls `outbound.recv(session.upstream_handle, timeout=1.0)`
3. If data received: calls `session.touch()` and `_forward_to_client()`
4. On exception: breaks the loop (session listener thread exits)

- **Threading**: Runs on an `upstream-XXXXXXXX` daemon thread (one per session).

#### `_keepalive_loop() -> None` (private)

Background loop that sends keepalive PINGs to idle sessions.

- Sleeps 30 seconds between iterations
- For each session idle > 45 seconds: sends `PING :keepalive\r\n` via the upstream handle
- Silently ignores send failures

- **Threading**: Runs on the `keepalive` daemon thread.

#### `_cleanup_loop() -> None` (private)

Background loop that destroys sessions that have exceeded the timeout.

- Sleeps 15 seconds between iterations
- Under lock: identifies sessions where `now - last_activity > session_timeout`
- Removes identified sessions from both tracking dicts under lock
- Calls `_destroy_session()` on each removed session outside the lock

- **Threading**: Runs on the `cleanup` daemon thread.

#### `session_count() -> int`

Return the number of active sessions.

- **Returns**: `int`.
- **Threading**: Acquires `_lock`.

#### `list_sessions() -> List[dict]`

Return a list of session info dicts for the status display.

- **Returns**: List of dicts with keys:
  - `"id"`: First 8 characters of the session UUID
  - `"nick"`: Client nick or `"?"`
  - `"transport"`: Inbound transport class name
  - `"idle"`: Idle time formatted as `"Ns"`
  - `"encrypted"`: Boolean encryption status
- **Threading**: Acquires `_lock`.

    pass

    translator.stop()
    logger.info("Translator shut down")


if __name__ == "__main__":
    main()
```

---

## irc_normalizer.py -- Protocol Normalization

**File**: `translator/irc_normalizer.py`

### `class IrcNormalizer`

Handles bidirectional translation between CSC and RFC 2812 dialects.

#### Constructor

```python
IrcNormalizer(mode: str)
```

- **Args**: `mode` -- `"csc_to_rfc"` or `"rfc_to_csc"`.

#### `normalize_client_to_server(block: str, session) -> Optional[str]`

Normalize a chunk of text going from Client -> Server. Can handle multiple lines.

#### `normalize_server_to_client(block: str, session) -> Optional[str]`

Normalize a chunk of text going from Server -> Client. Can handle multiple lines.

---

## crypto.py -- Encryption and Key Exchange

**File**: `translator/crypto.py`

### Module-Level Constants

| Constant | Value | Description |
|---|---|---|
| `HAS_CRYPTO` | `bool` | `True` if the `cryptography` package is installed. |
| `DH_PRIME` | `int` | RFC 3526 Group 14 2048-bit MODP prime. |
| `DH_GENERATOR` | `int` | `2` |

### `class DHExchange`

Diffie-Hellman key exchange using RFC 3526 Group 14 parameters.

#### Constructor

```python
DHExchange()
```

- Generates a 256-bit private key from `os.urandom(32)`
- Computes public key: `pow(DH_GENERATOR, private, DH_PRIME)`

#### Fields

| Field | Type | Description |
|---|---|---|
| `private` | `int` | The private DH key (256-bit random integer). |
| `public` | `int` | The public DH key (`g^private mod p`). |

#### `compute_shared_key(other_public: int) -> bytes`

Derive a 32-byte AES-256 key from the shared secret.

- **Args**: `other_public` -- the other party's DH public key as an integer.
- **Returns**: 32-byte `bytes` -- `SHA-256(shared_secret.to_bytes(256, "big"))`.
- **Threading**: Stateless computation, safe to call from any thread.

#### `format_init_message() -> str`

Format the `CRYPTOINIT DH` message to send to the other side.

- **Returns**: `str` -- `"CRYPTOINIT DH {p_hex} {g_hex} {pub_hex}\r\n"`.

#### `format_reply_message() -> str`

Format the `CRYPTOINIT DHREPLY` response message.

- **Returns**: `str` -- `"CRYPTOINIT DHREPLY {pub_hex}\r\n"`.

#### `parse_init_message(line: str) -> tuple` (static)

Parse a `CRYPTOINIT DH` message.

- **Args**: `line` -- the raw message string.
- **Returns**: `(p, g, pubkey)` as a tuple of `int`.
- **Raises**: `ValueError` if the message format is invalid.

#### `parse_reply_message(line: str) -> int` (static)

Parse a `CRYPTOINIT DHREPLY` message.

- **Args**: `line` -- the raw message string.
- **Returns**: `int` -- the other party's public key.
- **Raises**: `ValueError` if the message format is invalid.

---

### `encrypt(key: bytes, plaintext: bytes) -> bytes`

Encrypt plaintext with AES-256-GCM.

- **Args**:
  - `key`: 32-byte AES-256 key.
  - `plaintext`: Arbitrary bytes to encrypt.
- **Returns**: `bytes` -- `[12-byte IV][ciphertext + 16-byte GCM tag]`.
- **Raises**: `RuntimeError` if the `cryptography` library is not installed.
- **Threading**: Stateless, safe to call from any thread.

### `decrypt(key: bytes, data: bytes) -> bytes`

Decrypt AES-256-GCM encrypted data.

- **Args**:
  - `key`: 32-byte AES-256 key.
  - `data`: Encrypted bytes in the format `[12-byte IV][ciphertext + 16-byte GCM tag]`.
- **Returns**: `bytes` -- the decrypted plaintext.
- **Raises**:
  - `RuntimeError` if the `cryptography` library is not installed.
  - `ValueError` if data is shorter than 28 bytes (12 IV + 16 tag).
  - `cryptography.exceptions.InvalidTag` if decryption/authentication fails.
- **Threading**: Stateless, safe to call from any thread.

### `is_encrypted(data: bytes) -> bool`

Heuristic to detect whether data is encrypted vs plaintext IRC.

- **Args**: `data` -- raw bytes to inspect.
- **Returns**: `bool` -- `True` if the data appears to be encrypted; `False` if it looks like plaintext IRC.
- **Logic**:
  1. Returns `False` if data is shorter than 4 bytes
  2. Attempts to decode the first 20 bytes as UTF-8
  3. If the first character is `:` (IRC prefix) or uppercase (IRC command), returns `False`
  4. If the first word matches a known IRC command (`NICK`, `USER`, `PING`, `PONG`, `QUIT`, `PASS`, `PRIVMSG`, `NOTICE`, `JOIN`, `PART`, `KICK`, `MODE`, `TOPIC`, `NAMES`, `LIST`, `WHO`, `OPER`, `WALLOPS`, `KILL`, `ISOP`, `BUFFER`, `MOTD`, `CAP`, `CRYPTOINIT`), returns `False`
  5. On `UnicodeDecodeError` or `IndexError`, falls through
  6. Returns `True` (data is not recognizable as plaintext IRC)

---

## main.py -- Entry Point and CLI

**File**: `translator/main.py`

### `parse_host_port(value: str, default_host: str = "127.0.0.1") -> tuple`

Parse a `[host:]port` string into a `(host, port)` tuple.

- **Args**:
  - `value`: String like `"6667"` or `"0.0.0.0:6667"`.
  - `default_host`: Host to use when only a port is given.
- **Returns**: `(str, int)` tuple.

### `load_config(path: str) -> dict`

Load configuration from a JSON file.

- **Args**: `path` -- path to the JSON config file.
- **Returns**: `dict` -- parsed config, or empty dict on `FileNotFoundError` or `JSONDecodeError`.

### `build_parser() -> argparse.ArgumentParser`

Build and return the CLI argument parser. See [translator-cli.md](translator-cli.md) for full argument documentation.

### `main() -> None`

Entry point. Orchestrates:

1. Parse CLI arguments
2. Configure logging (`[%(asctime)s] [%(name)s] %(message)s` format)
3. Load config file (explicit `--config` path, or `translator_config.json` in the script directory)
4. Resolve settings (CLI args override config values)
5. Build inbound transports from `--intcp` and `--inudp` (falling back to config)
6. Build outbound transport from `--outudp` or `--outtcp` (falling back to config)
7. Create `Translator` instance
8. Install `SIGINT` handler to call `translator.stop()` and exit
9. Call `translator.start()`
10. Enter console input loop (commands: `status`/`s`, `quit`/`q`/`exit`, `help`/`h`/`?`)
11. On loop exit: call `translator.stop()`

---

## Supporting Modules

These modules are part of the CSC project's shared class hierarchy and are present in the translator directory but not specific to the translator's proxy functionality.

### `root.py` -- Root

Base class in the project inheritance hierarchy. Sets the system-wide command keyword (`"AI"`).

- **Class**: `Root`
- **Fields**: `command_keyword` (`str`), `name` (`str`)
- **Methods**: `get_command_keyword()`, `run()` (placeholder)

### `log.py` -- Log

Extends `Root`. Provides timestamped console and file logging.

- **Class**: `Log(Root)`
- **Fields**: `log_file` (`str`)
- **Methods**: `log(message)`, `help()`, `test()`

### `data.py` -- Data

Extends `Log`. Provides JSON-file-backed key-value storage.

- **Class**: `Data(Log)`
- **Fields**: `_storage` (`dict`), `_storage_lock` (`Lock`), `source_filename` (`str`)
- **Methods**: `connect()`, `put_data(key, value, flush=True)`, `get_data(key)`, `store_data()`, `init_data(source_filename)`

### `version.py` -- Version

Extends `Data`. Provides file versioning with sequential numbered backups.

- **Class**: `Version(Data)`
- **Methods**: `create_new_version(filepath)`, `restore_version(filepath, version)`, `get_version_dir_for_file(filepath)`

### `network.py` -- Network

Extends `Version`. Provides a UDP socket layer with keepalive and message queue.

- **Class**: `Network(Version)`
- **Fields**: `server_addr`, `sock`, `message_queue`, `buffsize` (65500), `clients`
- **Methods**: `start_listener()`, `get_message()`, `send(message)`, `sock_send(data, addr)`, `maybe_send_keepalive()`, `close()`

### `irc.py` -- IRC Message Handling

IRC message parser, formatter, and RFC 2812 numeric constants.

- **Classes**: `IRCMessage` dataclass (`prefix`, `command`, `params`, `trailing`, `raw`)
- **Functions**: `parse_irc_message(line)`, `format_irc_message(prefix, command, params, trailing)`, `numeric_reply(server_name, numeric, target_nick, *text_parts)`
- **Constants**: `RPL_WELCOME`, `RPL_YOURHOST`, `RPL_CREATED`, `RPL_MYINFO`, `ERR_NICKNAMEINUSE`, and all other standard RFC 2812 numerics

### `__init__.py`

Path setup: inserts the translator directory into `sys.path`.

### `transports/__init__.py`

Empty file (package marker).
