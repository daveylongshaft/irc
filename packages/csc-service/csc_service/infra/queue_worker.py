#!/usr/bin/env python3
"""
Queue Worker: Full lifecycle manager for AI agent prompt execution.

Runs as a polling service (--daemon) or one-shot via cron to manage the
complete lifecycle of agent tasks. Replaces the old agent-wrapper by
handling everything: git, prompt movement, agent spawning, and monitoring.

Lifecycle per task:
  1. git pull
  2. queue/in/ -> queue/work/  (+ workorders/ready/ -> workorders/wip/)
  3. Assemble prompt (README.1shot + agents/<name>/context/* + WIP)
  4. Spawn AI agent in background, note PID
  5. Exit (non-blocking)
  6. Next run: check PID - if alive, monitor WIP growth
  7. When agent exits: check WIP for COMPLETE
     - COMPLETE -> workorders/wip/ -> workorders/done/
     - No COMPLETE -> workorders/wip/ -> workorders/ready/
  8. queue/work/ -> queue/out/
  9. refresh-maps, git add/commit (with WIP summary in message)/push

Constraints:
  - Only ONE task runs at a time (if queue/work/ has a PID, skip inbox)
  - Stale detection: if WIP unchanged for several runs, log warning

Cross-platform: Windows (Docker service or --daemon), Linux (cron/systemd), macOS (launchd).

Usage:
    queue-worker                    # Run one cycle
    queue-worker --daemon           # Run continuously (check every 60s)
    queue-worker --setup-scheduler  # Print scheduler install instructions
"""

import os
import sys
import json
import re
import time
import shutil
import subprocess
from pathlib import Path
import signal
from datetime import datetime

from csc_service.shared.agent_executor import AgentExecutor
from csc_service.shared.api_key_manager import APIKeyManager
from csc_service.shared.service import Service

# --- Configuration ---
SCRIPT_DIR = Path(__file__).resolve().parent

# Declare global path variables (initialized by _initialize_paths)
CSC_ROOT = None
AGENTS_DIR = None
PROMPTS_BASE = None
READY_DIR = None
WIP_DIR = None
DONE_DIR = None
LOGS_DIR = None
AGENT_DATA_FILE = None  # kept for reference; writes go through _agent_svc
PENDING_FILE = None     # kept for reference; writes go through _qw_svc
AGENT_EXECUTOR = None   # Agent executor for spawning agents

# Service instances for Data/Log/Platform hierarchy (set by _initialize_paths)
_agent_svc: Service = None   # shared agent tracking (aligns with agent_service.py)
_qw_svc: Service = None      # queue-worker own state (pending list, config)

# Declare global API key manager and log file variables
API_KEY_MGR = None
QUEUE_LOG = None
STALE_FILE = None

# How many consecutive stale checks before warning / marking as failed
# At 60s poll interval, 10 checks = 10 minutes of no progress before declaring stale
STALE_THRESHOLD = 10

# Max total runtime for any agent (1 hour)
AGENT_MAX_TOTAL_RUNTIME_SECONDS = 3600

# Track spawned Popen objects by PID for reliable exit detection
ACTIVE_PROCS = {}

def _initialize_paths(work_dir_arg=None):
    global CSC_ROOT, AGENTS_DIR, PROMPTS_BASE, READY_DIR, WIP_DIR, DONE_DIR, LOGS_DIR, AGENT_DATA_FILE, API_KEY_MGR, QUEUE_LOG, STALE_FILE, PENDING_FILE, _agent_svc, _qw_svc, AGENT_EXECUTOR

    if work_dir_arg:
        CSC_ROOT = Path(work_dir_arg).resolve()
    else:
        try:
            from csc_service.shared.platform import Platform
            CSC_ROOT = Path(Platform.PROJECT_ROOT).resolve()
        except Exception:
            # Fallback: env var or .csc_root walk
            if os.environ.get("CSC_ROOT"):
                CSC_ROOT = Path(os.environ["CSC_ROOT"]).resolve()
            else:
                p = SCRIPT_DIR
                for _ in range(10):
                    if (p / ".csc_root").exists():
                        break
                    if p == p.parent:
                        break
                    p = p.parent
                CSC_ROOT = p

    # ops/agents/ is authoritative (ops is a submodule of csc)
    # Also check parent (when csc_root is the irc submodule, parent is the csc umbrella)
    _agents_candidate = CSC_ROOT / "ops" / "agents"
    if not _agents_candidate.exists():
        _agents_candidate = CSC_ROOT.parent / "ops" / "agents"
    AGENTS_DIR = _agents_candidate

    # ops/wo/ is the canonical workorder queue (ops submodule)
    # Fall back to wo/ or workorders/ for compat with older layouts
    def resolve_workorders_base_local():
        for candidate in [
            CSC_ROOT / "ops" / "wo",
            CSC_ROOT / "wo",
            CSC_ROOT / "workorders",
            CSC_ROOT / "prompts",
            CSC_ROOT.parent / "ops" / "wo",  # parent when csc_root is irc submodule
        ]:
            if candidate.exists():
                return candidate
        return CSC_ROOT / "ops" / "wo"  # will be created on first use

    PROMPTS_BASE = resolve_workorders_base_local()
    READY_DIR = PROMPTS_BASE / "ready"
    WIP_DIR = PROMPTS_BASE / "wip"
    DONE_DIR = PROMPTS_BASE / "done"
    LOGS_DIR = CSC_ROOT / "ops" / "logs"
    AGENT_DATA_FILE = CSC_ROOT / "etc" / "agent_data.json"  # reference only

    # Service instances for Data() hierarchy — no direct file I/O after this
    _agent_svc = Service(None)
    _agent_svc.name = "agent"
    _agent_svc.init_data()   # → agent_data.json in run_dir (aligns with agent_service)

    _qw_svc = Service(None)
    _qw_svc.name = "queue_worker"
    _qw_svc.init_data()      # → queue_worker_data.json in run_dir

    # Initialize API_KEY_MGR
    API_KEY_MGR = APIKeyManager()

    QUEUE_LOG = LOGS_DIR / "queue-worker.log"
    STALE_FILE = LOGS_DIR / "queue-wip-sizes.json"
    PENDING_FILE = LOGS_DIR / "queue-pending.json"

    AGENT_EXECUTOR = AgentExecutor(CSC_ROOT)

# _initialize_paths() # Initial call to set up paths on module load (removed)

IS_WINDOWS = os.name == 'nt'


# ======================================================================
# Agent temp repo helpers
# ======================================================================

def get_agent_temp_repo(agent_name):
    """Get the agent's temp repo path: CSC_ROOT/tmp/<agent>/repo.

    This is a clone of irc.git (code only) — NOT a clone of CSC_ROOT.
    Agents run with CWD=CSC_ROOT so they read/write WO journals directly.
    The temp repo is used only for code changes pushed to irc.git.
    """
    return CSC_ROOT / "tmp" / agent_name / "repo"


def _get_irc_remote():
    """Derive irc.git remote URL from csc.git origin (swap /csc.git -> /irc.git)."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=str(CSC_ROOT), timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip().replace("/csc.git", "/irc.git")
    except Exception:
        pass
    return "https://github.com/daveylongshaft/irc.git"


def ensure_agent_temp_repo(agent_name):
    """Ensure agent's temp repo exists and is a valid git clone of irc.git.

    Clones the IRC code repo (not csc.git/ops repo).
    Returns the Path to the temp repo, or None if creation fails.
    """
    repo = get_agent_temp_repo(agent_name)

    if not (repo / ".git").exists():
        irc_remote = _get_irc_remote()
        log(f"Cloning irc.git to {repo}")
        repo.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", irc_remote, str(repo)],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            log(f"ERROR: git clone of irc.git failed for {agent_name}: {result.stderr}", "ERROR")
        else:
            log(f"Cloned irc.git to {repo}")
    else:
        git_pull_in_repo(repo, label=f"{agent_name} irc repo")
    return repo


def create_agent_temp_repo(agent_name, wo_stem):
    """Create a unique temp repo for this agent+WO combination.

    Each workorder gets its own isolated clone so multiple agents can run
    concurrently without filesystem conflicts.

    Returns the Path to the newly cloned repo, or None if creation fails.
    """
    ts = int(time.time())
    # Sanitize wo_stem for filesystem use
    safe_stem = re.sub(r'[^\w-]', '_', wo_stem)[:40]
    # Use Platform for the clones base — never hardcode /opt
    from csc_service.shared.platform import Platform as _Plat
    _plat = _Plat()
    clones_base = (_plat.agent_work_base or CSC_ROOT / "tmp") / "clones"
    repo = clones_base / agent_name / f"{safe_stem}-{ts}" / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    irc_remote = _get_irc_remote()
    log(f"Cloning irc.git to {repo} (depth=1)")
    result = subprocess.run(
        ["git", "clone", "--depth=1", irc_remote, str(repo)],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        log(f"ERROR: git clone failed for {agent_name}: {result.stderr}", "ERROR")
        return None
    log(f"Cloned irc.git to {repo}")
    return repo


def git_pull_in_repo(repo_path, label=""):
    """Run git pull in the specified repo path.

    Returns True on success, False on failure.
    """
    desc = f" ({label})" if label else ""
    log(f"git pull in {repo_path}{desc}")

    # If a previous rebase was interrupted, clean up the state
    rebase_merge_dir = repo_path / ".git" / "rebase-merge"
    rebase_apply_dir = repo_path / ".git" / "rebase-apply"
    for rebase_dir in (rebase_merge_dir, rebase_apply_dir):
        if rebase_dir.exists():
            log(f"WARNING: Found {rebase_dir.name} in {repo_path}, aborting interrupted rebase.", "WARN")
            try:
                subprocess.run(
                    ["git", "rebase", "--abort"],
                    cwd=str(repo_path),
                    capture_output=True, text=True, timeout=15
                )
            except Exception:
                pass
            # If abort didn't clean it up, force remove
            if rebase_dir.exists():
                try:
                    shutil.rmtree(rebase_dir)
                except Exception as e:
                    log(f"ERROR: Failed to remove {rebase_dir.name} in {repo_path}: {e}", "ERROR")
                    return False

    # Ensure we're on a branch (not detached HEAD)
    try:
        head_result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=str(repo_path),
            capture_output=True, text=True, timeout=10
        )
        if head_result.returncode != 0:
            log(f"Detached HEAD in {repo_path}, checking out main", "WARN")
            subprocess.run(
                ["git", "checkout", "main"],
                cwd=str(repo_path),
                capture_output=True, text=True, timeout=15
            )
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["git", "pull", "--rebase", "--autostash"],
            cwd=str(repo_path),
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            log(f"git pull failed in {repo_path}: {result.stderr}", "WARN")
            return False
        return True
    except Exception as e:
        log(f"git pull failed in {repo_path}: {e}", "WARN")
        return False




def defer_git_sync() -> bool:
    """When enabled, skip per-workorder git sync and defer to batch orchestrator."""
    return os.environ.get("CSC_BATCH_DEFER_GIT_SYNC", "").strip() in {"1", "true", "yes"}
def git_commit_push_in_repo(repo_path, message, label=""):
    """Stage all, commit, push in the specified repo path.

    Returns: (success: bool, error_msg: str or None, repo_path: Path)
    """
    desc = f" ({label})" if label else ""
    try:
        subprocess.run(["git", "add", "-A"], cwd=str(repo_path),
                        capture_output=True, timeout=30)
    except Exception as e:
        log(f"git add failed in {repo_path}: {e}", "ERROR")
        return False, str(e), repo_path

    # Check if there's anything to commit
    result = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo_path),
                            capture_output=True, text=True)
    if not result.stdout.strip():
        log(f"Nothing to commit in {repo_path}{desc}")
        return True, None, repo_path

    log(f"git commit in {repo_path}{desc}: {message.splitlines()[0][:80]}")
    try:
        subprocess.run(["git", "commit", "-m", message], cwd=str(repo_path),
                        capture_output=True, timeout=30)
    except Exception as e:
        log(f"git commit failed in {repo_path}: {e}", "ERROR")
        return False, str(e), repo_path

    git_pull_in_repo(repo_path, desc)

    log(f"git push from {repo_path}{desc}")
    try:
        result = subprocess.run(["git", "push"], cwd=str(repo_path),
                        capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            error_msg = result.stderr
            log(f"git push failed from {repo_path}: {error_msg}", "WARN")
            return False, error_msg, repo_path
        else:
            log(f"git push succeeded from {repo_path}{desc}")
            return True, None, repo_path
    except Exception as e:
        error_msg = str(e)
        log(f"git push failed from {repo_path}: {error_msg}", "WARN")
        return False, error_msg, repo_path


def handle_push_success(agent_repo):
    """Delete agent temp repo after successful push.

    Args:
        agent_repo: Path to agent temp repo (the repo/ subdir inside the task dir)
    """
    task_dir = agent_repo.parent
    try:
        if task_dir.exists():
            import shutil
            shutil.rmtree(str(task_dir))
            log(f"Deleted clone dir after successful push: {task_dir.name}")
    except Exception as e:
        log(f"WARNING: Failed to delete clone dir {task_dir}: {e}", "WARN")


def handle_push_failure(agent_name, agent_repo, error_msg):
    """Create push-fail workorder when git push fails.

    Args:
        agent_name: Name of agent (haiku, opus, etc.)
        agent_repo: Path to agent temp repo with merge conflicts
        error_msg: Git error message
    """
    try:
        # Rename repo to repo-<timestamp>/
        ts = int(time.time())
        conflict_repo = agent_repo.parent / f"repo-{ts}"
        if agent_repo.exists():
            import shutil
            if conflict_repo.exists():
                shutil.rmtree(str(conflict_repo))
            shutil.move(str(agent_repo), str(conflict_repo))

        # Create push-fail workorder
        workorder_name = f"{ts}-push-fail-agent-{agent_name}-repo-{ts}.md"
        workorder_path = READY_DIR / workorder_name

        # Add priority marker so PM prioritizes this
        content = f"""# Push Failure - Merge Conflicts (PRIORITY: 1)

**Agent:** {agent_name}
**Conflict Repo:** {conflict_repo}
**Error:** {error_msg}

## Task

Resolve merge conflicts in the agent's temp repo and push changes to main branch.

## Steps

1. Navigate to conflict repo: {conflict_repo}
2. Check git status: `git status`
3. Resolve conflicts manually or with git merge tools
4. Stage resolved files: `git add <files>`
5. Commit merge: `git commit -m "Resolve merge conflicts"`
6. Push to main: `git push`
7. Verify push succeeded
8. Add COMPLETE as last line when done

---
PRIORITY: 1
CREATED: {time.strftime('%Y-%m-%d %H:%M:%S')}
"""

        workorder_path.write_text(content, encoding='utf-8')
        log(f"Created push-fail workorder: {workorder_name}")

        # Commit push-fail workorder
        subprocess.run(["git", "add", str(workorder_path)], cwd=str(CSC_ROOT),
                      capture_output=True, timeout=30)
        subprocess.run(["git", "commit", "-m", f"Push failure: {agent_name} - {ts}"],
                      cwd=str(CSC_ROOT), capture_output=True, timeout=30)
        subprocess.run(["git", "push"], cwd=str(CSC_ROOT),
                      capture_output=True, timeout=60)

    except Exception as e:
        log(f"ERROR: Failed to create push-fail workorder: {e}", "ERROR")


def agent_queue_dir(agent_name, dir_type):
    """Return path to an agent's queue directory (in, work, out).

    Args:
        agent_name: Name of agent (haiku, claude, etc.)
        dir_type: Type of directory ("in", "work", "out")

    Returns:
        Path object for agents/<agent_name>/queue/<dir_type>/
    """
    return AGENTS_DIR / agent_name / "queue" / dir_type

# Agent configs: name matches agents/<name>/ directory
# Includes cloud agents, local agents (cagent-based), and test agent
KNOWN_AGENTS = {
    # Cloud agents (use run_agent.py -> claude/gemini CLI)
    "claude", "claude-batch", "haiku", "sonnet", "opus",
    "gemini", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro",
    "gemini-2.5-pro-preview",
    "gemini-3-flash", "gemini-3-flash-preview", "gemini-3-pro", "gemini-3-pro-preview",
    "gemini-3.1-pro-preview", "gemini-3.1-flash-preview",
    "qwen", "deepseek", "codellama",
    "chatgpt",
    # Local agents (use cagent exec with cagent.yaml)
    "dmr_qwen_task_runner",
    "ollama-codellama", "ollama-deepseek", "ollama-qwen",
    # Test
    "test-agent",
}

# Local models that need Docker Model Runner endpoint
LOCAL_AGENTS = {"qwen", "deepseek", "codellama"}
DMR_ENDPOINT = "http://localhost:12434/engines/v1"

# agent_data.json: shared state file so `agent status` and `agent tail` work
# AGENT_DATA_FILE = CSC_ROOT / "agent_data.json" # Moved to _initialize_paths()


# ======================================================================
# agent_data.json helpers
# ======================================================================

def write_agent_data(agent_name, pid, prompt_filename, log_path):
    """Write agent tracking data through Data() hierarchy so `agent status` works."""
    if _agent_svc is None:
        log("write_agent_data: _agent_svc not initialized", "WARN")
        return
    _agent_svc.put_data("selected_agent", agent_name, flush=False)
    _agent_svc.put_data("current_pid", pid, flush=False)
    _agent_svc.put_data("current_prompt", prompt_filename, flush=False)
    _agent_svc.put_data("current_log", str(log_path), flush=False)
    _agent_svc.put_data("started_at", int(time.time()))


def clear_agent_data():
    """Clear agent tracking data through Data() hierarchy after agent finishes."""
    if _agent_svc is None:
        return
    _agent_svc.put_data("current_pid", None, flush=False)
    _agent_svc.put_data("current_prompt", None, flush=False)
    _agent_svc.put_data("current_log", None, flush=False)
    _agent_svc.put_data("started_at", None)


# ======================================================================
# Pending work list (FIFO by datestamp)
# ======================================================================

def load_pending_list():
    """Load the pending work list through Data() hierarchy. Returns [] if empty."""
    if _qw_svc is None:
        return []
    items = _qw_svc.get_data("pending_list")
    if isinstance(items, list):
        return items
    return []


def save_pending_list(items):
    """Save the pending work list through Data() hierarchy."""
    if _qw_svc is not None:
        _qw_svc.put_data("pending_list", items)


def scan_pending_work():
    """
    Scan all agents' queue/in/ directories for orders.md files.
    Extract workorder names and datestamps, sort by timestamp (FIFO).
    Save and return the ordered list.
    """
    items = []

    try:
        for agent_dir in sorted(AGENTS_DIR.iterdir()):
            if not agent_dir.is_dir():
                continue

            agent_name = agent_dir.name
            if agent_name not in KNOWN_AGENTS:
                continue

            in_dir = agent_queue_dir(agent_name, "in")
            if not in_dir.exists():
                continue

            orders_md_path = in_dir / "orders.md"
            if not orders_md_path.exists():
                continue

            # Extract workorder filename from orders.md
            try:
                content = orders_md_path.read_text(encoding='utf-8', errors='ignore')
                # Match both absolute paths (/opt/.../wip/PROMPT_foo.md)
                # and relative paths (ops/wo/wip/PROMPT_foo.md)
                match = re.search(r'(?:ops/wo/wip|wo/wip|workorders/wip|/wip)/([^\s\n]+\.md)', content)
                if not match:
                    continue

                workorder_filename = match.group(1)

                # Extract timestamp from filename prefix (e.g., "1772297624-haiku-cleanup...")
                ts_match = re.match(r'^(\d+)', workorder_filename)
                ts = int(ts_match.group(1)) if ts_match else 0

                items.append({
                    "agent": agent_name,
                    "workorder": workorder_filename,
                    "ts": ts
                })
            except Exception as e:
                log(f"Failed to read orders.md for {agent_name}: {e}", "WARN")
                continue
    except Exception as e:
        log(f"Failed to scan pending work: {e}", "ERROR")
        return []

    # Sort by timestamp ascending (FIFO: oldest first)
    items.sort(key=lambda x: x["ts"])

    # Save the list and log it
    save_pending_list(items)
    log(f"Scanned {len(items)} pending workorders from all agents")

    return items


# ======================================================================
# Logging
# ======================================================================

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [queue-worker] [{level}] {msg}"
    print(line, file=sys.stderr)
    try:
        if LOGS_DIR and QUEUE_LOG: # Only attempt file logging if paths are initialized
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            with open(QUEUE_LOG, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
    except Exception as e:
        print(f"ERROR: Failed to write to queue-worker log file: {e}", file=sys.stderr)
        pass # Continue without file logging if there's an error


def _runtime(msg):
    """Write to runtime.log for #runtime IRC feed."""
    if not CSC_ROOT:
        return
    try:
        ts = time.strftime("%H:%M:%S")
        log_dir = CSC_ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "runtime.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [Q] {msg}\n")
    except Exception:
        pass


# ======================================================================
# Environment
# ======================================================================

def load_env():
    """Load .env file into os.environ (don't override existing)."""
    env_file = CSC_ROOT / ".env"
    if not env_file.exists():
        return
    try:
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


# ======================================================================
# Git helpers
# ======================================================================

def git_pull():
    log("git pull")
    try:
        subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=str(CSC_ROOT),
                        capture_output=True, text=True, timeout=60)
    except Exception as e:
        log(f"git pull failed: {e}", "WARN")


def git_commit_push(message):
    """Stage all, commit with message, push."""
    try:
        subprocess.run(["git", "add", "-A"], cwd=str(CSC_ROOT),
                        capture_output=True, timeout=30)
    except Exception as e:
        log(f"git add failed: {e}", "ERROR")
        return

    # Check if there's anything to commit
    result = subprocess.run(["git", "status", "--porcelain"], cwd=str(CSC_ROOT),
                            capture_output=True, text=True)
    if not result.stdout.strip():
        log("Nothing to commit")
        return

    log(f"git commit: {message.splitlines()[0][:80]}")
    try:
        subprocess.run(["git", "commit", "-m", message], cwd=str(CSC_ROOT),
                        capture_output=True, timeout=30)
    except Exception as e:
        log(f"git commit failed: {e}", "ERROR")
        return

    log("git push")
    try:
        subprocess.run(["git", "push"], cwd=str(CSC_ROOT),
                        capture_output=True, timeout=60)
    except Exception as e:
        log(f"git push failed: {e}", "WARN")


def refresh_maps():
    """Run refresh-maps --quick before committing."""
    script = SCRIPT_DIR / "refresh-maps"
    if not script.exists():
        log("refresh-maps not found, skipping", "WARN")
        return
    log("Refreshing maps...")
    try:
        subprocess.run([sys.executable, str(script), "--quick"],
                        cwd=str(CSC_ROOT), timeout=120)
    except Exception as e:
        log(f"refresh-maps failed: {e}", "WARN")


# ======================================================================
# Process helpers
# ======================================================================

def is_pid_alive(pid):
    """Check if a process is still running using Popen.poll().

    This is the most reliable method - we check the actual Popen object
    we spawned instead of querying the OS externally (which can return
    false positives for hung/zombie processes).

    Returns True if still running, False if finished.
    """
    # Check if we have a Popen object for this PID
    if pid in ACTIVE_PROCS:
        proc = ACTIVE_PROCS[pid]
        # poll() returns None if still running, exit code if finished
        if proc.poll() is None:
            return True
        else:
            # Process finished - remove from active dict and return False
            del ACTIVE_PROCS[pid]
            return False

    # No Popen object - fall back to OS query (for backwards compatibility).
    # IMPORTANT: Without the Popen object, PID reuse on Windows can cause
    # false positives. We validate the process name to mitigate this.
    # Agent processes are spawned via cmd.exe (running .bat) or python.exe.
    AGENT_PROCESS_NAMES = {"cmd.exe", "python.exe", "python3.exe", "python",
                           "node.exe", "claude.exe", "claude", "gemini-cli",
                           "gemini-cli.exe", "conhost.exe"}
    if IS_WINDOWS:
        try:
            # tasklist is reliable in scheduled/non-interactive Windows sessions.
            # Parse CSV output to reduce locale/header formatting issues.
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if result.returncode == 0:
                out = result.stdout.strip()
                if out and "no tasks are running" not in out.lower() and "info:" not in out.lower():
                    # Validate process name to avoid PID reuse false positives
                    # CSV format: "Image Name","PID","Session Name","Session#","Mem Usage"
                    try:
                        import csv
                        import io
                        reader = csv.reader(io.StringIO(out))
                        for row in reader:
                            if row and row[0].strip('"').lower() in AGENT_PROCESS_NAMES:
                                return True
                        # PID exists but process name doesn't match — likely PID reuse
                        log(f"PID {pid} exists but process name '{row[0] if row else '?'}' doesn't match agent processes — treating as dead", "WARN")
                        return False
                    except Exception:
                        # CSV parsing failed, fall through to powershell
                        pass

            # Fallback for constrained tasklist environments.
            ps_result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; if ($p) {{ $p.ProcessName }}",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            proc_name = ps_result.stdout.strip().lower()
            if proc_name:
                # Check if process name matches expected agent processes
                matches = any(name.replace('.exe', '') in proc_name or proc_name in name
                              for name in AGENT_PROCESS_NAMES)
                if not matches:
                    log(f"PID {pid} exists but process '{proc_name}' doesn't match agent processes — treating as dead", "WARN")
                    return False
                return True
            return False
        except (OSError, ProcessLookupError): # For OS-level errors (e.g., PID not found)
            return False
        except subprocess.TimeoutExpired: # If PowerShell command times out
            log(f"Timeout checking PID {pid} on Windows", "WARN")
            return False # Assume not alive on timeout
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def is_complete_marker(content: str) -> bool:
    """Check if content ends with COMPLETE marker on its own line.

    The COMPLETE marker must be the last non-whitespace line in the file.
    Case-sensitive. Must be exactly 'COMPLETE', not 'complete' or 'COMPLETE!'.
    """
    lines = content.rstrip().split('\n')
    return len(lines) > 0 and lines[-1].strip() == "COMPLETE"


def mark_incomplete(wip_path) -> None:
    """Add INCOMPLETE marker to a workorder file if not already marked.

    Appends 'INCOMPLETE: Agent task did not finish properly (missing COMPLETE marker)'
    to the end of the file. Does nothing if already marked incomplete.
    """
    try:
        current_content = wip_path.read_text(encoding='utf-8', errors='ignore')
        if not current_content.rstrip().endswith("INCOMPLETE"):
            wip_path.write_text(
                current_content.rstrip() + "\n\nINCOMPLETE: Agent task did not finish properly (missing COMPLETE marker)\n",
                encoding='utf-8'
            )
    except Exception as e:
        log(f"WARNING: Could not add INCOMPLETE marker to {wip_path}: {e}")


def find_cagent():
    """Find the cagent binary."""
    found = shutil.which("cagent")
    if found:
        return found
    log("cagent not found in PATH", "ERROR")
    return None


# ======================================================================
# Agent spawning
# ======================================================================




# ======================================================================
# WIP helpers
# ======================================================================

def get_wip_summary(prompt_filename, max_lines=15):
    """Get last N lines of WIP file for commit message."""
    wip = WIP_DIR / prompt_filename
    if not wip.exists():
        return ""
    try:
        lines = wip.read_text(encoding='utf-8', errors='ignore').splitlines()
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        return "\n".join(tail)
    except Exception:
        return ""


def get_wip_size(prompt_filename):
    """Get WIP file size in bytes, or -1 if missing."""
    wip = WIP_DIR / prompt_filename
    try:
        return wip.stat().st_size if wip.exists() else -1
    except Exception:
        return -1


def get_agent_started_at():
    """Get the started_at timestamp from agent_data.json."""
    if not AGENT_DATA_FILE.exists():
        return None
    try:
        data = json.loads(AGENT_DATA_FILE.read_text(encoding='utf-8'))
        return data.get("started_at")
    except (json.JSONDecodeError, OSError):
        return None


def get_agent_current_log_path():
    """Get the path to the agent's current log file from agent_data.json."""
    if not AGENT_DATA_FILE.exists():
        return None
    try:
        data = json.loads(AGENT_DATA_FILE.read_text(encoding='utf-8'))
        log_path_str = data.get("current_log")
        return Path(log_path_str) if log_path_str else None
    except (json.JSONDecodeError, OSError):
        return None


# ======================================================================
# Stale detection
# ======================================================================

def load_stale_state():
    try:
        if STALE_FILE.exists():
            import json
            return json.loads(STALE_FILE.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def save_stale_state(state):
    try:
        import json
        STALE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STALE_FILE.write_text(json.dumps(state), encoding='utf-8')
    except Exception:
        pass


# ======================================================================
# Core lifecycle
# ======================================================================

def _inject_template_vars(orders_content, agent_name, clone_rel_path, wip_rel_path):
    """Replace template placeholders in orders.md content.

    Substitutes:
        <clone_rel_path>        -> e.g. tmp/clones/haiku/my-task-1234/repo
        <wip_file_rel_path>     -> e.g. ops/wo/wip/my-task.md
        <wip_file_abs_path>     -> absolute path to WIP file
        <agent_repo_rel_path>   -> same as <clone_rel_path> (legacy compat)
    """
    wip_abs = str(WIP_DIR / Path(wip_rel_path).name)
    replacements = {
        "<clone_rel_path>": clone_rel_path,
        "<wip_file_rel_path>": wip_rel_path,
        "<wip_file_abs_path>": wip_abs,
        "<agent_repo_rel_path>": clone_rel_path,  # legacy compat
    }
    for placeholder, value in replacements.items():
        orders_content = orders_content.replace(placeholder, value)
    return orders_content


def _build_agent_cmd(agent_name, orders_path, clone_path):
    """Build the command to spawn an agent.

    Checks for agent-specific bin/run_agent script first.
    Falls back to cagent exec with cagent.yaml.
    Falls back to claude CLI for Claude-family agents.

    Args:
        agent_name: Agent name (haiku, opus, gemini-2.5-pro, etc.)
        orders_path: Path to orders.md in queue/work/
        clone_path: Path to agent's temp repo clone

    Returns:
        (cmd_list, env_dict, cwd) or (None, None, None) on error
    """
    agents_dir = AGENTS_DIR
    agent_dir = agents_dir / agent_name

    env = os.environ.copy()
    # Unset nesting detection vars
    for var in ["CLAUDE_CODE_SESSION_ID", "CLAUDE_INVOCATION_ID", "CLAUDE_CODE_TASK_ID"]:
        env.pop(var, None)

    # Load .env
    env_file = CSC_ROOT / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in env:
                        env[k] = v
        except Exception:
            pass

    env["CSC_PROJECT_ROOT"] = str(CSC_ROOT)
    env["CSC_AGENT"] = agent_name
    if clone_path:
        env["CSC_AGENT_REPO"] = str(clone_path)

    cwd = str(CSC_ROOT)

    # Set agent name in env for run_agent.py detection
    env["CSC_AGENT_NAME"] = agent_name

    # 1. Check for agent-specific run_agent script in agents/<name>/bin/
    for script_name in ["run_agent.py", "run_agent.sh", "run_agent.bat", "run_agent"]:
        script = agent_dir / "bin" / script_name
        if script.exists():
            if script.suffix == ".py":
                cmd = [sys.executable, str(script), str(orders_path)]
            elif script.suffix == ".sh":
                cmd = ["bash", str(script), str(orders_path)]
            elif script.suffix == ".bat":
                # Use cmd.exe /c to run batch files hidden (without explicit command, subprocess spawns visible window)
                cmd = ["cmd.exe", "/c", str(script), str(orders_path)]
            else:
                cmd = ["bash", str(script), str(orders_path)]
            log(f"Using agent-specific script: {script}")
            return cmd, env, cwd

    # 2. Fallback: universal run_agent.py from agents/templates/
    template_runner = agents_dir / "templates" / "run_agent.py"
    if template_runner.exists():
        cmd = [sys.executable, str(template_runner), str(orders_path)]
        log(f"Using template runner: {template_runner}")
        return cmd, env, cwd

    log(f"ERROR: No execution method found for agent {agent_name} "
        f"(no bin/run_agent.* and no templates/run_agent.py)", "ERROR")
    return None, None, None


def process_finished_work(agent_name, prompt_filename, return_code, agent_log, clone_path):
    """Process a finished workorder.

    Returns:
        "done" if WO moved to done/, "ready" if moved back to ready/
    """
    log(f"Agent {agent_name} finished for {prompt_filename} with return code {return_code}")
    clear_agent_data()

    wip = WIP_DIR / prompt_filename

    is_complete = False
    if wip.exists():
        try:
            content = wip.read_text(encoding='utf-8', errors='ignore')
            is_complete = is_complete_marker(content)
        except Exception:
            pass

    # Append agent log to WIP
    if agent_log and agent_log.exists():
        try:
            log_content = agent_log.read_text(encoding='utf-8', errors='ignore')
            if log_content.strip():
                if wip.exists():
                    with open(wip, 'a', encoding='utf-8') as f:
                        f.write(f"\n\n--- Agent Log ---\n{log_content}")
                else:
                    wip.write_text(log_content, encoding='utf-8')
        except Exception as e:
            log(f"WARNING: Could not append agent log to WIP: {e}")

    if not is_complete and wip.exists():
        mark_incomplete(wip)

    # Move WO to done or back to ready
    if is_complete:
        log(f"COMPLETE: {prompt_filename} -> done/")
        _runtime(f"{prompt_filename} COMPLETE -> done/")
        DONE_DIR.mkdir(parents=True, exist_ok=True)
        dst = DONE_DIR / prompt_filename
        if wip.exists():
            shutil.move(str(wip), str(dst))
        result = "done"
    else:
        log(f"INCOMPLETE: {prompt_filename} -> ready/")
        _runtime(f"{prompt_filename} INCOMPLETE -> ready/. reassigning")
        dst = READY_DIR / prompt_filename
        if wip.exists():
            shutil.move(str(wip), str(dst))
        result = "ready"

    # Move orders.md from queue/work/ to queue/out/
    out_dir = agent_queue_dir(agent_name, "out")
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = agent_queue_dir(agent_name, "work")
    work_orders = work_dir / "orders.md"
    if work_orders.exists():
        try:
            shutil.move(str(work_orders), str(out_dir / "orders.md"))
            log(f"Moved orders.md from queue/work/ to queue/out/")
        except Exception as e:
            log(f"WARNING: Could not move orders.md to out/: {e}", "WARN")

    if agent_log and agent_log.exists():
        try:
            shutil.copy2(str(agent_log), str(out_dir / agent_log.name))
            log(f"Copied agent log to queue/out/{agent_log.name}")
        except Exception as e:
            log(f"WARNING: Could not copy agent log: {e}", "WARN")

    # Handle clone repo: commit/push if complete, archive either way
    if clone_path and Path(clone_path).exists():
        if is_complete and not defer_git_sync():
            success, error, _ = git_commit_push_in_repo(
                Path(clone_path),
                f"feat: {prompt_filename} - agent {agent_name}",
                label=f"{agent_name} clone"
            )
            if success:
                handle_push_success(Path(clone_path))
            else:
                handle_push_failure(agent_name, Path(clone_path), error or "unknown")
        else:
            # Delete the clone — task goes back to ready, no need to keep it
            try:
                task_dir = Path(clone_path).parent
                shutil.rmtree(str(task_dir))
                log(f"Deleted clone dir (incomplete/deferred): {task_dir.name}")
            except Exception as e:
                log(f"WARNING: Could not delete clone dir: {e}", "WARN")

    # Refresh maps and commit/push main repo
    refresh_maps()
    summary = get_wip_summary(prompt_filename)
    commit_msg = (
        f"feat: Complete prompt '{prompt_filename}'\n\n"
        f"Agent: {agent_name}\n\n"
        f"Work log tail:\n{summary}"
    )
    if not defer_git_sync():
        git_commit_push(commit_msg)

    return result


def process_inbox():
    """Process one workorder from the pending work list (FIFO).

    Lifecycle:
        1. Pop next item from pending list
        2. Move orders.md: queue/in/ -> queue/work/
        3. Clone temp repo for agent
        4. Inject clone path into orders.md (replace template vars)
        5. Spawn agent with orders.md, save PID
        6. Wait for agent to finish
        7. Process result (done/ready)

    Returns:
        "done" if WO completed, "ready" if WO needs retry, None if no work.
    """
    # Load pending work list or rescan if empty
    pending = load_pending_list()
    if not pending:
        pending = scan_pending_work()
        if not pending:
            return None  # Nothing queued anywhere

    item = pending.pop(0)
    save_pending_list(pending)

    agent_name = item["agent"]
    workorder_filename = item["workorder"]
    workorder_path = WIP_DIR / workorder_filename

    log(f"Processing workorder: {workorder_filename} for agent {agent_name}")
    _runtime(f"found {workorder_filename} for {agent_name}. running")

    if not workorder_path.exists():
        log(f"Workorder file not found: {workorder_path}", "ERROR")
        return None

    # Step 1: Move orders.md from queue/in/ to queue/work/
    in_dir = agent_queue_dir(agent_name, "in")
    work_dir_q = agent_queue_dir(agent_name, "work")
    work_dir_q.mkdir(parents=True, exist_ok=True)

    orders_in = in_dir / "orders.md"
    orders_work = work_dir_q / "orders.md"

    if orders_in.exists():
        shutil.move(str(orders_in), str(orders_work))
        log(f"Moved orders.md: queue/in/ -> queue/work/")
    elif orders_work.exists():
        log(f"orders.md already in queue/work/ (resuming)")
    else:
        log(f"ERROR: orders.md not found in queue/in/ or queue/work/", "ERROR")
        return None

    # Step 2: Clone temp repo
    wo_stem = Path(workorder_filename).stem
    clone_path = create_agent_temp_repo(agent_name, wo_stem)
    clone_rel_path = ""
    if clone_path:
        # Compute relative path from CSC_ROOT (forward slashes for agent compatibility)
        try:
            clone_rel_path = str(clone_path.relative_to(CSC_ROOT)).replace("\\", "/")
        except ValueError:
            clone_rel_path = str(clone_path).replace("\\", "/")
        log(f"Clone path (relative): {clone_rel_path}")
    else:
        log(f"WARNING: Could not create temp repo, agent will work without clone", "WARN")

    # Step 3: Inject template vars into orders.md
    wip_rel_path = f"ops/wo/wip/{workorder_filename}"
    try:
        orders_content = orders_work.read_text(encoding='utf-8')
        orders_content = _inject_template_vars(orders_content, agent_name, clone_rel_path, wip_rel_path)
        orders_work.write_text(orders_content, encoding='utf-8')
        log(f"Injected template vars into orders.md")
    except Exception as e:
        log(f"ERROR: Failed to inject template vars: {e}", "ERROR")

    # Step 4: Build command and spawn agent
    cmd, env, cwd = _build_agent_cmd(agent_name, orders_work, clone_path)
    if cmd is None:
        log(f"ERROR: Cannot build command for agent {agent_name}", "ERROR")
        return None

    # Log file for agent stdout/stderr
    ts = int(time.time())
    agent_log = LOGS_DIR / f"agent_{ts}_{Path(workorder_filename).stem}.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log(f"Spawning agent {agent_name} (cwd={cwd})")

    try:
        with open(agent_log, 'w', encoding='utf-8') as log_f:
            if IS_WINDOWS:
                proc = subprocess.Popen(
                    cmd,
                    cwd=cwd,
                    env=env,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                proc = subprocess.Popen(
                    cmd,
                    cwd=cwd,
                    env=env,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True
                )

            pid = proc.pid
            ACTIVE_PROCS[pid] = proc
            write_agent_data(agent_name, pid, workorder_filename, agent_log)
            log(f"Agent spawned: PID={pid}")
            _runtime(f"spawned {agent_name} PID={pid}")

            # Wait for agent to finish (blocking)
            return_code = proc.wait()
            log(f"Agent exited: PID={pid}, return_code={return_code}")
            _runtime(f"agent {agent_name} exited rc={return_code}")

    except Exception as e:
        log(f"ERROR: Failed to spawn agent: {e}", "ERROR")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return_code = 1

    # Step 5: Process the result
    result = process_finished_work(agent_name, workorder_filename, return_code, agent_log, clone_path)
    return result


def _cycle_pm():
    """Trigger a PM cycle to process completed workorders."""
    try:
        from csc_service.infra import pm
        log("Cycling PM...")
        pm.run_cycle()
        log("PM cycle complete")
    except Exception as e:
        log(f"WARNING: PM cycle failed: {e}", "WARN")


# ======================================================================
# Main cycle
# ======================================================================

def run_cycle(work_dir_arg=None):
    """Run one complete queue-worker cycle (event-driven).

    After processing a workorder:
        - If WO moved to done/ -> cycle PM, then self-cycle (check for more work)
        - If WO moved to ready/ -> self-cycle immediately (retry or pick up next)
        - If no work found -> return (caller decides whether to poll)

    Returns:
        True if work was processed, False if idle.
    """
    _initialize_paths(work_dir_arg)

    log("=" * 50)
    log("Cycle start")

    # Pull latest changes
    if not defer_git_sync():
        git_pull()

    # Process inbox
    try:
        result = process_inbox()
    except Exception as e:
        log(f"ERROR: process_inbox() crashed: {e}", "ERROR")
        import traceback
        log(traceback.format_exc(), "ERROR")
        log("Cycle end (error)")
        return False

    if result is None:
        log("Cycle end (idle)")
        return False

    if result == "done":
        # WO completed -> cycle PM for notification, then check for more work
        _cycle_pm()
        log("Cycle end (done -> cycling PM and self)")
        return True

    if result == "ready":
        # WO incomplete -> back in ready, check for more work immediately
        log("Cycle end (ready -> self-cycling)")
        return True

    log("Cycle end")
    return True


def main():
    load_env()

    work_dir = None
    if "--dir" in sys.argv:
        try:
            dir_idx = sys.argv.index("--dir")
            work_dir = sys.argv[dir_idx + 1]
            sys.argv.pop(dir_idx) # Remove --dir
            sys.argv.pop(dir_idx) # Remove path
        except (IndexError, ValueError):
            log("Error: --dir requires a path.", "ERROR")
            print(__doc__)
            sys.exit(1)


    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--daemon":
            log("Daemon mode - event-driven with smart backpressure (Ctrl+C to stop)")
            try:
                idle_cycles = 0  # Track consecutive idle cycles
                while True:
                    had_work = run_cycle(work_dir_arg=work_dir)

                    if had_work:
                        # Work was done -> reset idle counter and cycle again immediately
                        idle_cycles = 0
                        # Tight loop continues
                    else:
                        # No work found
                        idle_cycles += 1
                        if idle_cycles >= 3:
                            # 3+ idle cycles -> fall back to 60s polling
                            log(f"Idle for {idle_cycles} cycles, polling in 60s...")
                            time.sleep(60)
                            idle_cycles = 0
                        # else: keep cycling fast for a few attempts
            except KeyboardInterrupt:
                log("Stopped")
        elif arg == "--setup-scheduler":
            if IS_WINDOWS:
                print(f"Use --daemon mode (or Docker service):")
                print(f"  queue-worker --daemon")
                print(f"Do NOT use Task Scheduler (causes popup windows).")
            else:
                print(f"Add to crontab:")
                print(f"  */2 * * * * {SCRIPT_DIR}/queue-worker "
                      f">> {QUEUE_LOG} 2>&1")
                print(f"Or use systemd / --daemon mode.")
        else:
            print(__doc__)
    else:
        run_cycle(work_dir_arg=work_dir)


if __name__ == "__main__":
    main()
