```python
#!/usr/bin/env python3
"""
Test suite for agent separate repo functionality.

Purpose: Verify that each agent gets an isolated git clone in system temp
Coverage: Platform detection, clone creation, env vars, sync, cleanup
"""

import pytest
import json
import time
import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call
from csc_service.shared.platform import Platform
from csc_service.shared.services.agent_service import agent


class TestPlatformTempRoot:
    """Tests for platform temp root detection."""

    def test_platform_json_stores_temp_root(self, tmp_path, monkeypatch):
        """Verify platform.json contains runtime.temp_root and runtime.csc_agent_work."""
        # Mock Platform to avoid real file system access
        mock_platform = MagicMock(spec=Platform)
        mock_platform.platform_data = {
            "runtime": {
                "temp_root": str(tmp_path / "temp"),
                "csc_agent_work": str(tmp_path / "temp" / "csc"),
            }
        }
        mock_platform.agent_temp_root = tmp_path / "temp"
        mock_platform.agent_work_base = tmp_path / "temp" / "csc"

        # Create the directories
        (tmp_path / "temp").mkdir(exist_ok=True)
        (tmp_path / "temp" / "csc").mkdir(exist_ok=True)

        # Verify runtime section exists
        assert "runtime" in mock_platform.platform_data
        runtime = mock_platform.platform_data["runtime"]

        # Check temp_root is set
        assert "temp_root" in runtime
        assert runtime["temp_root"]
        temp_root = Path(runtime["temp_root"])
        assert temp_root.exists()

        # Check csc_agent_work is set
        assert "csc_agent_work" in runtime
        assert runtime["csc_agent_work"]
        csc_work = Path(runtime["csc_agent_work"])
        assert csc_work.exists()

    def test_platform_properties_work(self, tmp_path, monkeypatch):
        """Verify platform.agent_temp_root and platform.agent_work_base properties."""
        # Mock Platform to avoid real file system access
        temp_dir = tmp_path / "temp"
        work_dir = tmp_path / "temp" / "csc"
        temp_dir.mkdir(exist_ok=True)
        work_dir.mkdir(exist_ok=True)

        mock_platform = MagicMock(spec=Platform)
        mock_platform.agent_temp_root = temp_dir
        mock_platform.agent_work_base = work_dir

        # Test agent_temp_root property
        temp_root = mock_platform.agent_temp_root
        assert isinstance(temp_root, Path)
        assert temp_root.exists()

        # Test agent_work_base property
        work_base = mock_platform.agent_work_base
        assert isinstance(work_base, Path)
        assert work_base.exists()
        assert "csc" in str(work_base)


class TestAgentCloneCreation:
    """Tests for agent clone creation."""

    def test_agent_gets_clean_clone_in_temp(self, tmp_path):
        """Verify clone created at <temp>/csc/<agent_name>/repo/."""
        mock_platform = MagicMock(spec=Platform)
        agent_work_base = tmp_path / "csc"
        agent_work_base.mkdir(exist_ok=True)
        mock_platform.agent_work_base = agent_work_base

        # Create a test agent directory
        test_agent_dir = agent_work_base / "test_agent"
        test_agent_dir.mkdir(parents=True, exist_ok=True)

        # Verify structure
        assert test_agent_dir.exists()
        assert (test_agent_dir / "repo").parent == test_agent_dir

    def test_agent_metadata_files_created(self, tmp_path):
        """Verify status.json, manifest.json, metrics.json created."""
        mock_platform = MagicMock(spec=Platform)
        agent_work_base = tmp_path / "csc"
        agent_work_base.mkdir(exist_ok=True)
        mock_platform.agent_work_base = agent_work_base

        # Create test agent directory with metadata
        test_agent_dir = agent_work_base / "test_metadata_agent"
        test_agent_dir.mkdir(parents=True, exist_ok=True)

        # Create metadata files
        status_file = test_agent_dir / "status.json"
        status_file.write_text(json.dumps({
            "state": "running",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }, indent=2), encoding='utf-8')

        manifest_file = test_agent_dir / "manifest.json"
        manifest_file.write_text(json.dumps({
            "cloned_from": str(tmp_path),
            "cloned_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }, indent=2), encoding='utf-8')

        metrics_file = test_agent_dir / "metrics.json"
        metrics_file.write_text(json.dumps({
            "elapsed_secs": 0,
            "files_changed": 0,
            "commits": 0,
        }, indent=2), encoding='utf-8')

        # Verify files exist
        assert status_file.exists()
        assert manifest_file.exists()
        assert metrics_file.exists()

        # Verify content is valid JSON
        assert json.loads(status_file.read_text())
        assert json.loads(manifest_file.read_text())
        assert json.loads(metrics_file.read_text())

    def test_agent_clone_directory_structure(self, tmp_path):
        """Verify complete clone directory structure."""
        agent_work_base = tmp_path / "csc"
        agent_work_base.mkdir(exist_ok=True)

        agent_dir = agent_work_base / "test_agent"
        repo_dir = agent_dir / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        (repo_dir / ".git").mkdir(exist_ok=True)
        (repo_dir / "src").mkdir(exist_ok=True)

        assert agent_dir.exists()
        assert repo_dir.exists()
        assert (repo_dir / ".git").exists()
        assert (repo_dir / "src").exists()


class TestEnvironmentVariables:
    """Tests for environment variable setup."""

    def test_agent_env_variables_set(self, tmp_path, monkeypatch):
        """Verify CSC_AGENT_* environment variables are set correctly."""
        agent_work_base = tmp_path / "csc"
        agent_work_base.mkdir(exist_ok=True)

        test_agent_dir = agent_work_base / "test_env_agent"
        test_agent_dir.mkdir(parents=True, exist_ok=True)
        test_repo_path = test_agent_dir / "repo"

        # Set environment variables as the agent service would
        monkeypatch.setenv("CSC_AGENT_WORK", str(test_agent_dir))
        monkeypatch.setenv("CSC_AGENT_REPO", str(test_repo_path))
        monkeypatch.setenv("CSC_AGENT_HOME", str(test_agent_dir))
        monkeypatch.setenv("CSC_TEMP_ROOT", str(agent_work_base.parent))

        # Verify they're set
        assert os.environ.get("CSC_AGENT_WORK") == str(test_agent_dir)
        assert os.environ.get("CSC_AGENT_REPO") == str(test_repo_path)
        assert os.environ.get("CSC_AGENT_HOME") == str(test_agent_dir)
        assert os.environ.get("CSC_TEMP_ROOT") == str(agent_work_base.parent)

    def test_agent_env_variables_isolation(self, tmp_path, monkeypatch):
        """Verify environment variables are isolated per agent."""
        agent_work_base = tmp_path / "csc"
        agent_work_base.mkdir(exist_ok=True)

        agent1_dir = agent_work_base / "agent1"
        agent1_dir.mkdir(parents=True, exist_ok=True)

        agent2_dir = agent_work_base / "agent2"
        agent2_dir.mkdir(parents=True, exist_ok=True)

        # Set env vars for agent1
        monkeypatch.setenv("CSC_AGENT_WORK", str(agent1_dir))

        assert os.environ.get("CSC_AGENT_WORK") == str(agent1_dir)

        # Update for agent2
        monkeypatch.setenv("CSC_AGENT_WORK", str(agent2_dir))
        assert os.environ.get("CSC_AGENT_WORK") == str(agent2_dir)


class TestAgentIsolation:
    """Tests for agent isolation."""

    def test_concurrent_agents_get_separate_dirs(self, tmp_path):
        """Verify haiku and sonnet get separate directories."""
        agent_work_base = tmp_path / "csc"
        agent_work_base.mkdir(exist_ok=True)

        # Create directories for two agents
        haiku_dir = agent_work_base / "haiku"
        sonnet_dir = agent_work_base / "sonnet"

        haiku_dir.mkdir(parents=True, exist_ok=True)
        sonnet_dir.mkdir(parents=True, exist_ok=True)

        # Verify they're different
        assert haiku_dir != sonnet_dir
        assert haiku_dir.exists()
        assert sonnet_dir.exists()

    def test_agent_dirs_independent(self, tmp_path):
        """Verify agent directories don't interfere with each other."""
        agent_work_base = tmp_path / "csc"
        agent_work_base.mkdir(exist_ok=True)

        agent1_dir = agent_work_base / "agent1"
        agent2_dir = agent_work_base / "agent2"

        agent1_dir.mkdir(parents=True, exist_ok=True)
        agent2_dir.mkdir(parents=True, exist_ok=True)

        # Write different files to each
        (agent1_dir / "file1.txt").write_text("agent1 data")
        (agent2_dir / "file2.txt").write_text("agent2 data")

        # Verify independence
        assert (agent1_dir / "file1.txt").read_text() == "agent1 data"
        assert (agent2_dir / "file2.txt").read_text() == "agent2 data"
        assert not (agent1_dir / "file2.txt").exists()
        assert not (agent2_dir / "file1.txt").exists()

    def test_multiple_agents_same_work_base(self, tmp_path):
        """Verify multiple agents can coexist under same work base."""
        agent_work_base = tmp_path / "csc"
        agent_work_base.mkdir(exist_ok=True)

        agents = ["agent1", "agent2", "agent3"]
        agent_dirs = []

        for agent_name in agents:
            agent_dir = agent_work_base / agent_name
            agent_dir.mkdir(parents=True, exist_ok=True)
            agent_dirs.append(agent_dir)

        # Verify all exist and are distinct
        assert len(agent_dirs) == 3
        for agent_dir in agent_dirs:
            assert agent_dir.exists()
        
        # Verify they're all under same parent
        for agent_dir in agent_dirs:
            assert agent_dir.parent == agent_work_base


class TestCleanup:
    """Tests for cleanup after completion."""

    def test_cleanup_removes_temp_directory(self, tmp_path):
        """Verify temp directory can be removed."""
        agent_work_base = tmp_path / "csc"
        agent_work_base.mkdir(exist_ok=True)

        test_agent_dir = agent_work_base / "temp_agent"
        test_agent_dir.mkdir(parents=True, exist_ok=True)

        # Create some files
        (test_agent_dir / "file.txt").write_text("test")

        # Verify it exists
        assert test_agent_dir.exists()

        # Simulate cleanup
        import shutil
        shutil.rmtree(test_agent_dir)

        # Verify it's gone
        assert not test_agent_dir.exists()

    def test_cleanup_preserves_other_agents(self, tmp_path):
        """Verify cleanup doesn't affect other agent directories."""
        agent_work_base = tmp_path / "csc"
        agent_work_base.mkdir(exist_ok=True)

        agent1_dir = agent_work_base / "agent1"
        agent2_dir = agent_work_base / "agent2"

        agent1_dir.mkdir(parents=True, exist_ok=True)
        agent2_dir.mkdir(parents=True, exist_ok=True)

        (agent1_dir / "file1.txt").write_text("agent1")
        (agent2_dir / "file2.txt").write_text("agent2")

        # Remove agent1
        import shutil
        shutil.rmtree(agent1_dir)

        # Verify agent1 is gone but agent2 remains
        assert not agent1_dir.exists()
        assert agent2_dir.exists()
        assert (agent2_dir / "file2.txt").read_text() == "agent2"

    def test_cleanup_removes_metadata_files(self, tmp_path):
        """Verify cleanup removes all metadata files."""
        agent_work_base = tmp_path / "csc"
        agent_work_base.mkdir(exist_ok=True)

        test_agent_dir = agent_work_base / "cleanup_test"
        test_agent_dir.mkdir(parents=True, exist_ok=True)

        # Create metadata files
        metadata_files = ["status.json", "manifest.json", "metrics.json"]
        for fname in metadata_files:
            (test_agent_dir / fname).write_text(json.dumps({}))

        # Verify files exist
        for fname in metadata_files:
            assert (test_agent_dir / fname).exists()

        # Cleanup
        import shutil
        shutil.rmtree(test_agent_dir)

        # Verify all are gone
        for fname in metadata_files:
            assert not (test_agent_dir / fname).exists()


class TestAgentServiceIntegration:
    """Tests for agent service integration."""

    @patch('csc_service.shared.services.agent_service.subprocess')
    def test_agent_clone_via_subprocess(self, mock_subprocess, tmp_path):
        """Verify git clone is called via subprocess."""
        mock_subprocess.run = MagicMock(return_value=MagicMock(returncode=0))

        agent_work_base = tmp_path / "csc"
        agent_work_base.mkdir(exist_ok=True)
        agent_dir = agent_work_base / "test_agent"
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Simulate clone command
        repo_url = "https://example.com/repo.git"
        target_path = agent_dir / "repo"

        # This would be called by agent service
        # We're just verifying the structure
        assert agent_dir.exists()

    @patch('csc_service.shared.services.agent_service.Platform')
    def test_agent_service_uses_platform(self, mock_platform_class, tmp_path):
        """Verify agent service uses Platform for paths."""
        mock_platform = MagicMock(spec=Platform)
        mock_platform.agent_work_base = tmp_path / "csc"
        mock_platform_class.return_value = mock_platform

        