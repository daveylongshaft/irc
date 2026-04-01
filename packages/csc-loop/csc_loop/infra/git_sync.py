"""Git sync: pull before cycle, push after changes."""
import subprocess
import time
from pathlib import Path

WORK_DIR = None

def setup(work_dir: Path):
    global WORK_DIR
    WORK_DIR = work_dir

def _git(*args):
    """Run a git command in WORK_DIR. Returns (ok, output)."""
    try:
        r = subprocess.run(
            ["git"] + list(args),
            cwd=str(WORK_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)

def pull():
    """Pull latest changes. Returns True on success."""
    ok, out = _git("pull", "--rebase", "--autostash")
    if not ok:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [git-sync] pull failed: {out}")
    return ok

def push_if_changed():
    """Stage workorders + logs, commit and push if there are changes."""
    _git("add", "wo/")
    _git("add", "wo/")
    _git("add", "tests/logs/")

    ok, staged = _git("diff", "--cached", "--name-only")
    if not ok or not staged.strip():
        return False

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _git("commit", "-m", f"csc-service: auto-sync {time.strftime('%Y%m%d-%H%M%S')}")

    ok, out = _git("push")
    if ok:
        print(f"[{ts}] [git-sync] pushed changes")
    else:
        print(f"[{ts}] [git-sync] push failed: {out}")
    return ok
