"""Data layer: plaintext data store + encrypted VFS log store.

During VFS testing, data files (channels, users, history, etc.) remain on the
plain filesystem so the site stays stable. Only logs go into the encrypted VFS.

VFS path syntax uses :: as the separator:
    logs::haven.ef6e::runtime.log   →  /logs/haven.ef6e/runtime.log  (FAT internal)
    logs::haven.ef6e::              →  /logs/haven.ef6e/  (directory prefix)

Switch data to VFS later once the backend is proven stable.
"""

from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

from csc_data._enc_vfs import get_vfs_store
from csc_data.old_data import Data as OldData


class Data(OldData):
    """Data backed by plaintext for data files, enc-ext-vfs for logs only."""

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
    def _server_id() -> str:
        """Stable node identifier for VFS log path prefixes.
        Uses CSC_SERVER_ID env var, falls back to hostname."""
        return os.environ.get("CSC_SERVER_ID") or socket.gethostname()

    def _vfs_log_path(self, filename: str) -> str:
        """Return a :: VFS path for a log file scoped to this node.

        Example:  "Server.log"  →  "logs::haven.ef6e::Server.log"
        """
        node = self._server_id()
        name = Path(filename).name
        return f"logs::{node}::{name}"

    # ------------------------------------------------------------------
    # Data reads/writes — plaintext only while VFS backend is under test
    # ------------------------------------------------------------------

    def connect(self):
        """Always use plaintext storage for data files during VFS testing."""
        return super().connect()

    def store_data(self):
        """Always use plaintext storage for data files during VFS testing."""
        return super().store_data()

    # ------------------------------------------------------------------
    # Logs — encrypted VFS only
    # ------------------------------------------------------------------

    def log(self, message: str, level: str = "INFO"):
        """Write log entries to enc-ext-vfs; also print to console."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        class_name = self.__class__.__name__
        log_entry = f"[{timestamp}] [{class_name}] [{level}] {message}\n"

        if not os.environ.get("CSC_QUIET"):
            print(log_entry.strip())

        try:
            self._vfs().append_text(self._vfs_log_path(self.log_file), log_entry)
        except Exception as exc:
            if not os.environ.get("CSC_QUIET"):
                print(f"CRITICAL: Failed to write encrypted log '{self.log_file}': {exc}")

    def _write_runtime(self, line: str):
        """Persist runtime feed lines to encrypted VFS logs."""
        try:
            node = self._server_id()
            self._vfs().append_text(f"logs::{node}::runtime.log", line + "\n")
        except Exception:
            pass
