```python
"""Tests for WIPJournal utility class."""

import tempfile
from pathlib import Path

import pytest

from csc_service.shared.utils.wip_journal import WIPJournal


class TestWIPJournal:
    """Test WIPJournal class."""

    @pytest.fixture
    def temp_wip(self):
        """Create a temporary WIP file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wip_path = Path(tmpdir) / "task.md"
            journal = WIPJournal(wip_path)
            yield journal, wip_path

    def test_init_no_file_yet(self, temp_wip):
        """Test initialization when file doesn't exist yet."""
        journal, wip_path = temp_wip
        assert not wip_path.exists()
        assert journal.path == wip_path

    def test_append_entry_creates_file(self, temp_wip):
        """Test that appending entry creates file."""
        journal, wip_path = temp_wip
        success = journal.append_entry("Started task")
        assert success
        assert wip_path.exists()

    def test_append_multiple_entries(self, temp_wip):
        """Test appending multiple entries."""
        journal, wip_path = temp_wip
        assert journal.append_entry("First entry")
        assert journal.append_entry("Second entry")
        assert journal.append_entry("Third entry")

        content = wip_path.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 3
        assert "First entry" in lines[0]
        assert "Third entry" in lines[2]

    def test_stamp_pid(self, temp_wip):
        """Test stamping PID into content."""
        journal, wip_path = temp_wip
        wip_path.write_text("PID: {pending} started\nWorking...")

        success = journal.stamp_pid(12345)
        assert success

        content = wip_path.read_text()
        assert "PID: 12345" in content
        assert "{pending}" not in content

    def test_stamp_pid_returns_false_on_nonexistent_file(self, temp_wip):
        """Test stamp_pid returns False when file doesn't exist."""
        journal, wip_path = temp_wip
        success = journal.stamp_pid(99999)
        assert not success

    def test_get_last_entry(self, temp_wip):
        """Test retrieving last journal entry."""
        journal, wip_path = temp_wip
        journal.append_entry("First")
        journal.append_entry("Second")
        journal.append_entry("Third")

        last = journal.get_last_entry()
        assert "Third" in last

    def test_get_last_entry_empty_file(self, temp_wip):
        """Test get_last_entry on nonexistent file."""
        journal, wip_path = temp_wip
        last = journal.get_last_entry()
        assert last == ""

    def test_get_last_entry_with_blank_lines(self, temp_wip):
        """Test get_last_entry when file ends with blank lines."""
        journal, wip_path = temp_wip
        wip_path.write_text("First\nSecond\nThird\n")
        last = journal.get_last_entry()
        assert last == "Third"

    def test_read_content(self, temp_wip):
        """Test reading full file content."""
        journal, wip_path = temp_wip
        expected = "Line 1\nLine 2\nLine 3"
        wip_path.write_text(expected)

        content = journal.read_content()
        assert content == expected

    def test_read_content_nonexistent(self, temp_wip):
        """Test reading nonexistent file."""
        journal, wip_path = temp_wip
        content = journal.read_content()
        assert content == ""

    def test_write_content(self, temp_wip):
        """Test writing content to file."""
        journal, wip_path = temp_wip
        text = "New content\nMultiple lines"

        success = journal.write_content(text)
        assert success
        assert wip_path.read_text() == text

    def test_write_content_overwrites(self, temp_wip):
        """Test that write_content overwrites existing content."""
        journal, wip_path = temp_wip
        wip_path.write_text("Old content")

        journal.write_content("New content")
        assert wip_path.read_text() == "New content"

    def test_write_content_returns_false_on_permission_error(self, temp_wip):
        """Test write_content returns False on write error."""
        journal, wip_path = temp_wip
        # Create a read-only directory to simulate permission error
        wip_path.parent.chmod(0o444)
        try:
            success = journal.write_content("test content")
            assert not success
        finally:
            wip_path.parent.chmod(0o755)

    def test_exists(self, temp_wip):
        """Test checking file existence."""
        journal, wip_path = temp_wip
        assert not journal.exists()

        wip_path.touch()
        assert journal.exists()

    def test_get_line_count(self, temp_wip):
        """Test getting line count."""
        journal, wip_path = temp_wip
        assert journal.get_line_count() == 0

        wip_path.write_text("Line 1\nLine 2\nLine 3")
        assert journal.get_line_count() == 3

    def test_get_line_count_nonexistent(self, temp_wip):
        """Test line count on nonexistent file."""
        journal, wip_path = temp_wip
        count = journal.get_line_count()
        assert count == 0

    def test_get_line_count_single_line_no_newline(self, temp_wip):
        """Test line count with single line and no trailing newline."""
        journal, wip_path = temp_wip
        wip_path.write_text("Single line")
        assert journal.get_line_count() == 1

    def test_get_line_count_empty_file(self, temp_wip):
        """Test line count on empty file."""
        journal, wip_path = temp_wip
        wip_path.write_text("")
        # Empty file has 0 lines when split
        assert journal.get_line_count() == 0

    def test_get_last_n_lines(self, temp_wip):
        """Test retrieving last N lines."""
        journal, wip_path = temp_wip
        content = "\n".join([f"Line {i}" for i in range(1, 31)])
        wip_path.write_text(content)

        last_10 = journal.get_last_n_lines(10)
        lines = last_10.split("\n")
        assert len(lines) == 10
        assert "Line 30" in lines[-1]
        assert "Line 21" in lines[0]

    def test_get_last_n_lines_fewer_than_requested(self, temp_wip):
        """Test getting last N lines when file has fewer."""
        journal, wip_path = temp_wip
        wip_path.write_text("Line 1\nLine 2")

        last_10 = journal.get_last_n_lines(10)
        assert "Line 1" in last_10
        assert "Line 2" in last_10

    def test_get_last_n_lines_nonexistent(self, temp_wip):
        """Test getting last N lines from nonexistent file."""
        journal, wip_path = temp_wip
        last = journal.get_last_n_lines(20)
        assert last == ""

    def test_get_last_n_lines_zero_lines_requested(self, temp_wip):
        """Test getting 0 lines."""
        journal, wip_path = temp_wip
        wip_path.write_text("Line 1\nLine 2\nLine 3")
        result = journal.get_last_n_lines(0)
        assert result == ""

    def test_crash_recovery_scenario(self, temp_wip):
        """Test realistic crash recovery scenario."""
        journal, wip_path = temp_wip

        # Agent starts, stamps PID
        wip_path.write_text("PID: {pending} started at 2026-02-18\n")
        journal.stamp_pid(5678)

        # Agent logs work steps
        journal.append_entry("read requirements")
        journal.append_entry("created file1.py")
        journal.append_entry("wrote tests")
        # CRASH HERE

        # Next agent resumes, reads last entry
        last_entry = journal.get_last_entry()
        assert "wrote tests" in last_entry

        # Next agent can resume from here
        journal.append_entry("RESTART: resuming from 'wrote tests'")
        journal.append_entry("ran tests - PASSED")

        content = journal.read_content()
        assert "read requirements" in content
        assert "created file1.py" in content
        assert "wrote tests" in content
        assert "RESTART" in content
        assert "PASSED" in content
        assert "PID: 5678" in content

    def test_append_entry_returns_false_on_error(self, temp_wip):
        """Test append_entry returns False on error."""
        journal, wip_path = temp_wip
        # Make parent directory read-only
        wip_path.parent.chmod(0o444)
        try:
            success = journal.append_entry("test entry")
            assert not success
        finally:
            wip_path.parent.chmod(0o755)

    def test_multiline_content_handling(self, temp_wip):
        """Test handling of multiline content."""
        journal, wip_path = temp_wip
        multiline = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        success = journal.write_content(multiline)
        assert success
        assert journal.get_line_count() == 5
        assert journal.read_content() == multiline

    def test_unicode_content(self, temp_wip):
        """Test handling of unicode content."""
        journal, wip_path = temp_wip
        unicode_text = "Unicode: 日本語 émojis 🎉 special chars: ñ, ü, ø"
        success = journal.write_content(unicode_text)
        assert success
        assert journal.read_content() == unicode_text

    def test_special_characters_in_entries(self, temp_wip):
        """Test appending entries with special characters."""
        journal, wip_path = temp_wip
        journal.append_entry("Task: compile C++ code with -O2 flag")
        journal.append_entry("Path: /usr/local/bin/tool")
        journal.append_entry("Query: SELECT * FROM users WHERE id > 5")
        
        content = journal.read_content()
        assert "C++" in content
        assert "-O2" in content
        assert "SELECT *" in content

    def test_consecutive_operations(self, temp_wip):
        """Test sequence of consecutive operations."""
        journal, wip_path = temp_wip
        
        # Write initial content
        assert journal.write_content("Initial")
        assert journal.exists()
        assert journal.get_line_count() == 1
        
        # Append entry
        assert journal.append_entry("Added")
        assert journal.get_line_count() == 2
        
        # Read and verify
        assert "Initial" in journal.read_content()
        assert "Added" in journal.get_last_entry()
        
        # Overwrite
        assert journal.write_content("Overwritten")
        assert journal.get_line_count() == 1
        assert "Initial" not in journal.read_content()

    def test_get_last_n_lines_exact_match(self, temp_wip):
        """Test getting exactly the number of lines in file."""
        journal, wip_path = temp_wip
        wip_path.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5")
        
        result = journal.get_last_n_lines(5)
        lines = result.split("\n")
        assert len(lines) == 5
        assert "Line 1" in result
        assert "Line 5" in result

    def test_path_as_string(self):
        """Test initialization with path as string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wip_str = str(Path(tmpdir) / "test.md")
            journal = WIPJournal(wip_str)
            assert journal.path == Path(wip_str)
            assert journal.append_entry("test")
            assert Path(wip_str).exists()

    def test_nested_directory_creation(self):
        """Test with nested directory (parent must exist)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = Path(tmpdir) / "subdir" / "task.md"
            nested_path.parent.mkdir(parents=True, exist_ok=True)
            journal = WIPJournal(nested_path)
            assert journal.append_entry("nested test")
            assert nested_path.exists()
```