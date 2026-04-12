"""
Persistent data storage module for the CSC system.

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

    # Registry of config files and env vars per package
    # Maps: package_name -> {"config_files": [...], "env_vars": [...], "artifact_types": [...]}
    _CONFIG_REGISTRY = {
        "csc-server": {
            "config_files": ["csc-service.json"],
            "env_vars": ["CSC_SERVER_HOST", "CSC_SERVER_PORT", "CSC_SERVER_NAME", "CSC_SERVER_DEBUG", "CSC_ROOT"],
            "artifact_types": ["env_var"],
        },
        "csc-bridge": {
            "config_files": ["csc-service.json", "bridge_data.json"],
            "env_vars": ["CSC_ETC", "CSC_HOME"],
            "artifact_types": ["file_io", "json_parse"],
        },
        "csc-ai-api": {
            "config_files": ["client.conf", "{agent_name}_data.json"],
            "env_vars": ["CSC_SERVER_PORT"],
            "artifact_types": ["config_file_ref", "configparser"],
        },
        "csc-services": {
            "config_files": ["csc-service.json", "catalog.json", "benchmark_metadata.json", "approved_servers.json", "pki_tokens.json"],
            "env_vars": ["CSC_ROOT"],
            "artifact_types": ["file_io", "json_parse"],
        },
        "csc-loop": {
            "config_files": ["csc-service.json", "codex_monitor_data.json", ".env"],
            "env_vars": ["CSC_ROOT", "JULES_API_KEY", "GITHUB_WEBHOOK_SECRET", "WEBHOOK_HOST", "WEBHOOK_PORT"],
            "artifact_types": ["env_var", "json_parse", "file_io"],
        },
        "csc-data": {
            "config_files": ["csc-service.json", "api_key_config.json"],
            "env_vars": ["TEMP", "TMP", "CSC_ETC", "CSC_ROOT", "CSC_SERVER_ID", "ANTHROPIC_API_KEY"],
            "artifact_types": ["env_var", "json_parse", "file_io"],
        },
        "csc-ftpd": {
            "config_files": ["ftp_users.json", "ftp_master_index.json"],
            "env_vars": ["CSC_HOME"],
            "artifact_types": ["env_var", "json_parse"],
        },
        "csc-platform": {
            "config_files": [".env"],
            "env_vars": ["CSC_HOME", "CSC_ROOT"],
            "artifact_types": ["env_var", "file_io"],
        },
        "csc-pki": {
            "config_files": ["approved_servers.json", "pki_tokens.json"],
            "env_vars": [],
            "artifact_types": ["json_parse", "file_io"],
        },
    }

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
                if hasattr(self, 'log'):
                    self.log('Ignored exception', level='DEBUG')
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
                if hasattr(self, 'log'):
                    self.log('Ignored exception', level='DEBUG')
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
    # Config API (public) -- unified configuration management
    # -----------------------------------------------------------------------

    def config_get(self, key: str, default=None):
        """Get config value using dot-notation for nested keys.

        Args:
            key: dot-separated path (e.g., "bridge.tunnels[0].listen_port")
            default: value to return if key not found

        Returns:
            The config value or default
        """
        from csc_data.config import ConfigManager
        cfg = ConfigManager()
        result = cfg.get_value(key)
        return result if result is not None else default

    def config_set(self, key: str, value):
        """Set config value using dot-notation. Atomically persists to disk.

        Args:
            key: dot-separated path
            value: value to set

        Returns:
            True if successful, False otherwise
        """
        from csc_data.config import ConfigManager
        cfg = ConfigManager()
        cfg.set_value(key, value)
        cfg.save_config()
        return True

    def config_list_keys(self, prefix: str = "") -> list:
        """List all config keys under a prefix.

        Args:
            prefix: optional prefix filter (e.g., "bridge" returns all "bridge.*" keys)

        Returns:
            List of key paths
        """
        from csc_data.config import ConfigManager
        cfg = ConfigManager()
        keys = []

        def walk_dict(d, path_prefix=""):
            for k, v in d.items():
                full_key = f"{path_prefix}.{k}" if path_prefix else k
                if not prefix or full_key.startswith(prefix):
                    keys.append(full_key)
                if isinstance(v, dict):
                    walk_dict(v, full_key)

        walk_dict(cfg.config)
        return sorted(keys)

    def config_files(self) -> dict:
        """Return registry of config files and env vars used by all packages.

        Returns:
            Dict mapping package_name -> {
                "config_files": [list of file paths],
                "env_vars": [list of env var names],
                "artifact_types": ["json_parse", "file_io", ...]
            }
        """
        return self._CONFIG_REGISTRY

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
    # Privileged log reading
    # -----------------------------------------------------------------------

    def _tail_privileged_log_file(self, path, offset: int = 0):
        """Read new lines from a privileged log file using sudo, starting at byte offset.

        Returns (lines: list[str], new_offset: int) -- same contract as _tail_log_file.

        Delegates to bin/read_privileged_log.py which uses sudo to read files
        that the process user cannot access directly (e.g. /var/log/auth.log).
        """
        import subprocess
        import sys
        try:
            from csc_platform import Platform
            script = str(Platform.PROJECT_ROOT / "bin" / "read_privileged_log.py")
        except Exception:
            # Fallback: walk up from data.py
            here = Path(__file__).resolve().parent
            for _ in range(12):
                candidate = here / "bin" / "read_privileged_log.py"
                if candidate.exists():
                    script = str(candidate)
                    break
                if here == here.parent:
                    break
                here = here.parent
            else:
                self.log("Error: read_privileged_log.py not found")
                return [], offset

        try:
            result = subprocess.run(
                [sys.executable, script, str(path), str(offset)],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                self.log(f"Privileged log read failed for {path}: {result.stderr.strip()}")
                return [], offset

            # Extract new offset from stderr
            new_offset = offset
            for line in result.stderr.splitlines():
                if line.startswith("TOTAL_BYTES_READ:"):
                    new_offset = int(line.split(":")[1])
                    break

            lines = result.stdout.splitlines(keepends=True)
            return lines, new_offset
        except subprocess.TimeoutExpired:
            self.log(f"Privileged log read timed out for {path}")
            return [], offset
        except Exception as e:
            self.log(f"Error reading privileged log {path}: {e}")
            return [], offset

    # -----------------------------------------------------------------------
    # Misc
    # -----------------------------------------------------------------------

    def run(self):
        self.connect()


if __name__ == "__main__":
    data = Data()
    data.run()
