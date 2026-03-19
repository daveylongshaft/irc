"""Git state sync: track HEAD, detect new code, trigger reload on changes."""
import json
import subprocess
import time
from pathlib import Path

_head_before_pull = None
_reload_needed = False
_work_dir = None
_cycle_count = 0
_check_remote_every_n_cycles = 10  # Check remote HEAD every 10 cycles without pulling
_marker_file = None

def _git(*args):
    """Run a git command. Returns (ok, output)."""
    if _work_dir is None:
        return False, "work_dir not set"
    try:
        r = subprocess.run(
            ["git"] + list(args),
            cwd=str(_work_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)

def setup(work_dir):
    """Initialize the module with the work directory."""
    global _work_dir, _marker_file
    _work_dir = Path(work_dir)
    _marker_file = _work_dir / "ops" / "git_state.json"

def _get_local_head() -> str:
    """Get current local HEAD commit hash."""
    ok, output = _git("rev-parse", "HEAD")
    return output.strip() if ok else None

def _get_marker_commit() -> str:
    """Read marker file and return the irc_commit hash it specifies."""
    if not _marker_file or not _marker_file.exists():
        return None
    try:
        data = json.loads(_marker_file.read_text(encoding='utf-8'))
        return data.get("irc_commit", "").strip() or None
    except Exception:
        return None

def record_head_before_pull(work_dir):
    """Record the current HEAD commit hash just before pulling."""
    global _head_before_pull
    _head_before_pull = _get_local_head()

def check_marker_and_pull(work_dir) -> bool:
    """
    Check if marker file specifies a different HEAD than local.
    If marker is ahead, pull from git.
    Returns True if pull was performed and HEAD changed.

    This is the main sync mechanism: FTP syncs the marker file frequently,
    and this function keeps local repo in sync with the marker by pulling only when needed.
    """
    global _reload_needed

    local_head = _get_local_head()
    marker_commit = _get_marker_commit()

    if not local_head or not marker_commit:
        return False

    if local_head == marker_commit:
        # Local HEAD already matches marker, no pull needed
        return False

    # Marker differs from local HEAD - pull to sync
    # (e.g., FTP just synced a new marker from another server)
    if _perform_pull(work_dir):
        # Check if pull actually changed anything
        new_head = _get_local_head()
        if new_head and new_head != local_head:
            _reload_needed = True
            return True

    return False

def _perform_pull(work_dir) -> bool:
    """Perform git pull and return success."""
    ok, out = _git("pull", "--rebase", "--autostash")
    if not ok:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [git-sync] pull failed: {out}")
    return ok

def check_for_new_code(work_dir) -> bool:
    """
    Check if HEAD has changed since record_head_before_pull() was called.
    This is called after check_marker_and_pull() performed a pull.
    Returns True if HEAD changed, sets _reload_needed flag.
    """
    global _reload_needed
    if _head_before_pull is None:
        return False

    current_head = _get_local_head()
    if not current_head:
        return False

    if current_head != _head_before_pull:
        _reload_needed = True
        return True

    return False

def check_remote_head(work_dir) -> bool:
    """
    Periodically check remote HEAD without pulling to detect changes early.
    Updates marker if remote HEAD differs from local HEAD.
    This keeps the marker current even if no pull has happened yet.

    Returns True if remote HEAD differs from local HEAD.
    """
    global _cycle_count
    _cycle_count += 1

    # Only check periodically to avoid hammering git too often
    if _cycle_count % _check_remote_every_n_cycles != 0:
        return False

    # Get current local HEAD
    ok_local, local_head = _git("rev-parse", "HEAD")
    if not ok_local:
        return False
    local_head = local_head.strip()

    # Get remote HEAD (origin/main or origin/current-branch)
    ok_branch, branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if not ok_branch:
        return False
    branch = branch.strip()

    ok_remote, remote_head = _git("rev-parse", f"origin/{branch}")
    if not ok_remote:
        return False
    remote_head = remote_head.strip()

    # If remote HEAD differs from local, update the marker
    if remote_head != local_head:
        update_marker(work_dir, "remote-ahead")
        return True

    return False

def update_marker(work_dir, server_id):
    """
    Write ops/git_state.json with current commit and branch info.
    Called after a successful push to advertise the new code version.
    """
    ok_commit, commit = _git("rev-parse", "HEAD")
    ok_branch, branch = _git("rev-parse", "--abbrev-ref", "HEAD")

    if not ok_commit:
        commit = "unknown"
    else:
        commit = commit.strip()

    if not ok_branch:
        branch = "unknown"
    else:
        branch = branch.strip()

    marker_path = Path(work_dir) / "ops" / "git_state.json"
    marker_path.parent.mkdir(parents=True, exist_ok=True)

    marker_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_by": server_id,
        "irc_commit": commit,
        "irc_branch": branch,
    }

    try:
        marker_path.write_text(json.dumps(marker_data, indent=2), encoding='utf-8')
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [git-state] Updated marker -> {commit}")
    except Exception as e:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [git-state] Failed to update marker: {e}")

def is_reload_needed() -> bool:
    """Check if reload is needed (new code was pulled)."""
    return _reload_needed

def clear_reload_flag():
    """Clear the reload needed flag after taking action."""
    global _reload_needed
    _reload_needed = False
