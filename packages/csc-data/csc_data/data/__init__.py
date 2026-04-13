"""Data layer: plaintext data store + encrypted VFS log store.

During VFS testing, data files (channels, users, history, etc.) remain on the
plain filesystem so the site stays stable.  Only logs go into the encrypted VFS.

VFS path syntax uses :: as the native CSC encrypted filesystem separator.
These are not Unix or Windows paths — :: is the separator for all time:

    logs::haven-ef6e::runtime.log          — a log file scoped to haven-ef6e
    logs::haven-ef6e::relay::ask.log       — nested scoop
    logs::haven-ef6e::                     — prefix (list all logs for that node)

The FAT is a flat map:  enc_pathspec → block_address.  No conversion, ever.

ACL policy for server-key-encrypted log files:
  - Server shortname is always the default requester for writes
  - For offline / server-internal operations: requester defaults to shortname
  - Over IRC: requester must be a NickServ-identified nick or an oper
  - Any identified user is allowed by ACL for server-shortname-keyed files
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from csc_data._enc_vfs import find_csc_root, get_vfs_store
from csc_data.old_data import Data as OldData


class Data(OldData):
    """Data backed by plaintext for data files, enc-ext-vfs for logs only."""

    def __init__(self):
        self._encrypted_store = None
        self._shortname_cache: str | None = None
        super().__init__()

    def _vfs(self):
        if self._encrypted_store is None:
            self._encrypted_store = get_vfs_store()
        return self._encrypted_store

    @staticmethod
    def _safe_error(message: str):
        if not os.environ.get("CSC_QUIET"):
            print(message, file=sys.stderr)

    def _server_shortname(self) -> str:
        """Read server short name from csc_root/server_name (cached).
        Falls back to CSC_SERVER_ID env var, then hostname."""
        if self._shortname_cache is not None:
            return self._shortname_cache
        try:
            name = (find_csc_root() / "server_name").read_text(encoding="utf-8").strip()
            if name:
                self._shortname_cache = name
                return name
        except Exception:
            pass
        import socket
        fallback = os.environ.get("CSC_SERVER_ID") or socket.gethostname()
        self._shortname_cache = fallback
        return fallback

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

    def write_log(self, log_filename: str, log_text: str, requester: str | None = None) -> None:
        """Append log_text to an encrypted VFS log file.

        Builds the enc pathspec:  logs::<shortname>::<log_filename>
        log_filename may itself contain :: for deeper nesting, e.g.
            "relay::ask.log"  →  logs::haven-ef6e::relay::ask.log

        requester: IRC nick or oper id making this write.  Defaults to the
        server shortname, which is always ACL-permitted.  For IRC reads,
        callers must pass a NickServ-identified nick or oper id.
        """
        shortname = self._server_shortname()
        requester = requester or shortname
        enc_path = f"logs::{shortname}::{log_filename}"
        try:
            self._vfs().append_text(enc_path, log_text)
        except Exception as exc:
            if not os.environ.get("CSC_QUIET"):
                print(f"CRITICAL: Failed to write encrypted log '{enc_path}': {exc}", file=sys.stderr)

    def log(self, message: str, level: str = "INFO"):
        """Write a structured log entry to plain filesystem (not VFS).

        All logging in Data stays on plain filesystem.
        VFS is reserved for encrypted file transfers over IRC only."""
        from csc_log.log import _get_logs_dir

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        class_name = self.__class__.__name__
        log_entry = f"[{timestamp}] [{class_name}] [{level}] {message}\n"

        if not os.environ.get("CSC_QUIET"):
            print(log_entry.strip())

        try:
            log_filename = Path(self.log_file).name if hasattr(self, "log_file") else "data.log"
            log_path = _get_logs_dir() / log_filename
            with open(log_path, "a") as f:
                f.write(log_entry)
        except Exception as e:
            if not os.environ.get("CSC_QUIET"):
                print(f"CRITICAL: Failed to write log file '{log_filename}': {e}", file=sys.stderr)

    def _write_runtime(self, line: str):
        """Persist runtime feed lines to plain filesystem (not VFS).

        All runtime logs in Data stay on plain filesystem.
        VFS is reserved for encrypted file transfers over IRC only."""
        from csc_log.log import _get_logs_dir

        try:
            runtime_path = _get_logs_dir() / "runtime.log"
            with open(runtime_path, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _tail_log_file(self, path_or_enc, offset: int = 0):
        """Read new lines from a log file starting at byte offset.

        Transparent backend routing:
          - If path_or_enc contains '::' → VFS enc pathspec, read from encrypted store.
          - Otherwise → plain disk path, delegates to csc_log.Log._tail_log_file().

        Returns (lines: list[str], new_offset: int).

        VFS offset semantics: byte offset into the UTF-8-encoded full file content.
        Offsets stay stable as long as the file only grows (append-only logs).
        On truncation (new_size < offset) the offset resets to the new end.
        """
        if "::" in str(path_or_enc):
            return self._tail_vfs_log(str(path_or_enc), offset)
        return super()._tail_log_file(path_or_enc, offset)

    def _tail_vfs_log(self, enc_pathspec: str, offset: int = 0):
        """Tail an encrypted VFS log file by byte offset into its decoded content.

        Returns (lines: list[str], new_offset: int).
        """
        try:
            content = self._vfs().read_text(enc_pathspec)
            if not content:
                return [], 0
            encoded = content.encode("utf-8")
            total = len(encoded)
            if total < offset:
                # Truncated — reset to end
                return [], total
            if total == offset:
                return [], offset
            new_bytes = encoded[offset:]
            text = new_bytes.decode("utf-8", errors="ignore")
            if not text.endswith("\n"):
                last_nl = text.rfind("\n")
                if last_nl == -1:
                    return [], offset
                complete = text[:last_nl + 1]
                new_offset = offset + len(complete.encode("utf-8"))
                return [ln + "\n" for ln in complete.splitlines()], new_offset
            return [ln + "\n" for ln in text.splitlines()], total
        except Exception as e:
            self._safe_error(f"[_tail_vfs_log] Error reading {enc_pathspec}: {e}")
            return [], offset
