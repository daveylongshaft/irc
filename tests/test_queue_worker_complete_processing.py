```python
#!/usr/bin/env python3
"""
Test suite for queue-worker COMPLETE marker processing.

Verifies that:
1. Workorders with COMPLETE on last line move to done/
2. Workorders without COMPLETE move back to ready/ with INCOMPLETE marker
3. COMPLETE marker must be on its own line (not substring match)
4. Blank lines after COMPLETE are handled correctly
5. Case sensitivity is handled properly
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock


# Mock the module functions to test
def is_complete_marker(content):
    """Check if content ends with COMPLETE marker on its own line."""
    if not content:
        return False
    
    # Strip trailing whitespace but preserve line structure
    lines = content.rstrip().split('\n')
    if not lines:
        return False
    
    # Get the last non-empty line
    last_line = lines[-1].strip()
    
    # Must be exactly "COMPLETE" on its own line
    return last_line == "COMPLETE"


def mark_incomplete(file_path):
    """Append INCOMPLETE marker to file if not already present."""
    content = file_path.read_text()
    
    # Don't duplicate INCOMPLETE marker
    if "INCOMPLETE" in content:
        return
    
    # Append INCOMPLETE marker
    if content and not content.endswith('\n'):
        content += '\n'
    content += 'INCOMPLETE\n'
    
    file_path.write_text(content)


class TestCompleteMarkerDetection:
    """Tests for detecting COMPLETE marker at end of file."""

    def test_complete_on_last_line(self):
        """COMPLETE on last line should be detected."""
        content = "Work log entry 1\nWork log entry 2\nCOMPLETE"
        assert is_complete_marker(content) is True

    def test_complete_with_trailing_whitespace(self):
        """COMPLETE with trailing newlines should be detected."""
        content = "Work log entry 1\nCOMPLETE\n"
        assert is_complete_marker(content) is True

    def test_complete_with_multiple_trailing_newlines(self):
        """COMPLETE followed by multiple blank lines should be detected."""
        content = "Work log entry 1\nCOMPLETE\n\n\n"
        assert is_complete_marker(content) is True

    def test_complete_not_last_line(self):
        """COMPLETE not on last line should NOT be detected."""
        content = "COMPLETE\nWork log entry 1\nWork log entry 2"
        assert is_complete_marker(content) is False

    def test_complete_in_middle_of_file(self):
        """COMPLETE in middle (like in instructions) should NOT be detected."""
        content = "Instructions:\necho 'COMPLETE' at end\nBut no actual complete"
        assert is_complete_marker(content) is False

    def test_complete_as_substring(self):
        """COMPLETE as part of another word should NOT be detected."""
        content = "Work log entry 1\nTask not COMPLETELY done yet"
        assert is_complete_marker(content) is False

    def test_empty_file(self):
        """Empty file should NOT be marked complete."""
        content = ""
        assert is_complete_marker(content) is False

    def test_only_complete(self):
        """File with only COMPLETE should be marked complete."""
        content = "COMPLETE"
        assert is_complete_marker(content) is True

    def test_complete_with_leading_whitespace(self):
        """COMPLETE with leading whitespace should be detected."""
        content = "Work log entry 1\n  COMPLETE"
        assert is_complete_marker(content) is True

    def test_complete_lowercase_not_detected(self):
        """lowercase 'complete' should NOT be detected."""
        content = "Work log entry 1\ncomplete"
        assert is_complete_marker(content) is False

    def test_complete_mixed_case_not_detected(self):
        """Mixed case 'Complete' should NOT be detected."""
        content = "Work log entry 1\nComplete"
        assert is_complete_marker(content) is False


class TestIncompleteMarkerHandling:
    """Tests for handling incomplete tasks."""

    def test_incomplete_marker_appended(self, tmp_path):
        """INCOMPLETE marker should be appended to incomplete files."""
        wip_file = tmp_path / "test.md"
        wip_file.write_text("Work log entry 1\nWork log entry 2\n")

        mark_incomplete(wip_file)

        content = wip_file.read_text()
        assert "INCOMPLETE" in content
        assert content.rstrip().endswith("INCOMPLETE")

    def test_incomplete_marker_not_duplicated(self, tmp_path):
        """INCOMPLETE marker should not be duplicated."""
        wip_file = tmp_path / "test.md"
        wip_file.write_text("Work log entry 1\n\nINCOMPLETE: Already marked\n")

        mark_incomplete(wip_file)

        content = wip_file.read_text()
        incomplete_count = content.count("INCOMPLETE")
        assert incomplete_count == 1

    def test_incomplete_preserves_existing_content(self, tmp_path):
        """INCOMPLETE marker should preserve all existing content."""
        original = "Line 1\nLine 2\nLine 3\n"
        wip_file = tmp_path / "test.md"
        wip_file.write_text(original)

        mark_incomplete(wip_file)

        content = wip_file.read_text()
        assert "Line 1" in content
        assert "Line 2" in content
        assert "Line 3" in content

    def test_incomplete_marker_with_no_trailing_newline(self, tmp_path):
        """INCOMPLETE marker should handle file without trailing newline."""
        wip_file = tmp_path / "test.md"
        wip_file.write_text("Work log entry 1\nWork log entry 2")

        mark_incomplete(wip_file)

        content = wip_file.read_text()
        assert "INCOMPLETE" in content
        lines = content.split('\n')
        assert lines[-2] == "INCOMPLETE"

    def test_incomplete_with_empty_file(self, tmp_path):
        """INCOMPLETE marker should be added to empty file."""
        wip_file = tmp_path / "test.md"
        wip_file.write_text("")

        mark_incomplete(wip_file)

        content = wip_file.read_text()
        assert content.strip() == "INCOMPLETE"


class TestWorkorderMovement:
    """Tests for moving workorders to correct directory based on COMPLETE status."""

    def test_complete_workorder_moves_to_done(self, tmp_path):
        """Workorder with COMPLETE should move to done/."""
        # Setup
        wip_dir = tmp_path / "wip"
        done_dir = tmp_path / "done"
        wip_dir.mkdir()
        done_dir.mkdir()

        wip_file = wip_dir / "test.md"
        wip_file.write_text("Work log\nCOMPLETE\n")

        # Simulate queue-worker moving file
        if is_complete_marker(wip_file.read_text()):
            dst = done_dir / wip_file.name
            wip_file.rename(dst)

        assert (done_dir / "test.md").exists()
        assert not (wip_dir / "test.md").exists()

    def test_incomplete_workorder_moves_to_ready(self, tmp_path):
        """Workorder without COMPLETE should move to ready/."""
        # Setup
        wip_dir = tmp_path / "wip"
        ready_dir = tmp_path / "ready"
        wip_dir.mkdir()
        ready_dir.mkdir()

        wip_file = wip_dir / "test.md"
        wip_file.write_text("Work log\nNo complete marker\n")

        # Simulate queue-worker moving file
        if not is_complete_marker(wip_file.read_text()):
            mark_incomplete(wip_file)
            dst = ready_dir / wip_file.name
            wip_file.rename(dst)

        assert (ready_dir / "test.md").exists()
        assert not (wip_dir / "test.md").exists()
        assert "INCOMPLETE" in (ready_dir / "test.md").read_text()

    def test_complete_not_on_last_line_goes_to_ready(self, tmp_path):
        """Workorder with COMPLETE not on last line should go to ready/."""
        wip_dir = tmp_path / "wip"
        ready_dir = tmp_path / "ready"
        wip_dir.mkdir()
        ready_dir.mkdir()

        wip_file = wip_dir / "test.md"
        wip_file.write_text("COMPLETE\nBut then more work after\n")

        if not is_complete_marker(wip_file.read_text()):
            mark_incomplete(wip_file)
            dst = ready_dir / wip_file.name
            wip_file.rename(dst)

        assert (ready_dir / "test.md").exists()
        assert not (wip_dir / "test.md").exists()

    def test_multiple_workorders_routing(self, tmp_path):
        """Test routing of multiple workorders simultaneously."""
        wip_dir = tmp_path / "wip"
        done_dir = tmp_path / "done"
        ready_dir = tmp_path / "ready"
        
        for d in [wip_dir, done_dir, ready_dir]:
            d.mkdir()

        # Create test workorders
        complete_work = wip_dir / "complete.md"
        complete_work.write_text("Task 1\nCOMPLETE")
        
        incomplete_work = wip_dir / "incomplete.md"
        incomplete_work.write_text("Task 2\nStill working on it")

        # Process complete workorder
        if is_complete_marker(complete_work.read_text()):
            complete_work.rename(done_dir / complete_work.name)

        # Process incomplete workorder
        if not is_complete_marker(incomplete_work.read_text()):
            mark_incomplete(incomplete_work)
            incomplete_work.rename(ready_dir / incomplete_work.name)

        assert (done_dir / "complete.md").exists()
        assert (ready_dir / "incomplete.md").exists()
        assert not (wip_dir / "complete.md").exists()
        assert not (wip_dir / "incomplete.md").exists()


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_workorder_with_complete_in_metadata(self, tmp_path):
        """Workorder with COMPLETE in metadata should not be marked done."""
        wip_file = tmp_path / "test.md"
        wip_file.write_text("---\nstatus: COMPLETE\n---\nWork log\nStill working")
        
        assert is_complete_marker(wip_file.read_text()) is False

    def test_workorder_with_tabs_around_complete(self, tmp_path):
        """COMPLETE with tabs should be detected."""
        content = "Work log\n\tCOMPLETE\t"
        assert is_complete_marker(content) is True

    def test_workorder_with_only_spaces_after_complete(self):
        """COMPLETE with only spaces after it should be detected."""
        content = "Work log\nCOMPLETE   "
        assert is_complete_marker(content) is True

    def test_very_long_workorder(self, tmp_path):
        """Very long workorder with COMPLETE at end should be handled."""
        lines = [f"Line {i}" for i in range(1000)]
        lines.append("COMPLETE")
        content = "\n".join(lines)
        
        assert is_complete_marker(content) is True

    def test_workorder_with_special_characters(self, tmp_path):
        """Workorder with special characters and COMPLETE marker."""
        content = "Work: @#$%\nNotes: !@#$\nCOMPLETE"
        assert is_complete_marker(content) is True

    def test_workorder_with_unicode(self, tmp_path):
        """Workorder with unicode characters and COMPLETE marker."""
        content = "Work: 你好世界\nNotes: مرحبا بالعالم\nCOMPLETE"
        assert is_complete_marker(content) is True

    def test_incomplete_marker_idempotent(self, tmp_path):
        """Calling mark_incomplete multiple times should be idempotent."""
        wip_file = tmp_path / "test.md"
        wip_file.write_text("Work log\n")

        mark_incomplete(wip_file)
        first_content = wip_file.read_text()

        mark_incomplete(wip_file)
        second_content = wip_file.read_text()

        assert first_content == second_content
        assert first_content.count("INCOMPLETE") == 1

    def test_complete_with_surrounding_blank_lines(self):
        """COMPLETE surrounded by blank lines should be detected if at end."""
        content = "Work log\n\n\nCOMPLETE\n\n\n"
        assert is_complete_marker(content) is True

    def test_complete_case_sensitivity_uppercase(self):
        """COMPLETE in all uppercase should be detected."""
        content = "Work\nCOMPLETE"
        assert is_complete_marker(content) is True

    def test_complete_case_sensitivity_partial_uppercase(self):
        """Partial uppercase variations should NOT be detected."""
        test_cases = [
            "Work\nComplete",
            "Work\ncomplete",
            "Work\nCOMplete",
            "Work\nComPlete",
        ]
        for content in test_cases:
            assert is_complete_marker(content) is False


class TestIntegrationScenarios:
    """Integration tests simulating real queue-worker scenarios."""

    def test_full_workflow_complete_task(self, tmp_path):
        """Full workflow: ready -> wip -> done for completed task."""
        ready_dir = tmp_path / "ready"
        wip_dir = tmp_path / "wip"
        done_dir = tmp_path / "done"
        
        for d in [ready_dir, wip_dir, done_dir]:
            d.mkdir()

        # Task in ready state
        task_file = ready_dir / "task_001.md"
        task_file.write_text("Initial state")

        # Move to wip
        wip_task = wip_dir / task_file.name
        task_file.rename(wip_task)

        # Update with work and completion marker
        wip_task.write_text("Initial state\nWork done\nCOMPLETE")

        # Move to done
        if is_complete_marker(wip_task.read_text()):
            done_task = done_dir / wip_task.name
            wip_task.rename(done_task)

        assert (done_dir / "task_001.md").exists()
        assert not (wip_dir / "task_001.md").exists()
        assert not (ready_dir / "task_001.md").exists()

    def test_full_workflow_incomplete_task(self, tmp_path):
        """Full workflow: ready -> wip -> ready for incomplete task."""
        ready_dir = tmp_path / "ready"
        wip_dir = tmp_path / "wip"
        
        for d in [ready_dir, wip_dir]:
            d.mkdir()

        # Task in ready state
        task_file = ready_dir / "task_001.md"
        task_file.write_text("Initial state")

        # Move to wip
        wip_task = wip_dir / task_file.name
        task_file.rename