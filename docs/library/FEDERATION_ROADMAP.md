# CSC Server Federation Roadmap

## Overview

This document outlines the implementation of **CSC Server Federation** — a system enabling multiple independent CSC IRC servers to link together, synchronize channels and users, and handle network merges with automatic nick collision resolution.

---

## Architecture

```
[Local CSC Server]       [Remote CSC Server]       [Another CSC Server]
facingaddictionwithhope.com    other.server             third.server
        ↓                             ↓                        ↓
    [S2S Link] ←→ S2S Protocol ←→ [S2S Link] ←→ [S2S Link] ←→ [S2S Link]
        ↓                             ↓                        ↓
    [Channels]                   [Channels]              [Channels]
    [Users]                      [Users]                 [Users]
```

---

## Phase 1: Server Linking & Federation (OPUS)

**Task:** `prompts/wip/opus-server-linking-federation.md`
**Agent:** Claude Opus 4.6 (for complex architectural design)
**Status:** IN PROGRESS

### What Opus Will Implement

1. **S2S Protocol (`ServerLink` class)**
   - TCP-based server-to-server connections
   - SLINK/SLINKACK authentication handshake
   - S2S command parsing and routing
   - Message exchange between servers

2. **Server Network Manager (`ServerNetwork` class)**
   - Track all linked servers
   - Broadcast commands to network
   - Route messages between servers
   - Find users/channels on any server

3. **User & Channel Synchronization**
   - SYNCUSER — replicate user across servers
   - SYNCCHAN — replicate channel state
   - SYNCMSG — route messages between servers
   - Handle user joins/parts/quits across network

4. **Configuration & Security**
   - S2S port setup (9526 default)
   - Server linking password authentication
   - Server ID assignment for tie-breaking

**Expected Deliverables:**
- `packages/csc-server/server_s2s.py` — ServerLink & ServerNetwork classes
- Updated `server_message_handler.py` — S2S command handlers
- Tests demonstrating 2+ servers linking
- Documentation of S2S protocol

---

## Phase 2: Configuration & Official Server (HAIKU)

**Task:** `prompts/wip/haiku-configure-official-csc-server.md`
**Agent:** Claude Haiku 4.5 (configuration and client updates)
**Status:** IN PROGRESS

### What Haiku Will Do

1. **Update all clients to use official server**
   - `csc-claude` → read CSC_SERVER_HOSTNAME from .env
   - `csc-gemini` → read CSC_SERVER_HOSTNAME from .env
   - `csc-chatgpt` → read CSC_SERVER_HOSTNAME from .env
   - `csc-docker` → read CSC_SERVER_HOSTNAME from .env

2. **Documentation updates**
   - README.md — add official server info
   - CLAUDE.md — replace localhost references
   - Client READMEs — update connection instructions

3. **Testing**
   - Verify each client connects to facingaddictionwithhope.com
   - Check logs for successful connection

**Official Server Configuration:**
```env
CSC_SERVER_HOSTNAME=facingaddictionwithhope.com
CSC_SERVER_PORT=9525
```

**Expected Deliverables:**
- All clients read from .env for server hostname
- Documentation fully updated
- Tests passing

---

## Phase 2B: Time Synchronization (HAIKU)

**Task:** `prompts/wip/haiku-time-sync-for-server-merges.md`
**Agent:** Claude Haiku 4.5 (time sync implementation)
**Status:** IN PROGRESS

### What Haiku Will Implement

1. **Server Startup Timestamp**
   - Record when server starts (Unix timestamp)
   - Persist to `server_startup_time.json`
   - Use in server-to-server comparisons

2. **User Connection Tracking**
   - Track when each user connects (`connect_time`)
   - Store with user data
   - Use for collision detection

3. **NTP Time Verification**
   - `NTPClient` class in csc-shared
   - Verify system clock accuracy
   - Detect time drift > 10 seconds
   - Log warnings for misaligned servers

4. **S2S Time Exchange**
   - SLINKTIME command during handshake
   - Compare server startup times
   - Log time drift warnings

**Configuration:**
```env
CSC_SERVER_ID=server_001
CSC_NTP_SERVER=pool.ntp.org
CSC_TIME_DRIFT_TOLERANCE=10
```

**Expected Deliverables:**
- `packages/csc-shared/time_sync.py` — NTPClient class
- Server tracks startup_time and user connect_time
- S2S handshake includes time verification
- Tests demonstrating time tracking

---

## Phase 2C: Nick Collision Resolution (HAIKU)

**Task:** `prompts/wip/haiku-nick-collision-resolution.md`
**Agent:** Claude Haiku 4.5 (collision handling)
**Status:** IN PROGRESS

### What Haiku Will Implement

1. **Collision Detection**
   - When S2S link established, check for duplicate nicks
   - Compare nicknames across servers
   - Identify collisions

2. **Collision Resolution Algorithm**
   - **Rule 1:** Earlier connection time wins
   - **Rule 2:** If equal time, server ID wins (lexicographic)
   - Loser gets renamed: `alice` → `alice_s2`

3. **CollisionResolver Class**
   - `detect_collision()` — find conflicts
   - `resolve_collision()` — determine winner
   - `_rename_nick()` — generate new nick
   - Audit log tracking all resolutions

4. **User Rename Protocol**
   - KICK message forcing nick change
   - RENAMENICK command between servers
   - User disconnect and re-register with new nick

**Expected Deliverables:**
- `packages/csc-server/collision_resolver.py` — CollisionResolver class
- Server integration with S2S protocol
- Tests demonstrating collision detection and resolution
- Audit logging of all collision resolutions

---

## Integration Points

### Opus → Haiku Handoff

The three Haiku tasks depend on Opus's work:
1. Server linking creates S2S connections
2. Time sync runs during handshake
3. Collision resolution happens during SYNCUSER

**Coordination:**
- Opus completes S2S basic protocol
- Haiku adds time verification to handshake
- Haiku adds collision detection to SYNCUSER handling
- Opus integrates collision resolver into sync flow

### File Dependencies

```
Opus creates:
  - server_s2s.py (ServerLink, ServerNetwork)
  - Updates server_message_handler.py (S2S handlers)

Haiku extends:
  - server.py (startup_time, connect_time tracking)
  - server_message_handler.py (collision handling)
  - Creates time_sync.py (NTPClient)
  - Creates collision_resolver.py (CollisionResolver)
```

---

## Testing Strategy

### Phase 1: Opus Tests
- Single S2S connection (A ↔ B)
- Message routing between servers
- Channel sync across link
- User visibility on both servers

### Phase 2: Haiku Tests
- Time sync verification on connect
- NTP client functionality
- Nick collision detection
- Collision resolution (rename user)

### Phase 3: Integration Tests
- 3+ server chain (A ↔ B ↔ C)
- Channels sync across all servers
- Users see each other on all servers
- Nick collision handled correctly
- Time drift warning logged
- Message routing full-mesh

---

## Success Metrics

- [ ] Two CSC servers link successfully via S2S
- [ ] Users on Server A see users on Server B
- [ ] Messages route correctly between servers
- [ ] Nick collisions detected and resolved
- [ ] All clients use official server (facingaddictionwithhope.com)
- [ ] Time verification works (NTP synced)
- [ ] Full test suite passes
- [ ] No breaking changes to single-server operation

---

## Current Status (2026-02-19)

### Completed
- ✅ sm-run CLI tool (service module runner)
- ✅ dc-run CLI tool (docker prompt runner)
- ✅ Client .env configuration (CSC_SERVER_HOSTNAME)
- ✅ p-files.list (file index for grep discovery)
- ✅ csc-docker package (Docker-based client)
- ✅ Prompts created for federation work

### In Progress
- 🔄 opus-server-linking-federation.md (assigned to Opus)
- 🔄 haiku-configure-official-csc-server.md (assigned to Haiku)
- 🔄 haiku-time-sync-for-server-merges.md (assigned to Haiku)
- 🔄 haiku-nick-collision-resolution.md (assigned to Haiku)

### Blocked On
- Awaiting Opus work on S2S protocol
- Awaiting Haiku work on configuration and sync

---

## How Agents Start Work

Each agent will find their task in `prompts/wip/`:

```bash
# Opus starts with:
/opt/csc/prompts/wip/opus-server-linking-federation.md

# Haiku works on (in parallel):
/opt/csc/prompts/wip/haiku-configure-official-csc-server.md
/opt/csc/prompts/wip/haiku-time-sync-for-server-merges.md
/opt/csc/prompts/wip/haiku-nick-collision-resolution.md
```

### Workflow

1. **Read prompt** — Understand requirements
2. **Journal progress** — `echo "step" >> prompts/wip/TASK.md`
3. **Implement code** — Create/modify files
4. **Test work** — Verify tests pass
5. **Commit changes** — `git commit -m "..."`
6. **Move to done** — `mv prompts/wip/TASK.md prompts/done/`
7. **Push** — `git push`

---

## Commands for Manual Testing

Once agents finish, test the federation:

```bash
# Terminal 1: Start primary server
csc-server

# Terminal 2: Start secondary server (different port)
CSC_SERVER_PORT=9526 csc-server

# Terminal 3: Client to primary
csc-client

# Terminal 4: Client to secondary
CSC_SERVER_HOSTNAME=127.0.0.1 CSC_SERVER_PORT=9526 csc-client

# In client, issue S2S link command:
AI do server link 127.0.0.1:9526 <password>

# Verify federation:
/names #general  # Should see users from both servers
/msg <remote-user> Hello  # Message should route to other server
```

---

## References

- RFC 2813 — Internet Relay Chat: Server-to-Server Protocol
- CSC Platform Documentation: `docs/platform.md`
- CLAUDE.md — Development instructions
- README.1st — Task workflow
