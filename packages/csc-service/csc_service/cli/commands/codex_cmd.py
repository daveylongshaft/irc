"""Codex Cloud commands: submit, status, list, apply, diff.

Cross-platform CLI for managing OpenAI Codex Cloud tasks.
Uses the codex CLI (installed via npm install -g @openai/codex).
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _find_codex_bin():
    """Find the codex CLI binary path (cross-platform)."""
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


def _run_codex(args, timeout=60, cwd=None):
    """Run codex CLI command, return (stdout, stderr, returncode)."""
    cmd = _find_codex_bin() + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            shell=(sys.platform == "win32"),
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except FileNotFoundError:
        return "", "codex CLI not found. Install with: npm install -g @openai/codex", 127
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 1
    except Exception as e:
        return "", str(e), 1


def _get_csc_root():
    """Find CSC project root."""
    root = os.environ.get("CSC_ROOT", "")
    if root:
        return Path(root)
    p = Path(__file__).resolve()
    for _ in range(10):
        if (p / "csc-service.json").exists() or (p / "etc" / "csc-service.json").exists():
            return p
        if p == p.parent:
            break
        p = p.parent
    return Path.cwd()


def _get_codex_env(config_manager):
    """Get the Codex environment label from config."""
    config = config_manager.get()
    return config.get("codex", {}).get("environment", "csc")


def _get_tracking():
    """Load codex task tracking file."""
    root = _get_csc_root()
    tracking_file = root / "tmp" / "codex_tasks.json"
    if tracking_file.exists():
        try:
            return json.loads(tracking_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass
    return {"tasks": {}}


def _save_tracking(data):
    """Save codex task tracking file."""
    root = _get_csc_root()
    tracking_file = root / "tmp" / "codex_tasks.json"
    tracking_file.parent.mkdir(parents=True, exist_ok=True)
    tracking_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def codex_submit(args, config_manager):
    """Submit a workorder to Codex Cloud."""
    root = _get_csc_root()
    env_label = _get_codex_env(config_manager)
    prompt = args.prompt

    # If prompt looks like a workorder filename, read it
    wo_path = root / "ops" / "wo" / "ready" / prompt
    if wo_path.exists():
        content = wo_path.read_text(encoding="utf-8", errors="replace")
        prompt = f"Complete the task described below:\n\n{content}"
        print(f"Read workorder: {wo_path.name}")
    elif (root / "ops" / "wo" / "wip" / prompt).exists():
        wo_path = root / "ops" / "wo" / "wip" / prompt
        content = wo_path.read_text(encoding="utf-8", errors="replace")
        prompt = f"Complete the task described below:\n\n{content}"
        print(f"Read workorder: {wo_path.name}")

    # Submit to Codex Cloud
    print(f"Submitting to Codex Cloud (env: {env_label})...")
    stdout, stderr, rc = _run_codex(
        ["cloud", "exec", "--env", env_label, prompt],
        timeout=120,
        cwd=str(root),
    )

    if rc != 0:
        # Fallback for long prompts
        if "too long" in stderr.lower() or rc == 206:
            short = f"Complete the task in ops/wo/ready/{args.prompt}" if wo_path.exists() else args.prompt[:500]
            stdout, stderr, rc = _run_codex(
                ["cloud", "exec", "--env", env_label, short],
                timeout=120,
                cwd=str(root),
            )

    if rc != 0:
        print(f"Error: {stderr}")
        return

    print(stdout)

    # Track task if we got an ID
    import re
    match = re.search(r'(task_e_[a-f0-9]+)', stdout)
    if match and wo_path.exists():
        task_id = match.group(1)
        tracking = _get_tracking()
        tracking["tasks"][task_id] = {
            "workorder": wo_path.name,
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "submitted",
        }
        _save_tracking(tracking)
        print(f"Tracked: {wo_path.name} -> {task_id}")


def codex_status(args, config_manager):
    """Show status of Codex Cloud tasks (tracked ones)."""
    tracking = _get_tracking()

    if not tracking["tasks"]:
        print("No tracked Codex tasks.")
        return

    # Refresh from cloud
    root = _get_csc_root()
    stdout, stderr, rc = _run_codex(["cloud", "list", "--json"], timeout=30, cwd=str(root))

    cloud_status = {}
    if rc == 0:
        try:
            data = json.loads(stdout)
            for t in data.get("tasks", []):
                cloud_status[t["id"]] = t
        except json.JSONDecodeError:
            pass

    print(f"{'Task ID':<20s} {'Status':<12s} {'Workorder':<40s} {'Submitted'}")
    print("-" * 90)

    for task_id, info in sorted(tracking["tasks"].items(), key=lambda x: x[1].get("submitted_at", "")):
        status = info.get("status", "unknown")
        # Update from cloud if available
        if task_id in cloud_status:
            cloud_st = cloud_status[task_id].get("status", "")
            if cloud_st and cloud_st != status:
                status = cloud_st
                info["status"] = cloud_st

        wo = info.get("workorder", "")
        submitted = info.get("submitted_at", "")
        short_id = task_id[-16:]
        print(f"...{short_id:<17s} {status:<12s} {wo:<40s} {submitted}")

    _save_tracking(tracking)


def codex_list(args, config_manager):
    """List all Codex Cloud tasks (from cloud API)."""
    root = _get_csc_root()
    stdout, stderr, rc = _run_codex(["cloud", "list", "--json"], timeout=30, cwd=str(root))

    if rc != 0:
        print(f"Error: {stderr}")
        return

    try:
        data = json.loads(stdout)
        tasks = data.get("tasks", [])
    except json.JSONDecodeError:
        print(f"Failed to parse output")
        return

    if not tasks:
        print("No Codex Cloud tasks found.")
        return

    limit = args.limit if hasattr(args, "limit") and args.limit else 10
    print(f"{'Status':<12s} {'Title':<50s} {'Files':<6s} {'ID'}")
    print("-" * 90)

    for task in tasks[:limit]:
        status = task.get("status", "?")
        title = (task.get("title") or "")[:48]
        summary = task.get("summary", {})
        files = str(summary.get("files_changed", "")) if summary else ""
        task_id = task.get("id", "")[-16:]
        print(f"{status:<12s} {title:<50s} {files:<6s} ...{task_id}")


def codex_apply(args, config_manager):
    """Apply diffs from a completed Codex Cloud task."""
    root = _get_csc_root()
    task_id = args.task_id

    # Resolve short ID to full ID
    if not task_id.startswith("task_e_"):
        tracking = _get_tracking()
        for tid in tracking["tasks"]:
            if tid.endswith(task_id):
                task_id = tid
                break

    print(f"Applying diffs from {task_id}...")
    stdout, stderr, rc = _run_codex(["cloud", "apply", task_id], timeout=120, cwd=str(root))

    if rc != 0:
        print(f"Error: {stderr}")
        return

    print(stdout or "Diffs applied successfully.")

    # Update tracking
    tracking = _get_tracking()
    if task_id in tracking["tasks"]:
        tracking["tasks"][task_id]["status"] = "applied"
        tracking["tasks"][task_id]["applied_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _save_tracking(tracking)


def codex_diff(args, config_manager):
    """Show the diff for a Codex Cloud task."""
    root = _get_csc_root()
    task_id = args.task_id

    # Resolve short ID
    if not task_id.startswith("task_e_"):
        tracking = _get_tracking()
        for tid in tracking["tasks"]:
            if tid.endswith(task_id):
                task_id = tid
                break

    stdout, stderr, rc = _run_codex(["cloud", "diff", task_id], timeout=60, cwd=str(root))

    if rc != 0:
        print(f"Error: {stderr}")
        return

    print(stdout)


def codex_login(args, config_manager):
    """Check Codex login status or trigger login."""
    stdout, stderr, rc = _run_codex(["login", "status"], timeout=15)

    if rc == 0:
        print(f"Codex auth: {stdout}")
    else:
        print("Not logged in. Run: npx codex login")
        print(f"  {stderr}")
