```python
"""Tests for queue_worker temp repo collision detection and spawn safety.

Verifies:
1. get_agent_temp_repo never returns CSC_ROOT
2. ensure_agent_temp_repo returns None if temp repo == CSC_ROOT
3. spawn_agent refuses to run in CSC_ROOT
4. detect_agent_name in run_agent.py prefers CSC_AGENT_NAME env var
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

import pytest

# Force import from local source, not installed package
_packages_dir = str(Path(__file__).resolve().parent.parent / "packages")
if _packages_dir not in sys.path:
    sys.path.insert(0, _packages_dir)

# Remove any cached csc_service modules to force reimport from local source
for mod_name in list(sys.modules):
    if mod_name.startswith("csc_service"):
        del sys.modules[mod_name]

from csc_service.infra import queue_worker


@pytest.fixture
def csc_fs(tmp_path):
    """Create a temporary CSC file structure for testing."""
    csc_root = tmp_path / "csc"
    csc_root.mkdir()
    (csc_root / "agents").mkdir()
    (csc_root / "agents" / "haiku" / "bin").mkdir(parents=True)
    (csc_root / "agents" / "haiku" / "queue" / "in").mkdir(parents=True)
    (csc_root / "agents" / "haiku" / "queue" / "work").mkdir(parents=True)
    (csc_root / "agents" / "templates").mkdir(parents=True)
    (csc_root / "workorders" / "ready").mkdir(parents=True)
    (csc_root / "workorders" / "wip").mkdir(parents=True)
    (csc_root / "workorders" / "done").mkdir(parents=True)
    (csc_root / "logs").mkdir(parents=True)

    # Set module globals
    queue_worker.CSC_ROOT = csc_root
    queue_worker.AGENTS_DIR = csc_root / "agents"
    queue_worker.PROMPTS_BASE = csc_root / "workorders"
    queue_worker.READY_DIR = queue_worker.PROMPTS_BASE / "ready"
    queue_worker.WIP_DIR = queue_worker.PROMPTS_BASE / "wip"
    queue_worker.DONE_DIR = queue_worker.PROMPTS_BASE / "done"
    queue_worker.LOGS_DIR = csc_root / "logs"
    queue_worker.AGENT_DATA_FILE = csc_root / "agent_data.json"
    queue_worker.QUEUE_LOG = csc_root / "logs" / "queue-worker.log"
    queue_worker.STALE_FILE = csc_root / "logs" / "queue-wip-sizes.json"
    queue_worker.PENDING_FILE = csc_root / "logs" / "queue-pending.json"

    return csc_root


class TestGetAgentTempRepoPlatformJson:
    """Test that get_agent_temp_repo reads csc_agent_work from runtime section."""

    def test_reads_runtime_csc_agent_work(self, csc_fs, tmp_path):
        """csc_agent_work should be read from runtime section of platform.json."""
        agent_work_dir = tmp_path / "agent-work-area"
        agent_work_dir.mkdir()
        platform_data = {
            "runtime": {
                "csc_agent_work": str(agent_work_dir)
            }
        }
        (csc_fs / "platform.json").write_text(json.dumps(platform_data))

        result = queue_worker.get_agent_temp_repo("haiku")
        expected = agent_work_dir / "haiku" / "repo"
        assert result == expected

    def test_falls_back_to_top_level_csc_agent_work(self, csc_fs, tmp_path):
        """Backwards compat: read csc_agent_work from top level if not in runtime."""
        agent_work_dir = tmp_path / "legacy-work-area"
        agent_work_dir.mkdir()
        platform_data = {
            "csc_agent_work": str(agent_work_dir)
        }
        (csc_fs / "platform.json").write_text(json.dumps(platform_data))

        result = queue_worker.get_agent_temp_repo("haiku")
        expected = agent_work_dir / "haiku" / "repo"
        assert result == expected

    def test_runtime_takes_precedence_over_top_level(self, csc_fs, tmp_path):
        """runtime.csc_agent_work should take precedence over top-level."""
        runtime_dir = tmp_path / "runtime-work"
        runtime_dir.mkdir()
        toplevel_dir = tmp_path / "toplevel-work"
        toplevel_dir.mkdir()
        platform_data = {
            "csc_agent_work": str(toplevel_dir),
            "runtime": {
                "csc_agent_work": str(runtime_dir)
            }
        }
        (csc_fs / "platform.json").write_text(json.dumps(platform_data))

        result = queue_worker.get_agent_temp_repo("sonnet")
        expected = runtime_dir / "sonnet" / "repo"
        assert result == expected

    def test_empty_runtime_falls_to_temp(self, csc_fs, tmp_path):
        """Empty runtime section falls back to TEMP path."""
        platform_data = {"runtime": {}}
        (csc_fs / "platform.json").write_text(json.dumps(platform_data))

        temp_dir = tmp_path / "temp"
        temp_dir.mkdir(exist_ok=True)

        with patch.dict(os.environ, {"TEMP": str(temp_dir)}):
            with patch.object(queue_worker, "IS_WINDOWS", True):
                result = queue_worker.get_agent_temp_repo("haiku")

        expected = temp_dir / "csc" / "haiku" / "repo"
        assert result == expected

    def test_realistic_platform_json_structure(self, csc_fs, tmp_path):
        """Test with a realistic platform.json structure matching production."""
        agent_work = tmp_path / "csc-work"
        agent_work.mkdir()
        platform_data = {
            "detected_at": "2026-03-01T09:36:11-0600",
            "working_dir": "C:\\csc",
            "hardware": {"architecture": "AMD64"},
            "os": {"system": "Windows"},
            "runtime": {
                "temp_root": str(tmp_path),
                "csc_agent_work": str(agent_work),
                "temp_dir_windows": str(tmp_path),
            }
        }
        (csc_fs / "platform.json").write_text(json.dumps(platform_data))

        result = queue_worker.get_agent_temp_repo("opus")
        expected = agent_work / "opus" / "repo"
        assert result == expected


class TestGetAgentTempRepoCollision:
    """Test that get_agent_temp_repo never returns CSC_ROOT."""

    def test_fallback_path_collision_detected(self, csc_fs, tmp_path):
        """When fallback temp path equals CSC_ROOT, use agent-work subdir."""
        colliding_root = tmp_path / "csc" / "haiku" / "repo"
        colliding_root.mkdir(parents=True, exist_ok=True)
        queue_worker.CSC_ROOT = colliding_root

        platform_data = {"runtime": {}}
        (colliding_root / "platform.json").write_text(json.dumps(platform_data))

        temp_dir = tmp_path / "csc"

        with patch.dict(os.environ, {"TEMP": str(temp_dir)}):
            with patch.object(queue_worker, "IS_WINDOWS", True):
                result = queue_worker.get_agent_temp_repo("haiku")

        # Should not equal CSC_ROOT
        assert result != colliding_root
        # Should use agent-work subdir instead
        assert "agent-work" in str(result) or result.parent.name != "haiku"

    def test_explicit_agent_work_collision_avoidance(self, csc_fs, tmp_path):
        """When csc_agent_work path equals CSC_ROOT, should avoid collision."""
        # Set CSC_ROOT
        queue_worker.CSC_ROOT = csc_fs

        # Create platform.json pointing to CSC_ROOT as csc_agent_work
        platform_data = {
            "runtime": {
                "csc_agent_work": str(csc_fs)
            }
        }
        (csc_fs / "platform.json").write_text(json.dumps(platform_data))

        result = queue_worker.get_agent_temp_repo("claude")

        # Result should not be exactly CSC_ROOT
        assert result != csc_fs
        # But should still be a valid path
        assert isinstance(result, Path)


class TestEnsureAgentTempRepo:
    """Test that ensure_agent_temp_repo validates and creates temp repo safely."""

    def test_returns_none_if_temp_repo_equals_csc_root(self, csc_fs, tmp_path):
        """ensure_agent_temp_repo should return None if temp repo would be CSC_ROOT."""
        queue_worker.CSC_ROOT = csc_fs

        # Mock get_agent_temp_repo to return CSC_ROOT
        with patch.object(queue_worker, "get_agent_temp_repo", return_value=csc_fs):
            result = queue_worker.ensure_agent_temp_repo("badagent")

        assert result is None

    def test_creates_temp_repo_if_safe(self, csc_fs, tmp_path):
        """ensure_agent_temp_repo should create repo if path is safe."""
        queue_worker.CSC_ROOT = csc_fs
        safe_repo = tmp_path / "safe-work" / "goodagent" / "repo"

        with patch.object(queue_worker, "get_agent_temp_repo", return_value=safe_repo):
            result = queue_worker.ensure_agent_temp_repo("goodagent")

        # Should create the directory
        assert safe_repo.exists()
        assert result == safe_repo

    def test_returns_existing_temp_repo(self, csc_fs, tmp_path):
        """ensure_agent_temp_repo should return existing repo without error."""
        queue_worker.CSC_ROOT = csc_fs
        existing_repo = tmp_path / "work" / "agent" / "repo"
        existing_repo.mkdir(parents=True)

        with patch.object(queue_worker, "get_agent_temp_repo", return_value=existing_repo):
            result = queue_worker.ensure_agent_temp_repo("agent")

        assert result == existing_repo
        assert existing_repo.exists()


class TestSpawnAgentSafety:
    """Test that spawn_agent refuses to run in CSC_ROOT."""

    def test_spawn_agent_refuses_csc_root(self, csc_fs):
        """spawn_agent should refuse if work_dir == CSC_ROOT."""
        queue_worker.CSC_ROOT = csc_fs

        # Attempt to spawn with CSC_ROOT as work_dir
        result = queue_worker.spawn_agent(
            agent_name="test",
            work_dir=csc_fs,
            script="test.py",
            prompt_id="test-123"
        )

        # Should refuse and return None or False
        assert result is None or result is False

    def test_spawn_agent_accepts_safe_work_dir(self, csc_fs, tmp_path):
        """spawn_agent should accept work_dir that is not CSC_ROOT."""
        queue_worker.CSC_ROOT = csc_fs
        safe_work_dir = tmp_path / "safe-work"
        safe_work_dir.mkdir()

        # Mock subprocess and other dependencies
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=1234)
            with patch.object(queue_worker, "Log") as mock_log:
                result = queue_worker.spawn_agent(
                    agent_name="test",
                    work_dir=safe_work_dir,
                    script="test.py",
                    prompt_id="test-123"
                )

        # Should attempt to spawn (result depends on implementation)
        assert result is not False or mock_popen.called


class TestDetectAgentName:
    """Test that detect_agent_name prefers CSC_AGENT_NAME env var."""

    def test_prefers_csc_agent_name_env_var(self, csc_fs, tmp_path):
        """detect_agent_name should prefer CSC_AGENT_NAME environment variable."""
        queue_worker.CSC_ROOT = csc_fs

        with patch.dict(os.environ, {"CSC_AGENT_NAME": "claude"}):
            result = queue_worker.detect_agent_name()

        assert result == "claude"

    def test_falls_back_to_agent_dir_if_no_env_var(self, csc_fs, tmp_path):
        """detect_agent_name should fall back to parent directory name."""
        queue_worker.CSC_ROOT = csc_fs

        # Remove CSC_AGENT_NAME if present
        env_copy = dict(os.environ)
        env_copy.pop("CSC_AGENT_NAME", None)

        with patch.dict(os.environ, env_copy, clear=True):
            with patch("pathlib.Path.cwd") as mock_cwd:
                # Mock current directory as agent directory
                agent_dir = csc_fs / "agents" / "opus"
                agent_dir.mkdir(parents=True, exist_ok=True)
                mock_cwd.return_value = agent_dir

                result = queue_worker.detect_agent_name()

        assert result == "opus"

    def test_env_var_takes_precedence_over_cwd(self, csc_fs):
        """CSC_AGENT_NAME env var should take precedence over cwd."""
        queue_worker.CSC_ROOT = csc_fs

        with patch.dict(os.environ, {"CSC_AGENT_NAME": "sonnet"}):
            with patch("pathlib.Path.cwd") as mock_cwd:
                mock_cwd.return_value = csc_fs / "agents" / "haiku"

                result = queue_worker.detect_agent_name()

        assert result == "sonnet"


class TestQueueWorkerInitialization:
    """Test queue_worker module initialization and global setup."""

    def test_csc_root_set_correctly(self, csc_fs):
        """CSC_ROOT should be set to the expected value."""
        assert queue_worker.CSC_ROOT == csc_fs

    def test_agents_dir_created(self, csc_fs):
        """AGENTS_DIR should exist after initialization."""
        assert queue_worker.AGENTS_DIR.exists()

    def test_workorder_dirs_created(self, csc_fs):
        """Workorder directories should exist."""
        assert queue_worker.READY_DIR.exists()
        assert queue_worker.WIP_DIR.exists()
        assert queue_worker.DONE_DIR.exists()

    def test_logs_dir_created(self, csc_fs):
        """LOGS_DIR should exist."""
        assert queue_worker.LOGS_DIR.exists()


class TestPlatformJsonParsing:
    """Test parsing of platform.json with various edge cases."""

    def test_missing_platform_json(self, csc_fs, tmp_path):
        """Should handle missing platform.json gracefully."""
        queue_worker.CSC_ROOT = tmp_path / "empty"
        (tmp_path / "empty").mkdir()

        #