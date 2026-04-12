# Current Architecture Analysis & Design Recommendations

## Goal

This document analyzes the current queue-based agent assignment and execution architecture of the CSC system and proposes a pure Python implementation strategy to enhance cross-platform compatibility, robustness, and maintainability.

## Current Architecture

The CSC system uses an IRC-like mechanism for command and control, where "workorders" (tasks for AI agents) are managed through a file-based queuing system.

### High-Level Message Flow (Current)

```mermaid
graph TD
    User[User Input/Prompt] -->|Creates workorder.md| ReadyDir[workorders/ready/]
    ReadyDir -->|`agent_service.assign()`| WIPDir[workorders/wip/]
    WIPDir -->|`agent_service.assign()`| AgentQueueIn[agents/<agent_name>/queue/in/orders.md]
    AgentQueueIn -->|`queue_worker_service.process_queue_in()`| AgentQueueWork[agents/<agent_name>/queue/work/orders.md (+.pid)]
    AgentQueueWork -->|Spawns `run_agent.sh`/.`bat`/.`py`| AI_Agent_CLI[External AI CLI (e.g., claude, npx gemini, ollama)]
    AI_Agent_CLI -->|`echo ... >> workorders/wip/`| WIPDir
    AI_Agent_CLI -->|stdout/stderr| AgentLog[logs/agent_<timestamp>.log]
    AgentQueueWork --PID dies/complete check-->|`queue_worker_service.process_queue_work()`| DoneOrReady[workorders/done/ or workorders/ready/]
    DoneOrReady -->|`queue_worker_service.git_commit_push()`| GitRepo[Git Repository]
```

### Detailed Breakdown

#### `agent_service.py`
This service is responsible for assigning workorders to specific AI agents.

*   **Agent Assignment Flow:**
    1.  Receives a `prompt_filename` (workorder).
    2.  Locates the workorder in `workorders/ready/` or `workorders/wip/`.
    3.  **Capability Check (`_check_prompt_capabilities`):** Parses YAML front-matter from the workorder (e.g., `requires`, `platform`, `min_ram`). It uses the `Platform` class to check if the current system meets these requirements, preventing unsuitable machines from running tasks. If requirements are not met, the workorder remains in `ready/`.
    4.  Determines the `selected_agent` (e.g., "haiku", "gemini-3-pro").
    5.  Ensures the target agent's directory structure (`agents/<agent_name>/queue/in/`, etc.) exists.
    6.  Moves the workorder from `ready/` to `wip/` (if it was in `ready/`).
    7.  Reads an `orders.md-template` (or a default) and the workorder's content.
    8.  **Placeholder Replacement:** Replaces `<wip_file_relative_pathspec>` in the template with the actual path to the WIP file.
    9.  Concatenates the template and workorder content to form a "ticket".
    10. Writes this ticket to `agents/<agent_name>/queue/in/orders.md`, which signals to `queue_worker_service` that a task is pending.
*   **WIP Journaling:** Injects a `WIP_SYSTEM_PROMPT` into the prompt content given to the agent. This prompt explicitly instructs the AI to `echo` its progress to the WIP file and to write "COMPLETE" as the last line upon finishing.
*   **Platform Path Handling:** The `_build_cmd` method selects between `run_agent.sh` or `run_agent.bat` based on the script's existence, indicating platform awareness.

#### `queue_worker_service.py`
This service acts as the orchestrator, managing the lifecycle of agent execution.

*   **Initialization:** Loads `platform.json` for environment context. Creates `wip/`, `done/`, `ready/`, `logs/` directories. Crucially, it creates `agents/<agent_name>/bin` directories and copies `run_agent.sh`, `run_agent.bat`, or `run_agent.py` from templates.
*   **`process_queue_in()` (Starting Agents):**
    1.  **Single-task constraint:** Ensures only one agent task runs at a time.
    2.  Scans `agents/*/queue/in/` for pending `orders.md` files (the tickets).
    3.  Moves the `orders.md` ticket from `queue/in/` to `queue/work/`.
    4.  **Spawns Agent (`spawn_agent`):** Invokes the agent via its `run_agent.sh` or `run_agent.bat` script.
    5.  Records the spawned process's PID in a `.pid` file within `queue/work/`.
    6.  Captures `stdout`/`stderr` of the `run_agent` script to a timestamped log file (`logs/`).
*   **`process_queue_work()` (Handling Completion):**
    1.  Monitors `.pid` files in `agents/*/queue/work/`.
    2.  If a process associated with a PID is no longer alive, it proceeds with post-execution steps.
    3.  **WIP Audit:** Appends the captured agent log (`logs/`) content to the corresponding WIP file for full audit.
    4.  **Completion Check (`check_wip_complete`):** Verifies if the WIP file ends with the string "COMPLETE".
    5.  Moves the processed `orders.md` ticket from `queue/work/` to `queue/out/`.
    6.  **WIP Disposition:** Moves the WIP file from `wip/` to `done/` if `COMPLETE` was found, or to `ready/` (adding a verification message) if not.
    7.  **Repository Sync:** If any workorder was completed or moved, it triggers `run_refresh_maps()` and `git_commit_push()` (add, commit, pull --rebase, push).
*   **`_get_path_for_shell`:** Converts Windows paths to Linux-style paths for `bash` execution when necessary, using data from `platform.json`.

#### `run_agent.sh`, `run_agent.bat`, `run_agent.py` Scripts
These scripts act as the direct interface to the AI CLI tools.

*   **`run_agent.sh` (Unix-like):**
    *   Bash script directly invoking `claude` CLI.
    *   Finds `claude` binary in PATH or common locations.
    *   Pipes the full prompt content (from `orders.md` ticket) to `claude`'s stdin.
    *   Redirects `stdout`/`stderr` to `tee`, sending output to both console and a log file.
*   **`run_agent.bat` (Windows):**
    *   Batch script that acts as a wrapper.
    *   Simply calls `python "%~dp0run_agent.py"` passing the workorder path.
    *   Delegates all core logic to `run_agent.py`.
*   **`run_agent.py` (Universal Launcher):**
    *   Called by `run_agent.bat` (Windows) and sometimes directly (Unix).
    *   **Agent Detection:** Dynamically determines agent type (e.g., "haiku", "gemini-3-pro") from its parent directory name.
    *   **Root Discovery:** Finds `CSC_ROOT` by searching for `CLAUDE.md`.
    *   **Routes Execution:** Calls specific Python functions (`run_claude`, `run_gemini`, `run_local`) based on agent type.
    *   **`run_claude`:** Uses `subprocess.run` to execute `claude` CLI.
    *   **`run_gemini`:** Uses `subprocess.run` to execute `npx @google/gemini-cli`. **Crucially, on Windows, it employs a complex `subprocess.Popen` workaround with `CREATE_NEW_CONSOLE` and manual output relaying due to `node-pty` console requirements.**
    *   **`run_local`:** Uses `subprocess.run` to execute `ollama` CLI.
    *   **Journaling:** None of these scripts *journal* themselves; they merely pass the workorder content (which contains the `WIP_SYSTEM_PROMPT`) to the AI CLI, relying on the AI to follow the journaling instructions.

## Identified Pain Points (5+)

The current architecture, heavily relying on shell scripts and external CLI tools, introduces several points of fragility and complexity:

1.  **Cross-Platform Scripting Inconsistencies:** The need for separate `.sh` and `.bat` scripts (or Python scripts with platform-specific workarounds like `run_agent.py` for Gemini on Windows) creates maintenance overhead, potential for subtle behavioral differences, and duplication of logic. This is evident in `queue_worker_service.spawn_agent` and `agent_service._build_cmd`.
2.  **Brittle Project Root Detection:** `run_agent.py` uses `CLAUDE.md` to find `CSC_ROOT`. This is highly susceptible to breakage if the file is renamed, moved, or absent, leading to incorrect working directories for agents.
3.  **Complex Path Conversions:** `queue_worker_service._get_path_for_shell` attempts to translate Windows paths to Linux-style paths for `bash` execution. This is a workaround for bridging different shell environments, is fragile, and relies on `platform.json` being perfectly accurate.
4.  **External CLI Tool Dependencies and Discoverability:** All agent execution (`claude`, `npx`, `ollama`) depends on external binaries being installed and correctly configured in the system's PATH. Missing or misconfigured tools lead to runtime failures, which are harder to diagnose in a `subprocess` context.
5.  **Implicit Journaling Reliance:** The system relies on the AI agent *itself* to read and follow the `WIP_SYSTEM_PROMPT` to journal its work. If the AI deviates or fails to `echo` correctly, the task might be incorrectly marked as incomplete or fail audit. The orchestrator has no direct control over the journaling process.
6.  **Windows Gemini Console Workaround:** The `run_gemini` function in `run_agent.py` includes a complex `subprocess.Popen` implementation with `CREATE_NEW_CONSOLE` and manual output relaying. This is an elaborate and fragile solution to address `node-pty` requirements on Windows, adding significant complexity.
7.  **Process Monitoring & Cleanup:** The `queue_worker_service` monitors PIDs from spawned shell processes. This requires platform-specific `is_process_alive` checks (e.g., `os.kill(pid, 0)` vs. `tasklist`). This adds complexity and can be error-prone if processes become detached or their PIDs are reused.

## Proposed Pure Python Solution

The core idea is to eliminate intermediary shell scripts for agent invocation, bringing direct control and execution within Python for improved cross-platform consistency and debuggability.

### Design Decisions

1.  **Centralized Agent Execution:** Introduce a new Python class, `AgentExecutor`, to encapsulate the logic for invoking different AI CLIs.
2.  **Synchronous Agent Execution:** The `queue_worker_service` will execute agents synchronously using `AgentExecutor`, simplifying process management (no more PID tracking).
3.  **Simplified Workorder Assignment:** `agent_service.assign()` will focus on initial validation and moving workorders to WIP, signaling readiness via a simple marker file.
4.  **Pure Python Path Handling:** Leverage Python's `pathlib` for all file operations, eliminating the need for shell-specific path conversions.
5.  **Direct Tool Invocation:** `AgentExecutor` will directly call `claude`, `npx`, `ollama` binaries (found via `shutil.which`), but handle their `subprocess` invocation consistently and robustly.

### New Architecture Diagram

```mermaid
graph TD
    User[User Input/Prompt] -->|Creates workorder.md| ReadyDir[workorders/ready/]
    ReadyDir -->|`agent_service.assign()`| WIPDir[workorders/wip/]
    WIPDir -->|`agent_service.assign()` (places marker)| AgentQueueIn[agents/<agent_name>/queue/in/<workorder_name>]
    AgentQueueIn -->|`queue_worker_service.process_queue_in()`| QueueWorkerService[QueueWorkerService]
    QueueWorkerService -->|Calls `AgentExecutor.execute()` with full prompt| AgentExecutor[AgentExecutor (new class)]
    AgentExecutor -->|Spawns `claude`/`npx gemini`/`ollama` via `subprocess`| AI_Agent_CLI[External AI CLI]
    AI_Agent_CLI -->|`echo ... >> workorders/wip/`| WIPDir
    AI_Agent_CLI -->|stdout/stderr (captured by AgentExecutor/QWS)| AgentLog[logs/agent_<timestamp>.log]
    AgentExecutor -->|Returns exit code| QueueWorkerService
    QueueWorkerService --Checks WIP for COMPLETE--> DoneOrReady[workorders/done/ or workorders/ready/]
    DoneOrReady -->|`queue_worker_service.git_commit_push()`| GitRepo[Git Repository]
```

### Proposed Components

#### 1. `AgentExecutor` Class (`packages/csc-service/csc_service/shared/agent_executor.py`)

*   **Purpose:** To abstract and standardize the process of invoking different AI CLI tools.
*   **Key Responsibilities:**
    *   Detects agent type and maps to correct CLI binary and model.
    *   Finds necessary CLI binaries (`claude`, `npx`, `ollama`) using `shutil.which`.
    *   Constructs CLI commands for each agent type.
    *   Manages environment variables (e.g., `PYTHONIOENCODING`).
    *   Handles `subprocess.run`/`subprocess.Popen` calls, including platform-specific workarounds (like Gemini on Windows).
    *   Captures and relays agent `stdout`/`stderr` to the `QueueWorkerService`'s log file.
*   **Benefits:**
    *   Centralizes complex `subprocess` logic.
    *   Improves cross-platform consistency.
    *   Easier to test and debug agent invocations.
    *   Eliminates `run_agent.sh`, `run_agent.bat`, `run_agent.py` templates.

#### 2. Enhanced `agent_service.assign()`

*   **Key Changes:**
    *   **Removed Ticket Generation:** No longer constructs a "ticket" by combining templates with the workorder content. This logic will move to `QueueWorkerService`.
    *   **Marker File:** After performing capability checks and moving the workorder to `wip/`, it will create a simple empty marker file (named after the workorder) in `agents/<agent_name>/queue/in/`. This marker file serves as a signal for the `QueueWorkerService`.
*   **Benefits:** Simplifies `agent_service.assign()`, separating concerns (assigning vs. executing).

#### 3. Refactored `QueueWorkerService`

*   **Key Changes:**
    *   **Synchronous Execution:** `process_queue_in()` will directly call `AgentExecutor.execute()`. This means agent tasks will execute sequentially *within* the `queue_worker_service` process, eliminating the need for PID tracking and `process_queue_work()` to monitor detached processes.
    *   **Prompt Assembly:** Responsible for building the `full_prompt_content` by combining `README.1shot`, agent context files, `WIP_SYSTEM_PROMPT`, and the actual workorder content.
    *   **No `run_agent` Scripts:** Removes all logic related to selecting, copying, or invoking `run_agent.sh`/`.bat` scripts.
    *   **No Path Conversions:** Eliminates `_get_path_for_shell` and related logic, relying on Python's native path handling and `shutil.which` for binary discovery.
    *   **Simplified Cleanup:** `process_queue_work()` will be removed or repurposed for general cleanup of any stale artifacts (e.g., old `.pid` files from previous runs).
    *   **Enhanced Logging:** `spawn_agent` will capture all output from `AgentExecutor` and its spawned CLI tools into a log file.
*   **Benefits:**
    *   Streamlined and robust agent execution flow.
    *   Removes all direct shell script dependencies for agent invocation.
    *   Easier to understand and maintain the core execution loop.

#### 4. Role of `platform.json`

*   **Capability-Based Routing:** Remains critical for `agent_service.assign()` to perform pre-execution capability checks (`requires`, `platform`, `min_ram`) against the current system's capabilities (as reported in `platform.json`). This ensures workorders are only assigned to agents running on suitable machines.
*   **Simplified Environment:** With `AgentExecutor` using `shutil.which` and Python's native path handling, the need for complex path conversions based on `platform.json` is drastically reduced. `platform.json` primarily serves an informational and routing role.

## Deliverables

- `analysis/CURRENT_ARCHITECTURE.md` (this file) with complete analysis and design.

## Acceptance Criteria

- Current architecture fully documented.
- 5+ pain points identified with locations.
- Pure Python solution designed.
- Ready to guide Q02-Q05 implementation.
