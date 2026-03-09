```python
"""Tests for agent service."""

import os
import sys
import time
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directory structure for tests."""
    workorders_dir = tmp_path / "workorders"
    prompts_dir = tmp_path / "prompts"
    
    for base_dir in [workorders_dir, prompts_dir]:
        (base_dir / "ready").mkdir(parents=True, exist_ok=True)
        (base_dir / "wip").mkdir(parents=True, exist_ok=True)
        (base_dir / "done").mkdir(parents=True, exist_ok=True)
    
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    agents_dir = tmp_path / "ops" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    
    return {
        "root": tmp_path,
        "workorders": workorders_dir,
        "prompts": prompts_dir,
        "logs": logs_dir,
        "agents": agents_dir,
    }


@pytest.fixture
def mock_service(temp_dirs):
    """Create a mocked agent service."""
    with patch('csc_service.shared.services.agent_service.Service.__init__', return_value=None):
        from csc_service.shared.services.agent_service import agent
        
        service = agent.__new__(agent)
        service.server = MagicMock()
        service.log = MagicMock()
        
        # Set paths
        service.PROJECT_ROOT = temp_dirs["root"]
        service.WORKORDERS_BASE = temp_dirs["workorders"]
        service.LEGACY_PROMPTS_BASE = temp_dirs["prompts"]
        service.LOGS_DIR = temp_dirs["logs"]
        
        # Mock data store
        service._data = {}
        service.get_data = lambda key: service._data.get(key)
        service.put_data = lambda key, val, flush=True: service._data.update({key: val})
        
        # Initialize defaults
        service.put_data("selected_agent", "claude")
        service.put_data("current_pid", None)
        
        return service


class TestAgentServiceInit:
    """Test agent service initialization."""
    
    def test_init_sets_defaults(self, mock_service):
        """Test that service initializes with default values."""
        assert mock_service.get_data("selected_agent") == "claude"
        assert mock_service.get_data("current_pid") is None


class TestAgentServicePaths:
    """Test path resolution and properties."""
    
    def test_prompts_base_uses_workorders_if_exists(self, mock_service):
        """Test that PROMPTS_BASE returns workorders if it exists."""
        mock_service.WORKORDERS_BASE.mkdir(parents=True, exist_ok=True)
        assert mock_service.PROMPTS_BASE == mock_service.WORKORDERS_BASE
    
    def test_prompts_base_falls_back_to_legacy(self, mock_service):
        """Test that PROMPTS_BASE falls back to legacy prompts."""
        # Don't create workorders, so it falls back
        if mock_service.WORKORDERS_BASE.exists():
            shutil.rmtree(mock_service.WORKORDERS_BASE)
        assert mock_service.PROMPTS_BASE == mock_service.LEGACY_PROMPTS_BASE
    
    def test_ready_dir_property(self, mock_service):
        """Test READY_DIR property."""
        assert mock_service.READY_DIR == mock_service.PROMPTS_BASE / "ready"
    
    def test_wip_dir_property(self, mock_service):
        """Test WIP_DIR property."""
        assert mock_service.WIP_DIR == mock_service.PROMPTS_BASE / "wip"
    
    def test_done_dir_property(self, mock_service):
        """Test DONE_DIR property."""
        assert mock_service.DONE_DIR == mock_service.PROMPTS_BASE / "done"


class TestBuildCmd:
    """Test command building for different agents."""
    
    @patch('csc_service.shared.services.agent_service.Platform')
    def test_build_cmd_unknown_agent(self, mock_platform, mock_service):
        """Test that unknown agent returns empty command."""
        cmd, env = mock_service._build_cmd("unknown_agent", "prompt", "file.md")
        assert cmd == []
        assert env is None
    
    @patch('csc_service.shared.services.agent_service.Platform')
    def test_build_cmd_claude(self, mock_platform, mock_service):
        """Test command building for Claude agent."""
        mock_platform_instance = MagicMock()
        mock_platform_instance.agent_work_base = None
        mock_platform_instance.agent_temp_root = None
        mock_platform.return_value = mock_platform_instance
        
        cmd, env = mock_service._build_cmd("claude", "test prompt", "test.md")
        
        assert cmd is not None
        assert len(cmd) > 0
        assert "cagent" in cmd[0]
    
    @patch('csc_service.shared.services.agent_service.Platform')
    def test_build_cmd_with_repo_clone(self, mock_platform, mock_service, temp_dirs):
        """Test command building with repo clone path."""
        repo_clone = temp_dirs["root"] / "agent_repo"
        repo_clone.mkdir(parents=True, exist_ok=True)
        
        mock_platform_instance = MagicMock()
        mock_platform_instance.agent_work_base = None
        mock_platform_instance.agent_temp_root = None
        mock_platform.return_value = mock_platform_instance
        
        cmd, env = mock_service._build_cmd(
            "claude", 
            "test prompt", 
            "test.md",
            repo_clone_path=repo_clone
        )
        
        assert env is not None
        assert "CSC_AGENT_REPO" in env
        assert env["CSC_AGENT_REPO"] == str(repo_clone)
    
    @patch('csc_service.shared.services.agent_service.Platform')
    def test_build_cmd_local_agent_no_yaml(self, mock_platform, mock_service):
        """Test local agent when cagent.yaml is missing."""
        mock_platform_instance = MagicMock()
        mock_platform_instance.agent_work_base = None
        mock_platform_instance.agent_temp_root = None
        mock_platform.return_value = mock_platform_instance
        
        cmd, env = mock_service._build_cmd("qwen", "prompt", "file.md")
        
        assert cmd == []
        assert env is None
        mock_service.log.assert_called()


class TestListCommand:
    """Test list command."""
    
    @patch('shutil.which')
    def test_list_shows_known_agents(self, mock_which, mock_service):
        """Test that list command shows all known agents."""
        mock_which.return_value = "/bin/cagent"
        
        result = mock_service.list()
        
        assert "claude:" in result
        assert "sonnet:" in result
        assert "gemini:" in result
        assert "qwen:" in result
    
    @patch('shutil.which')
    def test_list_checks_agent_availability(self, mock_which, mock_service):
        """Test that list command checks if agents are available."""
        def which_side_effect(cmd):
            return "/bin/cagent" if cmd == "cagent" else None
        
        mock_which.side_effect = which_side_effect
        
        result = mock_service.list()
        
        # Should indicate cagent availability
        assert "cagent" in result or "[OK]" in result or "[X]" in result


class TestSelectCommand:
    """Test select command."""
    
    def test_select_known_agent(self, mock_service):
        """Test selecting a known agent."""
        result = mock_service.select("sonnet")
        
        assert "sonnet" in result.lower()
        assert mock_service.get_data("selected_agent") == "sonnet"
    
    def test_select_unknown_agent(self, mock_service):
        """Test selecting an unknown agent."""
        result = mock_service.select("nonexistent_agent")
        
        assert "unknown" in result.lower() or "error" in result.lower()
    
    def test_select_persists_choice(self, mock_service):
        """Test that select persists the choice."""
        mock_service.select("opus")
        assert mock_service.get_data("selected_agent") == "opus"


class TestAssignCommand:
    """Test assign command."""
    
    @patch('subprocess.Popen')
    @patch('csc_service.shared.services.agent_service.Platform')
    def test_assign_moves_file_to_wip(self, mock_platform, mock_popen, mock_service, temp_dirs):
        """Test that assign moves file from ready to wip."""
        mock_platform_instance = MagicMock()
        mock_platform_instance.agent_work_base = None
        mock_platform_instance.agent_temp_root = None
        mock_platform.return_value = mock_platform_instance
        
        # Create prompt file in ready
        ready_file = mock_service.READY_DIR / "task.md"
        ready_file.write_text("Test prompt content")
        
        # Mock subprocess
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_popen.return_value = mock_proc
        
        mock_service.select("claude")
        result = mock_service.assign("task.md")
        
        # Check result message
        assert "started" in result.lower() or "assigned" in result.lower()
        
        # Check file moved to wip
        assert not ready_file.exists()
        wip_file = mock_service.WIP_DIR / "task.md"
        assert wip_file.exists()
    
    @patch('subprocess.Popen')
    @patch('csc_service.shared.services.agent_service.Platform')
    def test_assign_stamps_pid_in_file(self, mock_platform, mock_popen, mock_service, temp_dirs):
        """Test that assign stamps PID in WIP file."""
        mock_platform_instance = MagicMock()
        mock_platform_instance.agent_work_base = None
        mock_platform_instance.agent_temp_root = None
        mock_platform.return_value = mock_platform_instance
        
        ready_file = mock_service.READY_DIR / "task.md"
        ready_file.write_text("Test prompt")
        
        mock_proc = MagicMock()
        mock_proc.pid = 5555
        mock_popen.return_value = mock_proc
        
        mock_service.select("claude")
        mock_service.assign("task.md")
        
        wip_file = mock_service.WIP_DIR / "task.md"
        content = wip_file.read_text()
        
        assert "5555" in content or "PID" in content
    
    @patch('subprocess.Popen')
    @patch('csc_service.shared.services.agent_service.Platform')
    def test_assign_stores_metadata(self, mock_platform, mock_popen, mock_service, temp_dirs):
        """Test that assign stores metadata about current task."""
        mock_platform_instance = MagicMock()
        mock_platform_instance.agent_work_base = None
        mock_platform_instance.agent_temp_root = None
        mock_platform.return_value = mock_platform_instance
        
        ready_file = mock_service.READY_DIR / "task.md"
        ready_file.write_text("Test prompt")
        
        mock_proc = MagicMock()
        mock_proc.pid = 7777
        mock_popen.return_value = mock_proc
        
        mock_service.select("claude")
        mock_service.assign("task.md")
        
        assert mock_service.get_data("current_pid") == 7777
        assert mock_service.get_data("current_prompt") == "task.md"
    
    def test_assign_missing_file(self, mock_service):
        """Test assign with non-existent file."""
        result = mock_service.assign("nonexistent.md")
        
        assert "not found" in result.lower() or "error" in result.lower()
    
    def test_assign_no_agent_selected(self, mock_service):
        """Test assign when no agent is selected."""
        ready_file = mock_service.READY_DIR / "task.md"
        ready_file.write_text("Test prompt")
        
        mock_service._data["selected_agent"] = None
        result = mock_service.assign("task.md")
        
        assert "select" in result.lower() or "agent" in result.lower()


class TestStatusCommand:
    """Test status command."""
    
    @patch('os.kill')
    def test_status_idle(self, mock_kill, mock_service):
        """Test status when no agent is running."""
        result = mock_service.status()
        
        assert "idle" in result.lower() or "no" in result.lower() or "none" in result.lower()
    
    @patch('os.kill')
    def test_status_running_process_exists(self, mock_kill, mock_service, temp_dirs):
        """Test status when process is running."""
        mock_kill.return_value = None  # Process exists
        
        mock_service.put_data("current_pid", 1234)
        mock_service.put_data("current_prompt", "task.md")
        mock_service.put_data("started_at", time.time() - 30)
        
        # Create WIP file
        wip_file = mock_service.WIP_DIR / "task.md"
        wip_file.write_text("Task content\n[X] Step 1\n[ ] Step 2")
        
        result = mock_service.status()
        
        assert "running" in result.lower() or "1234" in result
    
    @patch('os.kill')
    def test_status_stale_wip_file(self, mock_kill, mock_service, temp_dirs):
        """Test status detects stale WIP file."""
        mock_kill.return_value = None  # Process exists
        
        mock_service.put_data("current_pid", 1234)
        mock_service.put_data("current_prompt", "task.md")
        
        # Create old WIP file
        wip_file = mock_service.WIP_DIR / "task.md"
        wip_file.write_text("Old content")
        
        # Set mtime to 10 minutes ago
        old_time = time.time() - 600
        os.utime(wip_file, (old_time, old_time))
        
        result = mock_service.status()
        
        # Should warn about stale file
        assert "stale" in result.lower() or "unchanged" in result.lower() or "warning" in result.lower()
    
    @patch('os.kill')
    def test_status_process_dead(self, mock_kill, mock_service, temp_dirs):
        """Test status when process doesn't exist."""
        def kill_error(pid, sig):
            raise ProcessLookupError()
        
        mock_kill.side_effect = kill_error
        
        mock_service.put_data("current_pid", 9999)
        mock_service.put_data("current_prompt", "task.md")
        
        # Create WIP file
        wip_file = mock_service.WIP_DIR / "task.md"
        wip_file.write_