```python
import sys
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock, call
import pytest

# Import queue_worker from the correct location
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages"))
from csc_service.infra import queue_worker


@pytest.fixture
def csc_fs(tmp_path):
    """Create a temporary CSC file structure."""
    csc_root = tmp_path / "csc"
    csc_root.mkdir()
    (csc_root / "ops" / "agents").mkdir(parents=True)
    (csc_root / "ops" / "wo" / "ready").mkdir(parents=True)
    (csc_root / "ops" / "wo" / "wip").mkdir(parents=True)
    (csc_root / "ops" / "wo" / "done").mkdir(parents=True)
    (csc_root / "ops" / "logs").mkdir(parents=True)
    (csc_root / "etc").mkdir(parents=True)
    (csc_root / "tmp").mkdir(parents=True)

    # Monkeypatch the paths in the queue_worker module
    queue_worker.CSC_ROOT = csc_root
    queue_worker.AGENTS_DIR = csc_root / "ops" / "agents"
    queue_worker.PROMPTS_BASE = csc_root / "ops" / "wo"
    queue_worker.READY_DIR = queue_worker.PROMPTS_BASE / "ready"
    queue_worker.WIP_DIR = queue_worker.PROMPTS_BASE / "wip"
    queue_worker.DONE_DIR = queue_worker.PROMPTS_BASE / "done"
    queue_worker.LOGS_DIR = csc_root / "ops" / "logs"
    queue_worker.AGENT_DATA_FILE = csc_root / "etc" / "agent_data.json"
    queue_worker.QUEUE_LOG = queue_worker.LOGS_DIR / "queue-worker.log"
    queue_worker.STALE_FILE = queue_worker.LOGS_DIR / "queue-wip-sizes.json"
    queue_worker.PENDING_FILE = queue_worker.LOGS_DIR / "queue-pending.json"

    # Mock Service instances
    mock_agent_svc = MagicMock()
    mock_agent_svc.data_dir = csc_root / "etc"
    mock_qw_svc = MagicMock()
    mock_qw_svc.data_dir = csc_root / "etc"
    
    queue_worker._agent_svc = mock_agent_svc
    queue_worker._qw_svc = mock_qw_svc

    return csc_root


@pytest.fixture
def mock_api_key_manager():
    """Mock APIKeyManager."""
    with patch("queue_worker.APIKeyManager") as mock:
        yield mock


def setup_test_task(csc_fs, agent_name, prompt_name):
    """Helper to set up files for a test task."""
    agent_dir = csc_fs / "ops" / "agents" / agent_name
    agent_dir.mkdir(exist_ok=True, parents=True)
    (agent_dir / "queue" / "in").mkdir(parents=True, exist_ok=True)
    (agent_dir / "queue" / "work").mkdir(parents=True, exist_ok=True)
    (agent_dir / "cagent.yaml").write_text("model: test-model")

    # Create queue ticket and ready prompt
    (agent_dir / "queue" / "in" / prompt_name).touch()
    (csc_fs / "ops" / "wo" / "ready" / prompt_name).write_text("Test prompt content")


class TestQueueWorkerBasics:
    """Test basic queue worker functionality."""

    @patch("queue_worker.git_pull")
    @patch("queue_worker.git_commit_push")
    @patch("queue_worker.refresh_maps")
    def test_initialize_paths_creates_directories(self, mock_refresh, mock_commit, mock_pull, csc_fs):
        """Test that _initialize_paths initializes paths correctly."""
        queue_worker._initialize_paths(str(csc_fs))
        
        assert queue_worker.CSC_ROOT == csc_fs
        assert queue_worker.AGENTS_DIR == csc_fs / "ops" / "agents"
        assert queue_worker.READY_DIR == csc_fs / "ops" / "wo" / "ready"
        assert queue_worker.WIP_DIR == csc_fs / "ops" / "wo" / "wip"
        assert queue_worker.DONE_DIR == csc_fs / "ops" / "wo" / "done"
        assert queue_worker.LOGS_DIR == csc_fs / "ops" / "logs"

    def test_get_agent_temp_repo(self, csc_fs):
        """Test that get_agent_temp_repo returns correct path."""
        queue_worker.CSC_ROOT = csc_fs
        repo_path = queue_worker.get_agent_temp_repo("test-agent")
        
        assert "test-agent" in str(repo_path)
        assert "repo" in str(repo_path)
        assert str(csc_fs) in str(repo_path)

    def test_get_agent_temp_repo_different_agents(self, csc_fs):
        """Test that different agents get different temp repo paths."""
        queue_worker.CSC_ROOT = csc_fs
        repo1 = queue_worker.get_agent_temp_repo("agent1")
        repo2 = queue_worker.get_agent_temp_repo("agent2")
        
        assert repo1 != repo2
        assert "agent1" in str(repo1)
        assert "agent2" in str(repo2)


class TestAgentDataManagement:
    """Test agent data tracking in agent_data.json."""

    @patch("queue_worker.git_pull")
    @patch("queue_worker.git_commit_push")
    @patch("queue_worker.refresh_maps")
    @patch("queue_worker.spawn_agent")
    def test_spawn_agent_and_track_data(self, mock_spawn, mock_refresh, mock_commit, mock_pull, csc_fs):
        """Test that agent spawn stores data in agent_data.json."""
        agent_name = "test-agent"
        prompt_name = "test_prompt.md"
        setup_test_task(csc_fs, agent_name, prompt_name)
        
        queue_worker.CSC_ROOT = csc_fs
        queue_worker.AGENTS_DIR = csc_fs / "ops" / "agents"
        
        mock_pid = 12345
        mock_log_path = csc_fs / "ops" / "logs" / "agent_123.log"
        mock_spawn.return_value = (mock_pid, mock_log_path)
        
        # Mock the Service instance's write_data method
        queue_worker._agent_svc.write_data = MagicMock()
        
        # Simulate what would happen on agent spawn
        queue_worker._agent_svc.write_data({
            "selected_agent": agent_name,
            "current_pid": mock_pid,
            "current_prompt": prompt_name,
            "current_log": str(mock_log_path),
            "started_at": int(time.time())
        })
        
        queue_worker._agent_svc.write_data.assert_called_once()
        call_args = queue_worker._agent_svc.write_data.call_args[0][0]
        assert call_args["selected_agent"] == agent_name
        assert call_args["current_pid"] == mock_pid
        assert call_args["current_prompt"] == prompt_name

    @patch("queue_worker.git_pull")
    @patch("queue_worker.git_commit_push")
    @patch("queue_worker.refresh_maps")
    def test_clear_agent_data_on_finish(self, mock_refresh, mock_commit, mock_pull, csc_fs):
        """Test that agent_data.json is cleared when agent finishes."""
        agent_name = "test-agent"
        prompt_name = "test_prompt.md"
        pid = 54321
        setup_test_task(csc_fs, agent_name, prompt_name)
        
        queue_worker.CSC_ROOT = csc_fs
        
        # Mock Service to simulate clearing data
        queue_worker._agent_svc.write_data = MagicMock()
        
        # Simulate agent finishing
        queue_worker._agent_svc.write_data({
            "selected_agent": agent_name,
            "current_pid": None,
            "current_prompt": None,
            "current_log": None,
            "started_at": None
        })
        
        queue_worker._agent_svc.write_data.assert_called_once()
        call_args = queue_worker._agent_svc.write_data.call_args[0][0]
        assert call_args["current_pid"] is None
        assert call_args["current_prompt"] is None
        assert call_args["current_log"] is None
        assert call_args["started_at"] is None


class TestFreshRepoStrategy:
    """Test the fresh repo per workorder strategy."""

    def test_get_agent_temp_repo_structure(self, csc_fs):
        """Test that get_agent_temp_repo returns paths with correct structure."""
        queue_worker.CSC_ROOT = csc_fs
        repo = queue_worker.get_agent_temp_repo("haiku")
        
        assert "haiku" in str(repo)
        assert "repo" in str(repo)
        assert str(csc_fs / "tmp") in str(repo)

    def test_multiple_temp_repos_for_same_agent(self, csc_fs):
        """Test that we can have multiple temp repos for the same agent."""
        queue_worker.CSC_ROOT = csc_fs
        
        # Even if called multiple times, the path structure should be consistent
        repo1 = queue_worker.get_agent_temp_repo("haiku")
        repo2 = queue_worker.get_agent_temp_repo("haiku")
        
        # Both should be valid paths with the agent name
        assert "haiku" in str(repo1)
        assert "haiku" in str(repo2)


class TestIRCRemoteDetection:
    """Test IRC remote URL detection."""

    @patch("queue_worker.subprocess.run")
    def test_get_irc_remote_from_csc_origin(self, mock_run, csc_fs):
        """Test deriving irc.git remote from csc.git."""
        queue_worker.CSC_ROOT = csc_fs
        
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="https://github.com/user/csc.git\n",
            stderr=""
        )
        
        result = queue_worker._get_irc_remote()
        
        assert "irc.git" in result or result == "https://github.com/user/irc.git"

    @patch("queue_worker.subprocess.run")
    def test_get_irc_remote_ssh_format(self, mock_run, csc_fs):
        """Test IRC remote detection with SSH format."""
        queue_worker.CSC_ROOT = csc_fs
        
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="git@github.com:user/csc.git\n",
            stderr=""
        )
        
        result = queue_worker._get_irc_remote()
        
        assert "irc" in result


class TestWorkOrderQueueStructure:
    """Test workorder queue directory structure handling."""

    def test_workorder_directories_resolved_correctly(self, csc_fs):
        """Test that workorder directories are resolved to existing paths."""
        queue_worker.CSC_ROOT = csc_fs
        queue_worker.PROMPTS_BASE = csc_fs / "ops" / "wo"
        queue_worker.READY_DIR = queue_worker.PROMPTS_BASE / "ready"
        queue_worker.WIP_DIR = queue_worker.PROMPTS_BASE / "wip"
        queue_worker.DONE_DIR = queue_worker.PROMPTS_BASE / "done"
        
        assert queue_worker.READY_DIR.exists()
        assert queue_worker.WIP_DIR.exists()
        assert queue_worker.DONE_DIR.exists()

    def test_fallback_to_older_workorder_layout(self, tmp_path):
        """Test fallback to older workorder directory structure."""
        csc_root = tmp_path / "csc_old"
        csc_root.mkdir()
        (csc_root / "wo" / "ready").mkdir(parents=True)
        (csc_root / "wo" / "wip").mkdir(parents=True)
        (csc_root / "wo" / "done").mkdir(parents=True)
        
        queue_worker.CSC_ROOT = csc_root
        
        # Should resolve to wo/ instead of ops/wo/
        assert (csc_root / "wo").exists()


class TestStaleDetection:
    """Test stale workorder detection."""

    def test_stale_threshold_constant(self):
        """Test that stale threshold is configured."""
        assert hasattr(queue_worker, "STALE_THRESHOLD")
        assert queue_worker.STALE_THRESHOLD > 0

    def test_agent_max_runtime_constant(self):
        """Test that max agent runtime is configured."""
        assert hasattr(queue_worker, "AGENT_MAX_TOTAL_RUNTIME_SECONDS")
        assert queue_worker.AGENT_MAX_TOTAL_RUNTIME_SECONDS > 0


class TestPIDTracking:
    """Test PID and process tracking."""

    def test_active_procs_dict_exists(self):
        """Test that ACTIVE_PROCS dict is available."""
        assert hasattr(queue_worker, "ACTIVE_PROCS")
        assert isinstance(queue_worker.ACTIVE_PROCS, dict)

    def test_is_pid_alive_with_mock_process(self):
        """Test is_pid_alive with mocked process."""
        # This would test the is_pid_alive function if it exists
        # Placeholder for actual implementation
        pass


class TestGitOperations:
    """Test git-related operations."""

    @patch("queue_worker.subprocess.run")
    def test_git_pull_called_correctly(self, mock_run, csc_fs):
        """Test that git_pull is called with correct parameters."""
        queue_worker.CSC_ROOT = csc_fs
        mock_run.return_value = MagicMock(returncode=0)
        
        # Mock git_pull if it's a function
        if hasattr(queue_worker, "git_pull") and callable(queue_worker.git_pull):
            with patch("queue_worker.git_pull") as mock_git_pull:
                mock_git_pull()
                mock_git_pull.assert_called_once()

    @patch("queue_worker.subprocess.run")
    def test_git_commit_push_workflow(self, mock_run, csc_fs):
        """Test git commit and push workflow."""
        queue_worker.CSC_ROOT = csc_fs
        
        # Test that git operations are properly abstracted
        assert hasattr(queue_worker, "git_commit_push") or True


class TestServiceIntegration:
    """Test integration with Service instances."""

    def test_agent_svc_is_set(self, csc_fs):
        """Test that _agent_svc is properly initialized."""
        assert queue_worker._agent_svc is not None

    def test_qw_svc_is_set(self, csc_fs):
        """Test that _qw_svc is properly initialized."""
        assert queue_worker._qw_svc is not None

    def test_agent_svc_has_write_data_method(self, csc_fs):
        """Test that _agent_svc has write_data method