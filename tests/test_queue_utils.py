```python
"""Tests for QueueDirectories utility class."""

import tempfile
from pathlib import Path

import pytest

from csc_service.shared.utils.queue_utils import QueueDirectories


class TestQueueDirectories:
    """Test QueueDirectories class."""

    @pytest.fixture
    def temp_queue(self):
        """Create a temporary queue directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = QueueDirectories(Path(tmpdir))
            yield queue

    def test_init_creates_directories(self, temp_queue):
        """Test that initialization creates all directories."""
        assert temp_queue.get("ready").exists()
        assert temp_queue.get("wip").exists()
        assert temp_queue.get("done").exists()
        assert temp_queue.get("hold").exists()
        assert temp_queue.get("archive").exists()

    def test_get_returns_correct_path(self, temp_queue):
        """Test that get() returns correct directory paths."""
        ready = temp_queue.get("ready")
        assert ready.name == "ready"
        assert ready.exists()

    def test_get_returns_none_for_invalid_directory(self, temp_queue):
        """Test that get() returns None for invalid directory names."""
        result = temp_queue.get("invalid")
        assert result is None

    def test_list_files_empty_directory(self, temp_queue):
        """Test listing files in empty directory."""
        files = temp_queue.list_files("ready")
        assert files == []

    def test_list_files_with_markdown(self, temp_queue):
        """Test listing markdown files."""
        # Create test files
        (temp_queue.get("ready") / "test1.md").touch()
        (temp_queue.get("ready") / "test2.md").touch()
        (temp_queue.get("ready") / "test.txt").touch()  # Should not be listed

        files = temp_queue.list_files("ready")
        assert len(files) == 2
        assert "test1.md" in files
        assert "test2.md" in files
        assert "test.txt" not in files

    def test_list_files_sorted(self, temp_queue):
        """Test that files are returned sorted."""
        ready = temp_queue.get("ready")
        (ready / "zebra.md").touch()
        (ready / "apple.md").touch()
        (ready / "banana.md").touch()

        files = temp_queue.list_files("ready")
        assert files == ["apple.md", "banana.md", "zebra.md"]

    def test_list_files_custom_suffix(self, temp_queue):
        """Test listing files with custom suffix."""
        ready = temp_queue.get("ready")
        (ready / "test1.txt").touch()
        (ready / "test2.txt").touch()
        (ready / "test.md").touch()

        files = temp_queue.list_files("ready", suffix=".txt")
        assert len(files) == 2
        assert "test1.txt" in files
        assert "test2.txt" in files
        assert "test.md" not in files

    def test_list_files_nonexistent_directory(self, temp_queue):
        """Test listing files in nonexistent directory."""
        files = temp_queue.list_files("nonexistent")
        assert files == []

    def test_find_file_in_ready(self, temp_queue):
        """Test finding file in specific directory."""
        ready = temp_queue.get("ready")
        (ready / "test.md").touch()

        path, dirname = temp_queue.find_file("test.md")
        assert path == ready / "test.md"
        assert dirname == "ready"

    def test_find_file_auto_add_suffix(self, temp_queue):
        """Test that find_file auto-adds .md suffix."""
        ready = temp_queue.get("ready")
        (ready / "test.md").touch()

        path, dirname = temp_queue.find_file("test")  # No .md
        assert path == ready / "test.md"
        assert dirname == "ready"

    def test_find_file_no_auto_suffix(self, temp_queue):
        """Test that find_file respects add_suffix=False."""
        ready = temp_queue.get("ready")
        (ready / "test.txt").touch()

        path, dirname = temp_queue.find_file("test.txt", add_suffix=False)
        assert path == ready / "test.txt"
        assert dirname == "ready"

    def test_find_file_in_any_directory(self, temp_queue):
        """Test finding file across all directories."""
        # Create file in done/
        done = temp_queue.get("done")
        (done / "completed.md").touch()

        path, dirname = temp_queue.find_file("completed.md")
        assert path == done / "completed.md"
        assert dirname == "done"

    def test_find_file_in_archive(self, temp_queue):
        """Test finding file in archive directory."""
        archive = temp_queue.get("archive")
        (archive / "archived.md").touch()

        path, dirname = temp_queue.find_file("archived.md")
        assert path == archive / "archived.md"
        assert dirname == "archive"

    def test_find_file_not_found(self, temp_queue):
        """Test that find_file returns None when not found."""
        path, dirname = temp_queue.find_file("nonexistent.md")
        assert path is None
        assert dirname is None

    def test_find_file_prefers_ready_over_wip(self, temp_queue):
        """Test that find_file returns first match in directory order."""
        ready = temp_queue.get("ready")
        wip = temp_queue.get("wip")

        # Create same file in multiple directories
        (ready / "test.md").touch()
        (wip / "test.md").touch()

        path, dirname = temp_queue.find_file("test.md")
        # Should find in ready (first in ALL_DIRS)
        assert dirname == "ready"

    def test_get_counts(self, temp_queue):
        """Test getting file counts per directory."""
        ready = temp_queue.get("ready")
        wip = temp_queue.get("wip")

        (ready / "file1.md").touch()
        (ready / "file2.md").touch()
        (wip / "working.md").touch()

        counts = temp_queue.get_counts()
        assert counts["ready"] == 2
        assert counts["wip"] == 1
        assert counts["done"] == 0
        assert counts["hold"] == 0
        assert counts["archive"] == 0

    def test_get_counts_all_directories(self, temp_queue):
        """Test that get_counts includes all directories."""
        ready = temp_queue.get("ready")
        done = temp_queue.get("done")
        hold = temp_queue.get("hold")
        archive = temp_queue.get("archive")

        (ready / "r.md").touch()
        (done / "d.md").touch()
        (done / "d2.md").touch()
        (hold / "h.md").touch()
        (archive / "a.md").touch()

        counts = temp_queue.get_counts()
        assert counts["ready"] == 1
        assert counts["wip"] == 0
        assert counts["done"] == 2
        assert counts["hold"] == 1
        assert counts["archive"] == 1

    def test_move_file(self, temp_queue):
        """Test moving file between directories."""
        ready = temp_queue.get("ready")
        done = temp_queue.get("done")

        (ready / "task.md").touch()
        assert (ready / "task.md").exists()

        success = temp_queue.move_file("task.md", "ready", "done")
        assert success
        assert not (ready / "task.md").exists()
        assert (done / "task.md").exists()

    def test_move_file_to_archive(self, temp_queue):
        """Test moving file to archive directory."""
        ready = temp_queue.get("ready")
        archive = temp_queue.get("archive")

        (ready / "old.md").touch()

        success = temp_queue.move_file("old.md", "ready", "archive")
        assert success
        assert not (ready / "old.md").exists()
        assert (archive / "old.md").exists()

    def test_move_file_nonexistent(self, temp_queue):
        """Test moving nonexistent file returns False."""
        success = temp_queue.move_file("ghost.md", "ready", "done")
        assert not success

    def test_move_file_invalid_from_directory(self, temp_queue):
        """Test moving from invalid directory returns False."""
        ready = temp_queue.get("ready")
        (ready / "test.md").touch()

        success = temp_queue.move_file("test.md", "invalid", "done")
        assert not success
        assert (ready / "test.md").exists()

    def test_move_file_invalid_to_directory(self, temp_queue):
        """Test moving to invalid directory returns False."""
        ready = temp_queue.get("ready")
        (ready / "test.md").touch()

        success = temp_queue.move_file("test.md", "ready", "invalid")
        assert not success
        assert (ready / "test.md").exists()  # File should still be in ready

    def test_move_file_same_directory(self, temp_queue):
        """Test moving file to the same directory."""
        ready = temp_queue.get("ready")
        (ready / "test.md").touch()

        success = temp_queue.move_file("test.md", "ready", "ready")
        assert success
        assert (ready / "test.md").exists()

    def test_move_file_overwrites(self, temp_queue):
        """Test that moving a file overwrites destination if it exists."""
        ready = temp_queue.get("ready")
        done = temp_queue.get("done")

        (ready / "test.md").write_text("ready content")
        (done / "test.md").write_text("done content")

        success = temp_queue.move_file("test.md", "ready", "done")
        assert success
        assert not (ready / "test.md").exists()
        assert (done / "test.md").exists()
        assert (done / "test.md").read_text() == "ready content"

    def test_ensure_exist_idempotent(self, temp_queue):
        """Test that ensure_exist can be called multiple times."""
        ready = temp_queue.get("ready")
        (ready / "test.md").touch()

        temp_queue.ensure_exist()

        # File should still exist
        assert (ready / "test.md").exists()
        # Directories should still exist
        assert temp_queue.get("ready").exists()
        assert temp_queue.get("wip").exists()

    def test_all_dirs_constant(self):
        """Test that ALL_DIRS constant contains expected directories."""
        assert "ready" in QueueDirectories.ALL_DIRS
        assert "wip" in QueueDirectories.ALL_DIRS
        assert "done" in QueueDirectories.ALL_DIRS
        assert "hold" in QueueDirectories.ALL_DIRS
        assert "archive" in QueueDirectories.ALL_DIRS
        assert len(QueueDirectories.ALL_DIRS) == 5

    def test_class_constants(self):
        """Test that class constants are defined correctly."""
        assert QueueDirectories.READY == "ready"
        assert QueueDirectories.WIP == "wip"
        assert QueueDirectories.DONE == "done"
        assert QueueDirectories.HOLD == "hold"
        assert QueueDirectories.ARCHIVE == "archive"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```