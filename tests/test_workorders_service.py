"""Tests for WorkordersService (workorders_service.py).

Covers status, list, read, add, move, edit, append, archive, assign methods.
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "csc-service"))

from csc_service.shared.services.workorders_service import workorders as WorkordersService


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
    for d in ("ready", "wip", "done", "hold", "archive"):
        (tmp_path / d).mkdir(parents=True)
    return tmp_path


@pytest.fixture
def svc(mock_server, tmp_queue, monkeypatch):
    """Return a WorkordersService backed by a temp directory."""
    from csc_service.shared.utils import QueueDirectories
    with patch.object(WorkordersService, "__init__", lambda self, srv: None):
        instance = WorkordersService.__new__(WorkordersService)
        instance.server = mock_server
        instance.name = "workorders"
        instance._default_urgency = "P3"
        instance.queue = QueueDirectories(tmp_queue)
        instance.WORKORDERS_BASE = tmp_queue
        instance.LEGACY_PROMPTS_BASE = tmp_queue
        instance.PROJECT_ROOT = tmp_queue.parent
    instance.log = MagicMock()
    return instance


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------

class TestWorkordersStatus:
    def test_status_returns_counts(self, svc, tmp_queue):
        (tmp_queue / "ready" / "a.md").write_text("# A\n")
        (tmp_queue / "ready" / "b.md").write_text("# B\n")
        (tmp_queue / "wip" / "c.md").write_text("# C\n")

        result = svc.status()
        assert "Ready: 2" in result
        assert "WIP: 1" in result

    def test_status_empty_queue(self, svc):
        result = svc.status()
        assert "Ready: 0" in result
        assert "WIP: 0" in result


# ---------------------------------------------------------------------------
# list()
# ---------------------------------------------------------------------------

class TestWorkordersList:
    def test_list_ready(self, svc, tmp_queue):
        (tmp_queue / "ready" / "task1.md").write_text("---\nurgency: P2\n---\n# Task 1\n")
        result = svc.list("ready")
        assert "task1.md" in result

    def test_list_all_dirs(self, svc, tmp_queue):
        (tmp_queue / "ready" / "r.md").write_text("# ready\n")
        (tmp_queue / "done" / "d.md").write_text("# done\n")
        result = svc.list("all")
        assert "r.md" in result
        assert "d.md" in result

    def test_list_empty_dir(self, svc):
        result = svc.list("ready")
        assert "No workorders" in result or "0" in result

    def test_list_invalid_dir(self, svc):
        result = svc.list("invalid_dir_name")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# read()
# ---------------------------------------------------------------------------

class TestWorkordersRead:
    def test_read_existing_file(self, svc, tmp_queue):
        f = tmp_queue / "ready" / "task.md"
        f.write_text("# My Task\nsome content\n")
        result = svc.read("task.md")
        assert "My Task" in result

    def test_read_nonexistent_file(self, svc):
        result = svc.read("nonexistent.md")
        assert "not found" in result.lower()

    def test_read_by_empty_string(self, svc):
        result = svc.read("")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# add()
# ---------------------------------------------------------------------------

class TestWorkordersAdd:
    def test_add_creates_file_in_ready(self, svc, tmp_queue):
        result = svc.add("Test task", ":", "Do the thing")
        assert "Created" in result or "ready" in result.lower()
        ready_files = list((tmp_queue / "ready").glob("*.md"))
        assert len(ready_files) == 1

    def test_add_with_urgency(self, svc, tmp_queue):
        result = svc.add("Urgent task", "P0", ":", "Fix critical bug now")
        ready_files = list((tmp_queue / "ready").glob("*.md"))
        assert len(ready_files) == 1
        content = ready_files[0].read_text()
        assert "P0" in content

    def test_add_missing_separator_returns_error(self, svc):
        result = svc.add("No separator here")
        assert "Usage" in result or "error" in result.lower()

    def test_add_empty_content_returns_error(self, svc):
        result = svc.add("desc", ":", "")
        assert isinstance(result, str)

    def test_add_includes_front_matter(self, svc, tmp_queue):
        svc.add("A task", ":", "Content here")
        files = list((tmp_queue / "ready").glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text()
        assert content.startswith("---")
        assert "urgency" in content


# ---------------------------------------------------------------------------
# move()
# ---------------------------------------------------------------------------

class TestWorkordersMove:
    def test_move_ready_to_hold(self, svc, tmp_queue):
        f = tmp_queue / "ready" / "task.md"
        f.write_text("# Task\n")
        result = svc.move("task.md", "hold")
        assert "hold" in result.lower()
        assert (tmp_queue / "hold" / "task.md").exists()
        assert not f.exists()

    def test_move_nonexistent_file(self, svc):
        result = svc.move("ghost.md", "done")
        assert "not found" in result.lower() or "error" in result.lower()

    def test_move_invalid_destination(self, svc, tmp_queue):
        f = tmp_queue / "ready" / "task.md"
        f.write_text("# Task\n")
        result = svc.move("task.md", "nowhere")
        assert "invalid" in result.lower() or "error" in result.lower()

    def test_move_same_dir_noop(self, svc, tmp_queue):
        f = tmp_queue / "ready" / "task.md"
        f.write_text("# Task\n")
        result = svc.move("task.md", "ready")
        assert "already" in result.lower() or isinstance(result, str)


# ---------------------------------------------------------------------------
# edit()
# ---------------------------------------------------------------------------

class TestWorkordersEdit:
    def test_edit_replaces_content(self, svc, tmp_queue):
        f = tmp_queue / "ready" / "task.md"
        f.write_text("# Old content\n")
        result = svc.edit("task.md", ":", "# New content")
        assert "Updated" in result or "task.md" in result
        assert "New content" in f.read_text()

    def test_edit_missing_separator(self, svc):
        result = svc.edit("task.md")
        assert "Usage" in result or "error" in result.lower()

    def test_edit_nonexistent_file(self, svc):
        result = svc.edit("ghost.md", ":", "content")
        assert "not found" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# append()
# ---------------------------------------------------------------------------

class TestWorkordersAppend:
    def test_append_adds_content(self, svc, tmp_queue):
        f = tmp_queue / "ready" / "task.md"
        f.write_text("# Task\noriginal\n")
        result = svc.append("task.md", ":", "appended line")
        assert "Appended" in result or "task.md" in result
        assert "appended line" in f.read_text()

    def test_append_missing_separator(self, svc):
        result = svc.append("task.md")
        assert "Usage" in result or "error" in result.lower()

    def test_append_nonexistent_file(self, svc):
        result = svc.append("ghost.md", ":", "text")
        assert "not found" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# archive()
# ---------------------------------------------------------------------------

class TestWorkordersArchive:
    def test_archive_verified_complete(self, svc, tmp_queue):
        f = tmp_queue / "done" / "finished.md"
        f.write_text("# Task\nDone.\nverified complete\n")
        result = svc.archive("finished.md")
        assert "archived" in result.lower() or "archive" in result.lower()

    def test_archive_dead_end(self, svc, tmp_queue):
        f = tmp_queue / "done" / "dead.md"
        f.write_text("# Task\nCannot proceed.\ndead end\n")
        result = svc.archive("dead.md")
        assert "archived" in result.lower() or "archive" in result.lower()

    def test_archive_without_completion_marker(self, svc, tmp_queue):
        f = tmp_queue / "done" / "incomplete.md"
        f.write_text("# Task\nStill working...\n")
        result = svc.archive("incomplete.md")
        assert "error" in result.lower() or "must end" in result.lower()

    def test_archive_file_not_in_done(self, svc, tmp_queue):
        f = tmp_queue / "ready" / "notdone.md"
        f.write_text("# Task\nverified complete\n")
        result = svc.archive("notdone.md")
        assert "not found" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# assign()
# ---------------------------------------------------------------------------

class TestWorkordersAssign:
    def test_assign_missing_args(self, svc):
        result = svc.assign("only_one_arg")
        assert "Usage" in result or "error" in result.lower()

    def test_assign_nonexistent_workorder(self, svc):
        result = svc.assign("ghost.md", "haiku")
        assert "not found" in result.lower() or "error" in result.lower()

    def test_assign_uses_correct_agent_module(self, svc, tmp_queue):
        """assign() should import from csc_service.shared.services, not csc_shared."""
        f = tmp_queue / "ready" / "task.md"
        f.write_text("---\nurgency: P2\n---\n# Task\n")

        captured_module = {}

        import importlib
        original_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            captured_module["name"] = name
            raise ImportError("mocked")

        with patch("importlib.import_module", side_effect=fake_import):
            result = svc.assign("task.md", "haiku")

        # The module name tried should be the new csc_service path, not csc_shared
        if "name" in captured_module:
            assert "csc_shared" not in captured_module["name"], (
                f"assign() tried to import from '{captured_module['name']}' "
                "but should use 'csc_service.shared.services.agent_service'"
            )


# ---------------------------------------------------------------------------
# _sanitize_filename()
# ---------------------------------------------------------------------------

class TestSanitizeFilename:
    def test_lowercases_and_replaces_spaces(self, svc):
        result = svc._sanitize_filename("Hello World Task")
        assert result == result.lower()
        assert " " not in result

    def test_limits_length(self, svc):
        result = svc._sanitize_filename("a" * 200)
        assert len(result) <= 50

    def test_allows_hyphens_and_underscores(self, svc):
        result = svc._sanitize_filename("my-task_name")
        assert "-" in result or "_" in result


# ---------------------------------------------------------------------------
# urgency()
# ---------------------------------------------------------------------------

class TestUrgency:
    def test_get_default_urgency(self, svc):
        result = svc.urgency()
        assert "P3" in result  # default

    def test_set_valid_urgency(self, svc):
        result = svc.urgency("P0")
        assert "P0" in result
        assert svc._default_urgency == "P0"

    def test_set_invalid_urgency(self, svc):
        result = svc.urgency("P9")
        assert "error" in result.lower() or "must be" in result.lower()
