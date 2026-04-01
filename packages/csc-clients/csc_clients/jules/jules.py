"""Jules client for workorder execution via Jules REST API."""

import json
import time

try:
    import requests as _requests
except ImportError:
    _requests = None

from csc_log import Log
from csc_platform import Platform
from .config import JulesConfig

JULES_API_BASE = "https://jules.googleapis.com/v1alpha"


class Jules(Log):
    """Jules API client for autonomous coding tasks via REST API."""

    def __init__(self):
        super().__init__()
        self.plat = Platform()
        self.config = JulesConfig()
        self.api_key = self._load_api_key()
        self.sessions = {}  # Track active sessions

    def _load_api_key(self) -> str:
        """Load Jules API key from config file."""
        if not self.config.api_key_path:
            self.log("Jules API key path is not configured.", "ERROR")
            return None

        config_path = self.plat.get_abs_root_path(self.config.api_key_path.split('/'))

        try:
            with open(config_path, 'r') as f:
                return f.read().strip()
        except FileNotFoundError:
            self.log(f"Jules API key file not found at: {config_path}", "ERROR")
            return None

    def _api_headers(self) -> dict:
        """Build API request headers."""
        return {
            "X-Goog-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def submit_workorder(self, workorder_path: str, repo_url: str) -> str:
        """Submit workorder to Jules via REST API, return session ID."""
        with open(workorder_path, encoding="utf-8") as f:
            prompt = f.read()

        session_id = self._create_session(prompt, repo_url)

        self.sessions[session_id] = {
            'workorder': workorder_path,
            'created': time.time(),
            'repo': repo_url,
        }

        self.log(f"Jules session created: {session_id}", "INFO")
        return session_id

    def _create_session(self, prompt: str, repo_url: str) -> str:
        """Create Jules session via REST API."""
        if not _requests:
            raise ImportError("requests library required for Jules API")
        if not self.api_key:
            raise ValueError("Jules API key not configured")

        # repo_url format: "owner/repo" -> source format: "sources/github/owner/repo"
        source = f"sources/github/{repo_url}"

        body = {
            "prompt": prompt,
            "sourceContext": {
                "source": source,
                "githubRepoContext": {
                    "startingBranch": self.config.github_branch or "main"
                }
            },
            "automationMode": "AUTO_CREATE_PR",
            "requirePlanApproval": not self.config.auto_approve_plans,
        }

        resp = _requests.post(
            f"{JULES_API_BASE}/sessions",
            headers=self._api_headers(),
            json=body,
            timeout=60,
        )
        resp.raise_for_status()

        data = resp.json()
        session_id = data.get("name", "").split("/")[-1]
        if not session_id:
            session_id = data.get("name", data.get("id", "unknown"))
        return session_id

    def check_status(self, session_id: str) -> dict:
        """Check session status via REST API."""
        if not _requests:
            return {'state': 'failed', 'error': 'requests not available'}

        try:
            resp = _requests.get(
                f"{JULES_API_BASE}/sessions/{session_id}",
                headers=self._api_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.log(f"Failed to check Jules session {session_id}: {e}", "ERROR")
            return {'state': 'failed', 'error': str(e)}

    def list_sessions(self) -> list:
        """List all sessions via REST API."""
        if not _requests:
            return []

        try:
            resp = _requests.get(
                f"{JULES_API_BASE}/sessions",
                headers=self._api_headers(),
                params={"pageSize": 50},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("sessions", [])
        except Exception as e:
            self.log(f"Failed to list Jules sessions: {e}", "ERROR")
            return []

    def get_results(self, session_id: str) -> dict:
        """Get session activities/results via REST API."""
        if not _requests:
            return {'status': 'failed', 'error': 'requests not available'}

        try:
            resp = _requests.get(
                f"{JULES_API_BASE}/sessions/{session_id}/activities",
                headers=self._api_headers(),
                params={"pageSize": 30},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.log(f"Failed to get results for {session_id}: {e}", "ERROR")
            return {'status': 'failed', 'error': str(e)}

    def approve_plan(self, session_id: str) -> bool:
        """Approve a pending plan via REST API."""
        if not _requests:
            return False

        try:
            resp = _requests.post(
                f"{JULES_API_BASE}/sessions/{session_id}:approvePlan",
                headers=self._api_headers(),
                json={},
                timeout=30,
            )
            resp.raise_for_status()
            self.log(f"Plan approved for session {session_id}", "INFO")
            return True
        except Exception as e:
            self.log(f"Failed to approve plan for {session_id}: {e}", "ERROR")
            return False

    def send_message(self, session_id: str, message: str) -> bool:
        """Send a message to an active session."""
        if not _requests:
            return False

        try:
            resp = _requests.post(
                f"{JULES_API_BASE}/sessions/{session_id}:sendMessage",
                headers=self._api_headers(),
                json={"prompt": message},
                timeout=30,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            self.log(f"Failed to send message to {session_id}: {e}", "ERROR")
            return False

    def cancel_session(self, session_id: str) -> bool:
        """Cancel active session (not directly supported, send cancel message)."""
        return self.send_message(session_id, "Cancel this session and stop work.")
