"""High-level file operations that integrate with FTP slave and S2S bridge.

Used by queue_worker and agent_service for workorder lifecycle moves.
Handles: local rename, lock/unlock, S2S notification.
Falls back to plain shutil.move if no slave/bridge is available.
"""

import hashlib
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)


class FtpFileOps:
    """File operations with FTP slave + S2S bridge integration.

    If slave/bridge are None (standalone mode), falls back to shutil.move.
    """

    def __init__(self, slave=None, bridge=None, announce=None):
        self.slave = slave
        self.bridge = bridge
        self._announce = announce  # callable(str) or None

    def rename(self, old_path, new_path):
        """Rename a file and notify S2S peers.

        Args:
            old_path: Source path (absolute or Path object).
            new_path: Destination path (absolute or Path object).
        """
        old_path = Path(old_path)
        new_path = Path(new_path)

        if self.slave is None and self.bridge is None:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_path), str(new_path))
            return

        # Do local rename
        new_path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt" and new_path.exists():
            new_path.unlink()
        old_path.rename(new_path)

        if self._announce:
            try:
                self._announce(f"RENAME {old_path.name} -> {new_path.parent.name}/{new_path.name}")
            except Exception:
                if hasattr(self, 'log'):
                    self.log('Ignored exception', level='DEBUG')

        # Notify S2S bridge if available
        if self.bridge:
            try:
                serve_root = Path(self.slave.config.serve_root)
                old_vpath = "/" + old_path.relative_to(serve_root).as_posix()
                new_vpath = "/" + new_path.relative_to(serve_root).as_posix()
                st = new_path.stat()
                md5 = self._file_md5(new_path)
                self.bridge.notify_file_renamed(
                    old_vpath, new_vpath, st.st_size, md5, st.st_mtime
                )
            except (ValueError, OSError) as e:
                log.warning("FtpFileOps: S2S rename notify failed: %s", e)

        # Trigger inventory delta
        if self.slave:
            self.slave.schedule_inventory_delta()

    def lock(self, vpath, lock_id=None, ttl=7200):
        """Lock a file to suppress sync during edits.

        Args:
            vpath: Virtual path (e.g., "/ops/wo/wip/task.md") or absolute Path.
            lock_id: Lock identifier. Auto-generated if None.
            ttl: Time-to-live in seconds (default 7200 = 2 hours).

        Returns:
            str: The lock_id used.
        """
        if lock_id is None:
            lock_id = uuid.uuid4().hex

        if self.bridge:
            self.bridge.lock_file(vpath, lock_id, ttl)
        elif self.slave:
            self.slave.lock_file(vpath, lock_id, ttl)

        if self._announce:
            try:
                self._announce(f"LOCK {vpath} id={lock_id} ttl={ttl}s")
            except Exception:
                if hasattr(self, 'log'):
                    self.log('Ignored exception', level='DEBUG')

        return lock_id

    def unlock(self, vpath, lock_id):
        """Unlock a file, allowing sync to resume.

        Args:
            vpath: Virtual path or absolute Path.
            lock_id: The lock_id returned by lock().
        """
        if self.bridge:
            self.bridge.unlock_file(vpath, lock_id)
        elif self.slave:
            self.slave.unlock_file(vpath, lock_id)

        if self._announce:
            try:
                self._announce(f"UNLOCK {vpath} id={lock_id}")
            except Exception:
                if hasattr(self, 'log'):
                    self.log('Ignored exception', level='DEBUG')

    def path_to_vpath(self, path):
        """Convert an absolute path to a virtual path relative to serve_root.

        Returns None if slave is not available or path is outside serve_root.
        """
        if self.slave is None:
            return None
        try:
            serve_root = Path(self.slave.config.serve_root)
            return "/" + Path(path).relative_to(serve_root).as_posix()
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _file_md5(path, chunk_size=65536):
        """Compute MD5 hash of a file."""
        h = hashlib.md5()
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    h.update(chunk)
        except OSError:
            return ""
        return h.hexdigest()
