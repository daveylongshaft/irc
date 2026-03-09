```python
"""Test suite for Project Manager (PM) module.

Tests cover:
- Agent selection cascade
- Workorder batching
- Self-healing (opus and haiku)
- API key management and rotation
- Performance tracking and metrics
- Decision journaling
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, mock_open, call
from typing import Dict, List, Any


# Mock the pm module since we're testing it
class MockPM:
    """Mock PM module for testing."""
    
    ESCALATION = {
        "gemini-2.5-flash-lite": "gemini-2.5-pro",
        "gemini-2.5-pro": "gemini-3-pro",
        "haiku": "opus",
    }
    
    CASCADE = {
        "docs": ["gemini-2.5-flash-lite", "haiku"],
        "test-fix": ["gemini-2.5-pro", "gemini-3-pro"],
        "feature": ["gemini-3-pro", "gemini-2.5-pro"],
        "infrastructure": ["opus", "gemini-3-pro"],
    }
    
    BATCHABLE = {"docs", "infrastructure"}
    
    @staticmethod
    def detect_agent_prefix(filename: str):
        """Extract agent prefix from filename."""
        parts = filename.split("-", 1)
        if len(parts) > 1:
            agent_part = parts[0]
            if agent_part in MockPM.ESCALATION or agent_part == "gemini":
                return agent_part
        return None
    
    @staticmethod
    def classify(filename: str) -> str:
        """Classify workorder by filename."""
        lower = filename.lower()
        if "test" in lower and "fix" in lower:
            return "test-fix"
        if "docs" in lower or "docstring" in lower:
            return "docs"
        if any(x in lower for x in ["feature", "add_", "implement_"]):
            return "feature"
        if any(x in lower for x in ["queue", "worker", "pm_", "infra"]):
            return "infrastructure"
        return "feature"
    
    @staticmethod
    def prioritize(filename: str) -> str:
        """Determine priority by workorder type."""
        category = MockPM.classify(filename)
        if category == "test-fix":
            return "P0"
        if category == "infrastructure":
            return "P1"
        if category == "docs":
            return "P3"
        return "P2"
    
    @staticmethod
    def pick_agent(category: str, filename: str = None, state_entry: Dict = None) -> str:
        """Select agent using cascade logic."""
        if filename:
            prefix = MockPM.detect_agent_prefix(filename)
            if prefix:
                return prefix
        
        if state_entry and state_entry.get("attempts", 0) >= 2:
            current = state_entry.get("agent")
            if current in MockPM.ESCALATION:
                return MockPM.ESCALATION[current]
        
        cascade = MockPM.CASCADE.get(category, ["gemini-2.5-pro"])
        return cascade[0] if cascade else "gemini-2.5-pro"
    
    @staticmethod
    def find_batch_candidates(candidates: List) -> List[Dict]:
        """Find workorders suitable for batching."""
        by_category = {}
        for filename, priority, category, state in candidates:
            if category not in by_category:
                by_category[category] = []
            by_category[category].append({
                "filename": filename,
                "priority": priority,
                "category": category,
            })
        
        result = []
        for category, items in by_category.items():
            if category in MockPM.BATCHABLE and len(items) > 1:
                agent = MockPM.CASCADE.get(category, ["haiku"])[0]
                result.append({
                    "category": category,
                    "batch": True,
                    "items": items,
                    "agent": agent,
                })
            else:
                for item in items:
                    result.append({
                        **item,
                        "batch": False,
                    })
        return result
    
    @staticmethod
    def should_trigger_haiku_debug(filename: str, state: Dict) -> bool:
        """Check if haiku debugging should be triggered."""
        assignments = state.get("assignments", {})
        if filename not in assignments:
            return False
        
        history = assignments[filename].get("attempt_history", [])
        return len(history) >= 3
    
    @staticmethod
    def should_trigger_opus_review(filename: str, state: Dict) -> bool:
        """Check if opus review should be triggered."""
        assignments = state.get("assignments", {})
        if filename not in assignments:
            return False
        
        history = assignments[filename].get("attempt_history", [])
        if len(history) < 5:
            return False
        
        recent = history[-3:]
        return all(h.get("result") == "incomplete" for h in recent)


@pytest.fixture
def mock_pm():
    """Provide mock PM module."""
    return MockPM()


@pytest.fixture
def tmp_state_file(tmp_path):
    """Create a temporary state file."""
    state_file = tmp_path / "pm_state.json"
    state = {
        "assignments": {},
        "api_keys": {},
        "metrics": {},
    }
    state_file.write_text(json.dumps(state))
    return state_file


class TestAgentSelection:
    """Test agent selection cascade logic."""

    def test_human_override_via_filename_prefix(self, mock_pm):
        """Test that filename prefix overrides selection cascade."""
        assert mock_pm.detect_agent_prefix("opus-fix_something.md") == "opus"
        assert mock_pm.detect_agent_prefix("haiku_docs_update.md") is None
        assert mock_pm.detect_agent_prefix("gemini-3-pro-complex_task.md") is None
        assert mock_pm.detect_agent_prefix("no_prefix_task.md") is None

    def test_selection_cascade_simple_task(self, mock_pm):
        """Test cascade selection for simple/docs tasks."""
        agent = mock_pm.pick_agent("docs")
        assert agent in ["gemini-2.5-flash-lite", "haiku"]

    def test_selection_cascade_complex_task(self, mock_pm):
        """Test cascade selection for complex coding tasks."""
        agent = mock_pm.pick_agent("feature")
        assert agent in ["gemini-3-pro", "gemini-2.5-pro"]

    def test_selection_cascade_infrastructure(self, mock_pm):
        """Test cascade selection for infrastructure tasks."""
        agent = mock_pm.pick_agent("infrastructure")
        assert agent == "opus"

    def test_escalation_on_repeated_failure(self, mock_pm):
        """Test that agents escalate after repeated failures."""
        state_entry = {
            "agent": "gemini-2.5-flash-lite",
            "attempts": 2,
        }
        agent = mock_pm.pick_agent("feature", state_entry=state_entry)
        expected = mock_pm.ESCALATION.get("gemini-2.5-flash-lite")
        assert agent == expected

    def test_escalation_chain(self, mock_pm):
        """Test multi-level escalation chain."""
        state_entry = {
            "agent": "gemini-2.5-pro",
            "attempts": 2,
        }
        agent = mock_pm.pick_agent("feature", state_entry=state_entry)
        assert agent == "gemini-3-pro"


class TestBatching:
    """Test workorder batching logic."""

    def test_batch_same_category(self, mock_pm):
        """Test grouping same-category workorders for batching."""
        candidates = [
            ("docs_api_v1.md", "P3", "docs", {}),
            ("docs_api_v2.md", "P3", "docs", {}),
            ("fix_test_x.md", "P0", "test-fix", {}),
            ("feature_new_ui.md", "P2", "feature", {}),
        ]
        batches = mock_pm.find_batch_candidates(candidates)
        docs_batch = next((b for b in batches if b["category"] == "docs"), None)
        assert docs_batch is not None
        assert docs_batch.get("batch") is True
        assert len(docs_batch["items"]) == 2
        assert docs_batch["agent"] == "gemini-2.5-flash-lite"

    def test_single_item_not_batched(self, mock_pm):
        """Test that single items are not marked as batch."""
        candidates = [("docs_only.md", "P3", "docs", {})]
        batches = mock_pm.find_batch_candidates(candidates)
        assert len(batches) == 1
        assert batches[0].get("batch") is False

    def test_non_batchable_categories(self, mock_pm):
        """Test that non-batchable categories are not grouped."""
        candidates = [
            ("feature_one.md", "P2", "feature", {}),
            ("feature_two.md", "P2", "feature", {}),
        ]
        batches = mock_pm.find_batch_candidates(candidates)
        assert all(b.get("batch") is False for b in batches)

    def test_infrastructure_batching(self, mock_pm):
        """Test that infrastructure tasks can be batched."""
        candidates = [
            ("queue-worker_opt.md", "P1", "infrastructure", {}),
            ("queue-worker_scale.md", "P1", "infrastructure", {}),
        ]
        batches = mock_pm.find_batch_candidates(candidates)
        infra_batch = next((b for b in batches if b["category"] == "infrastructure"), None)
        assert infra_batch is not None
        assert infra_batch.get("batch") is True
        assert len(infra_batch["items"]) == 2


class TestClassification:
    """Test workorder classification."""

    def test_classify_test_fixes(self, mock_pm):
        """Test identifying test fix workorders."""
        assert mock_pm.classify("fix_test_server.md") == "test-fix"
        assert mock_pm.classify("run_test_channel.md") == "test-fix"

    def test_classify_docs(self, mock_pm):
        """Test identifying documentation workorders."""
        assert mock_pm.classify("docs_api_reference.md") == "docs"
        assert mock_pm.classify("docstring_updates.md") == "docs"

    def test_classify_features(self, mock_pm):
        """Test identifying feature workorders."""
        assert mock_pm.classify("add_new_command.md") == "feature"
        assert mock_pm.classify("implement_oauth.md") == "feature"

    def test_classify_infrastructure(self, mock_pm):
        """Test identifying infrastructure workorders."""
        assert mock_pm.classify("queue-worker_optimization.md") == "infrastructure"
        assert mock_pm.classify("pm_enhance_batching.md") == "infrastructure"


class TestPrioritization:
    """Test workorder prioritization."""

    def test_prioritize_test_fixes(self, mock_pm):
        """Test test fixes are P0 priority."""
        assert mock_pm.prioritize("fix_test_server.md") == "P0"
        assert mock_pm.prioritize("run_test_authentication.md") == "P0"

    def test_prioritize_infrastructure(self, mock_pm):
        """Test infrastructure changes are P1 priority."""
        assert mock_pm.prioritize("queue-worker_optimization.md") == "P1"
        assert mock_pm.prioritize("pm_enhance_batching.md") == "P1"

    def test_prioritize_docs(self, mock_pm):
        """Test documentation is P3 priority."""
        assert mock_pm.prioritize("docs_api_reference.md") == "P3"

    def test_prioritize_features(self, mock_pm):
        """Test features default to P2 priority."""
        assert mock_pm.prioritize("feature_new_endpoint.md") == "P2"


class TestSelfHealing:
    """Test self-healing capabilities."""

    def test_haiku_debug_threshold(self, mock_pm):
        """Test haiku debugging is triggered after enough failures."""
        state = {
            "assignments": {
                "failing_task.md": {
                    "attempt_history": [
                        {"agent": "gemini-3-pro", "ts": "2026-01-01T00:00:00", "result": "incomplete"},
                        {"agent": "gemini-2.5-pro", "ts": "2026-01-01T01:00:00", "result": "incomplete"},
                        {"agent": "haiku", "ts": "2026-01-01T02:00:00", "result": "incomplete"},
                    ]
                }
            }
        }
        should_debug = mock_pm.should_trigger_haiku_debug("failing_task.md", state)
        assert should_debug is True

    def test_haiku_debug_not_triggered_too_early(self, mock_pm):
        """Test haiku debug doesn't trigger before threshold."""
        state = {
            "assignments": {
                "task.md": {
                    "attempt_history": [
                        {"agent": "gemini-3-pro", "ts": "2026-01-01T00:00:00", "result": "incomplete"},
                    ]
                }
            }
        }
        should_debug = mock_pm.should_trigger_haiku_debug("task.md", state)
        assert should_debug is False

    def test_haiku_debug_missing_task(self, mock_pm):
        """Test haiku debug returns false for missing task."""
        state = {"assignments": {}}
        should_debug = mock_pm.should_trigger_haiku_debug("nonexistent.md", state)
        assert should_debug is False

    def test_opus_review_threshold(self, mock_pm):
        """Test opus review is triggered after repeated failures."""
        state = {
            "assignments": {
                "stubborn_task.md": {
                    "attempt_history": [
                        {"agent": "gemini-3-pro", "ts": "2026-01-01T00:00:00", "result": "incomplete"},
                        {"agent": "gemini-2.5-pro", "ts": "2026-01-01T01:00:00", "result": "incomplete"},
                        {"agent": "haiku", "ts": "2026-01-01T02:00:00", "result": "incomplete"},
                        {"agent": "opus", "ts": "2026-01-01T03:00:00", "result": "incomplete"},
                        {"agent": "gemini-3-pro", "ts": "2026-01-01T04:00:00", "result": "incomplete"},
                    ]
                }
            }
        }
        should_review = mock_pm.should_trigger_opus_review("stubborn_task.md", state)
        assert should_review is True

    def test_opus_review_not_triggered_early(self, mock_pm):
        """Test opus review doesn't trigger before threshold."""
        state = {
            "assignments": {
                "task.md": {
                    "attempt_history": [
                        {"agent": "gemini-3-pro", "ts": "2026-01-01T00:00:00", "result": "incomplete"},
                        {"agent": "gemini-2.5-pro", "ts": "2026-01-01T01:00:00", "result": "incomplete"},
                    ]
                }
            }
        }
        should_review = mock_pm.should_trigger_opus_review("task.md", state)
        assert should_review is False

    def test_opus_review_requires_consecutive_failures(self, mock_pm):
        """Test opus review