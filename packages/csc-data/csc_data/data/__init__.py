"""Encrypted Data package implementation.

This is the active Data layer. The previous plaintext implementation is kept in
`csc_data.old_data` so operators can switch by renaming package directories if
needed.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from csc_data._enc_vfs import get_vfs_store
from csc_data.old_data import Data as OldData


class Data(OldData):
    """Data implementation backed by enc-ext-vfs for logs + default data store."""

    def __init__(self):
        self._encrypted_store = None
        super().__init__()

    def _vfs(self):
        if self._encrypted_store is None:
            self._encrypted_store = get_vfs_store()
        return self._encrypted_store

    @staticmethod
    def _safe_error(message: str):
        if not os.environ.get("CSC_QUIET"):
            print(message, file=sys.stderr)

    @staticmethod
    def _vfs_data_path(filename: str) -> str:
        return f"/data/{Path(filename).name}"

    @staticmethod
    def _vfs_log_path(filename: str) -> str:
        return f"/logs/{Path(filename).name}"

    def connect(self):
        """Connect relative data files to encrypted VFS storage."""
        if self.isDataConnected:
            return

        filename = self.source_filename
        if os.path.isabs(filename):
            return super().connect()

        vfs_path = self._vfs_data_path(filename)
        if os.environ.get("DEBUG"):
            print(f"[{self.name}] Connecting to encrypted data source: {vfs_path}")
        self._connected_source = vfs_path
        try:
            self._storage = self._vfs().read_json(vfs_path)
        except Exception as exc:
            self._safe_error(f"[{self.name}] ERROR reading encrypted data source {vfs_path}: {exc}")
            self._storage = {}
        self.isDataConnected = True
        return True

    def store_data(self):
        """Flush the in-memory store to VFS for relative data files."""
        if not self._connected_source:
            self.log("Error: Not connected to a data source.", level="ERROR")
            return

        if os.path.isabs(self.source_filename):
            return super().store_data()

        try:
            self._vfs().write_json(self._connected_source, self._storage)
            if not os.environ.get("CSC_QUIET"):
                print(
                    f"Store data successful. Saved {len(self._storage)} items to encrypted '{self._connected_source}'."
                )
            return True
        except Exception as exc:
            self._safe_error(f"[{self.name}] ERROR writing encrypted data source {self._connected_source}: {exc}")
            return False

    def log(self, message: str, level: str = "INFO"):
        """Write log entries to enc-ext-vfs while preserving console output."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        class_name = self.__class__.__name__
        log_entry = f"[{timestamp}] [{class_name}] [{level}] {message}\n"

        if not os.environ.get("CSC_QUIET"):
            print(log_entry.strip())

        try:
            self._vfs().append_text(self._vfs_log_path(self.log_file), log_entry)
        except Exception as exc:
            if not os.environ.get("CSC_QUIET"):
                print(f"CRITICAL: Failed to write encrypted log file '{self.log_file}': {exc}")

    def _write_runtime(self, line: str):
        """Persist runtime feed lines in the encrypted VFS logs area."""
        try:
            self._vfs().append_text("/logs/runtime.log", line + "\n")
        except Exception:
            pass
