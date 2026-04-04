"""Utilities for work queue directory management (ready/wip/done/hold)."""

from pathlib import Path
from typing import Tuple, Dict, List


class QueueDirectories:
    """Manages ready/wip/done/hold directory structure for work queues."""

    READY = "ready"
    WIP = "wip"
    DONE = "done"
    HOLD = "hold"
    ARCHIVE = "archive"
    ALL_DIRS = [READY, WIP, DONE, HOLD, ARCHIVE]

    def __init__(self, base_path: Path):
        """Initialize queue directories.

        Args:
            base_path: Root directory containing ready/, wip/, done/, hold/
        """
        self.base = Path(base_path)
        self.dirs = {
            self.READY: self.base / "ready",
            self.WIP: self.base / "wip",
            self.DONE: self.base / "done",
            self.HOLD: self.base / "hold",
            self.ARCHIVE: self.base / "archive",
        }
        self.ensure_exist()

    def ensure_exist(self):
        """Create all queue directories if they don't exist."""
        for d in self.dirs.values():
            d.mkdir(parents=True, exist_ok=True)

    def get(self, name: str) -> Path:
        """Get directory path by name.

        Args:
            name: Directory name (ready, wip, done, hold)

        Returns:
            Path object for the directory
        """
        return self.dirs.get(name)

    def list_files(self, dirname: str, suffix: str = ".md") -> List[str]:
        """List files in directory with given suffix, sorted alphabetically.

        Args:
            dirname: Directory name (ready, wip, done, hold)
            suffix: File suffix to match (default: .md)

        Returns:
            Sorted list of filenames
        """
        d = self.dirs.get(dirname)
        if not d or not d.exists():
            return []
        return sorted([
            f.name for f in d.iterdir()
            if f.is_file() and f.suffix == suffix
        ])

    def find_file(self, filename: str, add_suffix: bool = True) -> Tuple[Path, str]:
        """Find file in any directory.

        Args:
            filename: File to search for
            add_suffix: Auto-add .md suffix if not present

        Returns:
            Tuple of (Path, dirname) or (None, None) if not found
        """
        if add_suffix and not filename.endswith(".md"):
            filename += ".md"

        for name, path in self.dirs.items():
            full_path = path / filename
            if full_path.exists():
                return full_path, name

        return None, None

    def get_counts(self) -> Dict[str, int]:
        """Get file counts per directory.

        Returns:
            Dict mapping directory name to file count
        """
        return {
            name: len(self.list_files(name))
            for name in self.ALL_DIRS
        }

    def move_file(self, filename: str, from_dir: str, to_dir: str) -> bool:
        """Move file between directories.

        Args:
            filename: File to move
            from_dir: Source directory name
            to_dir: Destination directory name

        Returns:
            True if successful, False otherwise
        """
        if from_dir not in self.dirs or to_dir not in self.dirs:
            return False

        from_path = self.dirs[from_dir] / filename
        if not from_path.exists():
            return False

        to_path = self.dirs[to_dir] / filename
        try:
            from_path.rename(to_path)
            return True
        except Exception:
            return False
