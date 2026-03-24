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
from csc_log import Log
from csc_data.server_data import ServerData


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
            except Exception:
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
            from csc_platform import Platform
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
    # Misc
    # -----------------------------------------------------------------------

    def run(self):
        self.connect()


if __name__ == "__main__":
    data = Data()
    data.run()
