# Permanent Storage Architecture

The system replaces monolithic snapshot persistence with separate JSON files,
each written atomically after every state change. Designed to survive power
failure at any point with zero data loss.

## Core Principles

1. **Immediate writes** - every state change triggers disk write, no buffering
2. **Atomic operations** - temp file + fsync + rename pattern
3. **Resilience over performance** - disk I/O on every change is acceptable
4. **Graceful degradation** - corrupt/missing files handled without crashing

## Storage Location

All files stored in `/opt/csc/server/`:

| File | Purpose |
|------|---------|
| `channels.json` | Channel state (names, topics, modes, members, bans, invites) |
| `users.json` | User sessions (nicks, credentials, modes, channel memberships) |
| `opers.json` | Operator nicks and credentials |
| `bans.json` | Per-channel ban masks |
| `history.json` | Disconnection records for WHOWAS (max 100) |

Each file has a `version` field for future schema migrations.

## File Schemas

### channels.json
- `version`: 1
- `channels`: dict keyed by channel name
  - `name`, `topic`, `modes` (list), `mode_params` (dict), `ban_list` (list),
    `invite_list` (list), `created` (float timestamp), `members` (dict of nick -> {addr, modes})

### users.json
- `version`: 1
- `users`: dict keyed by nick
  - `nick`, `user`, `realname`, `password`, `user_modes` (list),
    `away_message` (string or null), `last_addr` ([ip, port]),
    `last_seen` (float), `channels` (dict of channel_name -> {modes})

### opers.json
- `version`: 1
- `active_opers`: list of operator nicks
- `credentials`: dict of name -> password

### bans.json
- `version`: 1
- `channel_bans`: dict of channel_name -> list of ban masks

### history.json
- `version`: 1
- `disconnections`: list of {nick, user, realname, host, quit_time, quit_reason}

## Atomic Write Pattern

1. Serialize to JSON
2. Write to `filename.tmp`
3. `flush()` + `os.fsync(fd.fileno())`
4. `os.replace(tmp, final)` for atomic rename
5. On error: remove `.tmp`, log, return False

## Data Flow

Handler updates in-memory state -> calls `server._persist_session_data()` ->
StorageManager writes atomically -> returns after data is on disk.

## Migration

On first run: detect `Server_data.json` `session_snapshot` key, extract into
new files, keep `Server_data.json` for non-session data.

## Recovery

| Situation | Action |
|-----------|--------|
| Missing file | Create with empty defaults |
| Corrupt JSON | Rename to `.corrupt.<timestamp>`, create fresh |
| Partial data | Load what is valid, skip the rest |
