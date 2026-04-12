[← Back to README](../README.md)

# Services & Modules System

The Services System is the core of CSC's extensibility. It allows both human operators and AI agents to dynamically extend the server's functionality without a restart. This "self-evolving" capability is what enables CSC to adapt to new tasks in real-time.

---

## 🧩 What is a Service?

A service is a Python module located in the `services/` directory. Each service is a class that inherits from a base `Service` class. 

### Anatomy of a Service File
- **Filename**: Must end in `_service.py` (e.g., `weather_service.py`).
- **Class Name**: Must be lowercase and match the filename prefix (e.g., `class weather(Service):`).
- **Methods**: Any public method (not starting with `_`) becomes a callable IRC command.
- **Constructor**: Receives a reference to the `server` instance, allowing services to interact with the entire IRC ecosystem.

```python
from service import Service

class mytools(Service):
    def hello(self, *args):
        """Simple greeting service."""
        return "Hello from the new service!"
```

---

## 🤖 The AI Command Protocol

Services are invoked via the chatline using the `AI` keyword. This keyword is intercepted by the server's message handler and dispatched to the service manager.

**Syntax**: `AI <token> <service> <method> [args...]`

- **Token**: An arbitrary identifier (usually numeric) used by agents to track asynchronous responses. Use `0` for silent execution (no response broadcast).
- **Service**: The name of the service (e.g., `builtin`).
- **Method**: The method to execute (e.g., `current_time`).
- **Args**: Space-separated arguments passed to the method.

---

## ⚡ Dynamic Loading & Reloading

CSC uses "Hot Loading" for all services:
1.  **On-Demand Import**: A service is only imported when it's first called.
2.  **Auto-Reload**: Every time a service is called, the server uses `importlib.reload()` to ensure it's running the latest code on disk. This allows for immediate testing of code changes.
3.  **Caching**: Instantiated service objects are cached in `self.loaded_modules` to preserve state between calls during a session.

---

## 📤 AI Self-Modification (File Uploads)

AI agents can modify their own environment by uploading or extending service files.

### 1. Creating/Overwriting a Service
Agents use the `<begin file="name">` tag.
```irc
PRIVMSG #general :<begin file="weather">
PRIVMSG #general :from service import Service
PRIVMSG #general :class weather(Service):
PRIVMSG #general :    def get(self, city): return f"Sunny in {city}"
PRIVMSG #general :<end file>
```
The server validates the Python syntax, ensures the class name is correct, and moves it to `services/`. The service `weather` is now ready for use: `AI 1 weather get London`.

### 2. Extending an Existing Service
Agents can add methods to a service without overwriting the whole file using `<append file="name">`.
```irc
PRIVMSG #general :<append file="builtin">
PRIVMSG #general :    def ping_test(self): return "PONG!"
PRIVMSG #general :<end file>
```
The server uses AST (Abstract Syntax Tree) parsing to find the class definition and safely insert the new method into the existing code.

---

## 🛠️ Built-in Management Services

### `builtin`
Core utilities for system interaction.
- `echo <text>`: Returns the text.
- `status`: Returns system status.
- `current_time`: Returns server time.
- `download_url_content <url>`: Fetches web content.
- `download_url_to_file <url> <path>`: Downloads web content to a local file.
- `list_dir [path]`: Lists files in a directory.
- `read_file_content <path>`: Reads a file and wraps it in `<begin file>` tags for easy copying.
- `create_directory_local <path>`: Creates a local directory.
- `delete_local <path>`: Deletes a local file or empty directory.
- `move_local <src> <dest>`: Moves a local file or directory.
- `ftp_connect_list <host> [remote_path] [port] [user] [pass]`: Lists files on an FTP server.
- `ftp_download_file <host> <remote_path> <local_path> [port] [user] [pass]`: Downloads a file from FTP.
- `ftp_upload_file <host> <local_path> <remote_path> [port] [user] [pass]`: Uploads a file to FTP.

### `module_manager`
Administrative control over the service system.
- `list`: Lists all loaded and available services.
- `read <name>`: Reads the source code of a service module.
- `create <name> <base64>`: Creates a new service module from base64-encoded content.
- `rehash <name...>`: Force a reload of specific modules.
- `staging`: Lists files in `staging_uploads/` waiting for approval.
- `approve <name>`: Validates and moves a service module from `staging_uploads/` to `services/`.
  - Checks that the file contains exactly one class matching the service name.
  - Versions any existing file before overwriting.
- `reject <name>`: Deletes a service module from `staging_uploads/` (with version backup).

### `help`
Automated documentation generation.
- `help`: Lists all available service modules by scanning `services/*_service.py`.
- `help <service>`: Lists all commands for a specific service.
  - Uses AST (Abstract Syntax Tree) parsing to extract public methods and docstrings from the source code without executing it.
  - Attempts to load the module and call its `default()` method for additional context if available.

---

## 🧰 Utility Services

### `version`
File versioning and backup management system.

This service provides version control for individual files within the CSC project. The server maintains versioned backups of files in a dedicated version backup directory, allowing creation, restoration, and tracking of file changes over time.

**Commands:**
- `create <filepath>`: Creates a new version backup of the specified file. Returns the version number created.
- `restore <filepath> [version]`: Restores a file to a specific version. Defaults to "latest" if no version specified. Version can be a number or "latest".
- `history <filepath>`: Shows complete version history for a file, including latest version, active version, and all available backups.
- `list`: Lists all files that have version backups in the system.

**Version Information:**
- Version data comes from the server's version backup directory (`version_backup_dir`)
- Each versioned file has its own subdirectory containing:
  - Numbered backup files (e.g., `file.py.v1`, `file.py.v2`)
  - A `versions.json` metadata file tracking history, latest version, and active version
- Version numbers are integers starting from 1
- The "active" version is the one currently in use; "latest" is the most recent backup

**Example Usage:**
```irc
AI 1 version create services/myservice.py
AI 2 version history services/myservice.py
AI 3 version restore services/myservice.py 2
AI 4 version list
```

### `backup`
File and directory backup system using tar.gz archives.

This service provides comprehensive backup and restore capabilities for files and directories within the CSC project. The server maintains backup archives in a dedicated backup directory, allowing creation, listing, restoration, and comparison of backups over time.

**Commands:**
- `create <path1> [path2...]`: Creates a tar.gz backup archive of the specified files/directories. Multiple paths can be specified in a single backup. Returns the archive name, file count, and size.
- `list`: Lists all available backup archives in the backup directory with their sizes.
- `restore <archive> <dest>`: Restores a backup archive to a destination directory. Defaults to current directory if not specified. Includes path traversal protection.
- `diff <archive> <filepath>`: Compares a file in a backup archive with its current version on disk using unified diff format.

**Backup Information:**
- Backups are stored in the server's backup directory (`backups/` relative to project root)
- Archive naming format: `backup_<label>_<timestamp>.tar.gz` where label is derived from the first path
- Timestamp format: `YYYYMMDD_HHMMSS`
- Archives use gzip compression (tar.gz format)
- Backup history is tracked in service data including paths, creation time, file count, and size
- Security: restore operation validates paths to prevent directory traversal attacks

**Example Usage:**
```irc
AI 1 backup create services/myservice.py
AI 2 backup create services/ tests/
AI 3 backup list
AI 4 backup restore backup_services_20260217_123456.tar.gz ./restore_dir
AI 5 backup diff backup_services_20260217_123456.tar.gz services/myservice.py
```

### `curl`
A service to perform basic cURL-like web requests.

**Commands:**
- `run [options] <url>`: Executes an HTTP request.
  - `-H "Header: Value"`: Adds a custom header. Can be used multiple times.
  - `-d "Data"`: Sends data in the request body. Implies `POST` method.
  - Default method is `GET` if no data is provided.
  - Returns the status code and full response body.

**Example Usage:**
```irc
AI 1 curl run https://api.example.com/data
AI 2 curl run -H "Authorization: Bearer token" https://api.example.com/secure
AI 3 curl run -d '{"key": "value"}' -H "Content-Type: application/json" https://api.example.com/post
```

### `ntfy`
A dedicated service to send notifications via ntfy.sh. Uses the `curl` service as a backend.

**Commands:**
- `send <subject> <body>`: Sends a notification to the configured ntfy.sh topic.
  - Topic is hardcoded in the service file (default: `gemini_commander`).
  - Uses `curl` service to perform the HTTP POST.

**Dependencies:**
- Requires the `curl` service to be loaded.

---

## 🤖 Workflow & Automation Services

### `agent`

**AI Agent Runner Service**

Spawns and manages non-interactive AI CLI sessions to work on prompt files, following the `ready/wip/done` workflow with automatic journaling enforcement.

#### Architecture & Workflow

The agent service implements a complete task lifecycle:

1. **Selection** — Choose which AI backend (Claude Haiku/Sonnet/Opus, Gemini Flash/Pro, local models)
2. **Assignment** — Move a prompt file from `ready/` to `wip/`, create metadata, queue for agent work
3. **Execution** — Agent CLI spawns with full context (README, agent docs, WIP file)
4. **Monitoring** — Track PID, elapsed time, memory, WIP journal updates
5. **Completion** — Agent moves finished work to `done/`

#### Command Reference

**`list`** — List available AI agent backends and their status

Returns each configured agent with its label and availability status (OK or NOT FOUND):
```
Available agents:
  haiku: Claude Haiku 4.5 (fast, cheap) [OK] <-- selected
  sonnet: Claude Sonnet 4.6 (balanced, capable) [OK]
  opus: Claude Opus 4.6 (smartest) [NOT FOUND]
  gemini-2.5-pro: Gemini 2.5 Pro (smartest) [OK]
  ...
```

**`select <name>`** — Select active agent backend

Sets the default agent for subsequent `assign` commands. Validates that the agent is installed/available:
```irc
AI 1 agent select gemini-2.5-flash
# Returns: "Selected agent: gemini-2.5-flash"
```

**`assign <prompt_filename>`** — Queue a prompt for agent processing

Performs the full assignment workflow:

1. **Find prompt** — Locates the file in `ready/` or `wip/`
2. **Check capabilities** — Parses front-matter YAML tags (requires, platform, min_ram) and validates system meets requirements
3. **Move to WIP** — Relocates prompt from source to `workorders/wip/`
4. **Create metadata** — Writes JSON with timestamp, agent name, original path, platform info
5. **Queue for agent** — Copies workorder + metadata to `ops/agents/<name>/queue/in/`
6. **Generate orders.md** — Runs template script to create agent's task manifest

Errors include:
- Prompt not found in ready/wip
- System lacks required capabilities (Docker, git, specific tools, min RAM, platform mismatch)
- File I/O failures (with automatic rollback to ready/ if assignment fails mid-way)

Example:
```irc
AI 1 agent assign PROMPT_fix_bug.md
# Returns: "Queued 'PROMPT_fix_bug.md' for agent 'haiku'."
```

**`status`** — Show queue and running agent status

Comprehensive status report including:
- **Queue overview** — Count of tasks in queue/in, queue/work, queue/out per agent
- **Running tasks** — For each agent with active work: PID, start time, elapsed, memory (on Linux)
- **Current task** — WIP file name, progress (checkboxes), lines of output
- **Stale watchdog** — Warning if WIP file unchanged for > 5 minutes (agent may be stuck)

Example output:
```
Queue Status:
  haiku: queue/in=2, queue/work=1, queue/out=0
  gemini-2.5-pro: queue/in=0, queue/work=0, queue/out=3

Running Tasks:
  haiku (PID 5432): elapsed=12m 45s, mem=128.5 MB
    WIP: TASK_analyze_logs.md (5 done, 0 next, 3 pending | 78 lines total)
    (no stale warning)

No other running tasks.
```

**`stop`** — Gracefully stop the running agent

Sends SIGTERM to the agent PID, allowing clean shutdown (flushes WIP, closes files). Updates WIP file to mark incompletion if needed.

```irc
AI 1 agent stop
# Returns: "Agent stopped (PID 5432). Continue with 'agent assign' to restart."
```

**`kill`** — Force-terminate agent and roll back work

Sends SIGKILL (9) to agent PID, then moves WIP file back to `ready/` for reassignment. Use only if agent is unresponsive.

```irc
AI 1 agent kill
# Returns: "Agent killed (PID 5432). Workorder 'TASK_foo.md' moved back to ready/."
```

**`tail [N] [filename]`** — Stream last N lines of WIP journal

Displays agent's real-time progress by tailing the WIP file. If agent is running, checks temp repo first (where agent writes live updates).

- `tail` — Show last 20 lines of all WIP files
- `tail 50` — Show last 50 lines of all WIP files
- `tail 50 TASK_foo.md` — Show last 50 lines of specific task

Checks both main repo (`workorders/wip/`) and agent temp repos (`/tmp/csc/<agent>/repo/workorders/wip/`), preferring temp when agent is actively writing.

#### Agent Detection & Availability

The service detects available agents by checking:

**Remote agents** (Claude, Gemini, ChatGPT) — Look for `ops/agents/<name>/bin/run_agent.sh` or `.bat`

**Local agents** (Qwen, DeepSeek, Llama) — Require both:
- `cagent` CLI tool in PATH (from `cagent` pip package)
- `ops/agents/<name>/cagent.yaml` config file

#### Supported Agent Backends

| Name | Provider | Speed | Cost | Model |
|------|----------|-------|------|-------|
| `haiku` | Claude | ⚡⚡⚡ Fast | 💰 Cheap | Haiku 4.5 |
| `sonnet` | Claude | ⚡⚡ Medium | 💰💰 Medium | Sonnet 4.6 |
| `opus` | Claude | ⚡ Slow | 💰💰💰 Expensive | Opus 4.6 |
| `gemini-2.5-flash` | Google | ⚡⚡⚡ Fast | 💰 Cheap | Gemini 2.5 Flash |
| `gemini-2.5-pro` | Google | ⚡⚡ Medium | 💰💰 Medium | Gemini 2.5 Pro |
| `gemini-3-pro` | Google | ⚡ Slow | 💰💰💰 Expensive | Gemini 3 Pro |
| `chatgpt` | OpenAI | ⚡⚡ Medium | 💰💰💰 Expensive | GPT-4o |
| `qwen` | Local | ⚡⚡⚡ Fast | 🆓 Free | Qwen 3 |
| `deepseek` | Local | ⚡⚡ Medium | 🆓 Free | DeepSeek R1 |
| `codellama` | Local | ⚡⚡ Medium | 🆓 Free | Llama 3.1 |

#### Prompt Capability Tags

Prompts can declare requirements using YAML front-matter:

```markdown
---
requires: [docker, git, python3]
platform: [linux]
min_ram: 4GB
---

# My Task

Analyze the codebase...
```

**Supported tags:**
- `requires` — List of tools/agents that must be installed (docker, git, python3, etc.)
- `platform` — List of allowed platforms (linux, windows, macos, android, docker)
- `min_ram` — Minimum RAM required (e.g., 2GB, 512MB)

If system doesn't meet requirements, the prompt stays in `ready/` and assignment returns an error.

#### WIP Journaling & System Prompt Enforcement

Every agent is spawned with a **system prompt** injected at initialization (via `--append-system-prompt` for Claude, or prefix for others). This enforcement:

1. **Mandates journaling** — Agent MUST echo every step to WIP file BEFORE executing it
2. **Prevents destructive operations** — No manual git commits, no test runs, no file deletions
3. **Marks completion** — Agent writes "COMPLETE" when done and exits

Example system prompt:
```
MANDATORY: Journal every step to the WIP file BEFORE doing it. 
Run: echo '<what you are about to do>' >> workorders/wip/{wip_file} 
BEFORE each action. No checkboxes. No Edit tool. Just echo one line per step. 
...
When done, write COMPLETE to the WIP file and exit.
This is NON-NEGOTIABLE.
```

This ensures **full recoverability**: If the agent crashes or connection drops, the WIP file contains a complete audit trail of what was done and what remains.

#### Stale Watchdog

The `status` command monitors WIP file modification time. If the WIP file hasn't been updated for > 5 minutes (`STALE_THRESHOLD_SECS = 300`), a warning appears:

```
WARNING: WIP file unchanged for 5m — agent may be stuck
```

This alerts operators that the agent may be:
- Hung waiting for input
- Processing a very long task (in which case, can safely ignore)
- Crashed but process still running

Use `agent kill` to forcefully terminate if truly stuck.

#### Temp Repo Isolation

When an agent is assigned work, it runs in an **isolated temporary clone** of the repository:

- **Main repo**: `/opt/csc/irc/` (shared, not modified by agents)
- **Temp clone**: `/tmp/csc/<agent>/repo/` (per-agent, git-synced, agent can safely modify)

This prevents:
- Git merge conflicts between concurrent agents
- Accidental data corruption in shared repo
- Test failures due to stale code states

The agent syncs changes back to main via git push/pull wrapper.

#### Implementation Details

**Command syntax** (via IRC):
```irc
AI <token> agent <method> [args]
```

**State tracking** (in service data store):
- `selected_agent` — Currently selected backend name
- `current_pid` — PID of running agent (or None)
- `current_prompt` — WIP filename of running task
- `started_at` — Unix timestamp when agent started

**Directory structure:**
```
workorders/
  ready/       ← tasks awaiting assignment
  wip/         ← tasks in progress
  done/        ← completed tasks

ops/agents/<name>/
  bin/
    run_agent.sh    ← executable to spawn remote agent
  cagent.yaml       ← config for local agents
  queue/
    in/       ← queue worker picks from here
    work/     ← .pid files for running tasks
    out/      ← completed tasks
  context/
    *.md      ← per-agent docs/tips
```

#### Example Usage

**Workflow for a human operator or prompt:**

```bash
# 1. See available agents and current selection
AI 1 agent list

# 2. Pick a fast agent for quick task
AI 2 agent select gemini-2.5-flash

# 3. Assign a code review task
AI 3 agent assign PROMPT_review_server.md

# 4. Monitor progress
AI 4 agent status
AI 5 agent tail 50

# 5. If stuck, kill and reassign to a smarter model
AI 6 agent kill
AI 7 agent select opus
AI 8 agent assign PROMPT_review_server.md
```

#### Error Handling & Recovery

**Capabilities mismatch** — Prompt stays in `ready/`, awaits a capable system
```
Cannot assign 'task.md' — system lacks required capabilities:
  Docker not available; Tool 'python3' not installed
Workorder left in ready/ for a capable system to pick up.
```

**Agent not available** — Lists installed agents
```
Agent 'opus' is not installed (binary not found in PATH).
Known: haiku, sonnet, gemini-2.5-flash, ...
```

**Prompt not found**
```
Workorder not found in ready/ or wip/: nonexistent.md
```

**Assignment failure with rollback** — If an error occurs mid-assignment (e.g., metadata write fails), the WIP file is automatically moved back to `ready/` so no work is lost.

---

### `patch`
Fuzzy patch service for applying code changes to service modules. Supports loose anchor format (designed for LLMs) and standard unified diffs.

**Commands:**
- `apply <filename>`: Applies a patch file from the `patches/` directory.
  - Automatically creates a version backup of the target file before applying.
  - Supports "loose" format (anchored by context) and unified diffs.
- `revert <service> [version]`: Reverts a service file to a previous version (default: latest backup).
- `history <service>`: Shows version and patch history for a service file.

**Patch Formats:**
1.  **Loose Anchor**:
    ```
    <patch file=target_service>
    10 def target_method
    - def target_method(self):
    + def new_method(self):
    </patch>
    ```
2.  **Unified Diff**: Standard output from `diff -u` or `git diff`.

### `platform`
Platform detection and capability reporting service.

**Commands:**
- `info`: Shows full platform inventory (hardware, OS, virtualization, software, Docker, AI agents).
- `refresh`: Re-runs all detection and persists updated `platform.json`.
- `check <requires> [platform] [min_ram]`: Checks if the current system satisfies given requirements.

**Used by:** The `agent` service checks prompt capability tags against platform data before assigning work.

See [Platform Detection](platform.md) for full details.

### `prompts`
Work Queue Management Service. Allows creating, editing, and managing prompt files in the `workorders/` directory structure.

**Directories:**
- `ready/`: Tasks waiting to be executed.
- `wip/`: Tasks currently in progress.
- `done/`: Completed tasks.
- `hold/`: Tasks on hold.

**Commands:**
- `add <desc> : <content>`: Creates a new prompt file in `ready/`. Filename is timestamped and sanitized from description.
- `list [dir|all]`: Lists prompts in a specific directory (`ready`, `wip`, `done`, `hold`) or `all`.
- `read <filename>`: Reads and displays the content of a prompt file.
- `edit <filename> : <content>`: Overwrites a prompt file with new content.
- `move <filename> <dir>`: Moves a prompt file to a different directory.
- `delete <filename>`: Deletes a prompt file (creating a version backup first).
- `status`: Shows the count of prompts in each queue.

---

## 🔐 Security & Identity Services

### `cryptserv`
CryptServ is a key distribution bot, managing RSA key pairs for channels and DM pairs. It acts as a Certificate Authority, issuing keys and responding to client requests.

**Commands:**
- `request <target>`: Requests a certificate bundle (public/private keys) for a target (channel e.g., `#general` or DM pair e.g., `alice:bob`).
  - Generates new keys if they don't exist using `gencert.sh`.
  - Sends the private and public keys to the requestor via secure PRIVMSG (DH-AES encrypted tunnel).

**Dependencies:**
- Requires `gencert.sh` script in `scripts/` directory.
- Requires `wsl` (Windows Subsystem for Linux) if running on Windows, or `bash` on Linux.
- Requires `openssl` (invoked by `gencert.sh`).

### `nickserv`
User registration and identity management service. Stores credentials in `server/nickserv.db`.

**Commands:**
- `register <email> <password>`: Registers the current nick (placeholder, requires server integration).
- `ident <password>`: Identifies with the registered nick (placeholder, requires server integration).
- `unregister <nick>`: Unregisters a nick (Oper only).
- `info <nick>`: Shows registration information for a nick.

**Data Storage:**
- Uses a flat text file `server/nickserv.db`.
- Format: `nick:pass_hash:email:timestamp`.
- Passwords are hashed using MD5 (Note: legacy support).

---

## 🔒 Security & Safety
- **Root Confinement**: Services cannot read or write files outside the `C:\csc` directory.
- **Core Protection**: Critical files like `server.py` and `main.py` are protected from being overwritten via the service system.
- **Validation**: All uploaded code must pass a Python syntax check and structural validation (correct class name) before being activated.
- **Versioning**: The system automatically creates a backup in the `versions/` directory before any service is modified or deleted.

---
*The Services System turns the IRC server into a programmable operating environment for AI agents.*

[Prev: Server Guide](server.md) | [Next: AI Agents](ai_clients.md)
