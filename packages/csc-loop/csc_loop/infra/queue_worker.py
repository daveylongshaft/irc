#!/usr/bin/env python3
"""
Queue Worker: Full lifecycle manager for AI agent prompt execution.

Runs as a polling service (--daemon) or one-shot via csc-loop to manage the
complete lifecycle of agent tasks. 

Lifecycle per task:
  1. git pull
  2. Scan agent queue/in/ for new tasks
  3. Start next task (non-blocking):
     - queue/in/ -> queue/work/
     - Create temp repo clone
     - Inject path variables into orders.md
     - Spawn AI agent in background, note PID
  4. Monitor active tasks:
     - Check if PID is alive
     - If finished: process result (done/ready), sync git, cleanup clone
  5. refresh-maps, git add/commit/push (main repo)

Constraints:
  - Only ONE task runs at a time globally (enforced by PID tracking)
  - Non-blocking: loop continues while agent thinks
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

from csc_data.agent_executor import AgentExecutor
from csc_data.api_key_manager import APIKeyManager
from csc_services.service import Service

# --- Configuration ---
SCRIPT_DIR = Path(__file__).resolve().parent

# Declare global path variables
CSC_ROOT = None
AGENTS_DIR = None
PROMPTS_BASE = None
READY_DIR = None
WIP_DIR = None
DONE_DIR = None
LOGS_DIR = None
AGENT_DATA_FILE = None
PENDING_FILE = None
AGENT_EXECUTOR = None

# Service instances
_agent_svc: Service = None   # shared agent tracking
_qw_svc: Service = None      # queue-worker own state

# Global managers and logs
API_KEY_MGR = None
QUEUE_LOG = None
STALE_FILE = None

# Constants
STALE_THRESHOLD = 10
AGENT_MAX_TOTAL_RUNTIME_SECONDS = 3600

# Track spawned Popen objects by PID
ACTIVE_PROCS = {}

def _initialize_paths(work_dir_arg=None):
    global CSC_ROOT, AGENTS_DIR, PROMPTS_BASE, READY_DIR, WIP_DIR, DONE_DIR, LOGS_DIR, AGENT_DATA_FILE, API_KEY_MGR, QUEUE_LOG, STALE_FILE, PENDING_FILE, _agent_svc, _qw_svc, AGENT_EXECUTOR

    if work_dir_arg:
        CSC_ROOT = Path(work_dir_arg).resolve()
    else:
        try:
            from csc_platform import Platform
            CSC_ROOT = Path(Platform.PROJECT_ROOT).resolve()
        except Exception:
            if os.environ.get("CSC_ROOT"):
                CSC_ROOT = Path(os.environ["CSC_ROOT"]).resolve()
            else:
                p = SCRIPT_DIR
                for _ in range(10):
                    if (p / ".csc_root").exists(): break
                    if p == p.parent: break
                    p = p.parent
                CSC_ROOT = p

    # Canonical paths (Versioned irc/ docs and ops/ wo)
    AGENTS_DIR = CSC_ROOT / "ops" / "agents"
    PROMPTS_BASE = CSC_ROOT / "ops" / "wo"
    READY_DIR = PROMPTS_BASE / "ready"
    WIP_DIR = PROMPTS_BASE / "wip"
    DONE_DIR = PROMPTS_BASE / "done"
    LOGS_DIR = CSC_ROOT / "ops" / "logs"
    AGENT_DATA_FILE = CSC_ROOT / "etc" / "agent_data.json"

    _agent_svc = Service(None)
    _agent_svc.name = "agent"
    _agent_svc.init_data()

    _qw_svc = Service(None)
    _qw_svc.name = "queue_worker"
    _qw_svc.init_data()

    API_KEY_MGR = APIKeyManager()
    QUEUE_LOG = LOGS_DIR / "queue-worker.log"
    STALE_FILE = LOGS_DIR / "queue-wip-sizes.json"
    PENDING_FILE = LOGS_DIR / "queue-pending.json"
    AGENT_EXECUTOR = AgentExecutor(CSC_ROOT)

IS_WINDOWS = os.name == 'nt'

# ======================================================================
# Git & Repo Helpers
# ======================================================================

def _get_irc_remote():
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=str(CSC_ROOT), timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip().replace("/csc.git", "/irc.git")
    except Exception: pass
    return "https://github.com/daveylongshaft/irc.git"

def create_agent_temp_repo(agent_name, wo_stem):
    ts = int(time.time())
    safe_stem = re.sub(r'[^\w-]', '_', wo_stem)[:40]
<<<<<<< HEAD
    clones_base = CSC_ROOT / "tmp" / "clones"
    
=======
    # Use Platform for the clones base — never hardcode /opt
    from csc_platform import Platform as _Plat
    _plat = _Plat()
    clones_base = (_plat.agent_work_base or CSC_ROOT / "tmp") / "clones"

    # Purge stale clones for this agent before creating a new one
>>>>>>> 48e68d09763f0faba18d64b20069444bb0d5a1c8
    agent_clones_dir = clones_base / agent_name
    if agent_clones_dir.exists():
        for stale in agent_clones_dir.iterdir():
            try: shutil.rmtree(str(stale))
            except Exception: pass
            
    repo = clones_base / agent_name / f"{safe_stem}-{ts}" / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    irc_remote = _get_irc_remote()
    
    log(f"Cloning irc.git to {repo} (depth=1)")
    result = subprocess.run(
        ["git", "clone", "--depth=1", irc_remote, str(repo)],
        capture_output=True, text=True, timeout=120
    )
    return repo if result.returncode == 0 else None

def git_pull():
    try:
        subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=str(CSC_ROOT),
                        capture_output=True, text=True, timeout=60)
    except Exception: pass

def git_commit_push(message):
    try:
        subprocess.run(["git", "add", "-A"], cwd=str(CSC_ROOT), capture_output=True, timeout=30)
        result = subprocess.run(["git", "status", "--porcelain"], cwd=str(CSC_ROOT), capture_output=True, text=True)
        if not result.stdout.strip(): return
        subprocess.run(["git", "commit", "-m", message], cwd=str(CSC_ROOT), capture_output=True, timeout=30)
        subprocess.run(["git", "push"], cwd=str(CSC_ROOT), capture_output=True, timeout=60)
    except Exception: pass

def git_commit_push_in_repo(repo_path, message):
    try:
        subprocess.run(["git", "add", "-A"], cwd=str(repo_path), capture_output=True, timeout=30)
        subprocess.run(["git", "commit", "-m", message], cwd=str(repo_path), capture_output=True, timeout=30)
        result = subprocess.run(["git", "push"], cwd=str(repo_path), capture_output=True, text=True, timeout=60)
        return (result.returncode == 0, result.stderr if result.returncode != 0 else None)
    except Exception as e:
        return (False, str(e))

def refresh_maps():
    script = SCRIPT_DIR / "refresh-maps"
    if not script.exists(): return
    try: subprocess.run([sys.executable, str(script), "--quick"], cwd=str(CSC_ROOT), timeout=120)
    except Exception: pass

# ======================================================================
# Task Monitoring & State
# ======================================================================

def load_active_tasks():
    tasks = _qw_svc.get_data("active_tasks")
    return tasks if isinstance(tasks, list) else []

def save_active_tasks(tasks):
    _qw_svc.put_data("active_tasks", tasks)

def write_agent_data(agent_name, pid, prompt_filename, log_path):
    _agent_svc.put_data("selected_agent", agent_name, flush=False)
    _agent_svc.put_data("current_pid", pid, flush=False)
    _agent_svc.put_data("current_prompt", prompt_filename, flush=False)
    _agent_svc.put_data("current_log", str(log_path), flush=False)
    _agent_svc.put_data("started_at", int(time.time()))

def clear_agent_data():
    _agent_svc.put_data("current_pid", None, flush=False)
    _agent_svc.put_data("current_prompt", None, flush=False)
    _agent_svc.put_data("current_log", None, flush=False)
    _agent_svc.put_data("started_at", None)

def is_pid_alive(pid):
    if IS_WINDOWS:
        try:
            result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
            return str(pid) in result.stdout
        except Exception: return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError): return False

def is_complete_marker(content: str) -> bool:
    lines = content.rstrip().split('\n')
    return len(lines) > 0 and lines[-1].strip() == "COMPLETE"

# ======================================================================
# Core Lifecycle
# ======================================================================

def process_finished_work(task):
    agent_name = task["agent"]
    prompt_filename = task["workorder"]
    pid = task["pid"]
    agent_log_path = Path(task["log"])
    clone_path = Path(task["clone"]) if task.get("clone") else None
    return_code = task.get("rc", 0)

    log(f"Processing finished work for {agent_name} (PID {pid}, rc {return_code})")
    clear_agent_data()

    wip = WIP_DIR / prompt_filename
    if not wip.exists():
        log(f"WIP file missing: {prompt_filename}", "ERROR")
        return

    content = wip.read_text(encoding='utf-8', errors='ignore')
    is_complete = is_complete_marker(content)
    
    # 1. Clean existing markers and metadata/history blocks for surgical update
    lines = content.rstrip().split('\n')
    while lines and lines[-1].strip() in ["COMPLETE", "INCOMPLETE"]:
        lines.pop()
    
    content_no_markers = "\n".join(lines)
    
    # Extract latest metadata
    meta_content = ""
    meta_work = AGENTS_DIR / agent_name / "queue" / "work" / f"{Path(prompt_filename).stem}.json"
    if meta_work.exists():
        try:
            meta_content = meta_work.read_text(encoding='utf-8', errors='ignore').strip()
            meta_work.unlink()
        except Exception as e:
            log(f"Failed to read metadata: {e}", "WARN")

    # Extract latest log
    new_log = ""
    if agent_log_path.exists():
        new_log = agent_log_path.read_text(encoding='utf-8', errors='ignore').strip()

    # 2. Logic for collapsing consecutive errors
    # We look for the last "Attempt History" block. If this run is a failure and the 
    # last block was also a failure, we collapse them.
    history_pattern = r'--- Attempt History:.*? ---'
    blocks = re.split(history_pattern, content_no_markers)
    
    # Remove existing Assignment Metadata section from the base content if it exists
    content_base = re.sub(r'\n\n--- Assignment Metadata ---\n.*?\n------------------------------------------------', '', content_no_markers, flags=re.DOTALL)
    
    last_block = blocks[-1] if blocks else ""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Check if the previous state was also an error (marked by INCOMPLETE in original content)
    was_error = "INCOMPLETE" in content.rstrip().split('\n')[-1] if content.strip() else False

    if not is_complete and (last_block or was_error):
        # Collapse: update the last block or add a "Repeated" marker to the previous failure
        count_match = re.search(r'\(Total failures: (\d+)\)', last_block)
        count = int(count_match.group(1)) + 1 if count_match else 2
        
        # We'll update the log to the LATEST failure log so the most recent context is visible
        updated_block = f"\n[Agent Log (Latest Failure at {ts})]\n{new_log}\n" if new_log else last_block
        if count_match:
            updated_block = re.sub(r'\(Total failures: \d+\)', f"(Total failures: {count})", last_block)
            # If we have a new log, replace the old log section in the block
            if new_log:
                updated_block = re.sub(r'\[Agent Log\].*?(?=\n\()', f"[Agent Log]\n{new_log}", updated_block, flags=re.DOTALL)
        else:
            updated_block = last_block.rstrip() + f"\n(Total failures: {count})\n"
            
        # Replace or update the last block
        if last_block:
            final_history = content_base[:content_base.rfind(last_block)] + updated_block
        else:
            # Should not happen often if was_error is true, but for safety:
            final_history = content_base + f"\n\n--- Attempt History: {agent_name} (Multiple Failures) ---\n[Agent Log]\n{new_log}\n(Total failures: {count})\n------------------------------------------------\n"
    else:
        # New success or first failure in a while
        attempt_info = f"\n\n--- Attempt History: {agent_name} at {ts} ---\n"
        if new_log:
            attempt_info += f"\n[Agent Log]\n{new_log}\n"
        attempt_info += "------------------------------------------------\n"
        final_history = content_base + attempt_info

    # 3. Add Updated Assignment Metadata (Always the latest version)
    if meta_content:
        final_history += f"\n\n--- Assignment Metadata ---\n{meta_content}\n------------------------------------------------"

    # 4. Enforce size limit (~500KB to stay well under 200k tokens)
    # If too large, we keep the first 10KB (original task) and the last 100KB (recent history)
    if len(final_history) > 500000:
        log(f"Workorder {prompt_filename} exceeds 500KB, pruning history...", "WARN")
        header_chunk = final_history[:10000]
        tail_chunk = final_history[-400000:]
        final_history = header_chunk + "\n\n... [History Pruned Due to Size Limit] ...\n\n" + tail_chunk

    # 5. Final Status Marker
    status_marker = "COMPLETE" if is_complete else "INCOMPLETE"
    final_content = final_history.rstrip() + f"\n\n{status_marker}\n"
    
    # Write back to WIP
    wip.write_text(final_content, encoding='utf-8')

    # Move workorder
    if is_complete:
        log(f"COMPLETE: {prompt_filename} -> done/")
        DONE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(wip), str(DONE_DIR / prompt_filename))
    else:
        log(f"INCOMPLETE: {prompt_filename} -> ready/")
        shutil.move(str(wip), str(READY_DIR / prompt_filename))

    # Move orders.md to out/
    out_dir = AGENTS_DIR / agent_name / "queue" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_orders = AGENTS_DIR / agent_name / "queue" / "work" / "orders.md"
    if work_orders.exists(): shutil.move(str(work_orders), str(out_dir / "orders.md"))
    
    # Cleanup any stray .json files
    for stale_meta in list(out_dir.glob("*.json")) + list((AGENTS_DIR / agent_name / "queue" / "in").glob("*.json")):
        try: stale_meta.unlink()
        except Exception: pass

    # Cleanup clone
    if clone_path and clone_path.exists():
        if is_complete:
            success, err = git_commit_push_in_repo(clone_path, f"feat: {prompt_filename}")
            if not success: log(f"Clone push failed: {err}", "WARN")
        shutil.rmtree(str(clone_path.parent))

    # Final sync main repo
    refresh_maps()
    summary = ""
    if is_complete:
        lines = wip.read_text(errors='ignore').splitlines()
        summary = "\n".join(lines[-15:])
    git_commit_push(f"feat: Complete prompt '{prompt_filename}'\n\nAgent: {agent_name}\n\n{summary}")

def monitor_active_tasks():
    active = load_active_tasks()
    remaining = []
    
    for task in active:
        pid = task["pid"]
        if is_pid_alive(pid):
            remaining.append(task)
            continue
            
        # Task finished
        task["rc"] = 0 # In a real non-blocking system we'd need a way to capture RC
        process_finished_work(task)
        
    save_active_tasks(remaining)
    return len(remaining) > 0

def process_inbox():
    if load_active_tasks(): return False # Only one task at a time

    pending = _qw_svc.get_data("pending_list") or []
    if not pending:
        # Scan for work
        for agent_dir in sorted(AGENTS_DIR.iterdir()):
            if not agent_dir.is_dir(): continue
            in_dir = agent_dir / "queue" / "in"
            orders = in_dir / "orders.md"
            if not orders.exists(): continue
            
            content = orders.read_text(errors='ignore')
            match = re.search(r'ops/wo/wip/([^\s\n]+\.md)', content)
            if not match: continue
            
            filename = match.group(1)
            ts_match = re.match(r'^(\d+)', filename)
            pending.append({"agent": agent_dir.name, "workorder": filename, "ts": int(ts_match.group(1)) if ts_match else 0})
            
        pending.sort(key=lambda x: x["ts"])
        
    if not pending: return False
    
    item = pending.pop(0)
    _qw_svc.put_data("pending_list", pending)
    
    agent_name = item["agent"]
    filename = item["workorder"]
    wip_path = WIP_DIR / filename
    
    if not wip_path.exists(): return False
    
    log(f"Starting task: {filename} for {agent_name}")
    
    # Setup directories
    in_dir = AGENTS_DIR / agent_name / "queue" / "in"
    work_dir = AGENTS_DIR / agent_name / "queue" / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    
    orders_in = in_dir / "orders.md"
    orders_work = work_dir / "orders.md"
    if orders_in.exists(): shutil.move(str(orders_in), str(orders_work))
    
    # Also move associated metadata .json file
    meta_in = in_dir / f"{Path(filename).stem}.json"
    meta_work = work_dir / f"{Path(filename).stem}.json"
    if meta_in.exists():
        shutil.move(str(meta_in), str(meta_work))
    
    # Clone
    clone_path = create_agent_temp_repo(agent_name, Path(filename).stem)
    
    # Build Command
    # Use simple run_agent approach for now to ensure non-blocking
    run_script = AGENTS_DIR / agent_name / "bin" / "run_agent.py" # assuming .py runner
    cmd = [sys.executable, str(run_script), str(orders_work)]
    
    agent_log = LOGS_DIR / f"agent_{int(time.time())}_{Path(filename).stem}.log"
    
    try:
        with open(agent_log, 'w', encoding='utf-8') as log_f:
            flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
            proc = subprocess.Popen(cmd, cwd=str(CSC_ROOT), stdout=log_f, stderr=subprocess.STDOUT, creationflags=flags)
            
            task = {
                "agent": agent_name,
                "workorder": filename,
                "pid": proc.pid,
                "log": str(agent_log),
                "clone": str(clone_path) if clone_path else None,
                "started": int(time.time())
            }
            save_active_tasks([task])
            write_agent_data(agent_name, proc.pid, filename, agent_log)
            log(f"Spawned agent PID {proc.pid}")
            return True
    except Exception as e:
        log(f"Failed to spawn: {e}", "ERROR")
        return False

def run_cycle(work_dir_arg=None):
    _initialize_paths(work_dir_arg)
    git_pull()
    
    busy = monitor_active_tasks()
    if not busy:
        process_inbox()
    
    return True

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [queue-worker] [{level}] {msg}"
    print(line, file=sys.stderr)
    if QUEUE_LOG:
        with open(QUEUE_LOG, 'a', encoding='utf-8') as f: f.write(line + '\n')

def main():
<<<<<<< HEAD
    if "--daemon" in sys.argv:
        _initialize_paths()
        log("Daemon mode started")
        while True:
            run_cycle()
            time.sleep(60)
=======
    _initialize_paths()
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
>>>>>>> 48e68d09763f0faba18d64b20069444bb0d5a1c8
    else:
        run_cycle()

if __name__ == "__main__":
    main()
