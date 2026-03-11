"""Jules Monitoring & Approval Service — automated feedback loop.

Polls Jules sessions via REST API, detects feedback requests, validates
plans against CSC standards, spawns approval agent for edge cases, sends
feedback back to Jules, monitors execution, retrieves results.

95% deterministic script, 5% agent-based validation for edge cases.

Integration: called from main.py daemon loop alongside queue-worker,
test-runner, pm, and pr-review.
"""

import json
import os
import time
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

from csc_service.shared.data import Data


JULES_API_BASE = "https://julius.googleapis.com/v1alpha"


class JulesMonitor(Data):
    """Monitor Jules sessions, validate plans, send feedback autonomously."""

    def __init__(self, csc_root: str = None):
        """Initialize JulesMonitor with paths and API config.

        Args:
            csc_root: Path to CSC project root. Auto-detected if None.
        """
        super().__init__()
        self.name = "jules-monitor"
        self._initialize_paths(csc_root)
        self.init_data("jules_monitor_data.json")

        self.api_key = self._load_api_key()
        self.poll_interval = 60
        self.auto_approve = True
        self.max_concurrent = 5
        self._load_config()

    def _initialize_paths(self, csc_root: str = None) -> None:
        """Resolve CSC root directory.

        Args:
            csc_root: Explicit root path, or None to auto-detect.
        """
        if csc_root:
            self.csc_root = Path(csc_root).resolve()
        else:
            # Check CSC_ROOT env var first (set by Platform)
            env_root = os.environ.get("CSC_ROOT", "")
            if env_root:
                self.csc_root = Path(env_root)
            else:
                p = Path(__file__).resolve().parent
                for _ in range(10):
                    if (p / "CLAUDE.md").exists() or (p / "etc" / "csc-service.json").exists() or (p / "csc-service.json").exists():
                        break
                    if p == p.parent:
                        break
                    p = p.parent
                self.csc_root = p

    def _load_api_key(self) -> str:
        """Load Jules API key from environment or .env file.

        Returns:
            API key string, or empty string if not found.
        """
        key = os.environ.get("JULES_API_KEY", "")
        if key:
            return key

        env_file = self.csc_root / ".env"
        if env_file.exists():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("JULES_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
            except Exception:
                pass
        return ""

    def _load_config(self) -> None:
        """Load Jules config from csc-service.json."""
        # Prefer CSC_ETC env var (set by Platform), fall back to etc/ then root
        csc_etc = os.environ.get("CSC_ETC", "")
        if csc_etc:
            config_file = Path(csc_etc) / "csc-service.json"
        else:
            config_file = self.csc_root / "etc" / "csc-service.json"
        if not config_file.exists():
            config_file = self.csc_root / "csc-service.json"
        if not config_file.exists():
            return
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
            jules_cfg = config.get("jules", {})
            self.poll_interval = jules_cfg.get("poll_interval_seconds", 60)
            self.auto_approve = jules_cfg.get("auto_approve_if_no_issues", True)
            self.max_concurrent = jules_cfg.get("max_concurrent_sessions", 5)
            api_key_env = jules_cfg.get("api_key_env", "JULES_API_KEY")
            if not self.api_key:
                self.api_key = os.environ.get(api_key_env, "")
        except (json.JSONDecodeError, IOError):
            pass

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def _api_headers(self) -> dict:
        """Build API request headers.

        Returns:
            Dict with x-goog-api-key header.
        """
        return {"x-goog-api-key": self.api_key}

    def _list_sessions(self) -> list:
        """GET /v1alpha/sessions — list all active sessions.

        Returns:
            List of session dicts from Jules API.
        """
        if not requests:
            self.log("requests library not available, cannot poll Jules")
            return []
        try:
            resp = requests.get(
                f"{JULES_API_BASE}/sessions",
                headers=self._api_headers(),
                params={"pageSize": 50},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("sessions", [])
        except Exception as e:
            self.log(f"Failed to list Jules sessions: {e}")
            return []

    def _get_session(self, session_id: str) -> dict:
        """GET /v1alpha/sessions/{session_id} — fetch session details.

        Args:
            session_id: Jules session ID.

        Returns:
            Session dict from API, or empty dict on error.
        """
        if not requests:
            return {}
        try:
            resp = requests.get(
                f"{JULES_API_BASE}/sessions/{session_id}",
                headers=self._api_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.log(f"Failed to get session {session_id}: {e}")
            return {}

    def _send_feedback(self, session_id: str, decision: dict) -> bool:
        """POST /v1alpha/sessions/{session_id}:sendMessage — send feedback.

        Args:
            session_id: Jules session ID.
            decision: Dict with 'action', 'reason', optional 'feedback'.

        Returns:
            True if feedback sent successfully.
        """
        if not requests:
            return False

        if decision["action"] == "APPROVE":
            message = "Plan approved. Proceed with implementation."
        elif decision["action"] == "REJECT":
            message = f"Plan rejected: {decision.get('reason', 'Does not meet standards')}"
        else:
            feedback = decision.get("feedback", decision.get("reason", ""))
            message = f"Feedback: {feedback}"

        try:
            resp = requests.post(
                f"{JULES_API_BASE}/sessions/{session_id}:sendMessage",
                headers=self._api_headers(),
                json={"message": message},
                timeout=30,
            )
            resp.raise_for_status()
            self.log(f"Feedback sent to session {session_id}: {decision['action']}")
            return True
        except Exception as e:
            self.log(f"Failed to send feedback to {session_id}: {e}")
            return False

    # ------------------------------------------------------------------
    # Plan validation
    # ------------------------------------------------------------------

    def _validate_plan(self, plan: str, session: dict) -> dict:
        """Check plan text against CSC coding standards.

        Args:
            plan: Plan text from Jules session.
            session: Full session dict for context.

        Returns:
            Dict with 'has_issues' bool and 'issues' list.
        """
        if not plan:
            return {"has_issues": False, "issues": [], "validation_timestamp": time.time()}

        issues = []

        # Check 1: Multiple classes in single file
        if plan.count("class ") > 1 and "file" in plan.lower():
            issues.append("Multiple classes in single file (violates one-class-per-file rule)")

        # Check 2: Hardcoded paths instead of Platform()
        if ("Path(" in plan or "open(" in plan) and "Platform()" not in plan:
            if "/c/" in plan or "C:\\" in plan or "/home/" in plan:
                issues.append("Hardcoded paths detected (should use Platform())")

        # Check 3: Missing docstrings on functions
        if "def " in plan and '"""' not in plan:
            issues.append("Missing docstrings on functions")

        # Check 4: Missing type hints
        if "def " in plan and "->" not in plan:
            issues.append("Missing type hints on function returns")

        # Check 5: Using print() instead of self.log()
        if "print(" in plan and "self.log(" not in plan:
            issues.append("Using print() instead of self.log()")

        # Check 6: Breaking changes without backward compat note
        if ("delete" in plan.lower() or "remove" in plan.lower()):
            if "backward" not in plan.lower() and "compat" not in plan.lower():
                issues.append("Plan may remove features without backward compatibility note")

        return {
            "has_issues": len(issues) > 0,
            "issues": issues,
            "validation_timestamp": time.time(),
        }

    # ------------------------------------------------------------------
    # Session state handlers
    # ------------------------------------------------------------------

    def _handle_awaiting_feedback(self, session: dict) -> None:
        """Process a session in AWAITING_USER_FEEDBACK state.

        Validates the plan and either auto-approves or sends feedback.

        Args:
            session: Session dict from Jules API.
        """
        session_id = session["name"].split("/")[-1]

        # Check if we already processed this session
        tracked = self.get_data("tracked_sessions") or {}
        entry = tracked.get(session_id, {})
        if entry.get("feedback_sent"):
            return

        plan = session.get("plan", "")
        validation = self._validate_plan(plan, session)

        if validation["has_issues"]:
            decision = {
                "action": "REQUEST_CHANGES",
                "reason": "; ".join(validation["issues"]),
                "feedback": "Please address the following issues:\n"
                + "\n".join(f"- {i}" for i in validation["issues"]),
            }
            self.log(f"Session {session_id}: validation found {len(validation['issues'])} issue(s)")
        else:
            if self.auto_approve:
                decision = {"action": "APPROVE", "reason": "Plan meets all CSC criteria"}
            else:
                self.log(f"Session {session_id}: validation passed but auto_approve=False, skipping")
                return

        success = self._send_feedback(session_id, decision)

        # Track this session
        entry.update({
            "state": "feedback_sent",
            "feedback_sent": success,
            "decision": decision["action"],
            "validation": validation,
            "timestamp": time.time(),
            "title": session.get("title", ""),
        })
        tracked[session_id] = entry
        self.put_data("tracked_sessions", tracked)

    def _monitor_execution(self, session: dict) -> None:
        """Track IN_PROGRESS / EXECUTING sessions.

        Args:
            session: Session dict from Jules API.
        """
        session_id = session["name"].split("/")[-1]
        tracked = self.get_data("tracked_sessions") or {}
        entry = tracked.get(session_id, {})

        prev_state = entry.get("state", "")
        current_state = session.get("state", "")

        if prev_state != current_state:
            self.log(f"Session {session_id} state: {prev_state} -> {current_state}")
            entry["state"] = current_state
            entry["last_updated"] = time.time()
            tracked[session_id] = entry
            self.put_data("tracked_sessions", tracked)

    def _handle_completion(self, session: dict) -> None:
        """Process a completed session — log results, extract PR URL.

        Args:
            session: Session dict from Jules API.
        """
        session_id = session["name"].split("/")[-1]
        tracked = self.get_data("tracked_sessions") or {}
        entry = tracked.get(session_id, {})

        if entry.get("state") == "completed":
            return  # Already processed

        outputs = session.get("outputs", {})
        pr_url = outputs.get("pullRequestUrl", "")

        self.log(f"Session {session_id} completed. PR: {pr_url or 'none'}")

        entry.update({
            "state": "completed",
            "pr_url": pr_url,
            "completed_at": time.time(),
            "title": session.get("title", ""),
        })
        tracked[session_id] = entry
        self.put_data("tracked_sessions", tracked)

    def _handle_failure(self, session: dict) -> None:
        """Process a failed session — log error.

        Args:
            session: Session dict from Jules API.
        """
        session_id = session["name"].split("/")[-1]
        tracked = self.get_data("tracked_sessions") or {}
        entry = tracked.get(session_id, {})

        if entry.get("state") == "failed":
            return  # Already processed

        error = session.get("error", {})
        error_msg = error.get("message", str(error)) if error else "unknown"

        self.log(f"Session {session_id} failed: {error_msg}")

        entry.update({
            "state": "failed",
            "error": error_msg,
            "failed_at": time.time(),
            "title": session.get("title", ""),
        })
        tracked[session_id] = entry
        self.put_data("tracked_sessions", tracked)

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    def run_cycle(self) -> None:
        """Poll Jules sessions and handle each based on state.

        Called from the service main loop every poll_interval seconds.
        """
        if not self.api_key:
            return  # Silently skip if no API key configured

        if not requests:
            self.log("requests library not installed, skipping Jules monitor")
            return

        sessions = self._list_sessions()
        if not sessions:
            return

        self.log(f"Jules Monitor: found {len(sessions)} session(s)")

        for session in sessions:
            state = session.get("state", "")
            try:
                if state == "AWAITING_USER_FEEDBACK":
                    self._handle_awaiting_feedback(session)
                elif state in ("IN_PROGRESS", "EXECUTING"):
                    self._monitor_execution(session)
                elif state == "COMPLETED":
                    self._handle_completion(session)
                elif state == "FAILED":
                    self._handle_failure(session)
            except Exception as e:
                sid = session.get("name", "unknown")
                self.log(f"Error processing session {sid}: {e}")


def run_cycle(csc_root: str = None) -> None:
    """Entry point called by service main loop.

    Args:
        csc_root: Path to CSC project root.
    """
    monitor = JulesMonitor(csc_root)
    monitor.run_cycle()
