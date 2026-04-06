# GEMINI.md

This file provides guidance to Gemini CLI when working with code in this repository.

---

## Project Overview

**CSC (Client-Server-Commander)** is an IRC-based multi-AI orchestration system consisting of:

- **Server**: Central IRC server implementing RFC 2812 protocol with persistent storage
- **Clients**: Multiple AI agents (Claude, Gemini, ChatGPT) and human CLI client
- **Bridge**: Protocol bridge proxy for external IRC clients
- **Shared Library**: Core IRC protocol and utilities used by all components

**Location**: `/opt/csc/`
**Type**: Python 3.8+ with pip-installable packages

---

## Architecture

### High-Level Message Flow

```
User Input -> csc-client -> IRC Server -> [Route to Channels] -> AI Clients (Claude/Gemini/ChatGPT)
                                                ^
                                         [Persist to disk]
```

### Key Components & Organization

#### Server (`packages/csc-server/`)
- **Entry**: `main.py` -> `Server.run()`
- **Core**: `server.py` - Main IRC server and message routing
- **Handlers**: `server_message_handler.py` - All IRC command implementations (PRIVMSG, JOIN, MODE, etc.)
- **Storage**: `storage.py` - Atomic JSON-based persistence (channels, users, opers, bans, history)
- **Networking**: `network.py` - UDP socket handling, message encoding/decoding
- **State**: In-memory dicts (channels, users, opers) loaded from JSON on startup

#### Shared Library (`packages/csc-shared/`)
- Imports: `from csc_shared.irc import ...`
- `irc.py` - IRC message parsing, message building, numeric replies
- `channel.py` - Channel data structure with members, modes, bans
- `user.py` - User data structure with modes, channels
- `logging.py` - Logging utilities
- `platform.py` - Platform detection layer (hardware, OS, virtualization, software, Docker, AI agents)

#### AI Clients (claude/gemini/chatgpt)
- Each connects to server as a normal IRC client
- Receive PRIVMSG events when messages arrive in joined channels
- Send responses via PRIVMSG back to server

#### Human Client (`packages/csc-client/`)
- Interactive terminal interface
- Readline support for command history
- Command parser and display formatting

---

## Common Commands

### Setup & Installation

```bash
# Install all packages (run from /opt/csc)
pip install -e packages/csc-shared
pip install -e packages/csc-server
pip install -e packages/csc-client
pip install -e packages/csc-claude      # requires ANTHROPIC_API_KEY
pip install -e packages/csc-gemini      # requires GOOGLE_API_KEY
pip install -e packages/csc-chatgpt     # requires OPENAI_API_KEY
pip install -e packages/csc-bridge

# Quick reinstall of a single package
pip install -e packages/csc-server --force-reinstall --no-deps
```

### Running the System

```bash
# Terminal 1: Start server (listens on UDP port 9525)
csc-server

# Terminal 2: Human client
csc-client

# Terminal 3+: AI agents
csc-claude
csc-gemini
csc-chatgpt

# Optional: IRC bridge (bridges to external IRC clients)
csc-bridge
```

### Testing

**DO NOT RUN TESTS. Cron handles all test execution.**

The test cycle is fully automated:
1. **You** fix code, delete the stale log, commit, push, move prompt to done.
2. **Cron** (`tests/run_tests.sh`) detects missing logs, runs the tests, writes new logs.
3. **If tests fail**, cron auto-generates a new `prompts/ready/PROMPT_fix_test_<name>.md`.
4. **Next agent** picks up the fix prompt and repeats.

**Your job on a test-fix task:**
- Read the existing log to understand the failure
- Fix the code
- `rm tests/logs/test_<name>.log` (so cron re-runs it)
- Commit, push, move prompt to done
- **That's it. Do NOT run pytest.**

```bash
# Delete a log to trigger cron retest
rm tests/logs/test_server_irc.log

# Check an existing log (never re-run, just read)
cat tests/logs/test_server_irc.log | tail -5

# Cron test runner -- runs all tests missing a log, creates fix prompts for failures
bash tests/run_tests.sh
```

**Log file = lock**: If a log exists, cron skips that test. Delete the log to force a retest.

**Platform-gated tests**: Tests targeting a specific OS (Windows, macOS, Android, Docker) use `tests/platform_gate.py`. On the wrong platform they print `PLATFORM_SKIP:` and the log stays (locks that machine). Cron generates a `PROMPT_run_test_<name>.md` routing prompt. When an AI on the right platform picks it up, it deletes the log and lets cron run the test there.

### Development

```bash
# After editing a package, reinstall in dev mode
cd packages/csc-server
pip install -e . --force-reinstall

# Run server with Python directly (faster iteration)
cd packages/csc-server && python -m csc_server.main

# Check imports in interactive Python
python -c "from csc_shared.irc import IRCMessage; print(IRCMessage)"
```

### Refreshing Project Maps

Reference files (code maps, file listings, directory tree) must stay current.
**Run `refresh-maps` before every commit.** An outdated map sends agents to dead ends.

```bash
# Full refresh (tools/, tree.txt, p-files.list)
refresh-maps

# Quick refresh (tools/ only -- faster, for rapid iteration)
refresh-maps --quick
```

`agent-wrapper` calls `refresh-maps --quick` automatically before its commit step.

What it regenerates:
- `tools/INDEX.txt` + per-package `.txt` files -- code API maps (classes, methods, signatures)
- `tree.txt` -- ASCII directory tree
- `p-files.list` -- flat file listing for `grep` discovery
- `analysis_report.json` -- undocumented items audit
- `tools.txt` -- pointer file

---

## Key Design Patterns

### IRC Message Handling

All IRC commands flow through `server_message_handler.py`. Each command (PRIVMSG, JOIN, QUIT, etc.) has a handler method:

```python
def handle_privmsg(self, client_addr, nick, target, message_text):
    # Called when client sends: PRIVMSG #channel :message
    # target = "#channel" or "nick" (for direct messages)
    # message_text = the actual message content
```

### Persistent Storage

The server uses atomic JSON writes (temp file -> fsync -> atomic rename) to guarantee zero data loss:

```python
# Storage files in server working directory:
channels.json   # Channel state, members, modes, bans
users.json      # User credentials, modes
opers.json      # Operator passwords and active opers
bans.json       # Ban masks
history.json    # Disconnection history for WHOWAS
```

Key invariant: **Every state change is written to disk before the handler returns**. This means the server can recover completely from power failure mid-operation.

### On-Demand Disk Reading

Oper credentials, active opers, and client registry are **read from disk on every access** via `@property` methods in `server.py`. Editing `opers.json` or `users.json` while the server is running takes effect immediately -- no restart needed.

```python
# These are @property methods, not cached dicts:
server.oper_credentials  # -> reads opers.json every time
server.opers             # -> reads opers.json every time
server.client_registry   # -> reads users.json every time
```

Channels and bans still use in-memory state (`ChannelManager`) that is loaded at startup and persisted on every change.

### Channel & User State

- `self.channels` via `ChannelManager` - In-memory, persisted on change
- `self.clients: dict[addr, info]` - In-memory connected client sessions
- `self.oper_credentials` - On-demand from `opers.json` (property)
- `self.opers` - On-demand from `opers.json` (property)

When clients join/part/change modes, both the in-memory structure and JSON files are updated atomically.

### Message Routing

When a PRIVMSG arrives to a channel:
1. Handler validates the channel exists and user has permission
2. If target is a channel, broadcast to all members on that channel
3. If target is a user, route to that user's address
4. Message is also stored in `history.json` for persistence

---

## Work Log Journaling Protocol -- MANDATORY

**Before executing ANY action on a task, journal the action to the active WIP file.**

```bash
echo "Reading services/agent_service.py to understand assign command" >> /opt/csc/prompts/wip/TASK_NAME.md
```

**Every file modification, every git command must be preceded by an echo to the WIP file.**

This protocol is essential for crash recovery and team collaboration. Your conversational history is NOT a substitute for this on-disk log. See `/opt/csc/README.1st` for the full protocol.

---

### Platform Detection

The Platform layer (`packages/csc_shared/platform.py`) detects system capabilities on startup:

```python
# Inheritance: Root -> Log -> Data -> Version -> Platform -> Network -> Service
# Detects: hardware, OS, virtualization, software, Docker, AI agents, resources
# Persists to: /opt/csc/platform.json

# Capability checking (used by prompt routing):
platform.has_tool("git")                     # Is git installed?
platform.has_docker()                        # Is Docker usable?
platform.matches_platform(["windows"])       # Are we on Windows?
platform.check_requirements(requires=["docker"], platform_list=["linux"])
```

Prompt files can declare requirements via YAML front-matter:
```yaml
---
requires: [docker, git]
platform: [linux]
min_ram: 4GB
---
```

---

## Important Invariants

1. **Atomic Storage**: All updates to JSON files use atomic pattern - no partial writes
2. **Disk is Source of Truth**: Oper credentials and active opers are read from disk on every access. Channels/bans use in-memory state synced to disk on every change
3. **Case Sensitivity**: IRC channel/nick names are case-insensitive internally but normalized
4. **Mode System**: Users and channels have modes (`+i`, `-o`, etc.) that affect behavior
5. **Ban System**: Global and per-channel ban masks prevent users from joining
6. **Platform Detection**: Platform inventory runs on every startup and persists to platform.json

---

## File Locations & What's Where

| Location | Purpose |
|----------|---------|
| `packages/csc-shared/` | Shared IRC protocol library (imported by all) |
| `packages/csc-shared/platform.py` | Platform detection layer (hardware, OS, Docker, AI agents) |
| `packages/csc-server/` | Main server; storage, message routing, IRC handler |
| `packages/csc-client/` | Human CLI client |
| `packages/csc-claude/` | Claude AI client via Anthropic API |
| `packages/csc-gemini/` | Gemini AI client via Google API |
| `packages/csc-chatgpt/` | ChatGPT AI client via OpenAI API |
| `packages/coding-agent/` | Docker-based coding agent for isolated code execution |
| `packages/csc-bridge/` | Protocol bridge proxy for external IRC |
| `tests/` | Integration & unit tests |
| `tools/` | Generated code maps (one per package) |

### Code Map (tools/)

Before reading source files, check `tools/INDEX.txt` for a package overview, then read the specific package map (e.g. `tools/csc-server.txt`) to find which file and method you need. Only then open the actual `.py` file. This saves context -- you hold a map instead of all the source.

```bash
# Regenerate all maps after code changes (tools/, tree.txt, p-files.list)
refresh-maps

# Quick mode (tools/ only, faster)
refresh-maps --quick
```

Each `tools/<package>.txt` shows every class, method signature, and one-line doc -- like C++ header files. Find what you need there, then read the implementation.

---

## Instruction History

User directives are logged to `/opt/csc/instruction_history.log` -- one line per instruction, extracted from conversations.

**During every conversation:**
- As the user gives instructions, extract the core directive and append it:
  ```bash
  echo "2026-02-19T14:50 | do NOT remove logs on PLATFORM_SKIP, let prompt route to right machine" >> /opt/csc/instruction_history.log
  ```
- One line per distinct instruction. Capture **what the user said to do**, not what you did.
- Use ISO timestamp. Keep lines short but preserve the user's intent verbatim.

**On startup:** Do NOT read the full history. But if context feels thin, `tail -5 /opt/csc/instruction_history.log` can help.

Also check `docs/memory/INDEX.md` and `docs/memory/STATUS.md` first. They are the shared durable context map for repo-launched CLI sessions: read those indexes, then open only the specific memory entries that are relevant to the current task.

---

## Git Workflow

- **NEVER include Co-Authored-By, Signed-off-by, or any AI attribution in commit messages** -- commits represent user decisions, not AI work. AI contributions are logged ONLY in `/opt/csc/contrib.txt`.
- **Before every commit**: run `refresh-maps` (or `refresh-maps --quick`) to update project reference files. Stale maps cause agents to waste time on dead code paths.
- Use `git status` and `git diff` to review changes before committing
- Keep commits focused and well-described
- Branch from `main` for feature work

---

## Common Debugging Scenarios

**Server won't start**: Check that UDP port 9525 is available
```bash
lsof -i :9525
```

**Client can't connect**: Verify server is running and listening
```bash
python -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.sendto(b'test', ('localhost', 9525))"
```

**Persistence test failures**: Check that JSON files are valid, disk has free space, file permissions allow read/write, storage files are in server's working directory

**AI client not responding**: Check API keys are set in environment or `~/.config/csc-NAME/secrets.json`

---

## Performance Notes

- **Flash models**: Use for lightweight searches, tests, quick analysis, simple edits
- **Pro models**: Use for implementation, complex reasoning, architectural decisions
- **Tests are authoritative**: If behavior differs from tests, the tests define correctness
- **JSON is normalized**: Channel names normalized to lowercase before storage lookup

---

## Gemini-Specific Notes

- Your models: gemini-2.0-flash, gemini-2.5-flash, gemini-2.5-flash-light, gemini-2.5-pro, gemini-3.0-flash, gemini-3.0-pro
- In this context, `~` resolves to `/home/davey`
- Agent prompt files with agent recommendations use prefixes (e.g., `gemini-2.5-flash-`, `haiku-`, `sonnet-`)
- Full platform docs: `docs/platform.md`

---

## References

- `README.md` - Overview, quick start, directory structure
- `README.1st` - Startup guide, crash recovery, work log protocol
- `docs/platform.md` - Platform detection, cross-platform support, capability-aware routing
- `PERMANENT_STORAGE_SYSTEM.md` - Detailed storage architecture and recovery mechanics
- `POWER_FAILURE_VERIFICATION.md` - Test procedures and verification checklist
- `tests/platform_gate.py` - Cross-platform test gating helper
- `tools/gemini_context.md` - Gemini run reviews and performance guidance
- Individual package READMEs - Package-specific details
