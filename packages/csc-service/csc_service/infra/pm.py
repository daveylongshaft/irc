"""Project Manager: rule-based workorder classification, assignment, and lifecycle.

The PM is NOT an AI agent — it's a deterministic decision engine that:
1. Checks if queue-worker is busy (one task at a time)
2. Scans workorders/ready/ for new work
3. Prioritises by urgency (P0 > P1 > P2 > P3)
4. Classifies by filename pattern
5. Picks cheapest capable agent (with human-override prefix support)
6. Assigns ONE workorder per cycle via agent_service
7. Tracks attempts and escalates on repeated failure
8. Recovers orphaned/stuck workorders
9. Creates fix-workorders for problems it can't self-heal

Driven by csc-service main loop or csc-ctl.
"""

import os
import signal
import shutil
import subprocess
import time
from pathlib import Path
from datetime import datetime
from csc_service.shared.service import Service
try:
    from csc_service.shared.services.stats_service.stats_service import StatsService
except (ImportError, ModuleNotFoundError):
    StatsService = None  # sqlite3 not available on this build
try:
    from csc_service.clients.jules.jules import Jules
    from csc_service.clients.jules.config import JulesConfig
except (ImportError, ModuleNotFoundError):
    Jules = None
    JulesConfig = None

# ---------------------------------------------------------------------------
# Global paths (set by setup())
# ---------------------------------------------------------------------------
WORK_DIR = None
STATE_FILE = None  # kept for reference; actual storage goes through _svc
_svc: Service = None  # Service instance for Data/Log/Platform hierarchy
AGENTS_DIR = None
READY_DIR = None
WIP_DIR = None
DONE_DIR = None
jules: Jules = None


# ---------------------------------------------------------------------------
# Agent roster and assignment policy
# ---------------------------------------------------------------------------
AGENTS = [
    {"name": "gemini-2.5-flash", "role": "docs-and-tests",
     "good_for": ["docs", "test-fix", "validation"]},
    {"name": "gemini-2.5-pro", "role": "code",
     "good_for": ["feature", "refactor", "simple-fix", "complex-fix", "pr-review", "pr-reviewer", "audit"]},
    {"name": "sonnet", "role": "code",
     "good_for": ["feature", "refactor", "complex-fix", "architecture", "debug"]},
    {"name": "opus", "role": "debug",
     "good_for": ["debug", "push-fail"]},
]

# All agent names the PM is allowed to assign to
VALID_AGENTS = {a["name"] for a in AGENTS}

# Escalation path: current_agent -> next_agent
ESCALATION = {
    "gemini-2.5-flash": "gemini-2.5-pro",
    "gemini-2.5-pro": "sonnet",
    "sonnet": "opus",
    "opus": None,  # flag for human review
}

# Max attempts before flagging for human review
MAX_ATTEMPTS = 3

# How long (seconds) a WIP file can sit with no matching queue/work PID
# before we consider it orphaned and recover it
ORPHAN_TIMEOUT_SECS = 120  # 2 minutes


def _ts():
    return datetime.now().isoformat(timespec='seconds')


def _log(msg, level="INFO"):
    line = f"[{_ts()}] [pm] [{level}] {msg}"
    if _svc is not None:
        _svc.log(line)
    else:
        print(line)


# ======================================================================
# Setup
# ======================================================================

def setup(work_dir: Path):
    global WORK_DIR, STATE_FILE, AGENTS_DIR, READY_DIR, WIP_DIR, DONE_DIR, _svc
    from csc_service.shared.platform import Platform
    WORK_DIR = Path(work_dir)
    _svc = Service(None)
    _svc.name = "pm"
    _svc.init_data()
    STATE_FILE = Platform().run_dir / "pm_state.json"  # kept for reference
    # ops/agents/ is where agent configs live; fall back to agents/ for compat
    _agents_candidate = WORK_DIR / "ops" / "agents"
    AGENTS_DIR = _agents_candidate if _agents_candidate.exists() else WORK_DIR / "agents"
    # Resolve workorder base: ops/wo/ under WORK_DIR, then check parent (submodule layout)
    def _resolve_wo_base():
        for candidate in [
            WORK_DIR / "ops" / "wo",
            WORK_DIR / "wo",
            WORK_DIR / "workorders",
            WORK_DIR.parent / "ops" / "wo",  # parent when work_dir is irc submodule
        ]:
            if candidate.exists():
                return candidate
        return WORK_DIR / "ops" / "wo"  # will be created on first use
    _base = _resolve_wo_base()
    READY_DIR = _base / "ready"
    WIP_DIR   = _base / "wip"
    DONE_DIR  = _base / "done"

    global jules
    if Jules and JulesConfig:
        jules_config = JulesConfig()
        if jules_config.enabled:
            jules = Jules()



# ======================================================================
# State persistence
# ======================================================================

def _load_state() -> dict:
    """Load PM state from disk.

    Schema:
    {
        "assignments": {
            "filename.md": {
                "agent": "gemini-3-pro",
                "category": "feature",
                "priority": "P2",
                "status": "assigned" | "completed" | "failed" | "escalated" | "human-review",
                "attempts": 1,
                "attempt_history": [{"agent": "...", "ts": "...", "result": "..."}],
                "timestamp": "..."
            }
        }
    }
    """
    if _svc is None:
        return {"assignments": {}}
    saved = _svc.get_data("state")
    return saved if isinstance(saved, dict) else {"assignments": {}}


def _save_state(state: dict):
    if _svc is not None:
        _svc.put_data("state", state)


# ======================================================================
# Classification
# ======================================================================

VALID_CATEGORIES = {"push-fail", "test-fix", "simple-fix", "docs", "audit",
                    "debug", "refactor", "feature", "pr-reviewer"}


def classify(filename: str) -> str:
    """Classify workorder. Front-matter 'role:' wins; filename patterns are fallback."""
    # Front-matter role: field (optional)
    role = _read_frontmatter(filename).get('role', '')
    if role in VALID_CATEGORIES:
        return role

    fn = filename.lower()
    if "push-fail" in fn or "push_fail" in fn:
        return "push-fail"
    if "fix_test_" in fn or "run_test_" in fn:
        return "test-fix"
    if "fix_" in fn:
        return "simple-fix"
    if "docs_" in fn or "docstring" in fn or "document_" in fn:
        return "docs"
    if "audit" in fn or "review" in fn or "validate" in fn:
        return "audit"
    if "debug" in fn or "investigate" in fn:
        return "debug"
    if "refactor" in fn or "rename" in fn or "migrate" in fn:
        return "refactor"
    return "feature"


VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}


def prioritize(filename: str) -> str:
    """Assign priority tier based on filename pattern.

    P0 - blocks everything (test fixes, urgent, security, push failures)
    P1 - force multipliers (infra, PM, queue-worker, agent tooling)
    P2 - features, bug fixes
    P3 - documentation
    """
    # Front-matter priority: field wins (optional)
    fm_priority = _read_frontmatter(filename).get('priority', '').upper()
    if fm_priority in VALID_PRIORITIES:
        return fm_priority

    fn = filename.lower()
    # P0: urgent, test fixes, security, push failures
    if "push-fail" in fn or "push_fail" in fn:
        return "P0"
    if "urgent" in fn:
        return "P0"
    if "fix_test_" in fn or "run_test_" in fn:
        return "P0"
    if "fix_" in fn:
        return "P0"
    if "security" in fn:
        return "P0"
    # P1: infrastructure and force multipliers
    if any(kw in fn for kw in ["queue_worker", "queue-worker", "test_runner",
                                "test-runner", "pm_", "agent_service",
                                "infrastructure", "csc_service", "csc-service",
                                "csc_ctl", "csc-ctl"]):
        return "P1"
    # P3: documentation
    if "docs_" in fn or "docstring" in fn or "document_" in fn:
        return "P3"
    # P2: everything else (features, refactors, etc.)
    return "P2"


PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


# ======================================================================
# Agent selection
# ======================================================================

def detect_agent_prefix(filename: str):
    """Check if filename starts with an agent name (human override).

    Examples: haiku-foo.md -> "haiku", opus_bar.md -> "opus"
    """
    fn = filename.lower()
    for agent_name in sorted(VALID_AGENTS, key=len, reverse=True):
        # Check both dash and underscore separators
        if fn.startswith(agent_name + "-") or fn.startswith(agent_name + "_"):
            return agent_name
    return None


def _read_frontmatter(filename: str) -> dict:
    """Parse YAML front-matter from a workorder. Returns dict of key→value (strings).
    Returns {} if no front-matter or file not found. Front-matter is always optional."""
    for search_dir in [READY_DIR, WIP_DIR]:
        if not search_dir:
            continue
        path = search_dir / filename
        if path.exists():
            try:
                text = path.read_text(encoding='utf-8', errors='replace')
                if text.startswith('---'):
                    end = text.find('---', 3)
                    if end > 0:
                        result = {}
                        for line in text[3:end].splitlines():
                            if ':' in line:
                                k, _, v = line.partition(':')
                                result[k.strip().lower()] = v.strip()
                        return result
            except Exception:
                pass
    return {}


def _read_frontmatter_agent(filename: str) -> str:
    """Read the 'agent:' field from front-matter. Returns '' if absent."""
    val = _read_frontmatter(filename).get('agent', '').lower()
    return val if val in VALID_AGENTS else ""


def pick_agent(category: str, filename: str = "", state_entry: dict = None) -> str:
    """Pick agent, respecting: front-matter > filename prefix > escalation > policy default.

    Args:
        category: workorder classification
        filename: original filename (for prefix detection)
        state_entry: existing state entry (for escalation tracking)
    """
    # 1. Front-matter agent: field (explicit workorder assignment)
    fm_agent = _read_frontmatter_agent(filename)
    if fm_agent:
        return fm_agent

    # 2. Human override via filename prefix
    override = detect_agent_prefix(filename)
    if override and override in VALID_AGENTS:
        return override

    # 2. Check if we need to escalate from a previous failure
    if state_entry:
        attempts = state_entry.get("attempts", 0)
        last_agent = state_entry.get("agent", "")
        if attempts >= 2 and last_agent in ESCALATION:
            escalated = ESCALATION[last_agent]
            if escalated:
                _log(f"Escalating {filename}: {last_agent} -> {escalated} (attempt {attempts + 1})")
                return escalated
            else:
                # No further escalation possible
                return last_agent

    # 3. Default policy
    for agent in AGENTS:
        if category in agent["good_for"]:
            return agent["name"]
    return "gemini-2.5-pro"


# ======================================================================
# Busy detection — respect one-at-a-time constraint
# ======================================================================

def _pid_alive(pid: int) -> bool:
    """Check if a process is still running."""
    if os.name == "nt":
        try:
            import subprocess
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


def _clean_stale_queue_entry(queue_dir: Path, label: str):
    """Remove all files from a queue directory (stale cleanup)."""
    for f in list(queue_dir.iterdir()):
        try:
            f.unlink()
            _log(f"Cleaned stale {label}: {f.name}")
        except Exception as e:
            _log(f"Failed to clean {f.name}: {e}", "WARN")


def is_queue_busy() -> bool:
    """Check if any agent currently has work in progress.

    Also cleans up stale state:
    - PID files where the process is dead -> clean queue/work/
    - queue/in/ entries older than ORPHAN_TIMEOUT_SECS with no running agent -> clean
    """
    if not AGENTS_DIR or not AGENTS_DIR.exists():
        return False

    for agent_dir in AGENTS_DIR.iterdir():
        if not agent_dir.is_dir() or agent_dir.name == "templates":
            continue

        # --- Check queue/work/ for active PIDs ---
        work_dir = agent_dir / "queue" / "work"
        if work_dir.exists() and any(work_dir.iterdir()):
            pid_file = None
            pid_alive = False
            for f in work_dir.iterdir():
                if f.suffix == ".pid":
                    pid_file = f
                    try:
                        pid = int(f.read_text().strip())
                        pid_alive = _pid_alive(pid)
                    except Exception:
                        pid_alive = False

            if pid_file and pid_alive:
                return True  # Genuinely busy

            if pid_file and not pid_alive:
                # Agent crashed — clean up work dir
                _log(f"Agent {agent_dir.name} PID dead, cleaning queue/work/")
                _clean_stale_queue_entry(work_dir, f"{agent_dir.name}/queue/work")
                # Don't return busy — let recovery handle the WIP file
                continue

            # orders.md with no PID — check age
            orders = work_dir / "orders.md"
            if orders.exists():
                age = time.time() - orders.stat().st_mtime
                if age < ORPHAN_TIMEOUT_SECS:
                    return True  # Still within startup grace period
                _log(f"Stale orders.md in {agent_dir.name}/queue/work/ (age {int(age)}s), cleaning")
                _clean_stale_queue_entry(work_dir, f"{agent_dir.name}/queue/work")

        # --- Check queue/in/ for pending work ---
        in_dir = agent_dir / "queue" / "in"
        if in_dir.exists():
            md_files = [f for f in in_dir.iterdir() if f.suffix == ".md"]
            if md_files:
                # Check age of oldest .md — if too old, it's stale
                oldest_age = max(time.time() - f.stat().st_mtime for f in md_files)
                if oldest_age < ORPHAN_TIMEOUT_SECS:
                    return True  # Recently queued, queue-worker should pick it up

                # Stale queue/in/ — queue-worker never picked it up
                _log(f"Stale queue/in/ for {agent_dir.name} (age {int(oldest_age)}s), cleaning")
                _clean_stale_queue_entry(in_dir, f"{agent_dir.name}/queue/in")
                # Don't return busy — this entry was abandoned

    return False


# ======================================================================
# Recovery — detect and fix stuck states
# ======================================================================

def recover_orphaned_wip() -> list:
    """Find WIP files that have no matching queue entry and recover them.

    An orphaned WIP file is one where:
    - File exists in workorders/wip/
    - No matching entry in any agent's queue/in/ or queue/work/
    - PM state says it was assigned but there's no active process

    Recovery: move back to ready/ so it can be re-assigned.
    """
    if not WIP_DIR or not WIP_DIR.exists():
        return []

    recovered = []

    for wip_file in sorted(WIP_DIR.glob("*.md")):
        fname = wip_file.name

        # Check if this WIP file has a matching queue entry anywhere
        has_queue_entry = False
        if AGENTS_DIR and AGENTS_DIR.exists():
            for agent_dir in AGENTS_DIR.iterdir():
                if not agent_dir.is_dir() or agent_dir.name == "templates":
                    continue
                for subdir in ["in", "work"]:
                    queue_dir = agent_dir / "queue" / subdir
                    if queue_dir.exists():
                        # Check for orders.md (queue-worker renames to orders.md)
                        if (queue_dir / "orders.md").exists():
                            # Read orders.md to see if it references this WIP file
                            try:
                                content = (queue_dir / "orders.md").read_text(
                                    encoding="utf-8", errors="ignore")
                                if fname in content:
                                    has_queue_entry = True
                                    break
                            except Exception:
                                pass
                        # Check for direct filename match
                        if (queue_dir / fname).exists():
                            has_queue_entry = True
                            break
                if has_queue_entry:
                    break

        if has_queue_entry:
            continue  # Not orphaned, still being worked on

        # Check how old the WIP file is
        try:
            mtime = wip_file.stat().st_mtime
            age_secs = time.time() - mtime
        except Exception:
            age_secs = 0

        # Only recover if older than timeout (give agent time to start)
        if age_secs < ORPHAN_TIMEOUT_SECS:
            continue

        # This WIP file is orphaned — move back to ready
        ready_path = READY_DIR / fname
        try:
            if ready_path.exists():
                # Already exists in ready (shouldn't happen), skip
                _log(f"Orphan {fname} already in ready/, removing WIP copy", "WARN")
                wip_file.unlink()
            else:
                wip_file.rename(ready_path)
                _log(f"Recovered orphaned WIP: {fname} -> ready/ (age: {int(age_secs)}s)")
            recovered.append(fname)
        except Exception as e:
            _log(f"Failed to recover {fname}: {e}", "ERROR")

    return recovered


def cleanup_stale_state(state: dict) -> dict:
    """Remove state entries for workorders that no longer exist anywhere.

    Prevents pm_state.json from growing unboundedly and blocking
    re-assignment of workorders that were manually moved.
    """
    to_remove = []
    for fname, entry in state.get("assignments", {}).items():
        status = entry.get("status", "")
        # Keep completed/human-review entries as history
        if status in ("completed", "human-review"):
            continue
        # If the file doesn't exist in ready/, wip/, or done/, clear it
        exists_anywhere = (
            (READY_DIR and (READY_DIR / fname).exists()) or
            (WIP_DIR and (WIP_DIR / fname).exists()) or
            (DONE_DIR and (DONE_DIR / fname).exists())
        )
        if not exists_anywhere:
            to_remove.append(fname)

    for fname in to_remove:
        _log(f"Clearing stale state for {fname} (file no longer exists)")
        del state["assignments"][fname]

    return state


# ======================================================================
# Self-healing — create workorders for problems PM can't fix
# ======================================================================

def create_fix_workorder(title: str, description: str):
    """Create a workorder in ready/ for a problem the PM detected but can't fix.

    Uses a pm_fix_ prefix so it's recognizable.
    """
    if not READY_DIR:
        return
    READY_DIR.mkdir(parents=True, exist_ok=True)

    # Sanitize title for filename
    safe_title = title.lower().replace(" ", "_").replace("-", "_")
    safe_title = "".join(c for c in safe_title if c.isalnum() or c == "_")
    fname = f"pm_fix_{safe_title}.md"

    # Don't create duplicates
    if (READY_DIR / fname).exists():
        return

    content = f"# PM Auto-Generated Fix: {title}\n\n"
    content += f"**Generated**: {_ts()}\n"
    content += f"**Source**: PM self-healing detected a problem it cannot resolve.\n\n"
    content += f"## Problem\n\n{description}\n\n"
    content += "## Expected Resolution\n\nFix the issue described above and add COMPLETE as the last line.\n"

    try:
        (READY_DIR / fname).write_text(content, encoding="utf-8")
        _log(f"Created fix workorder: {fname}")
    except Exception as e:
        _log(f"Failed to create fix workorder: {e}", "ERROR")


# ======================================================================
# Completion tracking — called by queue-worker when a task finishes
# ======================================================================

def mark_completed(filename: str):
    """Mark a workorder as completed in PM state.

    Called externally (by queue-worker) when a workorder moves to done/.
    """
    state = _load_state()
    if filename in state["assignments"]:
        state["assignments"][filename]["status"] = "completed"
        state["assignments"][filename]["completed_at"] = _ts()
        _save_state(state)


def mark_failed(filename: str):
    """Record a failure for a workorder that bounced back to ready/.

    Increments attempt count. If max attempts exceeded, flags for human review
    or escalates to a stronger agent.
    """
    state = _load_state()
    entry = state["assignments"].get(filename, {})

    attempts = entry.get("attempts", 0) + 1
    entry["attempts"] = attempts

    # Record attempt history
    history = entry.get("attempt_history", [])
    history.append({
        "agent": entry.get("agent", "unknown"),
        "ts": _ts(),
        "result": "incomplete",
    })
    entry["attempt_history"] = history

    if attempts >= MAX_ATTEMPTS:
        # Check if we can escalate
        current_agent = entry.get("agent", "")
        escalated_to = ESCALATION.get(current_agent)
        if escalated_to:
            entry["status"] = "escalated"
            entry["agent"] = escalated_to
            _log(f"Escalating {filename}: {current_agent} -> {escalated_to} "
                 f"after {attempts} attempts")
        else:
            entry["status"] = "human-review"
            _log(f"Flagging {filename} for human review after {attempts} attempts "
                 f"(no further escalation from {current_agent})", "WARN")
    else:
        # Reset status so PM will re-assign on next cycle
        entry["status"] = "retry"

    state["assignments"][filename] = entry
    _save_state(state)


def _is_jules_task(workorder_path: str) -> bool:
    """Check if workorder is suitable for Jules."""
    try:
        content = Path(workorder_path).read_text(encoding='utf-8', errors='replace').lower()
        jules_keywords = [
            'bug', 'fix', 'refactor', 'test', 'documentation',
            'feature', 'implement', 'debug'
        ]
        return any(kw in content for kw in jules_keywords)
    except FileNotFoundError:
        return False

def jules_available() -> bool:
    """Check if Jules has capacity."""
    if not jules:
        return False

    active_sessions = jules.sessions
    return len(active_sessions) < jules.config.max_concurrent_sessions

def assign_to_jules(workorder_path: str):
    """Assign workorder to Jules."""
    if not jules:
        return

    repo_url = jules.config.github_repo
    if not repo_url:
        _log("Jules github_repo is not configured.", "ERROR")
        return

    try:
        session_id = jules.submit_workorder(workorder_path, repo_url)

        state = _load_state()
        state.setdefault('jules_assignments', {})[session_id] = {
            'workorder': workorder_path,
            'assigned_at': time.time(),
        }
        
        fname = Path(workorder_path).name
        state.setdefault('assignments', {})[fname] = {
            "agent": "jules",
            "status": "assigned",
            "timestamp": _ts(),
        }
        _save_state(state)

        # Move to wip
        wip_path = WIP_DIR / fname
        Path(workorder_path).rename(wip_path)

        _log(f"Assigned to Jules: {fname} (session: {session_id})", "INFO")
    except Exception as e:
        _log(f"Jules assignment failed: {e}", "ERROR")

def _monitor_jules_sessions():
    """Check on active Jules sessions, retrieve results."""
    if not jules:
        return

    state = _load_state()
    assignments = state.get('jules_assignments', {})
    sessions_to_remove = []

    for session_id, info in assignments.items():
        status = jules.check_status(session_id)

        if status.get('state') == 'completed':
            results = jules.get_results(session_id)
            pr_url = results.get('pr_url')
            if pr_url:
                _log(f"Jules completed {info['workorder']}: {pr_url}", "INFO")
                
                # Move workorder to done
                wip_path = WIP_DIR / Path(info['workorder']).name
                done_path = DONE_DIR / Path(info['workorder']).name
                wip_path.rename(done_path)
                
                mark_completed(Path(info['workorder']).name)

            sessions_to_remove.append(session_id)
        elif status.get('state') == 'failed':
            _log(f"Jules session failed: {session_id}", "ERROR")
            
            # Move workorder back to ready
            wip_path = WIP_DIR / Path(info['workorder']).name
            ready_path = READY_DIR / Path(info['workorder']).name
            wip_path.rename(ready_path)

            mark_failed(Path(info['workorder']).name)
            sessions_to_remove.append(session_id)

    for session_id in sessions_to_remove:
        del assignments[session_id]
        if session_id in jules.sessions:
            del jules.sessions[session_id]
            
    state['jules_assignments'] = assignments
    _save_state(state)


# ======================================================================
# Main cycle
# ======================================================================

def monitor_julius_plans() -> None:
    """Check pending Jules plans and forward approval decisions.

    Iterates over julius_sessions state entries whose state is
    'pending_approval'. For each, checks whether the plan-review agent has
    written a decision file. If APPROVE, calls julius.approve_plan_via_api();
    if DENY, records the denial reason and marks the session denied.

    Called from run_cycle() or directly by the service main loop.
    """
    if _svc is None:
        return

    try:
        from csc_service.clients.julius.julius import Julius
    except ImportError:
        _log("Julius client not available, skipping plan approval check", "WARN")
        return

    julius = Julius()

    active_sessions = _svc.get_data("julius_sessions") or {}
    if not active_sessions:
        return

    changed = False
    for session_id, info in list(active_sessions.items()):
        if info.get("state") != "pending_approval":
            continue

        decision = julius.check_plan_approval(session_id)
        if decision is None:
            continue  # Still pending review

        if decision.get("decision") == "APPROVE":
            _log(f"Plan approved: {session_id} — {decision.get('reason', '')}")
            # Attempt to tell Jules to proceed if API method exists
            if hasattr(julius, "approve_plan_via_api"):
                try:
                    julius.approve_plan_via_api(session_id)
                except Exception as e:
                    _log(f"approve_plan_via_api failed for {session_id}: {e}", "WARN")
            info["state"] = "executing"
        else:
            _log(
                f"Plan denied: {session_id} — {decision.get('reason', 'no reason')}",
                "WARN",
            )
            info["state"] = "denied"
            info["denial_reason"] = decision.get("reason", "")

        active_sessions[session_id] = info
        changed = True

    if changed:
        _svc.put_data("julius_sessions", active_sessions)


def run_cycle() -> list:
    """One PM cycle. Assigns at most ONE workorder.

    Steps:
    1. Recover orphaned WIP files
    2. Clean stale state entries
    3. Check if queue-worker is busy → if yes, wait (return empty)
    4. Scan ready/ for workorders
    5. Sort by priority (P0 > P1 > P2 > P3)
    6. Pick the highest-priority workorder that isn't blocked
    7. Classify, pick agent, assign
    8. Return [(filename, agent_name)] or []
    """
    if not WORK_DIR:
        return []
    if not READY_DIR or not READY_DIR.exists():
        return []

    # First, monitor Jules sessions
    _monitor_jules_sessions()

    state = _load_state()

    # --- Phase 1: Clean stale queue entries (dead PIDs, orphaned queue/in/) ---
    busy = is_queue_busy()

    # --- Phase 2: Recover orphaned WIP files (after queue cleanup so stale entries are gone) ---
    recovered = recover_orphaned_wip()
    if recovered:
        for fname in recovered:
            if fname in state["assignments"]:
                entry = state["assignments"][fname]
                entry["status"] = "recovered"
                state["assignments"][fname] = entry
            mark_failed(fname)

    # --- Phase 3: Cleanup stale state ---
    state = cleanup_stale_state(state)
    _save_state(state)

    # --- Phase 4: Check if busy (re-check after cleanup) ---
    if busy:
        # Re-check — cleanup may have cleared the blockage
        busy = is_queue_busy()
    if busy:
        _log("Queue busy, waiting for current task to finish")
        return []

    # --- Phase 4: Scan and prioritise ---
    candidates = []
    for wo_file in sorted(READY_DIR.glob("*.md")):
        fname = wo_file.name
        entry = state["assignments"].get(fname, {})
        status = entry.get("status", "")

        # Skip workorders flagged for human review
        if status == "human-review":
            continue

        # Skip if currently marked as assigned (shouldn't be in ready/ but guard)
        if status == "assigned":
            # If it's back in ready/ but state says assigned, it was recovered
            entry["status"] = "retry"
            state["assignments"][fname] = entry

        priority = prioritize(fname)
        category = classify(fname)
        candidates.append((wo_file, priority, category, entry))

    if not candidates:
        _save_state(state)
        return []

    # Sort by priority tier, then alphabetically within tier
    candidates.sort(key=lambda x: (PRIORITY_ORDER.get(x[1], 99), x[0].name))

    # --- Phase 5: Pick ONE and assign ---
    for wo_file, priority, category, entry in candidates:
        fname = wo_file.name
        
        # Check for Jules assignment
        if _is_jules_task(str(wo_file)) and jules_available():
            assign_to_jules(str(wo_file))
            return [(fname, "jules")]

        agent_name = pick_agent(category, fname, entry if entry else None)

        try:
            # Use agent_service directly (cross-platform, no subprocess)
            from csc_service.shared.services.agent_service import agent as AgentService
            _agent_svc = AgentService(None)

            sel_result = _agent_svc.select(agent_name)
            if "Unknown" in sel_result or "not installed" in sel_result:
                _log(f"Failed to select agent {agent_name}: {sel_result}", "WARN")
                continue

            assign_result = _agent_svc.assign(fname)
            if "Cannot assign" in assign_result or "not found" in assign_result:
                _log(f"Failed to assign {fname}: {assign_result}", "WARN")
                continue

            # 3. Record assignment in pm_state
            attempts = entry.get("attempts", 0) + 1 if entry.get("status") in ("retry", "recovered", "escalated") else 1
            history = entry.get("attempt_history", [])

            state["assignments"][fname] = {
                "agent": agent_name,
                "category": category,
                "priority": priority,
                "status": "assigned",
                "attempts": attempts,
                "attempt_history": history,
                "timestamp": _ts(),
            }
            _save_state(state)

            _log(f"Assigned {fname} -> {agent_name} [{priority}/{category}] (attempt {attempts})")
            return [(fname, agent_name)]

        except Exception as e:
            _log(f"FAILED to assign {fname}: {e}", "ERROR")
            state["assignments"][fname] = {
                "agent": agent_name,
                "category": category,
                "priority": priority,
                "status": "error",
                "attempts": entry.get("attempts", 0),
                "attempt_history": entry.get("attempt_history", []),
                "error": str(e)[:200],
                "timestamp": _ts(),
            }
            # Don't break — try the next candidate
            continue

    _save_state(state)
    return []
