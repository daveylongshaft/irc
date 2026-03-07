"""Utilities for WIP file journaling and crash recovery."""

from pathlib import Path
from typing import Optional


class WIPJournal:
    """Manages WIP file journaling for crash recovery and progress tracking."""

    def __init__(self, wip_path: Path):
        """Initialize journal for a WIP file.

        Args:
            wip_path: Path to the WIP markdown file
        """
        self.path = Path(wip_path)

    def append_entry(self, entry: str) -> bool:
        """Add a single-line journal entry.

        Used to log work steps BEFORE execution for crash recovery.
        Next agent reads the last entry to know where to resume.

        Args:
            entry: Single-line entry to append

        Returns:
            True if successful, False otherwise
        """
        try:
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(entry + "\n")
            return True
        except Exception:
            return False

    def stamp_pid(self, pid: int) -> bool:
        """Replace PID placeholder with actual process ID.

        Called after spawning a subprocess to record the real PID.

        Args:
            pid: Process ID to stamp

        Returns:
            True if successful, False otherwise
        """
        try:
            content = self.path.read_text(encoding='utf-8')
            content = content.replace("PID: {pending}", f"PID: {pid}")
            self.path.write_text(content, encoding='utf-8')
            return True
        except Exception:
            return False

    def get_last_entry(self) -> str:
        """Get the last journal entry (for crash recovery).

        When an agent resumes, it reads the last entry to know which
        step was the last one logged (before the crash).

        Returns:
            Last entry line, or empty string if no entries
        """
        try:
            content = self.path.read_text(encoding='utf-8')
            lines = content.splitlines()
            return lines[-1] if lines else ""
        except Exception:
            return ""

    def read_content(self) -> str:
        """Read full WIP file content.

        Returns:
            Full file content, or empty string if read fails
        """
        try:
            return self.path.read_text(encoding='utf-8')
        except Exception:
            return ""

    def write_content(self, content: str) -> bool:
        """Overwrite WIP file content.

        Args:
            content: New file content

        Returns:
            True if successful, False otherwise
        """
        try:
            self.path.write_text(content, encoding='utf-8')
            return True
        except Exception:
            return False

    def exists(self) -> bool:
        """Check if WIP file exists.

        Returns:
            True if file exists
        """
        return self.path.exists()

    def get_line_count(self) -> int:
        """Get number of lines in WIP file.

        Returns:
            Line count, or 0 if file doesn't exist
        """
        try:
            content = self.path.read_text(encoding='utf-8')
            return len(content.splitlines())
        except Exception:
            return 0

    def get_last_n_lines(self, n: int = 20) -> str:
        """Get last N lines of WIP file.

        Useful for displaying recent progress in status commands.

        Args:
            n: Number of lines to retrieve

        Returns:
            Last N lines as string, or empty if fewer lines exist
        """
        try:
            content = self.path.read_text(encoding='utf-8')
            lines = content.splitlines()
            tail_lines = lines[-n:] if len(lines) > n else lines
            return "\n".join(tail_lines)
        except Exception:
            return ""
