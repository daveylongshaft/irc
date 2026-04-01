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
import time
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

# Add packages to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "csc-service"))
sys.path.insert(1, str(PROJECT_ROOT / "packages"))

try:
    from csc_service.shared.api_key_manager import APIKeyManager
except ImportError:
    from csc_shared.api_key_manager import APIKeyManager

# --- Configuration ---
SCRIPT_DIR = Path(__file__).resolve().parent
CSC_ROOT = PROJECT_ROOT
AGENTS_DIR = CSC_ROOT / "agents"
def resolve_workorders_base():
    """Prefer workorders/, fall back to legacy prompts/."""
    workorders = CSC_ROOT / "workorders"
    legacy_prompts = CSC_ROOT / "prompts"
    return workorders if workorders.exists() else legacy_prompts


PROMPTS_BASE = resolve_workorders_base()
READY_DIR = PROMPTS_BASE / "ready"
WIP_DIR = PROMPTS_BASE / "wip"
DONE_DIR = PROMPTS_BASE / "done"
LOGS_DIR = CSC_ROOT / "logs"

# Agent queues stay repo-backed for multi-system sync
# agents/<agent_name>/queue/{in,work,out}


def agent_queue_dir(agent_name, stage):
    """Get queue stage directory under the repo-backed agents tree."""
    return AGENTS_DIR / agent_name / "queue" / stage


# Global dict to store active Popen objects for reliable exit detection
ACTIVE_PROCS = {}  # {pid: Popen object}

# API Key Manager for automatic rotation when credits exhausted
API_KEY_MGR = APIKeyManager()
QUEUE_LOG = LOGS_DIR / "queue-worker.log"
STALE_FILE = LOGS_DIR / "queue-wip-sizes.json"

IS_WINDOWS = os.name == 'nt'

# Agent configs: name matches agents/<name>/cagent.yaml
# All agents now use 'cagent run --exec' with their YAML config
KNOWN_AGENTS = {
    "claude", "haiku", "opus",
    "gemini", "gemini-2.5-flash", "gemini-2.5-flash-lite",
    "gemini-3-flash", "gemini-3-pro",
    "qwen", "deepseek", "codellama",
    "chatgpt",
}

# Local models that need Docker Model Runner endpoint
LOCAL_AGENTS = {"qwen", "deepseek", "codellama"}
DMR_ENDPOINT = "http://localhost:12434/engines/v1"

# How many consecutive stale checks before warning
STALE_THRESHOLD = 3

# agent_data.json: shared state file so `agent status` and `agent tail` work
AGENT_DATA_FILE = CSC_ROOT / "agent_data.json"


# ======================================================================
# agent_data.json helpers
# ======================================================================

def write_agent_data(agent_name, pid, prompt_filename, log_path):
    """Write agent tracking data so `agent status` and `agent tail` work."""
    data = {}
    # Preserve selected_agent if it exists
    if AGENT_DATA_FILE.exists():
        try:
            data = json.loads(AGENT_DATA_FILE.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            data = {}

    data.update({
        "selected_agent": agent_name,
        "current_pid": pid,
        "current_prompt": prompt_filename,
        "current_log": str(log_path),
        "started_at": int(time.time()),
    })

    try:
        AGENT_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        AGENT_DATA_FILE.write_text(
            json.dumps(data, indent=4), encoding='utf-8'
        )
    except OSError as e:
        log(f"Failed to write agent_data.json: {e}", "WARN")


def clear_agent_data():
    """Clear agent tracking data after agent finishes."""
    data = {}
    if AGENT_DATA_FILE.exists():
        try:
            data = json.loads(AGENT_DATA_FILE.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            data = {}

    data.update({
        "current_pid": None,
        "current_prompt": None,
        "current_log": None,
        "started_at": None,
    })

    try:
        AGENT_DATA_FILE.write_text(
            json.dumps(data, indent=4), encoding='utf-8'
        )
    except OSError as e:
        log(f"Failed to clear agent_data.json: {e}", "WARN")


# ======================================================================
# Logging
# ======================================================================

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [queue-worker] [{level}] {msg}"
    print(line, file=sys.stderr)
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(QUEUE_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
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
        subprocess.run(["git", "pull"], cwd=str(CSC_ROOT),
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

    # No Popen object - fall back to OS query (for backwards compatibility)
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
                out = result.stdout.strip().lower()
                if out and "no tasks are running" not in out and "info:" not in out:
                    return True

            # Fallback for constrained tasklist environments.
            ps_result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -First 1",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            return bool(ps_result.stdout.strip())
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

def build_full_prompt(agent_name, prompt_filename):
    """Assemble: README.1shot + agents/<name>/context/* + WIP content."""
    parts = []

    # 1. README.1shot
    readme = CSC_ROOT / "README.1shot"
    if readme.exists():
        parts.append(readme.read_text(encoding='utf-8'))

    # 2. Agent context files
    ctx_dir = AGENTS_DIR / agent_name / "context"
    if ctx_dir.exists():
        for f in sorted(ctx_dir.glob("*.md")):
            parts.append(f"=== {f.name} ===\n{f.read_text(encoding='utf-8')}")

    # 3. System rule (journal to WIP)
    sys_rule = (
        f"SYSTEM RULE: Journal every step to workorders/wip/{prompt_filename} "
        f"BEFORE doing it. Use: echo '<step>' >> workorders/wip/{prompt_filename}. "
        f"Do NOT touch git. Do NOT move files. Do NOT run tests. "
        f"When done, echo 'COMPLETE' >> workorders/wip/{prompt_filename} and exit."
    )
    parts.append(sys_rule)

    # 4. WIP file content (the actual task)
    wip = WIP_DIR / prompt_filename
    if wip.exists():
        parts.append(f"=== TASK: {prompt_filename} ===\n{wip.read_text(encoding='utf-8', errors='replace')}")

    return "\n\n".join(parts).replace('\0', '')


# ======================================================================
# Agent spawning
# ======================================================================

def spawn_agent(agent_name, prompt_filename):
    """Spawn AI agent via cagent exec. Returns (PID, log_path) or (None, None)."""
    if agent_name not in KNOWN_AGENTS:
        log(f"Unknown agent: {agent_name}", "ERROR")
        return None, None

    cagent_bin = find_cagent()
    if not cagent_bin:
        return None, None

    yaml_path = AGENTS_DIR / agent_name / "cagent.yaml"
    if not yaml_path.exists():
        log(f"No cagent.yaml for agent: {agent_name}", "ERROR")
        return None, None

    # Assemble prompt
    prompt_text = build_full_prompt(agent_name, prompt_filename)

    # Set API key for Anthropic agents (haiku, sonnet, opus, claude)
    # Use APIKeyManager for automatic rotation when credits exhausted
    if agent_name in ["haiku", "sonnet", "opus", "claude"]:
        api_key = API_KEY_MGR.get_current_key()
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key
            log(f"Using API key #{API_KEY_MGR.current_index + 1}/{API_KEY_MGR.get_key_count()}")

    # Local models need Docker Model Runner endpoint
    # Set these BEFORE building cmd so subprocess inherits them
    if agent_name in LOCAL_AGENTS:
        os.environ.setdefault("OPENAI_BASE_URL", DMR_ENDPOINT)
        os.environ.setdefault("OPENAI_API_KEY", "dummy")

    # Map CHATGPT_API_KEY to OPENAI_API_KEY for chatgpt agent
    if agent_name == "chatgpt":
        chatgpt_key = os.environ.get("CHATGPT_API_KEY")
        if chatgpt_key:
            os.environ["OPENAI_API_KEY"] = chatgpt_key
            log("Using CHATGPT_API_KEY as OPENAI_API_KEY")

    # Build cagent exec command (non-interactive mode)
    # Don't use --env-from-file; let subprocess inherit parent's environment
    cmd = [
        cagent_bin, "exec",
        str(yaml_path),
        prompt_text,
        "--working-dir", str(CSC_ROOT),
        "--yolo",  # Auto-approve all tool calls (read_file, write_file, run_terminal_cmd)
    ]

    # Log file for agent stdout/stderr
    ts = int(time.time())
    agent_log = LOGS_DIR / f"agent_{ts}_{Path(prompt_filename).stem}.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log(f"Command: cagent exec {yaml_path.name} ... --working-dir {CSC_ROOT}")

    try:
        log_fh = open(agent_log, 'w', encoding='utf-8')
        child_env = os.environ.copy()
        child_env["CSC_AGENT_NAME"] = agent_name

        if IS_WINDOWS:
            proc = subprocess.Popen(
                cmd, cwd=str(CSC_ROOT),
                stdin=None, stdout=log_fh, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                env=child_env
            )
        else:
            proc = subprocess.Popen(
                cmd, cwd=str(CSC_ROOT),
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

                # Stale detection
                key = f"{agent_name}/{prompt_filename}"
                prev = stale_state.get(key, {})
                prev_size = prev.get("size", -1)
                stale_count = prev.get("stale_count", 0)

                if wip_size == prev_size and wip_size >= 0:
                    stale_count += 1
                    if stale_count >= STALE_THRESHOLD:
                        log(f"STALE WARNING: WIP unchanged for {stale_count} checks", "WARN")
                else:
                    stale_count = 0

                stale_state[key] = {"size": wip_size, "stale_count": stale_count}
                continue

            # ---- AGENT FINISHED ----
            log(f"Agent {agent_name} PID {pid} finished for {prompt_filename}")
            clear_agent_data()

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

            # Check WIP for COMPLETE
            is_complete = False
            if wip.exists():
                try:
                    content = wip.read_text(encoding='utf-8', errors='ignore')
                    is_complete = "COMPLETE" in content
                except Exception:
                    pass

            # Get WIP summary for commit message
            summary = get_wip_summary(prompt_filename)

            # Move prompt to done/ or back to ready/
            if is_complete:
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
            else:
                log(f"INCOMPLETE: {prompt_filename} -> ready/")
                dst = READY_DIR / prompt_filename
                if wip.exists():
                    shutil.move(str(wip), str(dst))
                commit_msg = (
                    f"chore: Agent work on '{prompt_filename}' (incomplete)\n\n"
                    f"Agent: {agent_name}\n\n"
                    f"Work log tail:\n{summary}"
                )

            # Move queue file: work/ -> out/
            out_dir = agent_queue_dir(agent_name, "out")
            out_dir.mkdir(parents=True, exist_ok=True)
            work_file = work_dir / prompt_filename
            if work_file.exists():
                shutil.move(str(work_file), str(out_dir / prompt_filename))
            pid_file.unlink(missing_ok=True)

            # Clean stale state
            key = f"{agent_name}/{prompt_filename}"
            stale_state.pop(key, None)

            # Refresh maps, commit, push
            refresh_maps()
            git_commit_push(commit_msg)

    save_stale_state(stale_state)
    return has_active_work


def process_inbox():
    """Pick up ONE task from queue/in/ across all agents. First come first served."""
    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        in_dir = agent_queue_dir(agent_dir.name, "in")
        if not in_dir.exists():
            continue

        agent_name = agent_dir.name
        if agent_name not in KNOWN_AGENTS:
            continue

        for task_file in sorted(in_dir.glob("*.md")):
            prompt_filename = task_file.name
            log(f"Picking up: {agent_name}/{prompt_filename}")

            # 1. Move prompt from ready/ -> wip/ (if it exists)
            WIP_DIR.mkdir(parents=True, exist_ok=True)
            ready_prompt = READY_DIR / prompt_filename
            wip_prompt = WIP_DIR / prompt_filename

            if ready_prompt.exists() and not wip_prompt.exists():
                shutil.move(str(ready_prompt), str(wip_prompt))
                log(f"Moved prompt: ready/ -> wip/")
            elif not wip_prompt.exists():
                # Prompt not in ready/ either - create minimal WIP from queue file
                wip_prompt.write_text(
                    f"# {prompt_filename}\n\n## Work Log\n",
                    encoding='utf-8'
                )
                log(f"Created WIP (prompt not in ready/)")

            # 2. Move queue file: in/ -> work/
            work_dir = agent_queue_dir(agent_name, "work")
            work_dir.mkdir(parents=True, exist_ok=True)
            work_file = work_dir / prompt_filename
            shutil.move(str(task_file), str(work_file))
            log(f"Queue: in/ -> work/")

            # 3. Spawn agent
            pid, agent_log = spawn_agent(agent_name, prompt_filename)
            if pid:
                # Write PID file
                pid_file = work_dir / f"{prompt_filename}.pid"
                pid_file.write_text(str(pid), encoding='utf-8')

                # Update agent_data.json for `agent status`
                write_agent_data(agent_name, pid, prompt_filename, agent_log)

                # Stamp PID in WIP
                with open(wip_prompt, 'a', encoding='utf-8') as f:
                    f.write(
                        f"\nPID: {pid} agent: {agent_name} "
                        f"starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    )

                log(f"Started {agent_name} (PID {pid}) for {prompt_filename}")
            else:
                # Failed - move everything back
                log(f"Failed to start agent, reverting", "ERROR")
                shutil.move(str(work_file), str(task_file))
                if wip_prompt.exists() and not ready_prompt.exists():
                    shutil.move(str(wip_prompt), str(ready_prompt))

            # Only process ONE task per cycle
            return


# ======================================================================
# Main cycle
# ======================================================================

def run_cycle():
    log("=" * 50)
    log("Cycle start")

    # 1. Git pull to sync
    git_pull()

    # 2. Check work/ for running/finished tasks
    has_active = process_work()

    # 3. If nothing active, pick from inbox
    if not has_active:
        process_inbox()
    else:
        log("Task in progress, skipping inbox")

    log("Cycle end")


def main():
    load_env()

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--daemon":
            log("Daemon mode (Ctrl+C to stop)")
            try:
                while True:
                    run_cycle()
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
        run_cycle()


if __name__ == "__main__":
    main()
