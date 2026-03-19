"""Virtual file index for the FTP master.

Maps virtual paths to slave(s) + metadata. Persists to etc/ftpd_index.json.
The master uses this to know which slave holds which file.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)


class FtpMasterIndex:
    """Virtual file index: maps vpath -> slave(s) + file metadata.

    Thread-safe. Persists to disk on every mutation (atomic write).

    Index structure:
        {
            "/path/to/file": {
                "slaves": {"slave_id": {"size": N, "mtime": F, "md5": "..."}},
                "updated": timestamp
            }
        }
    """

    def __init__(self, index_path):
        """Initialize the index.

        Args:
            index_path: Absolute path to the JSON index file.
        """
        self._path = Path(index_path)
        self._lock = threading.Lock()
        self._index = {}
        self._load()

    def _load(self):
        """Load index from disk if it exists."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._index = data
                    log.info("FtpMasterIndex: loaded %d entries from %s",
                             len(self._index), self._path)
            except Exception as e:
                log.warning("FtpMasterIndex: failed to load %s: %s", self._path, e)

    def _persist(self):
        """Atomically write index to disk (temp + rename)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._index, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            # Atomic rename (works on POSIX; on Windows, replaces target)
            if os.name == "nt":
                if self._path.exists():
                    self._path.unlink()
            tmp.rename(self._path)
        except Exception as e:
            log.error("FtpMasterIndex: persist failed: %s", e)

    def update_from_inventory(self, slave_id, files):
        """Replace all entries for a slave with a full inventory.

        Args:
            slave_id: Identifier of the slave.
            files: List of dicts with keys: path, size, mtime, md5.
        """
        with self._lock:
            # Remove old entries for this slave
            for vpath in list(self._index.keys()):
                entry = self._index[vpath]
                entry["slaves"].pop(slave_id, None)
                if not entry["slaves"]:
                    del self._index[vpath]

            # Add new entries
            now = time.time()
            for f in files:
                vpath = self._normalize_path(f["path"])
                if vpath not in self._index:
                    self._index[vpath] = {"slaves": {}, "updated": now}
                self._index[vpath]["slaves"][slave_id] = {
                    "size": f.get("size", 0),
                    "mtime": f.get("mtime", 0),
                    "md5": f.get("md5", ""),
                }
                self._index[vpath]["updated"] = now

            self._persist()
            log.info("FtpMasterIndex: updated inventory for %s (%d files)",
                     slave_id, len(files))

    def apply_delta(self, slave_id, added=None, removed=None, modified=None):
        """Apply incremental inventory changes for a slave.

        Args:
            slave_id: Identifier of the slave.
            added: List of file dicts to add.
            removed: List of path strings to remove.
            modified: List of file dicts to update.
        """
        with self._lock:
            now = time.time()

            for f in (added or []):
                vpath = self._normalize_path(f["path"])
                if vpath not in self._index:
                    self._index[vpath] = {"slaves": {}, "updated": now}
                self._index[vpath]["slaves"][slave_id] = {
                    "size": f.get("size", 0),
                    "mtime": f.get("mtime", 0),
                    "md5": f.get("md5", ""),
                }
                self._index[vpath]["updated"] = now

            for path in (removed or []):
                vpath = self._normalize_path(path)
                if vpath in self._index:
                    self._index[vpath]["slaves"].pop(slave_id, None)
                    if not self._index[vpath]["slaves"]:
                        del self._index[vpath]

            for f in (modified or []):
                vpath = self._normalize_path(f["path"])
                if vpath not in self._index:
                    self._index[vpath] = {"slaves": {}, "updated": now}
                self._index[vpath]["slaves"][slave_id] = {
                    "size": f.get("size", 0),
                    "mtime": f.get("mtime", 0),
                    "md5": f.get("md5", ""),
                }
                self._index[vpath]["updated"] = now

            self._persist()

    def rename_entry(self, old_vpath, new_vpath):
        """Atomically rename an index entry from old_vpath to new_vpath."""
        old_vpath = self._normalize_path(old_vpath)
        new_vpath = self._normalize_path(new_vpath)
        with self._lock:
            entry = self._index.pop(old_vpath, None)
            if entry is None:
                log.warning("FtpMasterIndex: rename source not found: %s", old_vpath)
                return
            entry["updated"] = time.time()
            self._index[new_vpath] = entry
            self._persist()
            log.info("FtpMasterIndex: renamed %s -> %s", old_vpath, new_vpath)

    def remove_slave(self, slave_id):
        """Remove all entries for a disconnected slave."""
        with self._lock:
            for vpath in list(self._index.keys()):
                self._index[vpath]["slaves"].pop(slave_id, None)
                if not self._index[vpath]["slaves"]:
                    del self._index[vpath]
            self._persist()
            log.info("FtpMasterIndex: removed all entries for slave %s", slave_id)

    def lookup(self, vpath):
        """Look up which slave(s) hold a file.

        Args:
            vpath: Virtual path (e.g., "/ops/wo/ready/task.md").

        Returns:
            dict: {slave_id: {size, mtime, md5}} or empty dict.
        """
        vpath = self._normalize_path(vpath)
        with self._lock:
            entry = self._index.get(vpath)
            if entry:
                return dict(entry["slaves"])
            return {}

    def pick_slave(self, vpath):
        """Pick the best slave for a file download (most recent mtime).

        Args:
            vpath: Virtual path.

        Returns:
            str or None: slave_id, or None if file not found.
        """
        slaves = self.lookup(vpath)
        if not slaves:
            return None
        # Pick the slave with the newest mtime
        return max(slaves, key=lambda sid: slaves[sid].get("mtime", 0))

    def list_dir(self, vdir):
        """List files and subdirectories under a virtual directory.

        Args:
            vdir: Virtual directory path (e.g., "/" or "/ops/wo").

        Returns:
            list of dict: [{name, is_dir, size, mtime}, ...].
        """
        vdir = self._normalize_path(vdir)
        if not vdir.endswith("/"):
            vdir += "/"

        with self._lock:
            entries = {}
            for vpath, entry in self._index.items():
                if not vpath.startswith(vdir):
                    continue
                # Get the relative part after vdir
                rel = vpath[len(vdir):]
                if not rel:
                    continue

                parts = rel.split("/")
                name = parts[0]
                is_dir = len(parts) > 1

                if name not in entries:
                    if is_dir:
                        entries[name] = {
                            "name": name,
                            "is_dir": True,
                            "size": 0,
                            "mtime": 0,
                        }
                    else:
                        # Pick the best slave's metadata
                        best = max(
                            entry["slaves"].values(),
                            key=lambda s: s.get("mtime", 0),
                            default={"size": 0, "mtime": 0},
                        )
                        entries[name] = {
                            "name": name,
                            "is_dir": False,
                            "size": best.get("size", 0),
                            "mtime": best.get("mtime", 0),
                        }
                elif is_dir:
                    entries[name]["is_dir"] = True

            return sorted(entries.values(), key=lambda e: e["name"])

    def all_paths(self):
        """Return all virtual paths in the index."""
        with self._lock:
            return list(self._index.keys())

    @staticmethod
    def _normalize_path(path):
        """Normalize a virtual path: ensure leading /, no trailing /, forward slashes."""
        path = path.replace("\\", "/").strip()
        if not path.startswith("/"):
            path = "/" + path
        while "//" in path:
            path = path.replace("//", "/")
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        return path
