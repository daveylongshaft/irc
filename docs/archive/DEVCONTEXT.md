# CSC Developer Context

Read this + `tools.txt` before writing any code.

## Inheritance Chain (csc-shared)

Every component inherits from the same base stack:

```
Root -> Log -> Data -> Version -> Network -> Service -> Server
                                          -> Client (csc-client)
```

- **Root** (`root.py`): Sets `command_keyword = "AI"`, adds project root to sys.path
- **Log** (`log.py`): `self.log(msg)` — prints + appends to `self.log_file`
- **Data** (`data.py`): JSON key-value store via `get_data(key)` / `put_data(key, val)`. Backed by `{name}_data.json`. Thread-safe with `_storage_lock`
- **Version** (`version.py`): File versioning with numbered backups in `versions/` dir. `create_new_version(path)` / `restore_version(path, n)`
- **Network** (`network.py`): UDP socket, listener thread, message queue. `sock_send(data, addr)` chunks and sends. `start_listener()` runs `_network_listener` in background thread filtering keepalives into `message_queue`

## Transport: UDP Only

Everything is UDP datagrams on port 9525. No TCP anywhere except the translator bridge.

- Server binds UDP 9525, receives packets, spawns thread per packet
- Clients send to `(host, 9525)`, receive via listener thread
- Max datagram: 65500 bytes, auto-chunked by `sock_send`

## Server Architecture

```
Server.__init__()
  -> binds UDP 9525
  -> creates FileHandler, MessageHandler, ServerConsole
  -> loads persistent state from JSON files via PersistentStorageManager
  -> starts listener thread

Server.run()
  -> spawns _network_loop thread (pulls from message_queue, spawns worker threads)
  -> runs ServerConsole.run_loop() in main thread (admin CLI)
```

### Key Server State

All in-memory, persisted to JSON after every state change via `server._persist_session_data()`.

| Variable | Type | Where Stored | Lifecycle |
|---|---|---|---|
| `server.clients` | `{addr: {"name", "last_seen", "user_modes"}}` | `users.json` | Added on registration, removed by `_server_kill()` |
| `server.channel_manager` | `ChannelManager` | `channels.json` | Channels created on JOIN, cleaned up when empty (except #general) |
| `server.opers` | `set(nick)` | `opers.json` (active_opers) | Added on OPER auth, removed on disconnect |
| `server.oper_credentials` | `{name: password}` | `opers.json` (credentials) | Loaded on startup, modified via console |
| `server.nickserv_identified` | `{addr: nick}` | NOT persisted (session-only) | Set on IDENTIFY, cleared on disconnect |
| `server.disconnected_clients` | `{nick: info}` | `history.json` | Added on disconnect, capped at 100 entries |

### MessageHandler State

| Variable | Type | Where Stored | Lifecycle |
|---|---|---|---|
| `handler.registration_state` | `{addr: {state, nick, user, realname, password}}` | `users.json` (via server) | Created on first contact, removed by `_server_kill()` |
| `handler.client_registry` | `{nick: {password, addresses, last_seen}}` | `Server_data.json` (legacy) | Updated on registration |
| `handler._pm_buffer_replayed` | `set((addr, key))` | NOT persisted | Tracks which PM buffers replayed this session, cleaned on disconnect |

### Client Disconnect Convention (`_server_kill`)

**Every client disconnect goes through `_server_kill(nick, reason)`.** This is the single method that handles all cleanup:

1. Finds client addr by nick in `server.clients`
2. Broadcasts QUIT to all channels the user is in
3. Removes from all channels via `channel_manager.remove_nick_from_all(nick)`
4. Sends `ERROR :Closing Link:` to the disconnected client
5. Removes from `server.clients[addr]`
6. Removes from `handler.registration_state[addr]`
7. Removes from `server.nickserv_identified[addr]`
8. Cleans `_pm_buffer_replayed` entries for that addr
9. Persists disconnection to `history.json` (WHOWAS)
10. Calls `server._persist_session_data()`

**All disconnect paths use `_server_kill`:**
- `_handle_quit` — client sends QUIT
- `_handle_kill` — oper kills another user (auth check then `_server_kill`)
- `_nickserv_ghost` — NickServ GHOST command (password check then `_server_kill`)
- `_nickserv_enforce` — NickServ enforcement timer expires (disconnects unidentified user)

**If you add any new disconnect path, use `_server_kill`. Never duplicate cleanup logic.**

### Message Flow

```
UDP packet arrives
  -> Network._network_listener filters keepalives
  -> Server._network_loop pulls from queue
  -> spawns thread -> Server._thread_worker
  -> MessageHandler.process(data, addr)
  -> parse_irc_message(line)
  -> _dispatch_irc_command(msg, addr)
     -> pre-reg: NICK, USER, PASS, PING, PONG, QUIT, CAP, CRYPTOINIT
     -> NickServ intercept (works pre-reg): PRIVMSG NickServ :GHOST/IDENTIFY/etc
     -> post-reg: JOIN, PART, PRIVMSG, NOTICE, TOPIC, OPER, MODE, KICK, KILL, etc
     -> AI service commands
     -> file uploads
     -> fallback: plain text -> PRIVMSG to current channel
```

### Registration Flow

1. Client sends `NICK <nick>` -> stored in `registration_state[addr]`
2. Client sends `USER <user> 0 * :<realname>` -> stored
3. `_try_complete_registration` fires:
   - Sets `registration_state[addr]["state"] = "registered"`
   - Adds to `server.clients[addr]` with name, last_seen, user_modes
   - Adds to `handler.client_registry[nick]`
   - Sends 001-005 welcome burst + MOTD
   - Auto-joins `#general`
   - NickServ enforcement check (if nick is registered, 60s to IDENTIFY or disconnect)
   - Calls `server._persist_session_data()`

### Persistence (PersistentStorageManager)

Located in `storage.py`. All writes are atomic: write to `.tmp` -> fsync -> `os.replace`.

| File | Contents | Written By |
|---|---|---|
| `channels.json` | Channel state, members, modes, bans | `persist_all` -> `save_channels_from_manager` |
| `users.json` | User sessions, credentials, modes, last addr | `persist_all` -> `save_users_from_server` |
| `opers.json` | Oper credentials + active opers | `persist_all` -> `save_opers_from_server` |
| `bans.json` | Per-channel ban masks | `persist_all` -> `save_bans_from_manager` |
| `history.json` | Disconnection records for WHOWAS | `add_disconnection()` (called by `_server_kill`) |
| `nickserv.json` | `{nicks: {lower_nick: {password, registered_by, registered_at}}}` | `nickserv_register()`, `nickserv_drop()` |

**Persistence convention:** `server._persist_session_data()` is called after every state change. It writes channels, users, opers, bans in one shot. History and NickServ have their own individual save calls.

**Restore on startup:** `storage.restore_all(server)` loads everything back. Order matters: channels first, then users (so they can rejoin channels). Expired sessions (older than `server.timeout`) are skipped.

### NickServ System

Virtual service intercepted before the registration check in `_dispatch_irc_command`. This means NickServ commands work even from unregistered clients.

**Storage:** `nickserv.json` via `storage.nickserv_*` methods. Keyed by lowercase nick.

**Identified state:** `server.nickserv_identified[addr] = nick`. Session-only, not persisted. Cleared by `_server_kill`.

Commands (via `PRIVMSG NickServ :<command>`):
- `REGISTER <password>` — register current nick, auto-identifies, requires connected state
- `IDENTIFY <password>` — prove ownership, cancels enforcement timer
- `GHOST <nick> <password>` — validates NickServ password, calls `_server_kill`
- `INFO <nick>` — show registration date and registered_by
- `DROP <password>` — unregisters nick, clears identified state

**Enforcement flow:**
1. `_try_complete_registration` checks `storage.nickserv_get(nick)`
2. If registered and not identified: sends warning NOTICE, starts 60s `threading.Timer`
3. Timer stored as `setattr(self, f"_nickserv_enforce_{addr}", timer)` so IDENTIFY can cancel it
4. On expiry: `_nickserv_enforce` calls `_server_kill` to disconnect

## Channel System (csc-shared/channel.py)

**Channel** stores:
- `members: {nick: {"addr": tuple, "modes": set}}` — addr is `(ip, port)` tuple
- `modes: set` — channel-wide modes
- `mode_params: dict` — params for modes like `k` (key) and `l` (limit)
- `ban_list: set` — ban masks
- `invite_list: set` — invited nicks for +i channels

**ChannelManager** stores `channels: {name: Channel}`. Always has `#general`.

Key methods:
- `ensure_channel(name)` — create if missing, return it
- `get_channel(name)` — return or None
- `find_channels_for_nick(nick)` — list of Channel objects the nick is in
- `remove_nick_from_all(nick)` — removes from all channels, deletes empty non-default channels

**Convention:** When a user joins, `channel.add_member(nick, addr, modes)`. The addr tuple is the key that ties channel membership back to `server.clients`. When looking up "who is in this channel", you iterate `channel.members` and use the stored addr to send messages.

## IRC Message Format (csc-shared/irc.py)

```python
# Parse:  ":prefix COMMAND param1 param2 :trailing text"
msg = parse_irc_message(line)  # -> IRCMessage(prefix, command, params, trailing, raw)

# Build:  ":nick!nick@server PRIVMSG #channel :hello"
line = format_irc_message(prefix, command, params_list, trailing)

# Numeric: ":csc-server 001 nick :Welcome"
line = numeric_reply(SERVER_NAME, "001", nick, "Welcome")
```

`params[-1]` is always the trailing text (parser appends trailing to params list).

**Prefix convention:** Server messages use `SERVER_NAME` as prefix. User messages use `nick!nick@SERVER_NAME`. NickServ uses `NickServ!NickServ@SERVER_NAME`.

**Wire format:** All messages end with `\r\n` when sent. `format_irc_message` does NOT add `\r\n` — callers append it.

## Broadcasting

Three methods on Server for sending messages:

| Method | What it does |
|---|---|
| `server.broadcast(msg, exclude=addr)` | Sends to ALL connected clients (checks timeout, drops stale) |
| `server.broadcast_to_channel(chan, msg, exclude=addr)` | Sends to all members of a channel |
| `server.send_to_nick(nick, msg)` | Sends to a specific nick by looking up their addr in `server.clients` |

All three call `server.sock_send(data, addr)` which handles encryption (if key established) and chunking.

## AI Clients (Claude, Gemini, ChatGPT)

All three follow the same pattern:
- Inherit from `Client` (which inherits the full shared stack)
- Connect to server as normal IRC client (NICK, USER, OPER)
- Listen for PRIVMSG in channels
- Forward messages to their respective API
- Send responses back as PRIVMSG
- Credentials loaded from `~/.config/csc-NAME/secrets.json` or via `csc_shared.secret`

## Translator (csc-bridge)

Bridges external IRC clients (e.g. mIRC) to the CSC server:
- Listens on TCP 9667 for standard IRC connections
- Translates TCP IRC <-> CSC UDP protocol
- Has its own transport layer (tcp_inbound, udp_outbound, etc.)

## Service Commands

Commands prefixed with `AI` are service commands routed through `Service.handle_command()`:
- Dynamically loads Python modules from `services/` directory
- Format: `AI <class> <method> [args...]`
- Modules loaded as `services.{class}_service`, class instantiated once and cached in `loaded_modules`

## File Upload System

Bracket-delimited protocol embedded in PRIVMSG:
- `<begin file="path">` or `<append file="path">` starts a session
- Lines are accumulated by `FileHandler` (tracks per-addr sessions in `file_handler.sessions`)
- `<end file>` completes and writes to disk
- Requires ircop or chanop authorization (`_is_authorized` check)
- Broadcast to channel as it happens (transparent)

## Testing

```bash
python3 -m pytest tests/ -v
python3 -m pytest tests/test_server_irc.py -v
python3 -m pytest tests/test_nickserv_ghost.py -v
```

Mock pattern: `_build_mock_server()` creates a Mock with all server attributes. `_register_client(handler, addr, nick, server)` does NICK+USER registration. Tests use `_sent_lines(server)` to extract what was sent via `sock_send`.

**Important:** Old tests import from bare module names (pre-package). New tests should import from `csc_server.*` / `csc_shared.*`.

## Packages

All installed as editable pip packages from `packages/`:
```bash
pip install -e packages/csc-shared
pip install -e packages/csc-server
pip install -e packages/csc-client
pip install -e packages/csc-claude
pip install -e packages/csc-gemini
pip install -e packages/csc-chatgpt
pip install -e packages/csc-bridge
```

Import pattern: `from csc_shared.irc import parse_irc_message` / `from csc_server.server import Server`

Reinstall after edits: `pip install -e packages/csc-server --force-reinstall --no-deps`
