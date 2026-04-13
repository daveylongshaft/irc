# Codex State

Date: 2026-04-09 (updated after PR1 completion)
Repo root: `C:\csc`
Active submodule for server work: `C:\csc\irc`

## Root Layout Clarification

- `csc.git` at `C:\csc` is the real project root.
- `irc.git` at `C:\csc\irc` is a submodule repo inside `csc.git`.
- The root repo contains non-IRC project assets too:
  - workorders
  - agent configs
  - root `bin/`
  - `server_name` / `servername`
- The `irc` submodule contains the IRC server and related packages such as:
  - `csc-server`
  - `csc-services`
  - `csc-clients`
  - `csc-loop`

This matters for all harness/tooling work:
- server/runtime code edits belong under `C:\csc\irc`
- root-level helpers should live under `C:\csc\bin`
- separate server identities should be managed from the root level, not only inside the `irc` tree

## User Constraints and Preferences

- Continue development without pausing for permission until there is a working server and local two-server sync testing is mature.
- Any stubbed method must announce loudly that it is a stub and not doing real work.
- Use `csc-client` programmatic mode for live tests when possible.
- FIFO mode is broken on Windows, but the client's programmatic/plain-file mode works.
- Client `outfile` may not work reliably; server logs are acceptable verification output.
- For multiple local linked servers, separate clones/worktrees are preferred; `server_name` in the root can be used to give each instance a different identity.
- Always pick the right approach over any immediate shortcut.
- Values: honesty, integrity, prudence, diligence.
- Never use non-ASCII characters (emoji, em-dashes, special Unicode) in any output files.

## Completed Since Last Update

### 1. Dispatcher SERVER_NAME cleanup - DONE

All global `SERVER_NAME` references in `dispatcher.py` replaced with `self.server.name`:
- Import removed (no longer imports `SERVER_NAME` from `csc_services`)
- Added `_user_host()` helper that preserves origin server in relay hostmasks:
  ```python
  def _user_host(self, nick, envelope):
      origin = envelope.origin_server or self.server.name
      return f"{nick}!{nick}@{origin}"
  ```
- All 8 hostmask locations updated to use `_user_host()`: PRIVMSG (channel+PM), NOTICE (channel+PM), JOIN, PART, QUIT, NICK change
- ServiceBot response uses server shortname: `{sname}!service@{sname}`
- `local_targets` simplified to only `self.server.name`
- All welcome numerics, PONG, NAMES, LIST use `self.server.name`

### 2. Root-level S2S harness - DONE and DEBUGGED

Created `C:\csc\bin\s2s_test.sh` with full worktree management.

Commands: `start`, `restart`, `status`, `dump`, `stop`, `clean`

Key design decisions after debugging:
- **Port-based PID management**: Git Bash `$!` PIDs don't match Windows Python PIDs. All process discovery and killing uses `netstat -ano` to find PIDs by UDP port. No reliance on PID files for liveness.
- **PING-based startup verification**: `SO_REUSEADDR` on UDP means bind-tests can't detect an already-running server. Harness sends `PING :startup` and waits for `PONG` with retry loop (up to 10 attempts, 1s apart).
- **`restart` command**: Stops servers, clears command-log.jsonl and internal logs, then starts fresh. Critical for clean test cycles.
- **`dump` reads internal logs**: Server's Log class writes to `logs/log.log` inside each worktree, not to stdout. The harness's `dump` command reads from there, not from the nohup stdout capture.
- **`status` detects zombies**: Reports WARNING when multiple processes are bound to the same port.

Servers:
- server1: `haven.19525` on `127.0.0.1:19525`, peer `127.0.0.1:29525`
- server2: `haven.29525` on `127.0.0.1:29525`, peer `127.0.0.1:19525`
- Worktrees at `tmp/s2s-test/server1-root` and `server2-root`

### 3. Bidirectional S2S relay - VERIFIED WORKING

Full end-to-end test passed:
```
bob registers on server1, joins #general
carol registers on server2, joins #general
carol's NAMES list shows "@bob carol" (bob synced via SYNCLINE)
carol sends PRIVMSG #general -> bob receives it on server1
bob replies PRIVMSG #general -> carol receives it on server2
hostmasks correctly show origin server (carol@haven.29525 on server1, bob@haven.19525 on server2)
```

### 4. Bugs found and fixed

1. **Zombie server processes**: `SO_REUSEADDR` allowed multiple servers to bind same port. Old processes with stale state raced to handle messages. Fixed with port-based stop.
2. **Stale nick state**: "Nickname already in use" errors from zombie servers holding old sessions. Fixed by proper stop + command log clearing on restart.
3. **Startup verification false negatives**: Bind-test passed even with server running due to `SO_REUSEADDR`. Fixed with PING/PONG verification.
4. **Log capture incomplete**: nohup stdout capture missed most log output. Fixed by reading internal `logs/log.log`.
5. **Origin hostmask wrong on relay**: Relayed commands showed receiving server's name instead of origin. Fixed with `_user_host()` helper.

### 5. PR1: MODE + TOPIC + KICK - DONE

#### ServerState additions (server_state.py)

Added 17 helper methods for channel modes, member modes, bans, invites, and permissions:
- **Channel modes**: `set_channel_mode`, `unset_channel_mode`, `get_channel_modes`
- **Member modes**: `set_member_mode`, `unset_member_mode`, `is_voiced`
- **Bans**: `add_ban`, `remove_ban`, `get_bans`, `normalize_ban_mask`, `match_ban_mask`, `is_banned`
- **Invites**: `add_invite`, `is_invited`
- **Permissions**: `can_speak` (checks +m, allows ops/voiced), `can_set_topic` (checks +t, allows ops)
- **User modes**: `set_user_mode`, `unset_user_mode`, `get_user_modes`

#### Dispatcher handlers (dispatcher.py)

New command handlers with full implementation:
- **`_handle_mode()`** - User and channel modes:
  - User modes: +i (invisible), +w (wallops), +s (server notices), +o (oper, no self-grant)
  - Channel modes: nick modes (o/v require target param), flag modes (m/t/n/i/s/p/Q no param), param modes (k/l), list modes (b for bans)
  - Max 8 mode changes per command, full parameter parsing (left-to-right consumption)
  - Broadcasts mode changes to channel members
- **`_handle_topic()`** - Query/set with +t enforcement:
  - Query: `TOPIC #chan` returns RPL_TOPIC/RPL_NOTOPIC
  - Set: `TOPIC #chan :new topic` checks +t, stores topic_author and topic_time, broadcasts to channel
  - Added `RPL_TOPICWHOTIME` for topic metadata queries
- **`_handle_kick()`** - Op/oper-gated removal:
  - Checks kicker is op or oper, verifies target is in channel
  - Broadcasts KICK to all channel members and removes target from channel state
- **`_send_names_reply()`** - Updated to show voice prefix:
  - `@nick` for ops, `+nick` for voiced, plain for regular members
- **Mode enforcement in PRIVMSG/NOTICE**:
  - Check `can_speak()` before delivery: allow ops/voiced, silently deny others if +m
  - PRIVMSG sends ERR_CANNOTSENDTOCHAN on denial
  - NOTICE silently drops (per RFC)
- **Mode enforcement in JOIN**:
  - Enforce +i (invite-only): check `is_invited`, else ERR_INVITEONLYCHAN
  - Enforce +k (key): verify key matches, else ERR_BADCHANNELKEY
  - Enforce +l (limit): check capacity, else ERR_CHANNELISFULL
  - Enforce +b (ban): check `is_banned`, else ERR_BANNEDFROMCHAN
  - Auto-set +nt on new channels (first member is op)
- **`_handle_join()` key support**: Parse and pass channel key param to join logic

#### Ingress update (ingress.py)

- Added `WHO`, `WHOIS`, `MOTD` to non-replicated set (queries should not relay)
- MODE *does* replicate so mode changes sync across servers

#### Testing

Unit tests verified all functionality. To reproduce:

ServerState tests:
```
cd /c/csc/irc && py -c "
import sys
for p in ['packages/csc-server','packages/csc-services','packages/csc-network','packages/csc-crypto','packages/csc-platform','packages/csc-loop']:
    sys.path.insert(0, p)
from csc_server.state.server_state import ServerState
s = ServerState('test', '127.0.0.1', 9525)
s.set_channel_mode('#test', 'm')
s.add_ban('#test', 'bad*')
s.add_channel_member('#test', 'sess1', 'alice', op=True)
s.add_channel_member('#test', 'sess2', 'bob')
s.set_member_mode('#test', 'bob', 'v')
assert s.can_speak('#test', 'alice')
assert s.can_speak('#test', 'bob')
assert not s.can_speak('#test', 'charlie')
print('ServerState tests passed')
"
```

Dispatcher handler tests (MODE, TOPIC, KICK):
```
cd /c/csc/irc && py -c "
import sys, os
for p in ['packages/csc-server','packages/csc-services','packages/csc-network','packages/csc-crypto','packages/csc-platform','packages/csc-loop']:
    sys.path.insert(0, p)
os.environ.setdefault('CSC_ROOT', '/c/csc/irc')
from csc_server.state.server_state import ServerState
from csc_server.exec.dispatcher import CommandDispatcher
from csc_server.queue.command import CommandEnvelope

class MockServer:
    name = 'testserv'
    def check_oper_auth(self, *a): return None
    def add_active_oper(self, *a): pass
    def remove_active_oper(self, *a): pass
    def handle_command(self, *a): return 'OK'
    def debug(self, msg): pass

state = ServerState('testserv', '127.0.0.1', 9525)
disp = CommandDispatcher(MockServer(), state, lambda m: None)

def env(session, line):
    return CommandEnvelope(command_id='test', kind='irc', source_session=session, payload={'line': line}, origin_server=None)

disp.dispatch(env('s1', 'NICK alice'))
disp.dispatch(env('s1', 'USER alice 0 * :Alice'))
disp.dispatch(env('s2', 'NICK bob'))
disp.dispatch(env('s2', 'USER bob 0 * :Bob'))

# Test MODE channel +m
disp.dispatch(env('s1', 'MODE #general +m'))
modes, _ = state.get_channel_modes('#general')
assert 'm' in modes, f'MODE +m failed'

# Test TOPIC with +t enforcement
disp.dispatch(env('s1', 'TOPIC #general :alice topic'))
ch = state.get_channel('#general')
assert ch['topic'] == 'alice topic', f'TOPIC set failed'

# Test KICK
disp.dispatch(env('s1', 'KICK #general bob :bye'))
assert not state.is_channel_member('#general', 'bob'), f'KICK failed'

print('Dispatcher handler tests passed')
"
```

All tests passed without errors. Key numerics used:
- RPL_UMODEIS (221), RPL_CHANNELMODEIS (324), RPL_BANLIST (367), RPL_ENDOFBANLIST (368), RPL_TOPIC (332), RPL_NOTOPIC (331), RPL_TOPICWHOTIME (333)
- ERR_CHANOPRIVSNEEDED (482), ERR_USERNOTINCHANNEL (441), ERR_CANNOTSENDTOCHAN (404), ERR_INVITEONLYCHAN (473), ERR_BADCHANNELKEY (475), ERR_CHANNELISFULL (471), ERR_BANNEDFROMCHAN (474)

### 6. INVITE: One-shot semantics and tests - DONE

#### ServerState additions (server_state.py)

Added invite consumption and cleanup:
- **`consume_invite()`** - Remove nick from invite list after successful join (one-shot behavior)
- **`clear_invites()`** - Clear all invites for a channel when it is removed

#### Dispatcher updates (dispatcher.py)

- **`_join_channel()`** - Added `consume_invite()` call after successful join, making invites one-shot (consumed on use, not persistent)

#### Storage cleanup (server_state.py)

- **`remove_channel_member()`** - Calls `clear_invites()` before deleting empty channel (prevents stale invites from accumulating)

#### Testing (test_csc_server_dispatcher.py)

Added three focused tests:
- **`test_invite_only_channel_join_requires_invite()`** - Verifies +i channels block joins without invite
- **`test_invite_is_one_shot_consumed_on_join()`** - Verifies invite is consumed on successful join and becomes invalid on rejoin
- **`test_invites_cleared_on_channel_removal()`** - Verifies invites are cleared when last member leaves and channel is deleted

All tests pass. INVITE behavior is deterministic and fully covered.

## High-Level State of `csc-server`

### Working and verified
- Queue ingestion, durable JSONL persistence, recovery
- Dispatcher execution from queued envelopes
- Session context enrichment
- Targeted service-command authorization (server name matching)
- Live UDP ingress
- Bidirectional S2S relay via SYNCLINE (tested with two separate worktrees)
- Correct origin identity propagation across relay
- IRC commands: PASS, NICK, USER, OPER, PING, QUIT, JOIN, PART, NAMES, LIST, PRIVMSG, NOTICE
- NEW: MODE (user + channel), TOPIC (query/set with +t), KICK (op-gated), INVITE (one-shot consumption)
- NEW: Channel mode enforcement: +i, +k, +l, +b on JOIN; +m on PRIVMSG/NOTICE; +t on TOPIC
- NEW: Ban mask matching and enforcement
- NEW: Voice mode (+v) and voice-based speak permission
- NEW: Invite system with one-shot consumption on successful join

### Needs buildout - remaining Tier 1 commands

The old server code lives in `irc/packages/csc-service/csc_service/server/handlers/` with handler mixins. All old logic is accessible in git history. Port to the new queue-first dispatcher pattern.

**Tier 1 - Core IRC (required for usable server)**

| Command | Old handler file | What it does | Status |
|---------|-----------------|--------------|--------|
| TOPIC   | `handlers/channel.py` | Get/set topic, respects +t mode | [DONE] |
| KICK    | `handlers/oper.py` | Remove user from channel, op-required | [DONE] |
| MODE    | `handlers/modes.py` | User modes + channel modes (+o/+v/+m/+n/+t/+k/+l/+i/+b) + ban mask matching | [DONE] |
| WHO     | `handlers/info.py` | Channel member query | [TODO] |
| WHOIS   | `handlers/info.py` | User info lookup (nick, channels, idle, signon) | [TODO] |
| MOTD    | `handlers/info.py` | Message of the day on connect | [TODO] |
| AWAY    | `handlers/oper.py` | Away status toggle (sets/clears away message) | [TODO] |
| INVITE  | `handlers/channel.py` | Invite user to +i channel | [DONE] |

**Tier 2 - Oper/Admin**

| Command | Old handler file | What it does |
|---------|-----------------|--------------|
| KILL | `handlers/oper.py` | Force disconnect (oper-gated) |
| WALLOPS | `handlers/oper.py` | Broadcast to all opers |
| STATS | `handlers/oper.py` | Server statistics |
| SETMOTD | `handlers/oper.py` | Admin sets MOTD |
| SHUTDOWN | `handlers/oper.py` | Graceful server shutdown |
| TRUST | `handlers/oper.py` | Manage o-lines (oper credentials) |

**Tier 3 - Services (later phase)**

| Feature | Old handler file |
|---------|-----------------|
| NickServ | `handlers/nickserv.py` (register, identify, ghost, enforce) |
| ChanServ | `handlers/chanserv.py` (register, op/deop, voice, ban, set) |
| BotServ | `handlers/botserv.py` (add, del, setlog) |
| VFS | `handlers/vfs.py` (browse, encrypt, decrypt) |
| Buffer replay | `handlers/messaging.py` (_handle_buffer) |
| Collision resolver | `collision_resolver.py` |

### SyncMesh hardening needed
- `receive_command()` has no try/except around `json.loads()` - malformed JSON crashes
- No duplicate detection (same command_id arriving twice)
- No peer health checking

### Ingress gaps
- `_extract_channel()` only works for PRIVMSG, not JOIN/PART/MODE/TOPIC
- No line length validation (RFC 1459: 512 bytes)

## Important Files

| File | Role |
|------|------|
| `irc/packages/csc-server/csc_server/exec/dispatcher.py` | Command dispatch - MODE/TOPIC/KICK [OK], next: WHO/WHOIS/MOTD/AWAY |
| `irc/packages/csc-server/csc_server/state/server_state.py` | In-memory state ledger - MODE/ban/voice/invite/permission helpers [OK] |
| `irc/packages/csc-server/csc_server/sync/mesh.py` | S2S relay - needs hardening |
| `irc/packages/csc-server/csc_server/irc/ingress.py` | Client line ingestion - non_replicated set updated [OK] |
| `irc/packages/csc-server/csc_server/server.py` | UDP server loop |
| `irc/packages/csc-server/csc_server/queue/command.py` | CommandEnvelope dataclass |
| `irc/packages/csc-server/csc_server/queue/store.py` | JSONL persistence |
| `irc/packages/csc-server/csc_server/queue/local_queue.py` | In-memory deque queue |
| `bin/s2s_test.sh` | Root-level two-server test harness |
| `irc/packages/csc-service/csc_service/server/handlers/` | OLD handler mixins (port source) |
| `irc/packages/csc-service/csc_service/server/channel.py` | OLD Channel/ChannelManager (state model source) |
| `irc/docs/tools/server.txt` | Full map of old server code |

## Recommended Build Order

1. [OK] MODE - Ported, fully working
2. [OK] TOPIC - Ported, fully working
3. [OK] KICK - Ported, fully working
4. [OK] INVITE - One-shot consumption, fully working with tests
5. [TODO] WHO/WHOIS/MOTD - Info queries, no state mutation
6. [TODO] AWAY - Small state additions
7. [TODO] KILL/WALLOPS - Oper-gated, straightforward
8. [TODO] SyncMesh hardening - Error handling, dedup
9. [TODO] Services (NickServ/ChanServ/BotServ) - Later phase

## Next Steps: PR2

Port WHO, WHOIS, MOTD, AWAY from old handlers. These are mostly info queries with minimal state mutation.

Requirements:
- WHO: List channel members with mode flags (@, +)
- WHOIS: User info lookup (nick, channels, idle, signon)
- MOTD: Server message of the day
- AWAY: Set/clear away message on session (state change, not a read-only query)

Need to add to ServerState (if not already present):
- signon_time and idle_time tracking on sessions for WHOIS

Test same way as PR1: cd /c/csc/irc && py -c "..." with sys.path setup.

## Short Resume Prompt

> Read C:\csc\tmp\codex_state.md for full context. PR1 (MODE/TOPIC/KICK) is complete and tested. Next: PR2 port WHO/WHOIS/MOTD/AWAY from old irc/packages/csc-service/csc_service/server/handlers/info.py and handlers/oper.py to the new dispatcher. AWAY sets/clears away message (not read-only). Add signon_time, idle_time tracking to ServerState. Old handler code is in git history at commit e7ba97a345a. Use irc/docs/tools/server.txt as reference.
