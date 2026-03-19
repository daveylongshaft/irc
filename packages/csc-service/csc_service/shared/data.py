"""
Persistent data storage module for the CSC shared package.

Data is the third level in the CSC framework inheritance hierarchy:
    Root -> Log -> Data(Log, ServerData) -> Version -> Platform -> Network -> Service

All file I/O flows through two methods:
    _read_json_file(path)   -- read any JSON file
    _write_json_file(path, data) -- atomic write any JSON file

These are the encryption hook points: when encryption is added, only
these two methods change.  Everything else calls them.

Public API (backward compat):
    init_data(filename)     -- switch the default key-value store file
    get_data(key)           -- read a key from the default store
    put_data(key, value)    -- write a key to the default store + flush
    store_data()            -- flush the default store to disk
    connect()               -- (re)connect to the current source_filename

ServerData mixin provides ALL IRC-specific persistence (channels, users,
opers, bans, history, nickserv, chanserv, botserv, settings, restore/persist).
"""

import os
import json
import threading
from pathlib import Path
from csc_service.shared.log import Log
from csc_service.shared.server_data import ServerData


# ---------------------------------------------------------------------------
# Module-level path helpers (no class instance required)
# ---------------------------------------------------------------------------

def _get_run_dir() -> Path:
    """Runtime state directory -- cleared each process start."""
    temp_root = os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
    path = Path(temp_root) / "csc" / "run"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_etc_dir_static() -> Path:
    """Resolve etc/ without a class instance: CSC_ETC env -> walk up -> cwd/etc."""
    env = os.environ.get("CSC_ETC", "")
    if env:
        p = Path(env)
        p.mkdir(parents=True, exist_ok=True)
        return p
    here = Path(__file__).resolve().parent
    for _ in range(12):
        if (here / "etc" / "csc-service.json").exists() or (here / "csc-service.json").exists():
            p = here / "etc"
            p.mkdir(parents=True, exist_ok=True)
            return p
        if here == here.parent:
            break
        here = here.parent
    p = Path.cwd() / "etc"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

class Data(Log, ServerData):
    """
    Extends Log + ServerData.  Provides all file-backed persistence.

    Two responsibilities:
      1. General-purpose key-value store backed by a single JSON file
         (init_data / get_data / put_data).
      2. IRC-specific domain persistence via ServerData mixin
         (channels, users, opers, bans, history, nickserv, chanserv,
          botserv, settings, restore_all / persist_all).

    All disk I/O goes through _read_json_file / _write_json_file so that
    encryption can be layered in later without changing any other code.
    """

    def __init__(self):
        super().__init__()
        self.name = "data"
        self._storage = {}
        self._storage_lock = threading.Lock()
        self._connected_source = None
        self.source_filename = "data.json"
        self.isDataConnected = False
        self.connect()

        # ServerData initialization
        self.base_path = str(self._get_etc_dir())
        self._mtimes = {}
        self._ensure_all_files()

    # -----------------------------------------------------------------------
    # Core I/O -- ENCRYPTION HOOK POINT
    # To add encryption: override / wrap these two methods only.
    # -----------------------------------------------------------------------

    def _read_json_file(self, path: Path) -> dict:
        """Read a JSON file from disk.  Returns {} on missing or error."""
        try:
            p = Path(path)
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
                    return json.loads(content) if content.strip() else {}
        except Exception as e:
            self.log(f"Error reading {path}: {e}")
        return {}

    def _write_json_file(self, path: Path, data: dict) -> bool:
        """Atomically write data as JSON (temp -> fsync -> rename)."""
        path = Path(path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with self._storage_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
            return True
        except Exception as e:
            self.log(f"Error writing {path}: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def _read_text_file(self, path: Path) -> str:
        """Read a text file from disk. Returns "" on missing or error.

        Generic text file reader (not JSON). Used for workorders, markdown,
        context files, and any other text-based persistence.
        """
        try:
            p = Path(path)
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception as e:
            self.log(f"Error reading {path}: {e}")
        return ""

    def _write_text_file(self, path: Path, data: str) -> bool:
        """Atomically write text file (temp -> fsync -> rename).

        Generic text file writer. Same atomic pattern as JSON writes.
        Used for workorders, markdown, context files, and any other text-based persistence.
        """
        path = Path(path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with self._storage_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
            return True
        except Exception as e:
            self.log(f"Error writing {path}: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return False

    # -----------------------------------------------------------------------
    # Path resolution
    # -----------------------------------------------------------------------

    def _get_etc_dir(self) -> Path:
        """Return the etc/ directory via Platform (handles all OS path formats)."""
        try:
            from csc_service.shared.platform import Platform
            return Platform.get_etc_dir()
        except Exception:
            return _get_etc_dir_static()

    def _get_run_dir(self) -> Path:
        """Return the runtime temp directory."""
        return globals()["_get_run_dir"]()

    # -----------------------------------------------------------------------
    # Default key-value store  (backward-compat public API)
    # -----------------------------------------------------------------------

    def connect(self):
        """Connect to source_filename.  No-op if already connected."""
        if self.isDataConnected:
            return

        filename = self.source_filename
        if os.path.isabs(filename):
            path = Path(filename)
        else:
            path = self._get_run_dir() / filename

        if os.environ.get("DEBUG"):
            print(f"[{self.name}] Connecting to data source: {path}")
        self._connected_source = str(path)
        self._storage = self._read_json_file(path)
        if os.environ.get("DEBUG"):
            print(f"Connection successful. Loaded {len(self._storage)} items from '{path}'.")
        self.isDataConnected = True
        return True

    def init_data(self, source_filename="default"):
        """Switch the connected data file.  Resets in-memory store."""
        if source_filename == "default":
            self.source_filename = f"{self.name}_data.json"
        else:
            self.source_filename = source_filename
        self._storage = {}
        self.isDataConnected = False
        self._connected_source = None
        self.connect()

    def get_data(self, key: str, default=None):
        """Read a key from the in-memory store."""
        return self._storage.get(key, default)

    def put_data(self, key: str, value, flush=True):
        """Write a key to the store and optionally flush to disk."""
        if not self._connected_source:
            self.log("Error: Not connected to a data source.")
            return
        self._storage[key] = value
        if flush:
            self.store_data()
        return True

    def store_data(self):
        """Flush the in-memory store to disk."""
        if not self._connected_source:
            self.log("Error: Not connected to a data source.")
            return
        ok = self._write_json_file(Path(self._connected_source), self._storage)
        if ok and not os.environ.get("CSC_QUIET"):
            print(f"Store data successful. Saved {len(self._storage)} items to '{self._connected_source}'.")
        return ok

    # -----------------------------------------------------------------------
    # Log file I/O (append-only files)
    # -----------------------------------------------------------------------

    def _append_log_line(self, path, line):
        """Append a single line to a log file (append + fsync).

        For append-only log files. No temp+rename needed.
        Uses binary mode to write bare \\n (not \\r\\n on Windows),
        keeping byte offsets consistent with _tail_log_file().
        """
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "ab") as f:
                f.write((line + "\n").encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            self.log(f"Error appending to {path}: {e}")

    def _write_ftp_announce(self, line):
        """Append a formatted line to logs/ftp_announce.log."""
        from csc_service.shared.log import _get_logs_dir
        log_dir = _get_logs_dir()
        self._append_log_line(log_dir / "ftp_announce.log", line)

    def _write_runtime(self, line):
        """Append a formatted line to logs/runtime.log."""
        from csc_service.shared.log import _get_logs_dir
        log_dir = _get_logs_dir()
        self._append_log_line(log_dir / "runtime.log", line)

    def _tail_log_file(self, path, offset=0):
        """Read new lines from a log file starting at byte offset.

        Returns (lines: list[str], new_offset: int).
        Handles: file not found ([], 0), truncated files (resets offset).

        Uses binary mode so stat().st_size byte offsets match seek() exactly
        (text mode on Windows translates CRLF, breaking offset alignment).
        Only returns complete lines (ending with newline) -- partial lines
        at EOF are held back until the next poll when they're complete.
        """
        path = Path(path)
        try:
            if not path.exists():
                return [], 0
            current_size = path.stat().st_size
            if current_size < offset:
                # File was truncated, reset
                return [], current_size
            if current_size == offset:
                return [], offset
            with open(path, "rb") as f:
                f.seek(offset)
                raw = f.read(current_size - offset)
            # Only return complete lines (ending with \n)
            # Hold partial last line for next poll
            text = raw.decode("utf-8", errors="ignore")
            if not text.endswith("\n"):
                # Find last newline -- everything after it is incomplete
                last_nl = text.rfind("\n")
                if last_nl == -1:
                    # No complete lines yet
                    return [], offset
                # Return only complete lines, advance offset past them
                complete = text[:last_nl + 1]
                new_offset = offset + len(complete.encode("utf-8"))
                lines = complete.splitlines(keepends=False)
                return [ln + "\n" for ln in lines], new_offset
            lines = text.splitlines(keepends=False)
            return [ln + "\n" for ln in lines], current_size
        except Exception as e:
            self.log(f"Error tailing {path}: {e}")
            return [], offset

    # -----------------------------------------------------------------------
    # Misc
    # -----------------------------------------------------------------------

    def run(self):
        self.connect()


if __name__ == "__main__":
    data = Data()
    data.run()
