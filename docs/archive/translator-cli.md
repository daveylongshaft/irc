# CSC Translator -- Command-Line Usage Guide

## Synopsis

```
python main.py [--intcp [HOST:]PORT] [--inudp [HOST:]PORT]
               [--outudp HOST:PORT] [--outtcp HOST:PORT]
               [--no-encrypt] [--timeout SECONDS]
               [--config PATH]
```

At least one inbound transport (`--intcp` or `--inudp`) and one outbound transport (`--outudp` or `--outtcp`) are required. If not provided on the command line, they are read from the config file.

---

## CLI Arguments

### `--intcp [HOST:]PORT`

Listen for TCP connections from IRC clients.

- **HOST**: Bind address (default: `127.0.0.1`).
- **PORT**: TCP port number.
- Creates a `TCPInbound` transport that line-buffers on `\r\n` and delivers complete IRC lines to the translator.
- Standard IRC clients (mIRC, HexChat, irssi, WeeChat, etc.) connect here.

**Examples**:
```
--intcp 6667               # Listen on 127.0.0.1:6667
--intcp 0.0.0.0:6667       # Listen on all interfaces, port 6667
--intcp 192.168.1.10:6668  # Listen on a specific interface, port 6668
```

### `--inudp [HOST:]PORT`

Listen for UDP datagrams from CSC clients.

- **HOST**: Bind address (default: `127.0.0.1`).
- **PORT**: UDP port number.
- Creates a `UDPInbound` transport. CSC-native clients that speak UDP connect here.

**Examples**:
```
--inudp 9526               # Listen on 127.0.0.1:9526
--inudp 0.0.0.0:9526       # Listen on all interfaces
```

### `--outudp HOST:PORT`

Forward traffic to the CSC server via UDP.

- **HOST**: Server address (required when using this flag).
- **PORT**: Server UDP port.
- Creates a `UDPOutbound` transport with per-session ephemeral source ports.

**Examples**:
```
--outudp 127.0.0.1:9525        # Local server
--outudp 192.168.1.10:9525     # Remote server on LAN
--outudp my-server.com:9525    # Remote server by hostname
```

### `--outtcp HOST:PORT`

Forward traffic to the server via TCP.

- **HOST**: Server address (required when using this flag).
- **PORT**: Server TCP port.
- Creates a `TCPOutbound` transport with per-session TCP connections.

**Examples**:
```
--outtcp 127.0.0.1:9525        # Local server via TCP
--outtcp 192.168.1.10:9525     # Remote server via TCP
```

### `--no-encrypt`

Disable encryption. All traffic passes through in plaintext without any CRYPTOINIT negotiation.

- **Default**: Encryption is enabled (but not yet fully wired into the forwarding path).

### `--gateway-mode MODE`

Set protocol normalization mode.

- **MODE**: `"csc-to-irc"` or `"irc-to-csc"`.
  - `csc-to-irc`: Use when CSC clients connect to a standard IRC network.
  - `irc-to-csc`: Use when standard IRC clients connect to the CSC server.
- **Default**: None (pure transport proxy).

### `--daemon PORT`

Run in Daemon/BNC mode listening on the specified TCP port.

- **PORT**: TCP port number (e.g., 9520).
- This mode enables the interactive "Control Plane" where clients connect, authenticate, and then issue `/trans connect ...` commands to establish upstream connections dynamically.
- Mutually exclusive with `--outudp` and `--outtcp` (outbound is determined per-session).
- Inbound is TCP only on the specified port.

**Example**:
```bash
python main.py --daemon 9520
```

### `--timeout SECONDS`

Session timeout in seconds. Sessions with no traffic for this long are automatically destroyed.

- **Default**: `300` (5 minutes).
- **Type**: Integer.

**Examples**:
```
--timeout 600      # 10-minute timeout
--timeout 60       # 1-minute timeout (aggressive)
--timeout 3600     # 1-hour timeout
```

### `--config PATH`

Path to a JSON configuration file. CLI arguments override values from the config file.

- **Default**: Looks for `translator_config.json` in the same directory as `main.py`.

---

## Config File Format

The translator reads configuration from a JSON file named `translator_config.json` (or the path specified by `--config`). CLI arguments always take precedence over config file values.

### Example `translator_config.json`

```json
{
    "tcp_listen_host": "127.0.0.1",
    "tcp_listen_port": 6667,
    "udp_listen_host": "127.0.0.1",
    "udp_listen_port": 9526,
    "server_host": "127.0.0.1",
    "server_port": 9525,
    "session_timeout": 300
}
```

### Config Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `tcp_listen_host` | `string` | `"127.0.0.1"` | Bind address for TCP inbound. |
| `tcp_listen_port` | `integer` | (none) | Port for TCP inbound. Omit to disable TCP inbound from config. |
| `udp_listen_host` | `string` | `"127.0.0.1"` | Bind address for UDP inbound. |
| `udp_listen_port` | `integer` | (none) | Port for UDP inbound. Omit to disable UDP inbound from config. |
| `server_host` | `string` | (none) | CSC server address for outbound. |
| `server_port` | `integer` | (none) | CSC server port for outbound. |
| `session_timeout` | `integer` | `300` | Idle timeout in seconds. |

### Config Resolution Rules

1. If `--intcp` or `--inudp` is given on the command line, config inbound settings are ignored entirely.
2. If neither `--intcp` nor `--inudp` is given, the translator falls back to config values for both TCP and UDP inbound.
3. `--outudp` and `--outtcp` override `server_host`/`server_port` from config.
4. If no outbound is specified on the CLI, the config's `server_host`/`server_port` are used with UDP outbound.
5. `--timeout` overrides `session_timeout` from config.
6. If the config file is missing or contains invalid JSON, it is silently treated as empty.

---

## Console Commands

Once the translator is running, it presents an interactive console. Type commands and press Enter.

| Command | Aliases | Description |
|---|---|---|
| `status` | `s` | Display all active sessions with nick, transport, idle time, and encryption status. |
| `quit` | `q`, `exit` | Gracefully shut down the translator, destroying all sessions. |
| `help` | `h`, `?` | Show available console commands. |

### Status Output Format

```
Active sessions (2):
  [a1b2c3d4] alice via TCPInbound idle=12s plain
  [e5f6a7b8] bob via UDPInbound idle=3s plain
```

Each line shows:
- `[XXXXXXXX]` -- first 8 characters of the session UUID
- Nick or `?` if not yet known
- `via <transport>` -- which inbound transport the client connected through
- `idle=Ns` -- seconds since last activity
- `encrypted` or `plain` -- encryption status

If no sessions are active:
```
No active sessions
```

### Shutdown

The translator can be shut down by:
- Typing `quit`, `q`, or `exit` at the console
- Pressing `Ctrl+C` (SIGINT handler)
- Sending EOF to stdin (e.g., piped input ends)

On shutdown, the translator:
1. Calls `stop()` on all inbound transports
2. Sends `QUIT :Translator session closed\r\n` to the server for each active session
3. Closes all upstream sockets
4. Logs "Translator shut down"

---

## Example Invocations

### Basic: IRC client to local CSC server

Bridge IRC clients on the standard port to a local CSC server:

```bash
python main.py --intcp 6667 --outudp 127.0.0.1:9525
```

Then point any IRC client at `127.0.0.1:6667`.

### Dual inbound: TCP and UDP to local server

Accept both IRC clients (TCP) and CSC clients (UDP):

```bash
python main.py --intcp 6667 --inudp 9526 --outudp 127.0.0.1:9525
```

### Remote server

Bridge local IRC clients to a remote CSC server:

```bash
python main.py --intcp 6667 --outudp 192.168.1.10:9525
```

### Listen on all interfaces

Allow connections from any network interface:

```bash
python main.py --intcp 0.0.0.0:6667 --inudp 0.0.0.0:9526 --outudp 10.0.0.5:9525
```

### Config file only

Use settings from a config file:

```bash
python main.py --config translator_config.json
```

### Config file with CLI overrides

Load config but override the timeout:

```bash
python main.py --config translator_config.json --timeout 600
```

### Plaintext mode (no encryption)

Disable encryption negotiation:

```bash
python main.py --intcp 6667 --outudp 127.0.0.1:9525 --no-encrypt
```

### TCP-to-TCP bridging

Bridge IRC clients to a TCP-based server:

```bash
python main.py --intcp 6667 --outtcp 127.0.0.1:9525
```

### Custom ports

Use non-standard ports for everything:

```bash
python main.py --intcp 0.0.0.0:7000 --inudp 0.0.0.0:7001 --outudp 10.0.0.1:7002 --timeout 120
```

---

## Logging

The translator uses Python's `logging` module with the logger name `"translator"`.

### Log Format

```
[2025-01-15 14:30:00] [translator] Inbound transport started: TCPInbound
[2025-01-15 14:30:00] [translator] Translator started
[2025-01-15 14:30:00] [translator] Translator running (encrypt=on, timeout=300s)
```

### Logged Events

- Transport start/stop
- Session creation (with client ID and nick if known)
- Session end (disconnect or timeout)
- Forwarding errors
- Shutdown sequence

### Log Level

All translator log messages use `INFO` level. Errors within forwarding and session management are logged at `ERROR` level via `logger.error()`.
