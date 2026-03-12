"""
Persistent data storage module for the CSC shared package.

Data is the third level in the CSC framework inheritance hierarchy:
    Root -> Log -> Data -> Version -> Platform -> Network -> Service

All file I/O flows through two methods:
    _read_json_file(path)   — read any JSON file
    _write_json_file(path, data) — atomic write any JSON file

These are the encryption hook points: when encryption is added, only
these two methods change.  Everything else calls them.

Public API (backward compat):
    init_data(filename)     — switch the default key-value store file
    get_data(key)           — read a key from the default store
    put_data(key, value)    — write a key to the default store + flush
    store_data()            — flush the default store to disk
    connect()               — (re)connect to the current source_filename

Oper/O-line API (lives here so any subclass inherits it):
    get_olines()            — olines dict from opers.json
    get_active_opers()      — active oper list
    get_active_opers_info() — {nick_lower: entry} dict
    get_oper_flags(nick)    — flags string for active oper
    protect_local_opers     — property, bool
    add_active_oper(...)    — persist new active oper
    remove_active_oper(...) — remove active oper
    check_oper_auth(...)    — verify OPER credentials
    parse_olines_conf(path) — parse text conf -> dict
    write_olines_conf(...)  — write dict -> text conf
    reload_olines()         — re-parse conf and update opers.json
    save_opers_from_server(server) — sync from server memory
"""

import os
import json
import fnmatch
import threading
from pathlib import Path
from csc_service.shared.log import Log


# ---------------------------------------------------------------------------
# Module-level path helpers (no class instance required)
# ---------------------------------------------------------------------------

def _get_run_dir() -> Path:
    """Runtime state directory — cleared each process start."""
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

class Data(Log):
    """
    Extends Log.  Provides all file-backed persistence for the CSC stack.

    Two responsibilities:
      1. General-purpose key-value store backed by a single JSON file
         (init_data / get_data / put_data).
      2. Typed oper/o-line persistence (opers.json + olines.conf).

    All disk I/O goes through _read_json_file / _write_json_file so that
    encryption can be layered in later without changing any other code.
    """

    _OPERS_DEFAULTS = {
        "version": 2,
        "protect_local_opers": True,
        "active_opers": [],
        "olines": {},
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

    # -----------------------------------------------------------------------
    # Core I/O — ENCRYPTION HOOK POINT
    # To add encryption: override / wrap these two methods only.
    # -----------------------------------------------------------------------

    def _read_json_file(self, path: Path) -> dict:
        """Read a JSON file from disk.  Returns {} on missing or error."""
        try:
            p = Path(path)
            # print(f"DEBUG: _read_json_file checking if {p} exists")
            if p.exists():
                # print(f"DEBUG: _read_json_file opening {p}")
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
                    # print(f"DEBUG: _read_json_file read {len(content)} bytes")
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
        """Return the runtime temp directory. Avoids instantiating Platform to prevent recursion."""
        # Use module-level helper directly
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

        if not os.environ.get("CSC_QUIET"):
            print(f"[{self.name}] Connecting to data source: {path}")
        self._connected_source = str(path)
        self._storage = self._read_json_file(path)
        if not os.environ.get("CSC_QUIET"):
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
    # Oper / O-line persistence
    # All methods read/write opers.json in etc/ via _read_json_file/_write_json_file.
    # -----------------------------------------------------------------------

    def _opers_path(self) -> Path:
        return self._get_etc_dir() / "opers.json"

    def _olines_conf_path(self) -> Path:
        return self._get_etc_dir() / "olines.conf"

    @staticmethod
    def _migrate_opers_v1_to_v2(data: dict) -> dict:
        """Upgrade v1 {credentials: {name: pass}} to v2 olines format."""
        creds = data.get("credentials", {})
        olines = {}
        for name, password in creds.items():
            olines[name] = [{
                "user": name, "password": password,
                "servers": ["*"], "host_masks": ["*!*@*"],
                "flags": "aol", "comment": "migrated from v1",
            }]
        old_active = data.get("active_opers", [])
        new_active = []
        for e in old_active:
            if isinstance(e, str):
                new_active.append({"nick": e, "account": e, "flags": "aol"})
            else:
                new_active.append(e)
        return {
            "version": 2,
            "protect_local_opers": True,
            "active_opers": new_active,
            "olines": olines,
        }

    @staticmethod
    def _match_hostmask(mask: str, client_mask: str) -> bool:
        """Return True if client_mask matches the wildcard mask pattern."""
        try:
            m_nick, rest = mask.split("!", 1)
            m_user, m_host = rest.split("@", 1)
            c_nick, c_rest = client_mask.split("!", 1)
            c_user, c_host = c_rest.split("@", 1)
            return (fnmatch.fnmatch(c_nick.lower(), m_nick.lower()) and
                    fnmatch.fnmatch(c_user.lower(), m_user.lower()) and
                    fnmatch.fnmatch(c_host.lower(), m_host.lower()))
        except ValueError:
            return fnmatch.fnmatch(client_mask.lower(), mask.lower())

    def load_opers(self) -> dict:
        """Public alias — backward compat for existing callers."""
        return self._load_opers()

    def save_opers(self, data: dict) -> bool:
        """Public alias — backward compat for existing callers."""
        return self._save_opers(data)

    def _load_opers(self) -> dict:
        """Load opers.json, migrating v1→v2 if needed."""
        data = self._read_json_file(self._opers_path())
        if not data:
            return dict(self._OPERS_DEFAULTS)
        if data.get("version", 1) < 2:
            data = self._migrate_opers_v1_to_v2(data)
            self._write_json_file(self._opers_path(), data)
        return data

    def _save_opers(self, data: dict) -> bool:
        """Atomically save opers.json."""
        return self._write_json_file(self._opers_path(), data)

    def get_olines(self) -> dict:
        """Return olines dict: {account: [entry, ...]}."""
        return self._load_opers().get("olines", {})

    def get_active_opers(self) -> list:
        """Return list of active oper dicts: [{nick, account, flags}]."""
        return list(self._load_opers().get("active_opers", []))

    def get_active_opers_info(self) -> dict:
        """Return {nick_lower: entry_dict} for quick lookup."""
        return {
            e["nick"].lower(): e
            for e in self.get_active_opers()
            if isinstance(e, dict) and e.get("nick")
        }

    def get_oper_flags(self, nick: str) -> str:
        """Return flags string for an active oper nick, '' if not active."""
        nick_lower = nick.lower()
        for e in self._load_opers().get("active_opers", []):
            if isinstance(e, dict) and e.get("nick", "").lower() == nick_lower:
                return e.get("flags", "o")
        return ""

    @property
    def protect_local_opers(self) -> bool:
        """Whether remote opers without O flag can KILL local opers."""
        return self._load_opers().get("protect_local_opers", True)

    def add_active_oper(self, nick: str, account: str = "", flags: str = "o") -> bool:
        """Add or update an active oper entry."""
        data = self._load_opers()
        active = data.setdefault("active_opers", [])
        nick_lower = nick.lower()
        active[:] = [e for e in active
                     if not (isinstance(e, dict) and e.get("nick", "").lower() == nick_lower)]
        active.append({"nick": nick_lower, "account": account or nick_lower, "flags": flags})
        return self._save_opers(data)

    def remove_active_oper(self, nick: str) -> bool:
        """Remove an active oper entry by nick."""
        data = self._load_opers()
        nick_lower = nick.lower()
        data["active_opers"] = [
            e for e in data.get("active_opers", [])
            if not (isinstance(e, dict) and e.get("nick", "").lower() == nick_lower)
        ]
        return self._save_opers(data)

    def check_oper_auth(self, account: str, password: str,
                        server_name: str, client_mask: str):
        """Verify OPER credentials against o-lines.

        Returns flags string on success, None on failure.
        """
        data = self._load_opers()
        entries = (data.get("olines", {}).get(account, []) +
                   data.get("remote_olines", {}).get(account, []))
        for entry in entries:
            if entry.get("password") != password:
                continue
            servers = entry.get("servers", ["*"])
            if not any(s == "*" or fnmatch.fnmatch(server_name.lower(), s.lower())
                       for s in servers):
                continue
            masks = entry.get("host_masks", ["*!*@*"])
            if any(self._match_hostmask(m, client_mask) for m in masks):
                return entry.get("flags", "o")
        return None

    def parse_olines_conf(self, path=None) -> dict:
        """Parse olines.conf text format -> {account: [entry_dict, ...]}."""
        if path is None:
            path = self._olines_conf_path()
        olines = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(":")
                    comment = ""
                    if len(parts) >= 7:
                        comment = ":".join(parts[6:]).lstrip("# ").strip()
                        parts = parts[:6]
                    if len(parts) < 6:
                        continue
                    name, flags, user, password, servers_str, masks_str = parts
                    name = name.strip()
                    flags = flags.strip()
                    user = user.strip()
                    password = password.strip()
                    servers = [s.strip() for s in servers_str.split(",") if s.strip()]
                    masks = [m.strip() for m in masks_str.split(",") if m.strip()]
                    if not name or not user or not password:
                        continue
                    olines.setdefault(name, []).append({
                        "user": user, "password": password,
                        "servers": servers or ["*"],
                        "host_masks": masks or ["*!*@*"],
                        "flags": flags or "o",
                        "comment": comment,
                    })
        except FileNotFoundError:
            pass
        except Exception as e:
            self.log(f"Error parsing olines.conf: {e}")
        return olines

    def write_olines_conf(self, olines: dict, path=None,
                          server_name: str = "csc-server") -> bool:
        """Write olines dict to olines.conf text format atomically."""
        if path is None:
            path = self._olines_conf_path()
        path = Path(path)
        lines = [
            "# olines.conf — CSC IRC Server operator configuration",
            "# Format: name:flags:user:pass:servers:hostmasks:# comment",
            "# Flags: o=local oper  O=global oper  a=server admin  A=net admin",
            f"# Server: {server_name}",
            "",
        ]
        for name, entries in sorted(olines.items()):
            for entry in entries:
                servers = ",".join(entry.get("servers", ["*"]))
                masks = ",".join(entry.get("host_masks", ["*!*@*"]))
                flags = entry.get("flags", "o")
                user = entry.get("user", name)
                password = entry.get("password", "")
                comment = entry.get("comment", "")
                comment_str = f":# {comment}" if comment else ""
                lines.append(
                    f"{name}:{flags}:{user}:{password}:{servers}:{masks}{comment_str}"
                )
        lines.append("")
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return True
        except Exception as e:
            self.log(f"Error writing olines.conf: {e}")
            return False

    def reload_olines(self) -> dict:
        """Re-parse olines.conf and update opers.json."""
        olines = self.parse_olines_conf()
        if not olines:
            return olines
        data = self._load_opers()
        data["olines"] = olines
        self._save_opers(data)
        return olines

    def save_opers_from_server(self, server) -> bool:
        """Sync active_opers from server memory to opers.json."""
        data = self._load_opers()
        if hasattr(server, "_active_opers_full"):
            data["active_opers"] = list(server._active_opers_full)
        else:
            connected = {
                info.get("name", "").lower()
                for info in server.clients.values()
                if info.get("name")
            }
            data["active_opers"] = [
                e for e in data.get("active_opers", [])
                if isinstance(e, dict) and e.get("nick", "").lower() in connected
            ]
        return self._save_opers(data)

    # -----------------------------------------------------------------------
    # Misc
    # -----------------------------------------------------------------------

    def run(self):
        self.connect()


if __name__ == "__main__":
    data = Data()
    data.run()
