"""Codex Monitor — submit workorders to OpenAI Codex Cloud and track results.

Uses the Codex CLI (`codex cloud exec --env csc`) to submit coding tasks,
polls `codex cloud list --json` to track progress, and applies completed diffs.

Integration: called from main.py daemon loop alongside queue-worker,
test-runner, pm, jules-monitor, and pr-review.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Module-level state
_csc_root = None
_wo_dir = None
_agents_dir = None
_tracking_file = None
_codex_env = "csc"


def _log(msg, level="INFO"):
    """Print timestamped log message."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [codex-monitor] [{level}] {msg}")


def _runtime(msg):
    """Write to runtime.log for #runtime IRC feed."""
    if not _csc_root:
        return
    try:
        ts = time.strftime("%H:%M:%S")
        log_dir = _csc_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "runtime.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [codex] {msg}\n")
    except Exception:
        pass


def setup(csc_root=None):
    """Initialize module paths."""
    global _csc_root, _wo_dir, _agents_dir, _tracking_file, _codex_env

    if csc_root:
        _csc_root = Path(csc_root)
    elif os.environ.get("CSC_ROOT"):
        _csc_root = Path(os.environ["CSC_ROOT"])
    else:
        _csc_root = Path(__file__).resolve().parents[4]

    _wo_dir = _csc_root / "ops" / "wo"
    _agents_dir = _csc_root / "ops" / "agents"
    _tracking_file = _csc_root / "tmp" / "codex_tasks.json"

    # Load env label from config
    for cfg_path in [_csc_root / "csc-service.json", _csc_root / "etc" / "csc-service.json"]:
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                _codex_env = cfg.get("codex", {}).get("environment", "csc")
            except Exception:
                pass
            break


def _load_tracking():
    """Load task tracking data from disk."""
    if _tracking_file and _tracking_file.exists():
        try:
            return json.loads(_tracking_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass
    return {"tasks": {}}


def _save_tracking(data):
    """Save task tracking data to disk."""
    _tracking_file.parent.mkdir(parents=True, exist_ok=True)
    _tracking_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _find_codex_bin():
    """Find the codex CLI binary path."""
    codex_path = shutil.which("codex")
    if codex_path:
        return [codex_path]

    if sys.platform == "win32":
        npm_prefix = os.environ.get("APPDATA", "")
        if npm_prefix:
            cmd_path = Path(npm_prefix) / "npm" / "codex.cmd"
            if cmd_path.exists():
                return [str(cmd_path)]

    npx_path = shutil.which("npx")
    if npx_path:
        return [npx_path, "codex"]

    return ["codex"]


def _run_codex_cmd(args, timeout=60):
    """Run a codex CLI command, return (stdout, stderr, returncode)."""
    cmd = _find_codex_bin() + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_csc_root),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            shell=(sys.platform == "win32"),
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        _log(f"Codex command timed out: {' '.join(args)}", "WARN")
        return "", "", 1
    except Exception as e:
        _log(f"Codex command failed: {e}", "ERROR")
        return "", str(e), 1


def submit_workorder(workorder_filename):
    """Submit a workorder to Codex Cloud.

    Reads the workorder from wip/, builds a prompt, submits via
    `codex cloud exec --env csc`, and tracks the task ID.

    Returns:
        Task ID string if submitted, None on failure.
    """
    wip_path = _wo_dir / "wip" / workorder_filename
    if not wip_path.exists():
        _log(f"Workorder not found: {wip_path}", "ERROR")
        return None

    content = wip_path.read_text(encoding="utf-8", errors="replace")

    # Build a concise prompt (Codex has its own context from the repo)
    prompt = (
        f"Task: {workorder_filename}\n\n"
        f"{content}\n\n"
        f"Rules: one class per file (snake_case names), write tests, "
        f"do NOT run tests, use Platform for paths, ASCII only in .md files."
    )

    _log(f"Submitting to Codex Cloud: {workorder_filename}")

    # Write prompt to temp file to avoid command-line length limits
    prompt_file = _csc_root / "tmp" / f"codex_prompt_{int(time.time())}.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt, encoding="utf-8")

    # Use codex cloud exec --env <label> "$(cat prompt_file)"
    # On Windows, read the file content and pass as arg
    stdout, stderr, rc = _run_codex_cmd(
        ["cloud", "exec", "--env", _codex_env, prompt],
        timeout=120,
    )

    # Clean up temp file
    try:
        prompt_file.unlink()
    except Exception:
        pass

    if rc != 0:
        # Check if it's a command-line-too-long error
        if "too long" in stderr.lower() or rc == 206:
            _log("Prompt too long for CLI arg, using shorter prompt", "WARN")
            short_prompt = f"Complete the task described in ops/wo/wip/{workorder_filename}"
            stdout, stderr, rc = _run_codex_cmd(
                ["cloud", "exec", "--env", _codex_env, short_prompt],
                timeout=120,
            )

    if rc != 0:
        _log(f"Codex cloud exec failed (rc={rc}): {stderr[:300]}", "ERROR")
        return None

    # Parse task ID from output (URL or JSON)
    task_id = _parse_task_id(stdout)
    if not task_id:
        _log(f"Could not parse task ID from: {stdout[:200]}", "ERROR")
        return None

    # Track the task
    tracking = _load_tracking()
    tracking["tasks"][task_id] = {
        "workorder": workorder_filename,
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "submitted",
    }
    _save_tracking(tracking)

    _log(f"Submitted: {workorder_filename} -> {task_id}")
    return task_id


def _parse_task_id(output):
    """Extract task ID from codex cloud exec output."""
    # Output is typically a URL like:
    # https://chatgpt.com/codex/tasks/task_e_69b637c96ec48327867b04bd3617c3aa

    # Try URL pattern first
    match = re.search(r'(task_e_[a-f0-9]+)', output)
    if match:
        return match.group(1)

    # Try JSON parsing
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                tid = data.get("id") or data.get("task_id") or data.get("taskId")
                if tid:
                    return tid
        except json.JSONDecodeError:
            continue

    return None


def poll_tasks():
    """Poll Codex Cloud for task status updates.

    Returns:
        List of (task_id, workorder_filename, new_status) tuples for changed tasks.
    """
    stdout, stderr, rc = _run_codex_cmd(["cloud", "list", "--json"], timeout=30)
    if rc != 0:
        _log(f"Codex cloud list failed (rc={rc}): {stderr[:200]}", "WARN")
        return []

    try:
        data = json.loads(stdout)
        cloud_tasks = data.get("tasks", [])
    except json.JSONDecodeError:
        _log("Failed to parse cloud list output", "WARN")
        return []

    tracking = _load_tracking()
    changes = []

    for task in cloud_tasks:
        task_id = task.get("id", "")
        cloud_status = task.get("status", "")

        if task_id not in tracking["tasks"]:
            continue

        tracked = tracking["tasks"][task_id]
        old_status = tracked.get("status", "")

        if cloud_status != old_status:
            tracked["status"] = cloud_status
            tracked["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")

            if task.get("summary"):
                tracked["summary"] = task["summary"]

            changes.append((task_id, tracked["workorder"], cloud_status))
            _log(f"Task {task_id}: {old_status} -> {cloud_status} ({tracked['workorder']})")
            _runtime(f"task {task_id[-12:]}: {old_status} -> {cloud_status}")

    if changes:
        _save_tracking(tracking)

    return changes


def _git_run(args, cwd=None):
    """Run a git command, return (stdout, stderr, returncode)."""
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=cwd or str(_csc_root),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        _log(f"Git command failed: {' '.join(args)}: {e}", "ERROR")
        return "", str(e), 1


def _commit_and_push(workorder_filename, task_id):
    """Commit applied diffs and push to origin.

    Commits submodules (irc/, ops/) first if they have changes,
    then commits the CSC_ROOT repo and pushes.

    Returns:
        True if committed and pushed successfully.
    """
    short_id = task_id[-12:] if len(task_id) > 12 else task_id
    commit_msg = f"feat: {workorder_filename} (codex {short_id})"

    # Commit submodules first (irc/ and ops/) if they have changes
    for submod in ["irc", "ops"]:
        submod_path = _csc_root / submod
        if not (submod_path / ".git").exists():
            continue

        stdout, _, rc = _git_run(["status", "--porcelain"], cwd=str(submod_path))
        if rc != 0 or not stdout:
            continue

        _log(f"Committing changes in {submod}/ submodule")
        _git_run(["add", "-A"], cwd=str(submod_path))
        _, stderr, rc = _git_run(["commit", "-m", commit_msg], cwd=str(submod_path))
        if rc != 0:
            _log(f"Submodule {submod} commit failed: {stderr[:200]}", "WARN")
            continue

        _, stderr, rc = _git_run(["push"], cwd=str(submod_path))
        if rc != 0:
            _log(f"Submodule {submod} push failed: {stderr[:200]}", "WARN")

    # Commit the main CSC_ROOT repo
    stdout, _, rc = _git_run(["status", "--porcelain"])
    if rc != 0 or not stdout:
        _log("No changes to commit in CSC_ROOT after apply")
        return True  # Not an error — apply may have been a no-op

    _log(f"Committing changes in CSC_ROOT: {commit_msg}")
    _git_run(["add", "-A"])
    _, stderr, rc = _git_run(["commit", "-m", commit_msg])
    if rc != 0:
        _log(f"CSC_ROOT commit failed: {stderr[:200]}", "ERROR")
        return False

    _, stderr, rc = _git_run(["push"])
    if rc != 0:
        _log(f"CSC_ROOT push failed: {stderr[:200]}", "ERROR")
        return False

    _log("Committed and pushed successfully")
    _runtime(f"{workorder_filename} COMPLETE. committed & pushed")
    return True


def handle_completed_task(task_id):
    """Handle a completed Codex task — apply diffs, commit, push, move WO to done."""
    tracking = _load_tracking()
    if task_id not in tracking["tasks"]:
        return False

    tracked = tracking["tasks"][task_id]
    workorder_filename = tracked["workorder"]

    _log(f"Applying diffs for task {task_id} ({workorder_filename})")
    stdout, stderr, rc = _run_codex_cmd(["cloud", "apply", task_id], timeout=120)

    if rc != 0:
        _log(f"Failed to apply diffs for {task_id}: {stderr[:200]}", "ERROR")
        _runtime(f"FAILED to apply {workorder_filename}")
        tracked["status"] = "apply_failed"
        _save_tracking(tracking)
        return False

    _log(f"Applied diffs for {workorder_filename}")

    # Commit and push the applied changes
    push_ok = _commit_and_push(workorder_filename, task_id)
    if not push_ok:
        _log(f"Commit/push failed for {workorder_filename}, leaving in wip/", "WARN")
        _runtime(f"FAILED to apply {workorder_filename}")
        tracked["status"] = "apply_failed"
        _save_tracking(tracking)
        return False

    # Annotate and move WO to done
    wip_path = _wo_dir / "wip" / workorder_filename
    if wip_path.exists():
        with open(wip_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n[codex] Applied task {task_id} at {time.strftime('%Y-%m-%dT%H:%M:%S')}\nCOMPLETE\n")

        done_dir = _wo_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(wip_path), str(done_dir / workorder_filename))
        _log(f"Moved {workorder_filename} to done/")

    tracked["status"] = "applied"
    tracked["applied_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_tracking(tracking)
    return True


def handle_failed_task(task_id):
    """Handle a failed Codex task — move workorder back to ready."""
    tracking = _load_tracking()
    if task_id not in tracking["tasks"]:
        return

    tracked = tracking["tasks"][task_id]
    workorder_filename = tracked["workorder"]

    wip_path = _wo_dir / "wip" / workorder_filename
    if wip_path.exists():
        with open(wip_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n[codex] Task {task_id} failed at {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")

        ready_dir = _wo_dir / "ready"
        ready_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(wip_path), str(ready_dir / workorder_filename))
        _log(f"Moved {workorder_filename} back to ready/ (task failed)")

    tracked["status"] = "failed"
    _save_tracking(tracking)


def run_cycle(work_dir=None):
    """Entry point called by service main loop.

    Polls active Codex tasks for status changes and handles completions/failures.

    Returns:
        True if any work was done, False if idle.
    """
    setup(work_dir)

    tracking = _load_tracking()
    active_tasks = {
        tid: t for tid, t in tracking["tasks"].items()
        if t.get("status") not in ("applied", "failed", "apply_failed")
    }

    if not active_tasks:
        return False

    _log(f"Monitoring {len(active_tasks)} active Codex task(s)")

    changes = poll_tasks()
    had_work = False

    for task_id, workorder_filename, new_status in changes:
        had_work = True
        if new_status == "ready":
            handle_completed_task(task_id)
        elif new_status in ("failed", "error", "cancelled"):
            handle_failed_task(task_id)

    return had_work
