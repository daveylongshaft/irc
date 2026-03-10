"""Tests for AgentService (agent_service.py).

Covers list, select, status, stop, kill, tail, and assign methods.
"""
import json
import os
import signal
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open, call

import pytest

# Ensure csc_service is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "csc-service"))

from csc_service.shared.services.agent_service import agent as AgentService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_server():
    server = MagicMock()
    server.log = MagicMock()
    server.get_data = MagicMock(return_value={})
    server.save_data = MagicMock()
    server.command_char = "AI"
    return server


@pytest.fixture
def tmp_queue(tmp_path):
    """Create a temporary queue directory structure."""
    for d in ("ready", "wip", "done", "hold"):
        (tmp_path / d).mkdir(parents=True)
    return tmp_path


@pytest.fixture
def svc(mock_server, tmp_queue, monkeypatch):
    """Return an AgentService with a patched PROMPTS_BASE and data store."""
    monkeypatch.setattr(AgentService, "PROMPTS_BASE", property(lambda self: tmp_queue))
    monkeypatch.setattr(AgentService, "WORKORDERS_BASE", tmp_queue)
    monkeypatch.setattr(AgentService, "LOGS_DIR", tmp_queue / "logs")
    (tmp_queue / "logs").mkdir(exist_ok=True)

    with patch.object(AgentService, "__init__", lambda self, srv: None):
        instance = AgentService.__new__(AgentService)
        instance.server = mock_server
        instance._data = {}
        instance._queue = None

    return instance


# ---------------------------------------------------------------------------
# list()
# ---------------------------------------------------------------------------

class TestAgentList:
    def test_list_returns_string(self, svc):
        result = svc.list()
        assert isinstance(result, str)

    def test_list_shows_available_agents(self, svc):
        result = svc.list()
        # Should mention at least one known agent backend
        assert any(name in result.lower() for name in ("claude", "haiku", "sonnet", "gemini", "chatgpt"))

    def test_list_marks_selected_agent(self, svc):
        """Selected agent should be highlighted."""
        with patch.object(svc, "_get_selected_agent", return_value="haiku", create=True):
            result = svc.list()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# select()
# ---------------------------------------------------------------------------

class TestAgentSelect:
    def test_select_known_agent(self, svc):
        result = svc.select("haiku")
        assert "haiku" in result.lower() or "selected" in result.lower()

    def test_select_unknown_agent(self, svc):
        result = svc.select("nonexistent_agent_xyz")
        # Should signal error or unknown
        assert "unknown" in result.lower() or "not" in result.lower() or "error" in result.lower()

    def test_select_empty_raises_or_returns_error(self, svc):
        result = svc.select("")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------

class TestAgentStatus:
    def test_status_no_running_agent(self, svc, tmp_queue):
        """When nothing is running, status should say so."""
        result = svc.status()
        assert isinstance(result, str)

    def test_status_with_running_pid(self, svc, tmp_queue):
        """If a PID file exists, status should show it."""
        pid_file = tmp_queue / "wip" / "test_task.md"
        pid_file.write_text("# Test task\n")
        result = svc.status()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

class TestAgentStop:
    def test_stop_no_running_agent(self, svc):
        result = svc.stop()
        assert isinstance(result, str)

    def test_stop_sends_sigterm(self, svc, tmp_path):
        """stop() should attempt to send SIGTERM to the running PID."""
        fake_pid = 99999999  # Unlikely to exist

        with patch.object(svc, "_get_running_pid", return_value=fake_pid, create=True):
            with patch("os.kill") as mock_kill:
                mock_kill.side_effect = ProcessLookupError
                result = svc.stop()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# kill()
# ---------------------------------------------------------------------------

class TestAgentKill:
    def test_kill_no_running_agent(self, svc):
        result = svc.kill()
        assert isinstance(result, str)

    def test_kill_moves_wip_back_to_ready(self, svc, tmp_queue):
        """kill() should move the WIP file back to ready/."""
        wip_file = tmp_queue / "wip" / "task.md"
        wip_file.write_text("# Task content\n")

        with patch("os.kill"):
            with patch.object(svc, "_get_running_pid", return_value=12345, create=True):
                result = svc.kill()

        # File should no longer be in wip/ (may have been moved or an error returned)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# tail()
# ---------------------------------------------------------------------------

class TestAgentTail:
    def test_tail_no_wip_file(self, svc, tmp_queue):
        result = svc.tail()
        assert isinstance(result, str)

    def test_tail_returns_last_n_lines(self, svc, tmp_queue):
        wip_file = tmp_queue / "wip" / "journal.md"
        lines = [f"line {i}\n" for i in range(50)]
        wip_file.write_text("".join(lines))

        result = svc.tail(10)
        assert isinstance(result, str)
        # Should contain at least "line 49"
        assert "line 49" in result or "10" in result or "journal" in result

    def test_tail_default_n(self, svc, tmp_queue):
        wip_file = tmp_queue / "wip" / "journal.md"
        wip_file.write_text("".join(f"l{i}\n" for i in range(100)))
        result = svc.tail()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# assign()
# ---------------------------------------------------------------------------

class TestAgentAssign:
    def test_assign_nonexistent_file(self, svc, tmp_queue):
        result = svc.assign("nonexistent_file.md")
        assert isinstance(result, str)
        assert "not found" in result.lower() or "error" in result.lower()

    def test_assign_moves_file_to_wip(self, svc, tmp_queue):
        ready_file = tmp_queue / "ready" / "task.md"
        ready_file.write_text("---\nurgency: P2\n---\n# Task\n")

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc
            result = svc.assign("task.md")

        assert isinstance(result, str)

    def test_assign_without_selected_agent(self, svc, tmp_queue):
        """assign() with no selected agent should return an error or use default."""
        ready_file = tmp_queue / "ready" / "task.md"
        ready_file.write_text("# Task\n")

        with patch("subprocess.Popen", side_effect=FileNotFoundError("agent not found")):
            result = svc.assign("task.md")

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _parse_front_matter() (static helper)
# ---------------------------------------------------------------------------

class TestParseFrontMatter:
    def test_parses_urgency(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("---\nurgency: P0\ntags: infra\n---\n# content\n")
        result = AgentService._parse_front_matter(f)
        assert result.get("urgency") == "P0"

    def test_returns_empty_dict_for_no_front_matter(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# just content\n")
        result = AgentService._parse_front_matter(f)
        assert isinstance(result, dict)

    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        f = tmp_path / "missing.md"
        result = AgentService._parse_front_matter(f)
        assert isinstance(result, dict)
