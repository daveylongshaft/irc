"""Tests for JulesMonitor service.

Tests plan validation logic, session state handling, and API interaction
using mocked HTTP responses.
"""

import json
import os
import sys
import time
import pytest
from unittest.mock import patch, MagicMock

# Ensure package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'packages', 'csc-service'))

from csc_service.infra.jules_monitor import JulesMonitor, JULES_API_BASE


@pytest.fixture
def monitor(tmp_path):
    """Create a JulesMonitor with temp directory as root."""
    # Create minimal csc-service.json
    config = {
        "jules": {
            "enabled": True,
            "api_key_env": "JULES_API_KEY",
            "auto_approve_if_no_issues": True,
        }
    }
    (tmp_path / "csc-service.json").write_text(json.dumps(config))

    with patch.dict(os.environ, {"JULES_API_KEY": "test-key-123"}):
        m = JulesMonitor(csc_root=str(tmp_path))
    return m


# ------------------------------------------------------------------
# Plan validation tests
# ------------------------------------------------------------------

class TestValidatePlan:
    def test_empty_plan_passes(self, monitor):
        """Empty plan should have no issues."""
        result = monitor._validate_plan("", {})
        assert result["has_issues"] is False
        assert result["issues"] == []

    def test_multiple_classes_flagged(self, monitor):
        """Plan with multiple classes in one file should flag issue."""
        plan = "class Foo:\n    pass\nclass Bar:\n    pass\nfile: models.py"
        result = monitor._validate_plan(plan, {})
        assert result["has_issues"] is True
        assert any("one-class-per-file" in i for i in result["issues"])

    def test_single_class_ok(self, monitor):
        """Single class in plan should not flag multi-class issue."""
        plan = "class Foo:\n    pass\nfile: models.py"
        result = monitor._validate_plan(plan, {})
        assert not any("one-class-per-file" in i for i in result["issues"])

    def test_hardcoded_paths_flagged(self, monitor):
        """Hardcoded /c/ paths without Platform() should flag."""
        plan = "Path('/c/Users/dave/project')\nopen('/c/data.txt')"
        result = monitor._validate_plan(plan, {})
        assert result["has_issues"] is True
        assert any("Hardcoded paths" in i for i in result["issues"])

    def test_platform_paths_ok(self, monitor):
        """Using Platform() for paths should not flag."""
        plan = "path = Platform().get_abs_root_path(['data'])\nopen(path)"
        result = monitor._validate_plan(plan, {})
        assert not any("Hardcoded paths" in i for i in result["issues"])

    def test_missing_docstrings_flagged(self, monitor):
        """Functions without docstrings should flag."""
        plan = "def foo():\n    return 42"
        result = monitor._validate_plan(plan, {})
        assert any("docstrings" in i for i in result["issues"])

    def test_docstrings_ok(self, monitor):
        """Functions with docstrings should not flag."""
        plan = 'def foo():\n    """Do something."""\n    return 42'
        result = monitor._validate_plan(plan, {})
        assert not any("docstrings" in i.lower() for i in result["issues"])

    def test_missing_type_hints_flagged(self, monitor):
        """Functions without return type hints should flag."""
        plan = "def foo(x):\n    return x"
        result = monitor._validate_plan(plan, {})
        assert any("type hints" in i for i in result["issues"])

    def test_type_hints_ok(self, monitor):
        """Functions with type hints should not flag."""
        plan = 'def foo(x: int) -> int:\n    """Return x."""\n    return x'
        result = monitor._validate_plan(plan, {})
        assert not any("type hints" in i for i in result["issues"])

    def test_print_instead_of_log(self, monitor):
        """Using print() without self.log() should flag."""
        plan = "print('debug output')"
        result = monitor._validate_plan(plan, {})
        assert any("print()" in i for i in result["issues"])

    def test_log_usage_ok(self, monitor):
        """Using self.log() alongside print() should not flag."""
        plan = "self.log('info')\nprint('also ok')"
        result = monitor._validate_plan(plan, {})
        assert not any("print()" in i for i in result["issues"])

    def test_breaking_changes_flagged(self, monitor):
        """Plan mentioning delete/remove without compat note should flag."""
        plan = "Delete the old handler and replace it."
        result = monitor._validate_plan(plan, {})
        assert any("backward compatibility" in i for i in result["issues"])

    def test_validation_has_timestamp(self, monitor):
        """Validation result should include timestamp."""
        result = monitor._validate_plan("", {})
        assert "validation_timestamp" in result
        assert isinstance(result["validation_timestamp"], float)


# ------------------------------------------------------------------
# Session handling tests
# ------------------------------------------------------------------

class TestSessionHandling:
    def test_handle_awaiting_feedback_approve(self, monitor):
        """Session with clean plan should auto-approve."""
        session = {
            "name": "sessions/12345",
            "state": "AWAITING_USER_FEEDBACK",
            "title": "Test task",
            "plan": 'def foo(x: int) -> int:\n    """Return x."""\n    return x',
        }

        with patch.object(monitor, '_send_feedback', return_value=True) as mock_send:
            monitor._handle_awaiting_feedback(session)
            mock_send.assert_called_once()
            decision = mock_send.call_args[0][1]
            assert decision["action"] == "APPROVE"

    def test_handle_awaiting_feedback_request_changes(self, monitor):
        """Session with plan issues should request changes."""
        session = {
            "name": "sessions/12345",
            "state": "AWAITING_USER_FEEDBACK",
            "title": "Test task",
            "plan": "def foo():\n    print('bad')",
        }

        with patch.object(monitor, '_send_feedback', return_value=True) as mock_send:
            monitor._handle_awaiting_feedback(session)
            mock_send.assert_called_once()
            decision = mock_send.call_args[0][1]
            assert decision["action"] == "REQUEST_CHANGES"

    def test_handle_awaiting_feedback_idempotent(self, monitor):
        """Same session should not be processed twice."""
        session = {
            "name": "sessions/12345",
            "state": "AWAITING_USER_FEEDBACK",
            "title": "Test task",
            "plan": "",
        }

        # Pre-set tracked data
        monitor.put_data("tracked_sessions", {
            "12345": {"feedback_sent": True, "state": "feedback_sent"}
        })

        with patch.object(monitor, '_send_feedback') as mock_send:
            monitor._handle_awaiting_feedback(session)
            mock_send.assert_not_called()

    def test_handle_completion(self, monitor):
        """Completed session should log PR URL and update tracking."""
        session = {
            "name": "sessions/99999",
            "state": "COMPLETED",
            "title": "Done task",
            "outputs": {"pullRequestUrl": "https://github.com/org/repo/pull/42"},
        }

        monitor._handle_completion(session)

        tracked = monitor.get_data("tracked_sessions")
        assert tracked["99999"]["state"] == "completed"
        assert tracked["99999"]["pr_url"] == "https://github.com/org/repo/pull/42"

    def test_handle_completion_idempotent(self, monitor):
        """Same completed session should not update twice."""
        monitor.put_data("tracked_sessions", {
            "99999": {"state": "completed", "pr_url": "url1"}
        })

        session = {
            "name": "sessions/99999",
            "state": "COMPLETED",
            "outputs": {"pullRequestUrl": "url2"},
        }

        monitor._handle_completion(session)
        tracked = monitor.get_data("tracked_sessions")
        assert tracked["99999"]["pr_url"] == "url1"  # unchanged

    def test_handle_failure(self, monitor):
        """Failed session should log error and update tracking."""
        session = {
            "name": "sessions/55555",
            "state": "FAILED",
            "title": "Broken task",
            "error": {"message": "Compilation failed"},
        }

        monitor._handle_failure(session)

        tracked = monitor.get_data("tracked_sessions")
        assert tracked["55555"]["state"] == "failed"
        assert "Compilation failed" in tracked["55555"]["error"]

    def test_monitor_execution_state_change(self, monitor):
        """Execution monitoring should track state transitions."""
        monitor.put_data("tracked_sessions", {
            "11111": {"state": "feedback_sent"}
        })

        session = {
            "name": "sessions/11111",
            "state": "IN_PROGRESS",
        }

        monitor._monitor_execution(session)

        tracked = monitor.get_data("tracked_sessions")
        assert tracked["11111"]["state"] == "IN_PROGRESS"


# ------------------------------------------------------------------
# API interaction tests
# ------------------------------------------------------------------

class TestAPIInteraction:
    @patch("csc_service.infra.jules_monitor.requests")
    def test_list_sessions(self, mock_requests, monitor):
        """Should parse session list from API response."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "sessions": [
                {"name": "sessions/1", "state": "COMPLETED"},
                {"name": "sessions/2", "state": "AWAITING_USER_FEEDBACK"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        sessions = monitor._list_sessions()
        assert len(sessions) == 2
        mock_requests.get.assert_called_once()

    @patch("csc_service.infra.jules_monitor.requests")
    def test_list_sessions_error(self, mock_requests, monitor):
        """Should return empty list on API error."""
        mock_requests.get.side_effect = Exception("Network error")
        sessions = monitor._list_sessions()
        assert sessions == []

    @patch("csc_service.infra.jules_monitor.requests")
    def test_send_feedback_approve(self, mock_requests, monitor):
        """Should send approval message."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = mock_resp

        result = monitor._send_feedback("12345", {
            "action": "APPROVE",
            "reason": "Looks good",
        })

        assert result is True
        call_args = mock_requests.post.call_args
        payload = call_args[1]["json"]
        assert "approved" in payload["message"].lower()

    @patch("csc_service.infra.jules_monitor.requests")
    def test_send_feedback_reject(self, mock_requests, monitor):
        """Should send rejection message with reason."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = mock_resp

        result = monitor._send_feedback("12345", {
            "action": "REJECT",
            "reason": "Does not meet standards",
        })

        assert result is True
        payload = mock_requests.post.call_args[1]["json"]
        assert "rejected" in payload["message"].lower()

    @patch("csc_service.infra.jules_monitor.requests")
    def test_send_feedback_request_changes(self, mock_requests, monitor):
        """Should send feedback with change requests."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_requests.post.return_value = mock_resp

        result = monitor._send_feedback("12345", {
            "action": "REQUEST_CHANGES",
            "feedback": "Add docstrings to all functions",
        })

        assert result is True
        payload = mock_requests.post.call_args[1]["json"]
        assert "docstrings" in payload["message"].lower()


# ------------------------------------------------------------------
# Run cycle integration tests
# ------------------------------------------------------------------

class TestRunCycle:
    def test_run_cycle_no_api_key(self, tmp_path):
        """Should silently skip if no API key configured."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove JULES_API_KEY if present
            os.environ.pop("JULES_API_KEY", None)
            m = JulesMonitor(csc_root=str(tmp_path))
            m.api_key = ""
            # Should not raise
            m.run_cycle()

    @patch("csc_service.infra.jules_monitor.requests")
    def test_run_cycle_dispatches_states(self, mock_requests, monitor):
        """Should dispatch to correct handler based on session state."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "sessions": [
                {"name": "sessions/1", "state": "AWAITING_USER_FEEDBACK", "plan": ""},
                {"name": "sessions/2", "state": "IN_PROGRESS"},
                {"name": "sessions/3", "state": "COMPLETED", "outputs": {}},
                {"name": "sessions/4", "state": "FAILED", "error": {}},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        # Mock send_feedback to avoid POST call
        with patch.object(monitor, '_send_feedback', return_value=True):
            monitor.run_cycle()

        tracked = monitor.get_data("tracked_sessions") or {}
        # Session 1 should have been handled (feedback sent)
        assert "1" in tracked
        # Session 3 should be completed
        assert tracked.get("3", {}).get("state") == "completed"
        # Session 4 should be failed
        assert tracked.get("4", {}).get("state") == "failed"
