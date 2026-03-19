# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> -- refer to my_tool_pouch.md for things that I can do --

---

## CRITICAL: Subprocess Spawning Rules (2026-03-12)

**NEVER use these subprocess flags:**
- `subprocess.CREATE_NEW_PROCESS_GROUP` - BANNED
- `subprocess.DETACHED_PROCESS` - BANNED
- `subprocess.CREATE_NEW_WINDOW` - BANNED
- `subprocess.CREATE_NEW_CONSOLE` - BANNED

These spawn uncontrollable visible terminal windows that fill the desktop and make the system unusable.

**CORRECT Windows background process:**
```python
subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW, stdout=log_file, stderr=log_file)
```

See `SUBPROCESS_SPAWNING_RULES.md` and `WINDOW_SPAWNING_FIX_REQUIRED.txt` for details.

---

## Project Overview

**CSC (Client-Server-Commander)** is an IRC-based multi-AI orchestration system consisting of:

- **Server**: Central IRC server implementing RFC 2812 protocol with persistent storage
- **Clients**: Multiple AI agents (Claude, Gemini, ChatGPT) and human CLI client
- **Bridge**: Protocol bridge proxy for external IRC clients
- **Shared Library**: Core IRC protocol and utilities used by all components

**Location**: `PROJECT_ROOT` (for this repo layout: `/c/csc/`)
**Type**: Python 3.8+ with pip-installable packages

---

## Architecture

### High-Level Message Flow

```
User Input → csc-client → IRC Server → [Route to Channels] → AI Clients (Claude/Gemini/ChatGPT)
                                                ↑
                                         [Persist to disk]
```

### Key Components & Organization

#### Server (`packages/csc-server/`)
- **Entry**: `main.py` → `Server.run()`
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

## Workorder (Prompt) Command Workflow

**ALWAYS use these commands in this order when working on workorders:**

### Check Queue Status
```bash
prompts status          # See queue stats (ready/wip/done/hold counts)
prompts list ready      # List all available workorders
```

### Read a Workorder
```bash
prompts read 1          # Read workorder #1
prompts read <filename> # Or read by full filename
```

### Assign & Work
```bash
agent select sonnet              # Select which agent to use
agent assign 1 sonnet            # Assign workorder #1 to sonnet
agent tail 50                    # Watch workorder progress (tail WIP file)
agent stop                       # Stop the running agent
```

### Manage After Work
```bash
prompts append <filename>        # Append notes to completed workorder
prompts move <filename> done     # Move to done/ after completion
```

### Available Commands

**Workorders (Queue Management):**
- `workorders status` - Show queue statistics (ready/wip/done/hold)
- `workorders list [ready|wip|done|hold|archive|all]` - List workorders in a directory
- `workorders read <#|filename>` - Display workorder content (first 20 lines)
- `workorders add <desc> [tags] : <content>` - Create a new workorder in ready/
- `workorders edit <filename> : <content>` - Edit an existing workorder
- `workorders append <filename> : <text>` - Append text with timestamp to a workorder
- `workorders move <#|filename> <dir>` - Move workorder between directories
- `workorders assign <#|filename> <agent>` - Select agent and assign workorder
- `workorders archive <filename>` - Move verified workorder from done/ to archive/
- `workorders delete <filename>` - Permanently remove a workorder
- `workorders help` - Show help for workorder commands

**Agent (Execution Control):**
- `agent list` - List available AI agent backends and their status
- `agent select <name>` - Select active agent (haiku, gemini-3-pro, opus, etc.)
- `agent assign <filename>` - Assign workorder to the currently selected agent
- `agent status` - Show running/pending tasks and WIP progress
- `agent tail [N] [filename]` - Tail N lines of the WIP journal (checks temp repo if running)
- `agent stop` - Gracefully stop the running agent (SIGTERM)
- `agent kill` - Force kill agent and move WIP back to ready/
- `agent help` - Show help for agent commands

**Service Control (csc-ctl):**
- `csc-ctl status [service]` - Show status of all or a specific service
- `csc-ctl show <service> [setting]` - Display service configuration
- `csc-ctl config <service> <setting> [value]` - Get or set service configuration
- `csc-ctl set <key> <value>` - Shorthand to set a config value
- `csc-ctl enable/disable <service>` - Toggle service enabled state
- `csc-ctl restart <service> [--force]` - Restart a service
- `csc-ctl install [service|all] [--list]` - Install background services (Scheduled Tasks/Cron)
- `csc-ctl remove [service|all] [--list]` - Remove background services
- `csc-ctl cycle <service>` - Run a single processing cycle (queue-worker, test-runner, pm)
- `csc-ctl dump [service]` - Export config to stdout
- `csc-ctl import [service]` - Import config from stdin

**Dynamic Services (AI):**
- `AI <token> builtin <echo|time|ping|help>` - Core server services
- `AI <token> <plugin> <method> [args]` - Execute dynamic plugin methods
- `AI <token> help` - List local AI command capabilities

---

## Common Commands

### Setup & Installation

```bash
# Install all packages (run from project root, e.g. /c/csc)
pip install -e packages/csc-shared
pip install -e packages/csc-server
pip install -e packages/csc-client
pip install -e packages/csc-claude      # requires ANTHROPIC_API_KEY
pip install -e packages/csc-gemini      # requires GOOGLE_API_KEY
pip install -e packages/csc-chatgpt     # requires OPENAI_API_KEY
pip install -e packages/csc-bridge

# New unified package (replaces individual packages)
pip install -e packages/csc-service
# Or with AI client dependencies:
pip install -e "packages/csc-service[all]"

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

# Unified service (runs test-runner + queue-worker + PM in one process)
csc-service --daemon --local

# Manage components
```bash
# Status & Configuration Display
csc-ctl status                          # Show all services status
csc-ctl status <service>                # Show specific service status
csc-ctl show <service>                  # Display service config (JSON format)
csc-ctl show <service> <setting>        # Display single config setting

# Configuration Management
csc-ctl config <service> <setting> [value]
# Examples:
csc-ctl config queue-worker poll_interval       # Show current value
csc-ctl config queue-worker poll_interval 120   # Set to 120 seconds
csc-ctl config test-runner enabled true         # Enable test-runner
csc-ctl config csc-service log_level debug      # Set log level

# Backup & Restore
csc-ctl dump                            # Export all services config to stdout
csc-ctl dump <service>                  # Export single service config to stdout
csc-ctl dump > backup.json              # Save complete backup
csc-ctl dump queue-worker > qw.json     # Save queue-worker config

# Restore from backup
csc-ctl import < backup.json            # Restore all services from backup
csc-ctl import queue-worker < qw.json   # Restore single service

# Service Lifecycle Control
csc-ctl restart <service>               # Graceful restart: stop, wait 5s, start
csc-ctl restart <service> --force       # Hard restart: kill, wait 5s, start
csc-ctl restart all                     # Restart all services

csc-ctl install all                     # Install all background services
csc-ctl install queue-worker            # Install specific service
csc-ctl install --list                  # Show what would be installed

csc-ctl remove queue-worker             # Uninstall/stop service
csc-ctl remove all                      # Remove all background services
csc-ctl remove --list                   # Show what would be removed
```

# Docker deployment
docker compose up -d csc-service
```

### Testing

**DO NOT RUN TESTS. The test runner handles all test execution.**

The test cycle is fully automated:
1. **You** fix code, delete the stale log, commit, push, move prompt to done.
2. **Test runner** (`bin/test-runner`) polls every minute, detects missing logs, runs the tests, writes new logs.
3. **If tests fail**, test runner auto-generates a new `prompts/ready/PROMPT_fix_test_<name>.md`.
4. **Next agent** picks up the fix prompt and repeats.

**Your job on a test-fix task:**
- Read the existing log to understand the failure
- Fix the code
- `rm tests/logs/test_<name>.log` (so the test runner re-runs it)
- Commit, push, move prompt to done
- **That's it. Do NOT run pytest.**

```bash
# Delete a log to trigger retest
rm tests/logs/test_server_irc.log

# Check an existing log (never re-run, just read)
cat tests/logs/test_server_irc.log | tail -5

# Test runner (Python, runs automatically via scheduled task every 1 min)
python bin/test-runner              # Run one cycle manually
python bin/test-runner --daemon     # Run continuously (poll every 60s)
python bin/test-runner --install    # Install as Windows scheduled task
python bin/test-runner --uninstall  # Remove Windows scheduled task
bin/test-runner.bat                 # Windows batch wrapper

# Legacy bash runner (Linux/macOS cron)
bash tests/run_tests.sh
```

**Log file = lock**: If a log exists, the test runner skips that test. Delete the log to force a retest.

**Platform-gated tests**: Tests targeting a specific OS (Windows, macOS, Android, Docker) use `tests/platform_gate.py`. On the wrong platform they print `PLATFORM_SKIP:` and the log stays (locks that machine). Test runner generates a `PROMPT_run_test_<name>.md` routing prompt. When an AI on the right platform picks it up, it deletes the log and lets the test runner run the test there.

**Installer**: Run `bin/install-test-runner.bat` to build and start the Docker-based test runner (polls every 60s). Use `bin/uninstall-test-runner.bat` to stop and remove it. Do NOT use Windows Task Scheduler (causes popup windows).

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

# Quick refresh (tools/ only — faster, for rapid iteration)
refresh-maps --quick
```

`agent-wrapper` calls `refresh-maps --quick` automatically before its commit step.

What it regenerates:
- `tools/INDEX.txt` + per-package `.txt` files — code API maps (classes, methods, signatures)
- `tree.txt` — ASCII directory tree
- `p-files.list` — flat file listing for `grep` discovery
- `analysis_report.json` — undocumented items audit
- `tools.txt` — pointer file

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

The server uses atomic JSON writes (temp file → fsync → atomic rename) to guarantee zero data loss:

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

Oper credentials, active opers, and client registry are **read from disk on every access** via `@property` methods in `server.py`. Editing `opers.json` or `users.json` while the server is running takes effect immediately — no restart needed.

```python
# These are @property methods, not cached dicts:
server.oper_credentials  # → reads opers.json every time
server.opers             # → reads opers.json every time
server.client_registry   # → reads users.json every time
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

### Platform Detection

The Platform layer (`packages/csc_shared/platform.py`) detects system capabilities on startup:

```python
# Inheritance: Root -> Log -> Data -> Version -> Platform -> Network -> Service
# Detects: hardware, OS, virtualization, software, Docker, AI agents, resources
# Persists to: <PROJECT_ROOT>/platform.json

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
7. **Agent Temp Repo Isolation**: Queue-worker spawns agents in isolated temp repo clones, NEVER in CSC_ROOT itself. `get_agent_temp_repo()` includes collision detection to prevent the temp path from resolving to the main repo (which would cause git conflicts and data corruption).

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
| `packages/csc-service/` | Unified package (server, clients, infra, bridge) |
| `tests/` | Integration & unit tests |
| `tools/` | Generated code maps (one per package) |

### Code Map (tools/)

Before reading source files, check `tools/INDEX.txt` for a package overview, then read the specific package map (e.g. `tools/csc-server.txt`) to find which file and method you need. Only then open the actual `.py` file. This saves context — you hold a map instead of all the source.

```bash
# Regenerate all maps after code changes (tools/, tree.txt, p-files.list)
refresh-maps

# Quick mode (tools/ only, faster)
refresh-maps --quick
```

Each `tools/<package>.txt` shows every class, method signature, and one-line doc — like C++ header files. Find what you need there, then read the implementation.

---

## Instruction History

User directives are logged to `<PROJECT_ROOT>/instruction_history.log` — one line per instruction, extracted from conversations.

**During every conversation:**
- As the user gives instructions, extract the core directive and append it:
  ```bash
  echo "2026-02-19T14:50 | do NOT remove logs on PLATFORM_SKIP, let prompt route to right machine" >> "$CSC_ROOT/instruction_history.log"
  ```
- One line per distinct instruction. Capture **what the user said to do**, not what you did.
- Use ISO timestamp. Keep lines short but preserve the user's intent verbatim.
- Mixed instructions in one message → split into separate lines.

**On startup:** Do NOT read the full history (it may get large). But if context feels thin or a restart just happened, a quick `tail -5 "$CSC_ROOT/instruction_history.log"` can offer more insight than README.1st alone.

---

## Git Workflow

- **NEVER include Co-Authored-By, Signed-off-by, or any AI attribution in commit messages** — commits represent user decisions, not AI work. Do NOT append "Co-Authored-By: Claude ..." or any variant. AI contributions are logged ONLY in `<PROJECT_ROOT>/contrib.txt`.
- **Before every commit**: run `refresh-maps` (or `refresh-maps --quick`) to update project reference files. Stale maps cause agents to waste time on dead code paths.
- Use `git status` and `git diff` to review changes before committing
- Keep commits focused and well-described
- Branch from `main` for feature work

---

## Safe Deletion Protocol: Use `trash` Command Instead of `rm`

**NEVER use `rm` directly.** Use the `trash` command to safely stage deletions.

### Setup (One-Time)
Add trash aliases to your shell (`.bashrc` or equivalent):
```bash
source /path/to/csc/bin/setup-trash-aliases.sh
```

This creates:
- `rm` → Shows error message, directs you to use `trash`
- `trash` → Safe deletion command (moves to `.trash/`)
- `RM` → Emergency alias for actual `rm` (use only if absolutely necessary)

### Deletion Workflow

**Step 1: Move files to trash**
```bash
trash /path/to/file1
trash /path/to/file2
# or multiple at once:
trash /path/to/file1 /path/to/file2 /path/to/file3
```

**Step 2: Verify trash contents**
```bash
trash --list
# or: ls -lh .trash/
```

**Step 3: Empty trash when ready**
```bash
trash --empty
```

### Trash Command Options
```bash
trash file1 file2        # Move files to .trash/
trash -f file1           # Force (no confirmation output)
trash --list             # Show .trash/ contents
trash --empty            # Permanently delete all files in .trash/
trash --help             # Show usage
```

### Rules
- `.trash/` is in `.gitignore` — never committed to git
- Always verify with `trash --list` before emptying
- Use `RM` only in genuine emergencies (actual `rm` command)
- Filename conflicts in `.trash/` are auto-timestamped

### Why This Works
- Prevents accidental permanent deletion
- Provides recovery window if wrong files moved to trash
- Staged deletion is safer than direct rm
- Can review and verify before final removal
- Shells with `rm` alias prevent typos and muscle memory

---

## Common Debugging Scenarios

**Server won't start**: Check that UDP port 9525 is available and no other server is running
```bash
lsof -i :9525
```

**Client can't connect**: Verify server is running and listening
```bash
python -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.sendto(b'test', ('localhost', 9525))"
```

**Persistence test failures**: The storage system is critical. Check that:
- JSON files are valid (not corrupted)
- Disk has free space
- File permissions allow read/write
- Storage files are in the server's working directory (same dir as where server runs)

**AI client not responding**: Check API keys are set in environment or `~/.config/csc-NAME/secrets.json`

---

## Performance Notes

- **Haiku models**: Use for lightweight searches, tests, quick analysis
- **Sonnet models**: Use for implementation, complex reasoning, architectural decisions
- **Tests are authoritative**: If behavior differs from tests, the tests define correctness
- **JSON is normalized**: Channel names normalized to lowercase before storage lookup

---

## Critical: Mandatory PR Review Policy

**NO code changes merge to main without PR review by Opus or Gemini-3-Pro.**

This is the only safeguard against breaking changes in a complex, distributed system.

### Why This Is Critical

CSC is deeply interconnected:
- Queue-worker changes affect PM and all agents
- Server changes break IRC protocol for all clients
- Shared library changes cascade everywhere
- One agent only sees their task, not system-wide impact

**Code reviewers with full context must approve every change.**

### Workflow

1. **Feature branch**: `git checkout -b feature/description`
2. **Make changes** and commit
3. **Push**: `git push -u origin feature/description`
4. **Create PR**: `gh pr create --title "..." --body "..."`
5. **Assign to**: Opus or Gemini-3-Pro with full context
6. **Review checklist**: See `PR_REVIEW_POLICY.md`
7. **Approval required**: `gh pr review --approve`
8. **Merge only after approval**: `gh pr merge`

### Reviewers: Opus or Gemini-3-Pro (Single Review)

**Either one can approve** → PR merges
**Either one requests changes** → Author must revise and resubmit

Both are high-capability models with full context. Trust their judgment.

Critical files (deeper scrutiny, but single review):
- `packages/csc-service/csc_service/infra/queue_worker.py`
- `packages/csc-service/csc_service/infra/pm.py`
- `packages/csc-service/csc_service/main.py`
- Agent entry points
- Server core protocol

### Reviewer Responsibilities

Load full context before reviewing:
```bash
cat tools/csc-service.txt          # See what changed
git log --oneline -10              # Understand context
grep -r "<changed-module>" packages/  # Find dependencies
```

Check:
- [ ] Breaks any CLAUDE.md invariants?
- [ ] All related components updated?
- [ ] Could break tests?
- [ ] Matches project patterns?
- [ ] Security implications?
- [ ] Storage still atomic if needed?
- [ ] Could cascade to other systems?

### Main Branch Protection

- **No direct commits** to main
- **All PRs require review**
- **Tests must pass**
- **Context is mandatory**

See `PR_REVIEW_POLICY.md` for full details.

---

## Cross-Server Communication (claude-relay-ask)

CSC servers linked via S2S can query each other's Claude instance using mTLS relay.

### Usage
```bash
# Ask another server's Claude a question
echo "your prompt" | claude-relay-ask <host> [port]
claude-relay-ask haven.ef6e 9531 <<< "what is 2+2"

# From Python
import subprocess
result = subprocess.run(
    ["claude-relay-ask", "10.10.10.1", "9531"],
    input="your prompt", capture_output=True, text=True
)
print(result.stdout)
```

### How It Works
- Uses the SAME S2S mTLS certs (s2s_cert, s2s_key, s2s_ca from csc-service.json)
- Connects to the remote server's relay port (default 9531)
- Sends prompt as null-byte terminated UTF-8 frame
- Receives response (up to 5 min timeout)
- Both sides must present valid CSC CA-signed certs

### Environment Variables (optional, falls back to csc-service.json)
- `CLAUDE_RELAY_CERT` - Path to this node's cert chain PEM
- `CLAUDE_RELAY_KEY` - Path to this node's private key PEM
- `CLAUDE_RELAY_CA` - Path to CA cert PEM

### Known Peers
- `10.10.10.1:9531` - haven.ef6e (Linux)
- `10.10.10.2:9531` - haven.4346 (Windows)

### When to Use
- Need information from the other server's environment
- Want to delegate a task to the other server's Claude
- Cross-platform verification (run on Linux, verify on Windows)

---

## S2S Server Linking

### Architecture
- UDP-based with DH key exchange (RFC 3526 Group 14, 2048-bit)
- AES-256-GCM encryption after handshake
- mTLS cert authentication (cert CN must match server shortname)
- Auto-link daemon retries every 30 seconds

### Port Allocation (9520-9529)
- 9520: S2S inter-server link (UDP)
- 9525: IRC server (UDP)
- 9526: Bridge proxy (UDP, localhost only)
- 9531: Claude relay (TCP+TLS)

### Config (csc-service.json)
```json
{
  "s2s_cert": "C:\\csc\\etc\\haven.4346.chain.pem",
  "s2s_key": "C:\\csc\\etc\\haven.4346.key",
  "s2s_ca": "C:\\csc\\etc\\ca.crt",
  "s2s_peers": [{"host": "10.10.10.1", "port": 9520}]
}
```

### Troubleshooting
- `CSC_HOME` env var not needed -- code falls back to cwd for config
- Check cert CN matches `Platform.get_server_shortname()` output
- Both servers must have `enable_server: true`

---

## References

- `README.md` - Overview, quick start, directory structure
- `docs/platform.md` - Platform detection, cross-platform support, capability-aware routing
- `PERMANENT_STORAGE_SYSTEM.md` - Detailed storage architecture and recovery mechanics
- `POWER_FAILURE_VERIFICATION.md` - Test procedures and verification checklist
- `tests/platform_gate.py` - Cross-platform test gating helper
- Individual package READMEs - Package-specific details
