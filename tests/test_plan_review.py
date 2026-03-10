"""Tests for PlanReviewer service and Julius client.

Covers decision parsing, queue file I/O, plan submission, approval checking,
and the run_cycle integration path.
"""

import json
import os
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'packages', 'csc-service'))

from csc_service.infra.plan_review import PlanReviewer, run_cycle
from csc_service.clients.julius.julius import Julius


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def csc_root(tmp_path):
    """Create a minimal CSC root with plan-review agent directories."""
    (tmp_path / "csc-service.json").write_text(json.dumps({}))
    agent_dir = tmp_path / "agents" / "plan-review"
    (agent_dir / "queue" / "in").mkdir(parents=True)
    (agent_dir / "queue" / "work").mkdir(parents=True)
    (agent_dir / "queue" / "out").mkdir(parents=True)
    (agent_dir / "context").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def reviewer(csc_root):
    """Create a PlanReviewer with temp root."""
    return PlanReviewer(csc_root=str(csc_root))


@pytest.fixture
def julius_client(csc_root):
    """Create a Julius client with temp root."""
    return Julius(csc_root=str(csc_root))


# ---------------------------------------------------------------------------
# PlanReviewer._parse_decision
# ---------------------------------------------------------------------------

class TestParseDecision:
    def test_parse_approve(self, reviewer):
        """Should extract APPROVE decision from JSON in output."""
        output = '{"decision": "APPROVE", "reason": "Looks good", "confidence": 0.9}'
        result = reviewer._parse_decision(output)
        assert result["decision"] == "APPROVE"
        assert result["reason"] == "Looks good"
        assert result["confidence"] == 0.9

    def test_parse_deny(self, reviewer):
        """Should extract DENY decision from JSON in output."""
        output = '{"decision": "DENY", "reason": "Missing docs", "confidence": 0.8}'
        result = reviewer._parse_decision(output)
        assert result["decision"] == "DENY"

    def test_parse_json_embedded_in_text(self, reviewer):
        """Should extract JSON even when surrounded by prose."""
        output = (
            'After reviewing this plan, I conclude:\n'
            '{"decision": "APPROVE", "reason": "Good plan", "confidence": 0.95}\n'
            'That is my assessment.'
        )
        result = reviewer._parse_decision(output)
        assert result["decision"] == "APPROVE"

    def test_parse_fallback_on_empty(self, reviewer):
        """Should return DENY fallback when output is empty."""
        result = reviewer._parse_decision("")
        assert result["decision"] == "DENY"
        assert result["confidence"] == 0.0

    def test_parse_fallback_on_invalid_json(self, reviewer):
        """Should return DENY fallback when JSON is malformed."""
        result = reviewer._parse_decision("not json at all")
        assert result["decision"] == "DENY"

    def test_parse_fallback_on_unknown_decision(self, reviewer):
        """Should return DENY if 'decision' value is not APPROVE or DENY."""
        output = '{"decision": "MAYBE", "reason": "Unsure"}'
        result = reviewer._parse_decision(output)
        assert result["decision"] == "DENY"


# ---------------------------------------------------------------------------
# PlanReviewer._review_plan
# ---------------------------------------------------------------------------

class TestReviewPlan:
    def test_review_plan_writes_decision(self, reviewer, csc_root):
        """Should write decision JSON to queue/out/ after reviewing."""
        queue_in = csc_root / "agents" / "plan-review" / "queue" / "in"
        plan_file = queue_in / "sess_abc_plan.json"
        plan_file.write_text(json.dumps({
            "session_id": "sess_abc",
            "content": "Add logging to the handler.",
            "submitted_at": time.time(),
        }))

        ai_response = '{"decision": "APPROVE", "reason": "Simple and safe", "confidence": 0.95}'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=ai_response, returncode=0)
            reviewer._review_plan(plan_file)

        out_file = csc_root / "agents" / "plan-review" / "queue" / "out" / "sess_abc_decision.json"
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert data["decision"] == "APPROVE"

    def test_review_plan_removes_input_file(self, reviewer, csc_root):
        """Input plan file should be deleted after review."""
        queue_in = csc_root / "agents" / "plan-review" / "queue" / "in"
        plan_file = queue_in / "sess_del_plan.json"
        plan_file.write_text(json.dumps({
            "session_id": "sess_del",
            "content": "Small fix.",
            "submitted_at": time.time(),
        }))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout='{"decision": "DENY", "reason": "Issues found", "confidence": 0.7}',
                returncode=0,
            )
            reviewer._review_plan(plan_file)

        assert not plan_file.exists()

    def test_review_plan_handles_timeout(self, reviewer, csc_root):
        """Should produce DENY fallback and clean up on subprocess timeout."""
        import subprocess
        queue_in = csc_root / "agents" / "plan-review" / "queue" / "in"
        plan_file = queue_in / "sess_timeout_plan.json"
        plan_file.write_text(json.dumps({
            "session_id": "sess_timeout",
            "content": "Big refactor.",
            "submitted_at": time.time(),
        }))

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 120)):
            reviewer._review_plan(plan_file)

        out_file = csc_root / "agents" / "plan-review" / "queue" / "out" / "sess_timeout_decision.json"
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert data["decision"] == "DENY"

    def test_review_plan_handles_bad_json_input(self, reviewer, csc_root):
        """Should delete corrupted plan file without crashing."""
        queue_in = csc_root / "agents" / "plan-review" / "queue" / "in"
        plan_file = queue_in / "corrupt_plan.json"
        plan_file.write_text("not valid json{{{")

        reviewer._review_plan(plan_file)
        assert not plan_file.exists()


# ---------------------------------------------------------------------------
# PlanReviewer.run_cycle
# ---------------------------------------------------------------------------

class TestRunCycle:
    def test_run_cycle_no_plans(self, reviewer):
        """Should do nothing when queue/in/ is empty."""
        reviewer.run_cycle()  # Should not raise

    def test_run_cycle_processes_all_plans(self, reviewer, csc_root):
        """Should review all .json files found in queue/in/."""
        queue_in = csc_root / "agents" / "plan-review" / "queue" / "in"
        for i in range(3):
            (queue_in / f"sess_{i}_plan.json").write_text(json.dumps({
                "session_id": f"sess_{i}",
                "content": "Some plan text.",
                "submitted_at": time.time(),
            }))

        ai_response = '{"decision": "APPROVE", "reason": "OK", "confidence": 0.9}'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=ai_response, returncode=0)
            reviewer.run_cycle()

        out_dir = csc_root / "agents" / "plan-review" / "queue" / "out"
        decisions = list(out_dir.glob("*_decision.json"))
        assert len(decisions) == 3

    def test_run_cycle_updates_state_metrics(self, reviewer, csc_root):
        """Should increment total_reviewed and total_approved in state.json."""
        queue_in = csc_root / "agents" / "plan-review" / "queue" / "in"
        (queue_in / "sess_metrics_plan.json").write_text(json.dumps({
            "session_id": "sess_metrics",
            "content": "Simple fix.",
            "submitted_at": time.time(),
        }))

        ai_response = '{"decision": "APPROVE", "reason": "OK", "confidence": 0.9}'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=ai_response, returncode=0)
            reviewer.run_cycle()

        state_file = csc_root / "agents" / "plan-review" / "state.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["total_reviewed"] >= 1
        assert state["total_approved"] >= 1


# ---------------------------------------------------------------------------
# Julius.submit_plan_for_review
# ---------------------------------------------------------------------------

class TestSubmitPlanForReview:
    def test_submit_creates_file(self, julius_client, csc_root):
        """Should create a plan JSON file in queue/in/."""
        result = julius_client.submit_plan_for_review(
            "session-xyz", "Fix the login bug."
        )
        assert result is True
        plan_file = csc_root / "agents" / "plan-review" / "queue" / "in" / "session-xyz_plan.json"
        assert plan_file.exists()
        data = json.loads(plan_file.read_text())
        assert data["session_id"] == "session-xyz"
        assert data["content"] == "Fix the login bug."
        assert "submitted_at" in data

    def test_submit_creates_dir_if_missing(self, julius_client, csc_root):
        """Should create queue/in/ directory if it does not exist."""
        import shutil
        shutil.rmtree(csc_root / "agents" / "plan-review" / "queue" / "in", ignore_errors=True)
        result = julius_client.submit_plan_for_review("session-new", "Plan content.")
        assert result is True


# ---------------------------------------------------------------------------
# Julius.check_plan_approval
# ---------------------------------------------------------------------------

class TestCheckPlanApproval:
    def test_returns_none_when_pending(self, julius_client):
        """Should return None when no decision file exists."""
        result = julius_client.check_plan_approval("nonexistent-session")
        assert result is None

    def test_returns_decision_when_ready(self, julius_client, csc_root):
        """Should return decision dict when decision file exists."""
        out_dir = csc_root / "agents" / "plan-review" / "queue" / "out"
        decision = {"decision": "APPROVE", "reason": "All good", "confidence": 0.98}
        (out_dir / "session-done_decision.json").write_text(json.dumps(decision))

        result = julius_client.check_plan_approval("session-done")
        assert result is not None
        assert result["decision"] == "APPROVE"

    def test_returns_none_on_corrupt_decision_file(self, julius_client, csc_root):
        """Should return None when decision file is malformed JSON."""
        out_dir = csc_root / "agents" / "plan-review" / "queue" / "out"
        (out_dir / "session-corrupt_decision.json").write_text("not json")

        result = julius_client.check_plan_approval("session-corrupt")
        assert result is None


# ---------------------------------------------------------------------------
# run_cycle module entry point
# ---------------------------------------------------------------------------

class TestRunCycleEntryPoint:
    def test_module_run_cycle(self, csc_root):
        """Module-level run_cycle() should instantiate and invoke correctly."""
        run_cycle(csc_root=str(csc_root))  # Should not raise on empty queue
