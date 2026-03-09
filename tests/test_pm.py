```python
"""Tests for the Project Manager (PM) module.

Tests cover: classification, prioritization, agent selection cascade,
batching, self-healing, API key management, performance metrics, and journal.
"""
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime

import pytest

# Import PM module
from csc_service.infra import pm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pm_env(tmp_path, monkeypatch):
    """Set up a temporary PM environment with ready/wip/done dirs."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    
    # Create directory structure
    (work_dir / "wo" / "ready").mkdir(parents=True)
    (work_dir / "wo" / "wip").mkdir(parents=True)
    (work_dir / "wo" / "done").mkdir(parents=True)
    (work_dir / "ops" / "agents").mkdir(parents=True)
    (work_dir / "logs").mkdir(parents=True)
    
    # Mock Platform to avoid real filesystem access
    mock_platform = MagicMock()
    mock_platform.run_dir = tmp_path / "run"
    mock_platform.run_dir.mkdir(exist_ok=True)
    
    with patch('csc_service.infra.pm.Platform', return_value=mock_platform):
        with patch('csc_service.infra.pm.Service') as mock_service_class:
            mock_svc = MagicMock()
            mock_svc.get_data.return_value = {"assignments": {}}
            mock_svc.put_data.return_value = None
            mock_service_class.return_value = mock_svc
            
            pm.setup(work_dir)
            yield work_dir
    
    # Cleanup state
    pm.WORK_DIR = None
    pm.STATE_FILE = None
    pm.AGENTS_DIR = None
    pm.READY_DIR = None
    pm.WIP_DIR = None
    pm.DONE_DIR = None
    pm._svc = None


@pytest.fixture
def ready_dir(pm_env):
    """Return the ready directory path."""
    return pm_env / "wo" / "ready"


@pytest.fixture
def wip_dir(pm_env):
    """Return the WIP directory path."""
    return pm_env / "wo" / "wip"


@pytest.fixture
def done_dir(pm_env):
    """Return the done directory path."""
    return pm_env / "wo" / "done"


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

class TestClassify:
    """Test workorder classification by filename pattern."""

    def test_push_fail(self):
        assert pm.classify("push-fail_ci_error.md") == "push-fail"

    def test_push_fail_underscore(self):
        assert pm.classify("push_fail_issue.md") == "push-fail"

    def test_test_fix(self):
        assert pm.classify("fix_test_server.md") == "test-fix"

    def test_run_test(self):
        assert pm.classify("run_test_platform.md") == "test-fix"

    def test_simple_fix(self):
        assert pm.classify("fix_storage_bug.md") == "simple-fix"

    def test_docs(self):
        assert pm.classify("docs_readme.md") == "docs"

    def test_docstring(self):
        assert pm.classify("add_docstring_server.md") == "docs"

    def test_document(self):
        assert pm.classify("document_api.md") == "docs"

    def test_audit(self):
        assert pm.classify("audit_security_review.md") == "audit"

    def test_review(self):
        assert pm.classify("review_code.md") == "audit"

    def test_validate(self):
        assert pm.classify("validate_schema.md") == "audit"

    def test_debug(self):
        assert pm.classify("debug_connection_issue.md") == "debug"

    def test_investigate(self):
        assert pm.classify("investigate_memory_leak.md") == "debug"

    def test_refactor(self):
        assert pm.classify("refactor_storage_layer.md") == "refactor"

    def test_rename(self):
        assert pm.classify("rename_classes.md") == "refactor"

    def test_migrate(self):
        assert pm.classify("migrate_database.md") == "refactor"

    def test_feature_default(self):
        assert pm.classify("add_dark_mode.md") == "feature"

    def test_classify_case_insensitive(self):
        assert pm.classify("DOCS_README.MD") == "docs"
        assert pm.classify("FIX_BUG.MD") == "simple-fix"
        assert pm.classify("DEBUG_ISSUE.MD") == "debug"


# ---------------------------------------------------------------------------
# Prioritization tests
# ---------------------------------------------------------------------------

class TestPrioritize:
    """Test priority assignment based on filename patterns."""

    def test_urgent_is_p0(self):
        assert pm.prioritize("urgent_server_crash.md") == "P0"

    def test_fix_test_is_p0(self):
        assert pm.prioritize("fix_test_irc.md") == "P0"

    def test_fix_is_p0(self):
        assert pm.prioritize("fix_bug.md") == "P0"

    def test_security_is_p0(self):
        assert pm.prioritize("security_patch.md") == "P0"

    def test_push_fail_is_p0(self):
        assert pm.prioritize("push-fail_issue.md") == "P0"

    def test_infra_is_p1(self):
        assert pm.prioritize("queue_worker_improvement.md") == "P1"

    def test_pm_is_p1(self):
        assert pm.prioritize("pm_agent_update.md") == "P1"

    def test_architecture_is_p1(self):
        assert pm.prioritize("architecture_redesign.md") == "P1"

    def test_docs_is_p3(self):
        assert pm.prioritize("docs_readme_update.md") == "P3"

    def test_feature_is_p2(self):
        assert pm.prioritize("add_new_feature.md") == "P2"

    def test_refactor_is_p2(self):
        assert pm.prioritize("refactor_code.md") == "P2"

    def test_audit_is_p1(self):
        assert pm.prioritize("audit_review.md") == "P1"

    def test_priority_case_insensitive(self):
        assert pm.prioritize("URGENT_ISSUE.MD") == "P0"
        assert pm.prioritize("DOCS_README.MD") == "P3"


# ---------------------------------------------------------------------------
# Agent selection cascade tests
# ---------------------------------------------------------------------------

class TestAgentSelection:
    """Test agent selection cascade and overrides."""

    def test_human_override_prefix(self):
        """Filename prefix overrides cascade."""
        agent = pm.pick_agent("feature", "opus_critical_fix.md")
        assert agent == "opus"

    def test_human_override_haiku(self):
        agent = pm.pick_agent("docs", "haiku-batch_docs.md")
        assert agent == "haiku"

    def test_human_override_gemini_flash(self):
        agent = pm.pick_agent("feature", "gemini-2.5-flash_task.md")
        assert agent == "gemini-2.5-flash"

    def test_cascade_docs_gets_flash(self, pm_env):
        """Docs should get gemini-2.5-flash."""
        agent = pm.pick_agent("docs", "docs_readme.md")
        assert agent == "gemini-2.5-flash"

    def test_cascade_test_fix_gets_flash(self, pm_env):
        """Test-fix should get gemini-2.5-flash."""
        agent = pm.pick_agent("test-fix", "fix_test_server.md")
        assert agent == "gemini-2.5-flash"

    def test_cascade_audit_gets_haiku(self, pm_env):
        """Audits should get haiku."""
        agent = pm.pick_agent("audit", "audit_code.md")
        assert agent == "haiku"

    def test_cascade_feature_gets_pro_preview(self, pm_env):
        """Features should get gemini-2.5-pro-preview."""
        agent = pm.pick_agent("feature", "add_widget.md")
        assert agent == "gemini-2.5-pro-preview"

    def test_cascade_simple_fix_gets_pro_preview(self, pm_env):
        """Simple fixes should get gemini-2.5-pro-preview."""
        agent = pm.pick_agent("simple-fix", "fix_bug.md")
        assert agent == "gemini-2.5-pro-preview"

    def test_cascade_push_fail_gets_opus(self, pm_env):
        """Push-fail should get opus."""
        agent = pm.pick_agent("push-fail", "push_fail_ci.md")
        assert agent == "opus"

    def test_escalation_after_failures(self, pm_env):
        """After 2 failures, agent should escalate."""
        state_entry = {
            "agent": "gemini-2.5-flash",
            "attempts": 2,
        }
        agent = pm.pick_agent("docs", "docs_readme.md", state_entry)
        assert agent == "gemini-2.5-pro-preview"

    def test_escalation_pro_preview_to_3_1_pro(self, pm_env):
        """Pro-preview escalates to 3.1-pro."""
        state_entry = {
            "agent": "gemini-2.5-pro-preview",
            "attempts": 2,
        }
        agent = pm.pick_agent("feature", "add_feature.md", state_entry)
        assert agent == "gemini-3.1-pro-preview"

    def test_escalation_3_1_pro_to_haiku(self, pm_env):
        """3.1-pro escalates to haiku."""
        state_entry = {
            "agent": "gemini-3.1-pro-preview",
            "attempts": 2,
        }
        agent = pm.pick_agent("feature", "add_feature.md", state_entry)
        assert agent == "haiku"

    def test_escalation_haiku_to_opus(self, pm_env):
        """Haiku escalates to opus."""
        state_entry = {
            "agent": "haiku",
            "attempts": 2,
        }
        agent = pm.pick_agent("audit", "audit_code.md", state_entry)
        assert agent == "opus"

    def test_escalation_opus_returns_none(self, pm_env):
        """Opus has nowhere to escalate."""
        state_entry = {
            "agent": "opus",
            "attempts": 2,
        }
        agent = pm.pick_agent("push-fail", "push_fail.md", state_entry)
        assert agent is None


# ---------------------------------------------------------------------------
# Frontmatter tests
# ---------------------------------------------------------------------------

class TestReadFrontmatter:
    """Test YAML frontmatter parsing."""

    def test_read_valid_frontmatter(self):
        content = """---
role: docs
priority: P0
---
Some content"""
        with patch('builtins.open', mock_open(read_data=content)):
            fm = pm._read_frontmatter("test.md")
            assert fm.get("role") == "docs"
            assert fm.get("priority") == "P0"

    def test_read_no_frontmatter(self):
        content = "Just content, no frontmatter"
        with patch('builtins.open', mock_open(read_data=content)):
            fm = pm._read_frontmatter("test.md")
            assert fm == {}

    def test_read_empty_frontmatter(self):
        content = """---
---
Content"""
        with patch('builtins.open', mock_open(read_data=content)):
            fm = pm._read_frontmatter("test.md")
            assert fm == {}

    def test_read_frontmatter_nonexistent_file(self):
        with patch('builtins.open', side_effect=FileNotFoundError):
            fm = pm._read_frontmatter("nonexistent.md")
            assert fm == {}


# ---------------------------------------------------------------------------
# State persistence tests
# ---------------------------------------------------------------------------

class TestStatePersistence:
    """Test state loading and saving."""

    def test_load_state_no_svc(self):
        pm._svc = None
        state = pm._load_state()
        assert state == {"assignments": {}}

    def test_load_state_with_svc(self):
        mock_svc = MagicMock()
        test_state = {"assignments": {"file.md": {"agent": "opus"}}}
        mock_svc.get_data.return_value = test_state
        pm._svc = mock_svc
        
        state = pm._load_state()
        assert state == test_state
        mock_svc.get_data.assert_called_with("state")

    def test_load_state_invalid_data(self):
        mock_svc = MagicMock()
        mock_svc.get_data.return_value = "invalid"
        pm._svc = mock_svc
        
        state = pm._load_state()
        assert state == {"assignments": {}}

    def test_save_state_no_svc(self):
        pm._svc = None
        pm._save_state({"assignments": {}})
        # Should not raise

    def test_save_state_with_svc(self):
        mock_svc = MagicMock()
        pm._svc = mock_svc
        test_state = {"assignments": {"file.md": {"agent": "opus"}}}
        
        pm._save_state(test_state)
        mock_svc.put_data.assert_called_with("state", test_state)


# ---------------------------------------------------------------------------
# Agent initialization and checking tests
# ---------------------------------------------------------------------------

class TestAgentInit:
    """Test agent initialization and availability checking."""

    def test_init_agent_success(self, pm_env):
        mock_svc = MagicMock()
        mock_svc.get_data.return_value = {"key": "test-key"}
        pm._svc = mock_svc
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = pm.init_agent("gemini-2.5-flash", "test-key")
            assert result is True

    def test_init_agent_failure(self, pm_env):
        mock_svc = MagicMock()
        pm._svc = mock_svc
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = pm.init_agent("gemini-2.5-flash", "test-key")
            assert result is False

    def test_check_agent_available(self, pm_env):
        mock_svc = MagicMock()
        pm._svc = mock_svc
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = pm.check_agent("gemini-2.5-flash")
            assert result is True

    def test_check_agent_unavailable(self, pm_env):
        mock_svc = MagicMock()
        pm._svc = mock_svc
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = pm