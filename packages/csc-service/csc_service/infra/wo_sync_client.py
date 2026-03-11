"""
wo_sync_client.py — Slave-side sync client for ops/wo/.

On startup (or when a filelist hash mismatch is detected), fetches the
filelist hash from the FTP master, compares it to the local state, and
downloads only the changed or missing files.

Usage:
    client = WoSyncClient(
        wo_dir="/path/to/ops/wo",
        ftp_master_host="fahu.facingaddictionwithhope.com",
        ftp_master_port=9521,
        ftp_user="csc-node",
        ftp_password="...",
    )
    client.sync()   # sync once
    client.run()    # run continuously (blocks)
"""

import ftplib
import io
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .wo_watcher import compute_filelist_hash

log = logging.getLogger(__name__)


class WoSyncClient:
    """Slave-side sync client: compares filelist hash, downloads deltas.

    Args:
        wo_dir: Local path to the ops/wo/ directory.
        ftp_master_host: Hostname of the FTP master (fahu).
        ftp_master_port: Control port (default 9521).
        ftp_user: FTP username.
        ftp_password: FTP password / credential.
        poll_interval_s: How often to check for updates when run() is used.
    """

    def __init__(
        self,
        wo_dir: str,
        ftp_master_host: str,
        ftp_master_port: int = 9521,
        ftp_user: str = "csc-node",
        ftp_password: str = "",
        poll_interval_s: int = 30,
    ):
        self.wo_dir = Path(wo_dir).resolve()
        self.ftp_master_host = ftp_master_host
        self.ftp_master_port = ftp_master_port
        self.ftp_user = ftp_user
        self.ftp_password = ftp_password
        self.poll_interval_s = poll_interval_s
        self._stop = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync(self) -> bool:
        """Perform one sync cycle.  Returns True if files were updated."""
        ftp = self._connect()
        try:
            return self._do_sync(ftp)
        finally:
            try:
                ftp.quit()
            except Exception:
                pass

    def run(self) -> None:
        """Run continuously, syncing every poll_interval_s.  Blocks."""
        log.info(
            "WoSyncClient: starting, polling every %ds", self.poll_interval_s
        )
        while not self._stop:
            try:
                self.sync()
            except Exception as exc:
                log.error("WoSyncClient: sync error: %s", exc)
            time.sleep(self.poll_interval_s)

    def stop(self) -> None:
        """Signal run() to exit on next iteration."""
        self._stop = True

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _connect(self) -> ftplib.FTP_TLS:
        ftp = ftplib.FTP_TLS()
        ftp.connect(self.ftp_master_host, self.ftp_master_port, timeout=30)
        ftp.auth()
        ftp.login(self.ftp_user, self.ftp_password)
        ftp.prot_p()
        return ftp

    def _fetch_remote_hash(self, ftp: ftplib.FTP_TLS) -> Optional[str]:
        """Download wo/.filelist.hash from master.  Returns hash string or None."""
        buf = io.BytesIO()
        try:
            ftp.retrbinary("RETR wo/.filelist.hash", buf.write)
            return buf.getvalue().decode().strip()
        except ftplib.error_perm:
            log.warning("WoSyncClient: no .filelist.hash on master yet")
            return None

    def _fetch_remote_listing(self, ftp: ftplib.FTP_TLS) -> Dict[str, Tuple[int, str]]:
        """Return {rel_path: (size, mtime_str)} from master's wo/ directory."""
        listing: Dict[str, Tuple[int, str]] = {}
        try:
            lines: List[str] = []
            ftp.retrlines("LIST -a wo", lines.append)
            for line in lines:
                self._parse_list_line(line, "wo", listing)
        except ftplib.error_perm as exc:
            log.error("WoSyncClient: LIST failed: %s", exc)
        return listing

    def _parse_list_line(
        self,
        line: str,
        prefix: str,
        listing: Dict[str, Tuple[int, str]],
    ) -> None:
        """Parse one LIST line and recurse into subdirectories (not implemented here
        for simplicity — callers use MLSD when available)."""
        # Minimal parse: skip directories and hidden files
        parts = line.split()
        if len(parts) < 9:
            return
        perms = parts[0]
        size_str = parts[4]
        name = parts[8]
        if name in (".", ".."):
            return
        if perms.startswith("d"):
            return  # skip dirs in simple listing
        rel = f"{prefix}/{name}".lstrip("wo/")
        try:
            listing[rel] = (int(size_str), "")
        except ValueError:
            pass

    def _fetch_mlsd_listing(
        self, ftp: ftplib.FTP_TLS, remote_dir: str = "wo"
    ) -> Dict[str, int]:
        """Return {rel_path: size} using MLSD (RFC 3659), recursing into subdirs."""
        result: Dict[str, int] = {}
        try:
            entries = list(ftp.mlsd(remote_dir, facts=["type", "size"]))
        except ftplib.error_perm:
            return result

        for name, facts in entries:
            if name in (".", ".."):
                continue
            ftype = facts.get("type", "file")
            rel = f"{remote_dir}/{name}"[len("wo/"):]  # strip leading wo/
            if ftype == "dir":
                sub = self._fetch_mlsd_listing(ftp, f"{remote_dir}/{name}")
                result.update(sub)
            else:
                try:
                    result[rel] = int(facts.get("size", 0))
                except ValueError:
                    result[rel] = 0
        return result

    def _download_file(
        self, ftp: ftplib.FTP_TLS, rel_path: str
    ) -> None:
        """Download wo/<rel_path> from master into local wo_dir."""
        remote = f"wo/{rel_path}"
        local = self.wo_dir / rel_path
        local.parent.mkdir(parents=True, exist_ok=True)
        with open(local, "wb") as fh:
            ftp.retrbinary(f"RETR {remote}", fh.write)
        log.debug("WoSyncClient: downloaded %s", rel_path)

    def _local_sizes(self) -> Dict[str, int]:
        """Return {rel_path: size} for all local files under wo_dir."""
        result: Dict[str, int] = {}
        for root, _dirs, files in os.walk(str(self.wo_dir)):
            for fname in files:
                full = Path(root) / fname
                try:
                    rel = str(full.relative_to(self.wo_dir))
                    result[rel] = full.stat().st_size
                except OSError:
                    pass
        return result

    def _do_sync(self, ftp: ftplib.FTP_TLS) -> bool:
        """Core sync logic.  Returns True if any files were downloaded."""
        # 1. Fetch remote hash
        remote_hash = self._fetch_remote_hash(ftp)
        if remote_hash is None:
            return False

        # 2. Compare to local hash
        local_hash = compute_filelist_hash(self.wo_dir)
        if remote_hash == local_hash:
            log.debug("WoSyncClient: already in sync (%s)", local_hash[:12])
            return False

        log.info(
            "WoSyncClient: hash mismatch local=%s remote=%s, syncing delta",
            local_hash[:12],
            remote_hash[:12],
        )

        # 3. Fetch remote listing (prefer MLSD)
        remote_sizes = self._fetch_mlsd_listing(ftp)
        local_sizes = self._local_sizes()

        # 4. Download changed/missing files
        updated = False
        for rel_path, remote_size in sorted(remote_sizes.items()):
            if rel_path.startswith("."):
                continue  # skip hidden meta files
            local_size = local_sizes.get(rel_path)
            if local_size != remote_size:
                try:
                    self._download_file(ftp, rel_path)
                    updated = True
                except Exception as exc:
                    log.error(
                        "WoSyncClient: failed to download %s: %s", rel_path, exc
                    )

        if updated:
            log.info("WoSyncClient: delta sync complete")
        return updated
