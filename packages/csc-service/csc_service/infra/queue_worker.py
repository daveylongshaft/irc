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
    global CSC_ROOT, AGENTS_DIR, PROMPTS_BASE, READY_DIR, WIP_DIR, DONE_DIR, LOGS_DIR, AGENT_DATA_FILE, API_KEY_MGR, QUEUE_LOG, STALE_FILE, PENDING_FILE, _agent_svc, _qw_svc

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
    repo = Path("/opt/clones") / agent_name / f"{safe_stem}-{ts}" / "repo"
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
    """Move agent temp repo to .trash after successful push.

    Args:
        agent_repo: Path to agent temp repo
    """
    trash_path = agent_repo.parent / ".trash"
    try:
        trash_path.mkdir(parents=True, exist_ok=True)
        if agent_repo.exists():
            import shutil
            dest = trash_path / agent_repo.name
            if dest.exists():
                shutil.rmtree(str(dest))
            shutil.move(str(agent_repo), str(dest))
            log(f"Moved successful agent repo to trash: {agent_repo.name}")
    except Exception as e:
        log(f"WARNING: Failed to trash successful repo {agent_repo}: {e}", "WARN")


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
# Prompt assembly
# ======================================================================

def _extract_role(wip_path):
    """Read role from workorder YAML front-matter. Default: 'worker'."""
    try:
        text = Path(wip_path).read_text(encoding='utf-8', errors='replace')
        if text.startswith('---'):
            end = text.find('---', 3)
            if end > 0:
                for line in text[3:end].splitlines():
                    if line.strip().startswith('role:'):
                        return line.split(':', 1)[1].strip()
    except Exception:
        pass
    return 'worker'


def build_full_prompt(agent_name, prompt_filename):
    """Assemble: role context + agent context + WIP content."""
    parts = []

    # 1. Role context from ops/roles/<role>/
    wip_path = WIP_DIR / prompt_filename
    role = _extract_role(wip_path)
    role_dir = CSC_ROOT / "ops" / "roles" / role
    if not role_dir.exists():
        role_dir = CSC_ROOT / "ops" / "roles" / "worker"  # fallback
    if role_dir.exists():
        readme = role_dir / "README.md"
        if readme.exists():
            parts.append(readme.read_text(encoding='utf-8'))
        for f in sorted(role_dir.glob("*.md")):
            if f.name != "README.md":
                parts.append(f"=== {f.name} ===\n{f.read_text(encoding='utf-8')}")
    else:
        # Legacy fallback: docs/README.1shot
        legacy = CSC_ROOT / "docs" / "README.1shot"
        if legacy.exists():
            parts.append(legacy.read_text(encoding='utf-8'))

    # 2. Agent-specific context files (overrides/additions)
    ctx_dir = AGENTS_DIR / agent_name / "context"
    if ctx_dir.exists():
        for f in sorted(ctx_dir.glob("*.md")):
            parts.append(f"=== {f.name} ===\n{f.read_text(encoding='utf-8')}")

    # 3. System rule (journal to WIP — use absolute path since agent runs in irc.git clone)
    wip_abs = str(WIP_DIR / prompt_filename)
    sys_rule = (
        f"SYSTEM RULE: Journal every step to {wip_abs} "
        f"BEFORE doing it. Use: echo '<step>' >> {wip_abs}. "
        f"Do NOT touch git. Do NOT move files. Do NOT run tests. "
        f"When done, echo 'COMPLETE' >> {wip_abs} and exit."
    )
    parts.append(sys_rule)

    # 4. WIP file content (the actual task)
    if wip_path.exists():
        parts.append(f"=== TASK: {prompt_filename} ===\n{wip_path.read_text(encoding='utf-8', errors='replace')}")

    return "\n\n".join(parts).replace('\0', '')


# ======================================================================
# Agent spawning
# ======================================================================

def spawn_agent(agent_name, prompt_filename, agent_repo=None):
    """Spawn AI agent in agent's temp repo. Returns (PID, log_path) or (None, None).

    Args:
        agent_name: Name of the agent (e.g., "haiku")
        prompt_filename: The workorder filename
        agent_repo: Path to agent's temp repo (if None, falls back to CSC_ROOT)
    """
    if agent_name not in KNOWN_AGENTS:
        log(f"Unknown agent: {agent_name}", "ERROR")
        return None, None

    # Find the run_agent script: agent-specific first, then template fallback
    agent_dir = AGENTS_DIR / agent_name
    if IS_WINDOWS:
        run_agent_script = agent_dir / "bin" / "run_agent.bat"
        if not run_agent_script.exists():
            # Fallback to template
            run_agent_script = AGENTS_DIR / "templates" / "run_agent.bat"
    else:
        run_agent_script = agent_dir / "bin" / "run_agent.sh"
        if not run_agent_script.exists():
            run_agent_script = AGENTS_DIR / "templates" / "run_agent.sh"

    if not run_agent_script.exists():
        log(f"run_agent script not found for {agent_name} (checked agent dir and templates)", "ERROR")
        return None, None

    # Agent runs from /opt — parent of both /opt/clones (temp repos) and /opt/csc (WO files).
    # Gemini's sandbox will cover both locations. Claude reads WO at abs path directly.
    spawn_cwd = "/opt"

    work_orders_relative = str(Path("ops") / "agents" / agent_name / "queue" / "work" / "orders.md")

    # Use ABSOLUTE path to run_agent script to avoid path resolution issues
    # The script may be in templates/, and relative paths don't resolve correctly when
    # cwd is set to a different directory (the temp repo)
    cmd = [str(run_agent_script.absolute()), work_orders_relative]

    # Log file for agent stdout/stderr
    ts = int(time.time())
    agent_log = LOGS_DIR / f"agent_{ts}_{Path(prompt_filename).stem}.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Diagnostic logging for spawn debugging
    orders_abs = Path(spawn_cwd) / work_orders_relative
    log(f"Spawn: agent={agent_name}, script={run_agent_script.absolute()}")
    log(f"  cwd={spawn_cwd}")
    log(f"  orders_relative={work_orders_relative}")
    log(f"  orders_exists={orders_abs.exists()}")
    if agent_repo:
        log(f"  agent_repo={agent_repo}, is_csc_root={agent_repo.resolve() == CSC_ROOT.resolve()}")

    try:
        log_fh = open(agent_log, 'w', encoding='utf-8')
        child_env = os.environ.copy()
        child_env["CSC_AGENT_NAME"] = agent_name
        child_env["CSC_ROOT"] = str(CSC_ROOT)  # pass correct CSC_ROOT to run_agent.sh
        child_env["CSC_AGENTS_DIR"] = str(AGENTS_DIR)
        child_env["CSC_WIP_DIR"] = str(WIP_DIR)
        if agent_repo:
            child_env["CSC_AGENT_REPO"] = str(agent_repo)

        if IS_WINDOWS:
            proc = subprocess.Popen(
                cmd, cwd=spawn_cwd,
                stdin=None, stdout=log_fh, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=child_env
            )
        else:
            proc = subprocess.Popen(
                cmd, cwd=spawn_cwd,
                stdin=None, stdout=log_fh, stderr=subprocess.STDOUT,
                start_new_session=True,
                env=child_env
            )

        log(f"Agent PID: {proc.pid}, log: {agent_log.name}")

        # Store Popen object for reliable exit detection
        ACTIVE_PROCS[proc.pid] = proc

        return proc.pid, agent_log

    except Exception as e:
        log(f"Failed to spawn agent: {e}", "ERROR")
        return None, None


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

def process_work():
    """Check queue/work/ for running or finished tasks.

    Returns True if a task is currently in-progress (don't pick up new work).
    """
    has_active_work = False
    stale_state = load_stale_state()

    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue

        agent_name = agent_dir.name
        if agent_name not in KNOWN_AGENTS:
            continue

        work_dir = agent_queue_dir(agent_name, "work")
        if not work_dir.exists():
            continue

        for pid_file in sorted(work_dir.glob("*.pid")):
            prompt_filename = pid_file.name[:-4]  # strip .pid

            try:
                pid = int(pid_file.read_text(encoding='utf-8').strip())
            except Exception:
                log(f"Bad PID file: {pid_file}, removing", "WARN")
                pid_file.unlink(missing_ok=True)
                continue

            if is_pid_alive(pid):
                # ---- STILL RUNNING ----
                has_active_work = True
                wip_size = get_wip_size(prompt_filename)
                log(f"Agent {agent_name} PID {pid} running | WIP size: {wip_size}b")

                # Check total runtime
                started_at = get_agent_started_at()
                elapsed_time = 0
                if started_at:
                    elapsed_time = time.time() - started_at
                
                # Assume agent is terminated by default
                agent_terminated = False 

                if elapsed_time > AGENT_MAX_TOTAL_RUNTIME_SECONDS:
                    log(f"ERROR: Agent {agent_name} PID {pid} exceeded max total runtime ({AGENT_MAX_TOTAL_RUNTIME_SECONDS}s). Terminating process.", "ERROR")
                    try:
                        if IS_WINDOWS:
                            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, text=True, timeout=10)
                        else:
                            os.kill(pid, signal.SIGTERM)
                        log(f"Successfully terminated PID {pid}")
                        agent_terminated = True
                    except Exception as e:
                        log(f"ERROR: Failed to terminate PID {pid}: {e}", "ERROR")
                
                if not agent_terminated:
                    # Stale detection (only if not terminated by max runtime)
                    key = f"{agent_name}/{prompt_filename}"
                    prev = stale_state.get(key, {})
                    stale_count = prev.get("stale_count", 0)

                    # Get current agent log file size
                    current_agent_log_path = get_agent_current_log_path()
                    current_agent_log_size = current_agent_log_path.stat().st_size if current_agent_log_path and current_agent_log_path.exists() else -1

                    prev_wip_size = prev.get("wip_size", -1)
                    prev_log_size = prev.get("log_size", -1)

                    # Check for growth in either WIP or agent log
                    wip_grown = (wip_size > prev_wip_size)
                    log_grown = (current_agent_log_size > prev_log_size)
                    
                    if not (wip_grown or log_grown):
                        stale_count += 1
                        if stale_count >= STALE_THRESHOLD:
                            log(f"STALE WARNING: WIP and agent log unchanged for {stale_count} checks", "WARN")
                            # If agent is stale, we also treat it as a finished (failed) task
                            # and let the PM handle escalation.
                            log(f"Agent {agent_name} PID {pid} considered stalled, moving workorder to ready/ for PM escalation.")
                            # Set agent_terminated to True so it falls through to the "AGENT FINISHED" logic
                            agent_terminated = True
                    else:
                        stale_count = 0 # Reset stale count if there's any growth

                    stale_state[key] = {
                        "wip_size": wip_size,
                        "log_size": current_agent_log_size,
                        "stale_count": stale_count
                    }
                    # If not terminated and not stale, continue to next iteration
                    if not agent_terminated:
                        continue
            
            # ---- AGENT FINISHED (or terminated due to timeout/staleness) ----
            # If agent_terminated is True, we forced it to stop, so it's effectively "finished" from our perspective.
            # If is_pid_alive(pid) was False, it means the process ended naturally.
            # The code below handles both scenarios.
            log(f"Agent {agent_name} PID {pid} finished for {prompt_filename}")
            clear_agent_data()

            # Track git success - if git ops fail and aren't deferred, don't move WIP
            git_sync_success = True

            # Commit + push from agent's TEMP REPO (where agent was working).
            # Read the per-WO repo path written at spawn time; fall back to legacy path.
            repo_file = work_dir / f"{prompt_filename}.repo"
            if repo_file.exists():
                try:
                    agent_repo = Path(repo_file.read_text(encoding='utf-8').strip())
                    repo_file.unlink(missing_ok=True)
                except Exception:
                    agent_repo = get_agent_temp_repo(agent_name)
            else:
                agent_repo = get_agent_temp_repo(agent_name)
            if (agent_repo / ".git").exists():
                agent_summary = get_wip_summary(prompt_filename)
                commit_msg_agent = (
                    f"chore: Agent work on '{prompt_filename}'\n\n"
                    f"Agent: {agent_name}\n\n"
                    f"Work log tail:\n{agent_summary}"
                )
                if defer_git_sync():
                    log("Deferring temp repo commit/push until batch completion")
                else:
                    push_success, push_error, _ = git_commit_push_in_repo(agent_repo, commit_msg_agent, label=f"agent {agent_name} temp repo")
                    git_sync_success = push_success  # Track failure
                    if push_success:
                        # Push succeeded - move repo to .trash
                        handle_push_success(agent_repo)
                    else:
                        # Push failed - create push-fail workorder (PRIORITY: 1)
                        log(f"ERROR: Git push failed for {prompt_filename} - WIP will NOT be moved", "ERROR")
                        handle_push_failure(agent_name, agent_repo, push_error)
            else:
                log(f"WARNING: Agent temp repo not found at {agent_repo}, skipping commit+push", "WARN")

            # Check agent log for credit exhaustion errors
            agent_log_file = None
            for log_file in LOGS_DIR.glob(f"agent_*_{Path(prompt_filename).stem}.log"):
                agent_log_file = log_file
                break

            if agent_log_file and agent_log_file.exists():
                try:
                    log_content = agent_log_file.read_text(encoding='utf-8', errors='ignore')
                    if API_KEY_MGR.is_credit_exhaustion_error(log_content):
                        log("Credit exhaustion detected - rotating API key", "WARN")
                        new_key = API_KEY_MGR.rotate_key()
                        if new_key:
                            log(f"Rotated to key #{API_KEY_MGR.current_index + 1}/{API_KEY_MGR.get_key_count()}")
                            # Re-queue the prompt for retry with new key
                            log(f"Re-queuing {prompt_filename} with new API key")
                            queue_in = agent_dir / "queue" / "in"
                            queue_in.mkdir(parents=True, exist_ok=True)
                            retry_ticket = queue_in / prompt_filename
                            retry_ticket.write_text(
                                f"retry_after_credit_exhaustion: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"agent: {agent_name}\n"
                                f"previous_key_index: {(API_KEY_MGR.current_index - 1) % API_KEY_MGR.get_key_count()}\n",
                                encoding='utf-8'
                            )
                            # Clean up work dir and skip normal completion flow
                            work_file = work_dir / prompt_filename
                            if work_file.exists():
                                work_file.unlink()
                            pid_file.unlink(missing_ok=True)
                            continue  # Skip to next iteration, don't do normal completion
                except Exception as e:
                    log(f"Failed to check for credit exhaustion: {e}", "WARN")

            wip = WIP_DIR / prompt_filename

            # Check WIP for COMPLETE marker BEFORE appending agent log
            is_complete = False
            summary = ""
            if wip.exists():
                try:
                    content = wip.read_text(encoding='utf-8', errors='ignore')
                    lines = content.rstrip().split('\n')
                    is_complete = len(lines) > 0 and lines[-1].strip() == "COMPLETE"
                except Exception:
                    pass
                summary = get_wip_summary(prompt_filename)

            # Append agent log to WIP for full audit trail
            for log_file in LOGS_DIR.glob(f"agent_*_{Path(prompt_filename).stem}.log"):
                if log_file.exists():
                    try:
                        log_content = log_file.read_text(encoding='utf-8', errors='ignore')
                        if log_content.strip():
                            if wip.exists():
                                with open(wip, 'a', encoding='utf-8') as f:
                                    f.write(f"\n\n--- Agent Log ---\n{log_content}")
                            else:
                                wip.write_text(log_content, encoding='utf-8')
                    except Exception as e:
                        log(f"WARNING: Could not append agent log to WIP: {e}")
                break

            # If not complete, append verification message
            if not is_complete and wip.exists():
                try:
                    with open(wip, 'a', encoding='utf-8') as f:
                        f.write(f"\n\n--- Verify/Complete or Finish ---\nPlease verify this workorder is complete or finish the work and add COMPLETE as the last line.\n")
                except Exception as e:
                    log(f"WARNING: Could not append verification message: {e}")

            # ONLY move prompt to done/ or back to ready/ if git sync completed (or was deferred for batch)
            # If git operations failed and weren't deferred, DON'T move the WIP file
            allow_wip_move = git_sync_success if not defer_git_sync() else True

            if is_complete and allow_wip_move:
                log(f"COMPLETE: {prompt_filename} -> done/")
                DONE_DIR.mkdir(parents=True, exist_ok=True)
                dst = DONE_DIR / prompt_filename
                if wip.exists():
                    shutil.move(str(wip), str(dst))
                commit_msg = (
                    f"feat: Complete prompt '{prompt_filename}'\n\n"
                    f"Agent: {agent_name}\n\n"
                    f"Work log tail:\n{summary}"
                )
                # Notify PM of completion
                try:
                    from csc_service.infra import pm
                    pm.setup(CSC_ROOT)
                    pm.mark_completed(prompt_filename)
                except Exception:
                    pass
            elif allow_wip_move:  # Only move to ready if git sync succeeded (or was deferred)
                log(f"INCOMPLETE: {prompt_filename} -> ready/")
                # Add INCOMPLETE note to the WIP file before moving back
                if wip.exists():
                    try:
                        current_content = wip.read_text(encoding='utf-8', errors='ignore')
                        # Add INCOMPLETE marker if not already present
                        if not current_content.rstrip().endswith("INCOMPLETE"):
                            wip.write_text(
                                current_content.rstrip() + "\n\nINCOMPLETE: Agent task did not finish properly (missing COMPLETE marker)\n",
                                encoding='utf-8'
                            )
                    except Exception as e:
                        log(f"WARNING: Could not add INCOMPLETE marker to {prompt_filename}: {e}")

                dst = READY_DIR / prompt_filename
                if wip.exists():
                    shutil.move(str(wip), str(dst))
                commit_msg = (
                    f"chore: Agent work on '{prompt_filename}' (incomplete)\n\n"
                    f"Agent: {agent_name}\n\n"
                    f"Work log tail:\n{summary}"
                )
            else:
                # Git sync failed - keep WIP file in place for next cycle to retry
                log(f"WARNING: Git sync failed - keeping {prompt_filename} in WIP for retry", "WARN")
                commit_msg = (
                    f"chore: Agent work on '{prompt_filename}' (incomplete)\n\n"
                    f"Agent: {agent_name}\n\n"
                    f"Work log tail:\n{summary}"
                )
                # Notify PM of failure (tracks attempts, escalation)
                try:
                    from csc_service.infra import pm
                    pm.setup(CSC_ROOT)
                    pm.mark_failed(prompt_filename)
                except Exception:
                    pass

            # Move queue file: work/ -> out/
            out_dir = agent_queue_dir(agent_name, "out")
            out_dir.mkdir(parents=True, exist_ok=True)
            # Try both the workorder name and orders.md (queue-worker renames to orders.md)
            work_file = work_dir / prompt_filename
            if work_file.exists():
                shutil.move(str(work_file), str(out_dir / prompt_filename))
            orders_file = work_dir / "orders.md"
            if orders_file.exists():
                # Append unixtime to orders.md to avoid collision (all orders.md have same name)
                ts = int(time.time())
                orders_out_name = f"orders-{ts}.md"
                shutil.move(str(orders_file), str(out_dir / orders_out_name))
            pid_file.unlink(missing_ok=True)
            # Clean up the per-WO repo path file if it still exists
            repo_file_cleanup = work_dir / f"{prompt_filename}.repo"
            repo_file_cleanup.unlink(missing_ok=True)

            # Copy agent log to queue/out/ for debugging
            for log_file in LOGS_DIR.glob(f"agent_*_{Path(prompt_filename).stem}.log"):
                if log_file.exists():
                    try:
                        shutil.copy2(str(log_file), str(out_dir / log_file.name))
                        log(f"Copied agent log to queue/out/{log_file.name}")
                    except Exception as e:
                        log(f"WARNING: Could not copy agent log: {e}", "WARN")
                    break

            # Clean stale state
            key = f"{agent_name}/{prompt_filename}"
            stale_state.pop(key, None)

            # Refresh maps, commit, push
            if defer_git_sync():
                log("Deferring refresh_maps + commit/push until batch completion")
            else:
                refresh_maps()
                git_commit_push(commit_msg)

    save_stale_state(stale_state)
    return has_active_work


def process_inbox():
    """
    Process one workorder from the pending work list (FIFO by datestamp).

    Flow:
    1. Check if any queue/work/ has an active agent (has non-empty work/)
    2. If queue/work/ is EMPTY, load or scan the pending work list
    3. Take the first (oldest) item from the list
    4. Verify workorder still exists (if not, dump list and rescan)
    5. Move orders.md: queue/in/ → queue/work/
    6. git add agents/ && git commit -m "assigning task X to agent_Y" && git push
    7. git pull in agent's temp repo (to get orders.md and WIP file)
    8. Spawn agent to work non-interactively
    9. Pop the processed item from the list
    """
    # Build set of agents that are currently busy (have live PID files).
    # Also clean up orphaned work files (orders.md without .pid) along the way.
    busy_agents = set()
    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        agent_name = agent_dir.name
        if agent_name not in KNOWN_AGENTS:
            continue

        work_dir = agent_queue_dir(agent_name, "work")
        if not work_dir.exists():
            continue

        live_pids = []
        other_files = []
        for f in work_dir.iterdir():
            if f.is_file() and f.suffix == '.pid':
                try:
                    pid = int(f.read_text().strip())
                    if is_pid_alive(pid):
                        live_pids.append(f)
                    else:
                        f.unlink(missing_ok=True)  # dead PID, clean up
                except Exception:
                    f.unlink(missing_ok=True)
            elif f.is_file():
                other_files.append(f)

        if live_pids:
            busy_agents.add(agent_name)
            log(f"Agent {agent_name} is busy ({len(live_pids)} live PID files), skipping for now")
        elif other_files:
            # Orphaned files (e.g. orders.md without a .pid) — clean up
            out_dir = agent_queue_dir(agent_name, "out")
            out_dir.mkdir(parents=True, exist_ok=True)
            for orphan in other_files:
                ts = int(time.time())
                dest_name = f"{orphan.stem}-orphan-{ts}{orphan.suffix}"
                shutil.move(str(orphan), str(out_dir / dest_name))
                log(f"Cleaned up orphaned {orphan.name} from {agent_name}/queue/work/ -> out/{dest_name}", "WARN")

    # Load pending work list or rescan if empty
    pending = load_pending_list()
    if not pending:
        pending = scan_pending_work()
        if not pending:
            return  # Nothing queued anywhere

    # Find the first pending item whose agent is NOT currently busy
    item = None
    for candidate in pending:
        if candidate["agent"] not in busy_agents:
            item = candidate
            break

    if item is None:
        log(f"All pending agents are busy ({busy_agents}), waiting")
        return

    # Remove item from pending list now that it will be processed
    pending.remove(item)
    save_pending_list(pending)

    agent_name = item["agent"]
    workorder_filename = item["workorder"]

    log(f"Processing pending workorder: {workorder_filename} (agent: {agent_name}, ts: {item['ts']})")

    # Verify workorder still exists in workorders/wip/
    workorder_path = WIP_DIR / workorder_filename
    if not workorder_path.exists():
        log(f"Workorder not found: {workorder_filename} — dumping list, rescanning", "WARN")
        save_pending_list([])  # Dump the list
        pending = scan_pending_work()  # Rescan all agents
        if not pending:
            return
        # Retry with the newly scanned list
        item = pending[0]
        agent_name = item["agent"]
        workorder_filename = item["workorder"]
        workorder_path = WIP_DIR / workorder_filename
        if not workorder_path.exists():
            log(f"Still not found after rescan: {workorder_filename}", "ERROR")
            # Remove this item from the list and continue
            save_pending_list(pending[1:])
            return

    # Find the agent's queue/in/ and orders.md file
    in_dir = agent_queue_dir(agent_name, "in")
    orders_md_path = in_dir / "orders.md"

    if not orders_md_path.exists():
        log(f"orders.md not found for {agent_name}: {orders_md_path}", "ERROR")
        # Remove this item from list and rescan
        save_pending_list(pending[1:])
        return

    # Move orders.md from queue/in/ -> queue/work/
    work_dir = agent_queue_dir(agent_name, "work")
    work_dir.mkdir(parents=True, exist_ok=True)
    work_file = work_dir / "orders.md"

    try:
        shutil.move(str(orders_md_path), str(work_file))
        log(f"Moved orders.md: queue/in/ → queue/work/")
    except Exception as e:
        log(f"ERROR: Failed to move orders.md: {e}", "ERROR")
        return

    if not defer_git_sync():
        # Determine the git repo that contains AGENTS_DIR (may be a submodule)
        # Walk up from AGENTS_DIR to find the nearest .git dir/file
        def _find_git_root(path):
            p = Path(path)
            for _ in range(10):
                if (p / ".git").exists():
                    return p
                if p == p.parent:
                    break
                p = p.parent
            return None

        ops_git_root = _find_git_root(AGENTS_DIR)
        if ops_git_root is None:
            ops_git_root = CSC_ROOT

        # Paths relative to the ops git root
        try:
            agents_rel = str(AGENTS_DIR.relative_to(ops_git_root))
        except ValueError:
            agents_rel = "agents"
        try:
            prompts_rel = str(PROMPTS_BASE.relative_to(ops_git_root))
        except ValueError:
            prompts_rel = PROMPTS_BASE.name

        # Stage and commit inside the ops git root
        try:
            result = subprocess.run(
                ["git", "add", f"{agents_rel}/", f"{prompts_rel}/"],
                cwd=str(ops_git_root),
                capture_output=True,
                text=True,
                timeout=30
            )
            log(f"git add {agents_rel}/ {prompts_rel}/ completed")
        except Exception as e:
            log(f"ERROR: Failed to git add: {e}", "ERROR")
            return

        try:
            result = subprocess.run(
                ["git", "commit", "-m", "chore: Assigning workorder to agent"],
                cwd=str(ops_git_root),
                capture_output=True,
                text=True,
                timeout=30
            )
            log(f"git commit completed: {result.stdout.strip()}")
            committed = result.returncode == 0
        except Exception as e:
            log(f"ERROR: Failed to git commit workorder assignment: {e}", "ERROR")
            return

        try:
            result = subprocess.run(
                ["git", "push"],
                cwd=str(ops_git_root),
                capture_output=True,
                text=True,
                timeout=30
            )
            log(f"git push completed: {result.stdout.strip()}")
        except Exception as e:
            log(f"ERROR: Failed to git push workorder assignment: {e}", "ERROR")
            return

        # If ops_git_root is a submodule of CSC_ROOT, update the parent submodule pointer
        if ops_git_root != CSC_ROOT and committed:
            try:
                ops_rel = str(ops_git_root.relative_to(CSC_ROOT))
                subprocess.run(
                    ["git", "add", ops_rel],
                    cwd=str(CSC_ROOT),
                    capture_output=True, text=True, timeout=30
                )
                subprocess.run(
                    ["git", "commit", "-m", "chore: update ops submodule pointer"],
                    cwd=str(CSC_ROOT),
                    capture_output=True, text=True, timeout=30
                )
                subprocess.run(
                    ["git", "push"],
                    cwd=str(CSC_ROOT),
                    capture_output=True, text=True, timeout=30
                )
                log(f"Updated parent submodule pointer for {ops_rel}")
            except Exception as e:
                log(f"WARN: Failed to update parent submodule pointer: {e}", "WARN")
    else:
        log("Deferring assignment commit/push until batch completion")
        shutil.move(str(work_file), str(orders_md_path))
        return

    # Create a unique per-WO temp repo clone of irc.git for this agent run
    wo_stem = Path(workorder_filename).stem
    agent_repo = create_agent_temp_repo(agent_name, wo_stem)
    if agent_repo is None:
        log(f"ERROR: Could not create temp repo for {agent_name}, reverting orders.md", "ERROR")
        in_dir = agent_queue_dir(agent_name, "in")
        in_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(work_file), str(in_dir / "orders.md"))
        except Exception:
            pass
        return

    # Verify orders.md exists in the WORKING TREE (agents run from CSC_ROOT, not temp repo)
    # orders.md is in ops submodule, not irc.git clone — check CSC_ROOT directly
    main_orders = AGENTS_DIR / agent_name / "queue" / "work" / "orders.md"
    if not main_orders.exists():
        log(f"ERROR: orders.md not found in working tree ({main_orders})", "ERROR")
        in_dir = agent_queue_dir(agent_name, "in")
        in_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(work_file), str(in_dir / "orders.md"))
            log(f"Reverted orders.md back to queue/in/ for retry")
        except Exception as e:
            log(f"ERROR: Failed to revert orders.md: {e}", "ERROR")
        return

    # Spawn agent in temp repo (not main repo)
    pid, agent_log = spawn_agent(agent_name, workorder_filename, agent_repo=agent_repo)
    if pid:
        # Brief wait to catch immediate startup failures (bad path, missing CLI, etc.)
        time.sleep(3)
        if pid in ACTIVE_PROCS and ACTIVE_PROCS[pid].poll() is not None:
            exit_code = ACTIVE_PROCS[pid].returncode
            log(f"ERROR: Agent {agent_name} (PID {pid}) exited immediately with code {exit_code}", "ERROR")
            # Log the first few lines of the agent log for diagnosis
            if agent_log and agent_log.exists():
                try:
                    log_content = agent_log.read_text(encoding='utf-8', errors='ignore')[:500]
                    log(f"Agent log: {log_content}", "ERROR")
                except Exception:
                    pass
            del ACTIVE_PROCS[pid]
            clear_agent_data()
            # Move orders.md back to queue/in/ for retry
            in_dir = agent_queue_dir(agent_name, "in")
            in_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(work_file), str(in_dir / "orders.md"))
                log(f"Reverted orders.md back to queue/in/ for retry after early exit")
            except Exception as e:
                log(f"ERROR: Failed to revert orders.md: {e}", "ERROR")
            return

        # Write PID file and repo path file (so process_work can find the unique repo)
        pid_file = work_dir / f"{workorder_filename}.pid"
        pid_file.write_text(str(pid), encoding='utf-8')
        repo_file = work_dir / f"{workorder_filename}.repo"
        repo_file.write_text(str(agent_repo), encoding='utf-8')

        write_agent_data(agent_name, pid, workorder_filename, agent_log)
        log(f"Started {agent_name} (PID {pid}) for {workorder_filename}")
    else:
        log(f"ERROR: Failed to spawn agent, reverting", "ERROR")
        # Move orders.md back to queue/in/
        shutil.move(str(work_file), str(orders_md_path))
        return

    # Only process ONE task per cycle
    return


# ======================================================================
# Main cycle
# ======================================================================

def run_cycle(work_dir_arg=None):
    """Run one complete queue-worker cycle.

    1. Initialize paths (using work_dir_arg if provided)
    2. git pull to get latest from remote
    3. Check queue/work/ for running or finished agents
    4. If no active work, pick up new task from queue/in/
    """
    _initialize_paths(work_dir_arg)

    log("=" * 50)
    log("Cycle start")

    # Pull latest changes
    git_pull()

    # Check work in progress first
    has_active_work = process_work()

    # If nothing running, pick up new work
    if not has_active_work:
        process_inbox()

    log("Cycle end")


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
            log("Daemon mode (Ctrl+C to stop)")
            try:
                while True:
                    run_cycle(work_dir_arg=work_dir)
                    time.sleep(60)
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
