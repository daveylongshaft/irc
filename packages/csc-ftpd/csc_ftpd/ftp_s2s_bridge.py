"""Bridge between FTPD and S2S for slave-to-slave file sync.

Watches for filesystem changes on the local slave, broadcasts SYNCFILE
over the S2S control channel, handles incoming SYNCFILE/RSYNCFILE/SYNCFILE_ACK,
and supports cascading (a receiver re-broadcasts to further peers).

Protocol messages (carried over existing S2S encrypted UDP):
  SYNCFILE <xfer_id> <vpath> <size> <md5> <source_host> <data_port>
  RSYNCFILE <xfer_id> <vpath> <size> <md5> <target_host> <target_port>
  SYNCFILE_ACK <xfer_id> <vpath> <success> <bytes>
"""

import fnmatch
import hashlib
import json
import logging
import os
import socket
import threading
import time
import uuid
from pathlib import Path

from .ftp_data_server import FtpDataServer

log = logging.getLogger(__name__)

# How long (seconds) to remember a (md5, vpath) pair to prevent loops
DEDUP_TTL = 300

# Max entries per SYNCINVENTORY chunk (~40KB JSON, well under 65535 UDP limit)
INVENTORY_CHUNK_SIZE = 500

# Default patterns always excluded from S2S replication
# Patterns with / or ** match the full relative path.
# Bare patterns match the first path component only (top-level).
# Use dir/** to exclude everything under a directory.
_BUILTIN_EXCLUDES = [
    ".git/**",
    ".gitignore",
    ".gitmodules",
    ".trash/**",
    ".claude/**",
    "**/*.pyc",
    "**/__pycache__/**",
    "**/*.s2s.tmp",
    ".s2s-manifest.json",
]


def _load_s2s_ignore(serve_root):
    """Load ignore patterns from .s2s-ignore in serve_root.

    File format is identical to .gitignore: one glob pattern per line,
    '#' comments, blank lines ignored.  Patterns match against the
    virtual path (leading '/').

    Returns:
        List of glob pattern strings.
    """
    patterns = list(_BUILTIN_EXCLUDES)
    ignore_file = Path(serve_root) / ".s2s-ignore"
    if ignore_file.exists():
        try:
            for line in ignore_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
        except Exception as e:
            log.warning("s2s_bridge: failed to read .s2s-ignore: %s", e)
    return patterns


def _is_excluded(vpath, patterns):
    """Check if a virtual path matches any exclude pattern.

    Args:
        vpath: Virtual path like "/ops/wo/ready/task.md".
        patterns: List of glob patterns.

    Returns:
        True if the path should be excluded from replication.
    """
    # Strip leading slash for matching
    rel = vpath.lstrip("/")
    parts = rel.split("/")

    for pat in patterns:
        if "/" in pat or "**" in pat:
            # Path pattern: match against full relative path
            if fnmatch.fnmatch(rel, pat):
                return True
        else:
            # Bare pattern (no slash): match against first path component
            # or the filename.  This prevents "*.md" from matching deep
            # files -- it only matches at the top level.
            if fnmatch.fnmatch(parts[0], pat):
                return True
            if len(parts) == 1 and fnmatch.fnmatch(rel, pat):
                return True
    return False


class FtpS2sBridge:
    """Bridge between the local FTPD slave and the S2S network.

    Lifecycle:
        1. Instantiated with references to the FtpSlave and ServerNetwork.
        2. Registers S2S message handlers for SYNCFILE/RSYNCFILE/SYNCFILE_ACK.
        3. When local files change, opens a TCP listener and broadcasts SYNCFILE.
        4. When receiving SYNCFILE, tries TCP pull; on failure sends RSYNCFILE.
        5. After successful receive, re-broadcasts (cascade) so further peers get it.
    """

    def __init__(self, slave, s2s_network, advertise_host=None):
        """Initialize the bridge.

        Args:
            slave: FtpSlave instance (provides config, serve_root, file_md5).
            s2s_network: ServerNetwork instance (provides broadcast, link access).
            advertise_host: IP to advertise in SYNCFILE. Auto-detected if None.
        """
        self.slave = slave
        self.s2s_network = s2s_network
        self.data_server = FtpDataServer(slave.config.serve_root)
        self._advertise_host = advertise_host or self._detect_host()
        self._seen = {}  # (md5, vpath) -> expiry_timestamp
        self._seen_lock = threading.Lock()
        self._pending_xfers = {}  # xfer_id -> {vpath, size, md5, ...}
        self._xfer_lock = threading.Lock()
        self._exclude_patterns = _load_s2s_ignore(slave.config.serve_root)

        # Manifest: tracks every replicated file for reconciliation on reconnect
        self._manifest_path = Path(slave.config.serve_root) / ".s2s-manifest.json"
        self._manifest = self._load_manifest()
        self._manifest_lock = threading.Lock()

        # Chunk reassembly buffer: link_id -> {total, chunks_dict}
        self._inventory_buf = {}
        self._inventory_buf_lock = threading.Lock()

    def _detect_host(self):
        """Detect the local IP to advertise to peers."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.10.10.1", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            if hasattr(self, 'log'):
                self.log('Ignored exception', level='DEBUG')
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

    # ------------------------------------------------------------------
    # Manifest persistence
    # ------------------------------------------------------------------

    def _load_manifest(self):
        """Load the manifest from disk, or return empty dict."""
        if self._manifest_path.exists():
            try:
                return json.loads(self._manifest_path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("s2s_bridge: failed to load manifest: %s", e)
        return {}

    def _save_manifest(self):
        """Atomic-write the manifest to disk (tmp + rename)."""
        tmp = self._manifest_path.with_suffix(".tmp")
        try:
            data = json.dumps(self._manifest, indent=None, separators=(",", ":"))
            tmp.write_text(data, encoding="utf-8")
            # Atomic rename (on Windows this replaces existing)
            if os.name == "nt":
                if self._manifest_path.exists():
                    self._manifest_path.unlink()
            tmp.rename(self._manifest_path)
        except Exception as e:
            log.warning("s2s_bridge: failed to save manifest: %s", e)
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _update_manifest(self, vpath, md5, size, mtime):
        """Update a single entry in the manifest and persist."""
        with self._manifest_lock:
            self._manifest[vpath] = {
                "md5": md5,
                "size": size,
                "mtime": mtime,
            }
            self._save_manifest()

    # ------------------------------------------------------------------
    # Dedup
    # ------------------------------------------------------------------

    def _is_seen(self, md5, vpath):
        """Check if we already have this exact file version."""
        now = time.time()
        key = (md5, vpath)
        with self._seen_lock:
            exp = self._seen.get(key)
            if exp and exp > now:
                return True
            return False

    def _mark_seen(self, md5, vpath):
        """Record that we have this file version."""
        key = (md5, vpath)
        with self._seen_lock:
            self._seen[key] = time.time() + DEDUP_TTL

    def _prune_seen(self):
        """Remove expired entries from seen set."""
        now = time.time()
        with self._seen_lock:
            expired = [k for k, exp in self._seen.items() if exp <= now]
            for k in expired:
                del self._seen[k]

    # ------------------------------------------------------------------
    # Outbound: local file changed -> broadcast SYNCFILE
    # ------------------------------------------------------------------

    def notify_file_changed(self, vpath, size, md5):
        """Called when a local file is created or modified.

        Opens a TCP listener and broadcasts SYNCFILE over S2S.
        Also updates the local manifest for reconciliation.

        Args:
            vpath: Virtual path (e.g. "/ops/wo/ready/task.md").
            size: File size in bytes.
            md5: MD5 hex digest of the file.
        """
        if _is_excluded(vpath, self._exclude_patterns):
            return

        if self.slave.is_locked(vpath):
            cb = getattr(self.slave, '_announce_callback', None)
            if cb:
                try:
                    cb(f"S2S SYNCFILE {vpath} SUPPRESSED (locked)")
                except Exception:
                    if hasattr(self, 'log'):
                        self.log('Ignored exception', level='DEBUG')
            return

        # Update manifest with current mtime
        local_path = self.data_server.vpath_to_local(vpath)
        try:
            mtime = local_path.stat().st_mtime
        except OSError:
            mtime = time.time()
        self._update_manifest(vpath, md5, size, mtime)

        if self._is_seen(md5, vpath):
            return  # Already propagated this version

        self._mark_seen(md5, vpath)

        xfer_id = uuid.uuid4().hex[:12]
        port, thread = self.data_server.serve_file(vpath)
        if port is None:
            log.error("s2s_bridge: cannot serve %s, skipping broadcast", vpath)
            return

        with self._xfer_lock:
            self._pending_xfers[xfer_id] = {
                "vpath": vpath,
                "size": size,
                "md5": md5,
                "port": port,
                "thread": thread,
                "time": time.time(),
            }

        msg = f"{xfer_id} {vpath} {size} {md5} {self._advertise_host} {port}"
        self.s2s_network.broadcast_to_network("SYNCFILE", msg)
        log.info("s2s_bridge: broadcast SYNCFILE %s (%d bytes, port %d)",
                 vpath, size, port)

    def notify_files_changed(self, file_infos):
        """Batch notify for multiple file changes.

        Args:
            file_infos: List of dicts with keys: path, size, md5.
        """
        for info in file_infos:
            self.notify_file_changed(info["path"], info["size"], info["md5"])

    # ------------------------------------------------------------------
    # Inbound S2S message handlers (called by ServerNetwork dispatch)
    # ------------------------------------------------------------------

    def handle_syncfile(self, link, rest):
        """Handle incoming SYNCFILE: try to pull the file via TCP.

        Format: SYNCFILE <xfer_id> <vpath> <size> <md5> <source_host> <data_port>
        """
        parts = rest.split()
        if len(parts) < 6:
            log.warning("s2s_bridge: malformed SYNCFILE: %s", rest)
            return

        xfer_id = parts[0]
        vpath = parts[1]
        size = int(parts[2])
        md5 = parts[3]
        source_host = parts[4]
        data_port = int(parts[5])

        # Exclusion check
        if _is_excluded(vpath, self._exclude_patterns):
            log.debug("s2s_bridge: skipping SYNCFILE %s (excluded)", vpath)
            return

        # Reject incoming sync for locked files
        if self.slave.is_locked(vpath):
            log.debug("s2s_bridge: skipping SYNCFILE %s (locked)", vpath)
            cb = getattr(self.slave, '_announce_callback', None)
            if cb:
                try:
                    cb(f"S2S SYNCFILE {vpath} BLOCKED (locked)")
                except Exception:
                    if hasattr(self, 'log'):
                        self.log('Ignored exception', level='DEBUG')
            return

        # Dedup: skip if we already have this version
        if self._is_seen(md5, vpath):
            log.debug("s2s_bridge: skipping SYNCFILE %s (already seen)", vpath)
            return

        # Check if local file already matches
        local_path = self.data_server.vpath_to_local(vpath)
        if local_path.exists():
            local_md5 = self.slave._file_md5(local_path)
            if local_md5 == md5:
                self._mark_seen(md5, vpath)
                log.debug("s2s_bridge: %s already up to date", vpath)
                return

        # Try TCP pull from source
        def _do_pull():
            success, nbytes = self.data_server.pull_file(
                vpath, source_host, data_port
            )

            if success:
                self._mark_seen(md5, vpath)
                # Update manifest with the received file's mtime
                received_path = self.data_server.vpath_to_local(vpath)
                try:
                    st = received_path.stat()
                    self._update_manifest(vpath, md5, st.st_size, st.st_mtime)
                except OSError:
                    self._update_manifest(vpath, md5, size, time.time())
                # Send ACK
                ack = f"{xfer_id} {vpath} 1 {nbytes}"
                self.s2s_network.broadcast_to_network("SYNCFILE_ACK", ack)
                log.info("s2s_bridge: pulled %s (%d bytes)", vpath, nbytes)
                cb = getattr(self.slave, '_announce_callback', None)
                if cb:
                    try:
                        cb(f"S2S SYNCFILE {vpath} (received)")
                    except Exception:
                        import logging
                        logging.getLogger(__name__).debug('Ignored exception', exc_info=True)
                # Trigger inventory delta on slave
                self.slave.schedule_inventory_delta()
                # Cascade: re-broadcast so further peers can pull from us
                self._cascade(vpath, size, md5)
            else:
                # TCP connect failed (NAT/firewall) -> reverse fallback
                log.info("s2s_bridge: pull failed for %s, requesting RSYNCFILE",
                         vpath)
                self._request_reverse(xfer_id, vpath, size, md5)

        t = threading.Thread(target=_do_pull, daemon=True,
                             name=f"s2s-pull-{xfer_id}")
        t.start()

    def handle_rsyncfile(self, link, rest):
        """Handle incoming RSYNCFILE: receiver wants us to push the file.

        Format: RSYNCFILE <xfer_id> <vpath> <size> <md5> <target_host> <target_port>
        """
        parts = rest.split()
        if len(parts) < 6:
            log.warning("s2s_bridge: malformed RSYNCFILE: %s", rest)
            return

        xfer_id = parts[0]
        vpath = parts[1]
        # size = int(parts[2])  # not needed for push
        # md5 = parts[3]
        target_host = parts[4]
        target_port = int(parts[5])

        # Check if we have the file
        local_path = self.data_server.vpath_to_local(vpath)
        if not local_path.exists():
            log.warning("s2s_bridge: RSYNCFILE for %s but file not found", vpath)
            return

        # Check if this RSYNCFILE is for one of our pending transfers
        with self._xfer_lock:
            pending = self._pending_xfers.get(xfer_id)

        if not pending:
            # Not our transfer, maybe another peer's. Check if we have it.
            log.debug("s2s_bridge: RSYNCFILE %s not our xfer, checking file",
                       xfer_id)

        def _do_push():
            success, nbytes = self.data_server.push_file(
                vpath, target_host, target_port
            )
            if success:
                ack = f"{xfer_id} {vpath} 1 {nbytes}"
                self.s2s_network.broadcast_to_network("SYNCFILE_ACK", ack)
                log.info("s2s_bridge: pushed %s (%d bytes) to %s:%d",
                         vpath, nbytes, target_host, target_port)
            else:
                log.error("s2s_bridge: push failed for %s to %s:%d",
                          vpath, target_host, target_port)

        t = threading.Thread(target=_do_push, daemon=True,
                             name=f"s2s-push-{xfer_id}")
        t.start()

    def handle_syncfile_ack(self, link, rest):
        """Handle incoming SYNCFILE_ACK: transfer confirmed.

        Format: SYNCFILE_ACK <xfer_id> <vpath> <success> <bytes>
        """
        parts = rest.split()
        if len(parts) < 4:
            return

        xfer_id = parts[0]
        vpath = parts[1]
        success = parts[2]
        nbytes = parts[3]

        with self._xfer_lock:
            self._pending_xfers.pop(xfer_id, None)

        log.info("s2s_bridge: ACK %s %s=%s (%s bytes)",
                 xfer_id, vpath, success, nbytes)

    # ------------------------------------------------------------------
    # Reverse fallback
    # ------------------------------------------------------------------

    def _request_reverse(self, xfer_id, vpath, size, md5):
        """Open a listener and send RSYNCFILE asking source to push."""
        port, thread = self.data_server.accept_and_recv(vpath)
        if port is None:
            log.error("s2s_bridge: cannot open listener for RSYNCFILE %s", vpath)
            return

        msg = f"{xfer_id} {vpath} {size} {md5} {self._advertise_host} {port}"
        self.s2s_network.broadcast_to_network("RSYNCFILE", msg)
        log.info("s2s_bridge: sent RSYNCFILE %s (listening on %d)", vpath, port)

        # Wait for the receive to complete in background, then cascade
        def _wait_and_cascade():
            thread.join(timeout=DEDUP_TTL)
            local_path = self.data_server.vpath_to_local(vpath)
            if local_path.exists():
                local_md5 = self.slave._file_md5(local_path)
                if local_md5 == md5:
                    self._mark_seen(md5, vpath)
                    ack = f"{xfer_id} {vpath} 1 {local_path.stat().st_size}"
                    self.s2s_network.broadcast_to_network("SYNCFILE_ACK", ack)
                    self.slave.schedule_inventory_delta()
                    self._cascade(vpath, size, md5)

        t = threading.Thread(target=_wait_and_cascade, daemon=True,
                             name=f"s2s-rwait-{xfer_id}")
        t.start()

    # ------------------------------------------------------------------
    # Cascade
    # ------------------------------------------------------------------

    def _cascade(self, vpath, size, md5):
        """Re-broadcast SYNCFILE so further peers can pull from us."""
        xfer_id = uuid.uuid4().hex[:12]
        port, thread = self.data_server.serve_file(vpath)
        if port is None:
            return

        with self._xfer_lock:
            self._pending_xfers[xfer_id] = {
                "vpath": vpath,
                "size": size,
                "md5": md5,
                "port": port,
                "thread": thread,
                "time": time.time(),
            }

        msg = f"{xfer_id} {vpath} {size} {md5} {self._advertise_host} {port}"
        self.s2s_network.broadcast_to_network("SYNCFILE", msg)
        log.info("s2s_bridge: cascade SYNCFILE %s (port %d)", vpath, port)

    # ------------------------------------------------------------------
    # Reconciliation: SYNCINVENTORY
    # ------------------------------------------------------------------

    def send_inventory(self, link):
        """Send our manifest to a peer as chunked SYNCINVENTORY messages.

        Called after _send_full_sync on link-up.

        Args:
            link: The ServerLink to send inventory to.
        """
        with self._manifest_lock:
            entries = [
                {"path": vpath, "md5": info["md5"],
                 "size": info["size"], "mtime": info["mtime"]}
                for vpath, info in self._manifest.items()
            ]

        if not entries:
            # Send a single empty chunk so the peer knows we have nothing
            link.send_message("SYNCINVENTORY", "0 1 []")
            log.info("s2s_bridge: sent empty SYNCINVENTORY to %s",
                     link.remote_server_id)
            return

        # Chunk the entries
        total_chunks = (len(entries) + INVENTORY_CHUNK_SIZE - 1) // INVENTORY_CHUNK_SIZE
        for i in range(total_chunks):
            chunk = entries[i * INVENTORY_CHUNK_SIZE:(i + 1) * INVENTORY_CHUNK_SIZE]
            payload = json.dumps(chunk, separators=(",", ":"))
            link.send_message("SYNCINVENTORY", f"{i} {total_chunks} {payload}")

        log.info("s2s_bridge: sent SYNCINVENTORY to %s (%d files, %d chunks)",
                 link.remote_server_id, len(entries), total_chunks)

    def handle_syncinventory(self, link, rest):
        """Handle incoming SYNCINVENTORY: reassemble chunks, then reconcile.

        Format: SYNCINVENTORY <chunk_index> <total_chunks> <json_blob>
        """
        parts = rest.split(" ", 2)
        if len(parts) < 3:
            log.warning("s2s_bridge: malformed SYNCINVENTORY: %s", rest[:80])
            return

        try:
            chunk_idx = int(parts[0])
            total_chunks = int(parts[1])
        except ValueError:
            log.warning("s2s_bridge: bad SYNCINVENTORY header: %s", rest[:80])
            return

        json_blob = parts[2]
        link_id = link.remote_server_id or id(link)

        with self._inventory_buf_lock:
            if link_id not in self._inventory_buf:
                self._inventory_buf[link_id] = {
                    "total": total_chunks,
                    "chunks": {},
                }
            buf = self._inventory_buf[link_id]
            buf["chunks"][chunk_idx] = json_blob

            # Not all chunks received yet
            if len(buf["chunks"]) < total_chunks:
                return

            # All chunks received -- reassemble
            all_entries = []
            for idx in range(total_chunks):
                chunk_json = buf["chunks"].get(idx, "[]")
                try:
                    all_entries.extend(json.loads(chunk_json))
                except json.JSONDecodeError as e:
                    log.warning("s2s_bridge: bad JSON in SYNCINVENTORY chunk %d: %s",
                                idx, e)
            del self._inventory_buf[link_id]

        log.info("s2s_bridge: received SYNCINVENTORY from %s (%d files)",
                 link.remote_server_id, len(all_entries))

        # Run reconciliation in a background thread to avoid blocking dispatch
        t = threading.Thread(
            target=self._reconcile,
            args=(link, all_entries),
            daemon=True,
            name=f"s2s-reconcile-{link.remote_server_id}",
        )
        t.start()

    def _reconcile(self, link, remote_entries):
        """Compare remote inventory against local manifest, pull newer files.

        For each remote file:
          - Not in local manifest -> pull (new file)
          - MD5 differs AND remote mtime > local mtime -> pull (remote is newer)
          - Same mtime, different md5 -> log warning, keep local
          - Otherwise -> skip (local is same or newer)

        Files in local but not remote are ignored (no delete propagation).
        """
        with self._manifest_lock:
            local = dict(self._manifest)

        pull_count = 0
        skip_count = 0
        conflict_count = 0

        for entry in remote_entries:
            vpath = entry.get("path")
            remote_md5 = entry.get("md5")
            remote_mtime = entry.get("mtime", 0)
            remote_size = entry.get("size", 0)

            if not vpath or not remote_md5:
                continue

            if _is_excluded(vpath, self._exclude_patterns):
                continue

            if self.slave.is_locked(vpath):
                cb = getattr(self.slave, '_announce_callback', None)
                if cb:
                    try:
                        cb(f"S2S RECONCILE {vpath} SKIPPED (locked)")
                    except Exception:
                        if hasattr(self, 'log'):
                            self.log('Ignored exception', level='DEBUG')
                continue

            local_entry = local.get(vpath)

            if local_entry is None:
                # New file -- pull it
                self._request_file_from_peer(link, vpath, remote_size, remote_md5)
                pull_count += 1
            elif local_entry["md5"] != remote_md5:
                local_mtime = local_entry.get("mtime", 0)
                if remote_mtime > local_mtime:
                    # Remote is newer -- pull it
                    self._request_file_from_peer(link, vpath, remote_size, remote_md5)
                    pull_count += 1
                elif remote_mtime == local_mtime:
                    # Same mtime, different md5 -- conflict
                    log.warning(
                        "s2s_bridge: reconcile conflict %s "
                        "(same mtime %.0f, local md5=%s remote md5=%s) -- keeping local",
                        vpath, remote_mtime, local_entry["md5"], remote_md5)
                    conflict_count += 1
                else:
                    skip_count += 1  # Local is newer
            else:
                skip_count += 1  # Same md5

        log.info(
            "s2s_bridge: reconciliation with %s complete: "
            "%d pulled, %d skipped, %d conflicts",
            link.remote_server_id, pull_count, skip_count, conflict_count)

    def _request_file_from_peer(self, link, vpath, size, md5):
        """Request a specific file from a peer via SYNCFILE mechanism.

        Sends a targeted SYNCFILE to the peer so they open a data port for us.
        """
        xfer_id = uuid.uuid4().hex[:12]

        # Ask the remote to serve this file by sending SYNCFILE back at them
        # with our host as target.  The remote's bridge will see it, check
        # dedup (which will pass since the md5 matches their local copy),
        # and the file is already on disk there.  Instead, we use the
        # existing RSYNCFILE reverse-push mechanism: open a listener locally,
        # then ask the remote to push.
        port, thread = self.data_server.accept_and_recv(vpath)
        if port is None:
            log.error("s2s_bridge: reconcile: cannot open listener for %s", vpath)
            return

        msg = f"{xfer_id} {vpath} {size} {md5} {self._advertise_host} {port}"
        link.send_message("RSYNCFILE", msg)
        log.debug("s2s_bridge: reconcile: requesting %s from %s (port %d)",
                  vpath, link.remote_server_id, port)

        # Wait for receive in background, then update manifest
        def _wait_and_update():
            thread.join(timeout=DEDUP_TTL)
            local_path = self.data_server.vpath_to_local(vpath)
            if local_path.exists():
                local_md5 = self.slave._file_md5(local_path)
                if local_md5 == md5:
                    self._mark_seen(md5, vpath)
                    st = local_path.stat()
                    self._update_manifest(vpath, md5, st.st_size, st.st_mtime)
                    self.slave.schedule_inventory_delta()
                    log.info("s2s_bridge: reconcile: received %s", vpath)
                else:
                    log.warning("s2s_bridge: reconcile: md5 mismatch after pull %s "
                                "(expected %s, got %s)", vpath, md5, local_md5)

        t = threading.Thread(target=_wait_and_update, daemon=True,
                             name=f"s2s-reconcile-pull-{xfer_id}")
        t.start()

    # ------------------------------------------------------------------
    # SYNCRENAME: atomic rename propagation
    # ------------------------------------------------------------------

    def notify_file_renamed(self, old_vpath, new_vpath, size, md5, mtime):
        """Broadcast SYNCRENAME to all peers after a local rename."""
        if _is_excluded(old_vpath, self._exclude_patterns):
            return
        if _is_excluded(new_vpath, self._exclude_patterns):
            return

        # Update manifest: remove old, add new
        with self._manifest_lock:
            self._manifest.pop(old_vpath, None)
            self._manifest[new_vpath] = {
                "md5": md5, "size": size, "mtime": mtime,
            }
            self._save_manifest()

        # Mark new version as seen
        self._mark_seen(md5, new_vpath)

        msg = f"{old_vpath} {new_vpath} {size} {md5} {mtime}"
        self.s2s_network.broadcast_to_network("SYNCRENAME", msg)
        log.info("s2s_bridge: broadcast SYNCRENAME %s -> %s", old_vpath, new_vpath)

        cb = getattr(self.slave, '_announce_callback', None)
        if cb:
            try:
                cb(f"S2S SYNCRENAME {old_vpath} -> {new_vpath} (broadcast)")
            except Exception:
                if hasattr(self, 'log'):
                    self.log('Ignored exception', level='DEBUG')

    def handle_syncrename(self, link, rest):
        """Handle incoming SYNCRENAME: rename local file atomically.

        Format: SYNCRENAME <old_vpath> <new_vpath> <size> <md5> <mtime>
        """
        parts = rest.split()
        if len(parts) < 5:
            log.warning("s2s_bridge: malformed SYNCRENAME: %s", rest)
            return

        old_vpath = parts[0]
        new_vpath = parts[1]
        size = int(parts[2])
        md5 = parts[3]
        mtime = float(parts[4])

        if _is_excluded(new_vpath, self._exclude_patterns):
            return

        # Execute local rename
        old_local = self.data_server.vpath_to_local(old_vpath)
        new_local = self.data_server.vpath_to_local(new_vpath)

        if not old_local.exists():
            log.debug("s2s_bridge: SYNCRENAME source %s not found locally", old_vpath)
            return

        try:
            new_local.parent.mkdir(parents=True, exist_ok=True)
            if os.name == "nt" and new_local.exists():
                new_local.unlink()
            old_local.rename(new_local)
            log.info("s2s_bridge: renamed %s -> %s", old_vpath, new_vpath)

            cb = getattr(self.slave, '_announce_callback', None)
            if cb:
                try:
                    peer = getattr(link, 'remote_server_id', 'unknown')
                    cb(f"S2S SYNCRENAME {old_vpath} -> {new_vpath} (received from {peer})")
                except Exception:
                    if hasattr(self, 'log'):
                        self.log('Ignored exception', level='DEBUG')
        except OSError as e:
            log.error("s2s_bridge: SYNCRENAME failed %s -> %s: %s",
                       old_vpath, new_vpath, e)
            return

        # Update manifest
        with self._manifest_lock:
            self._manifest.pop(old_vpath, None)
            self._manifest[new_vpath] = {
                "md5": md5, "size": size, "mtime": mtime,
            }
            self._save_manifest()

        self._mark_seen(md5, new_vpath)
        self.slave.schedule_inventory_delta()

    # ------------------------------------------------------------------
    # Lock delegation (called by FtpFileOps)
    # ------------------------------------------------------------------

    def lock_file(self, vpath, lock_id, ttl=7200):
        """Lock a file on the local slave."""
        self.slave.lock_file(vpath, lock_id, ttl)

    def unlock_file(self, vpath, lock_id):
        """Unlock a file on the local slave."""
        self.slave.unlock_file(vpath, lock_id)

    # ------------------------------------------------------------------
    # Periodic cleanup
    # ------------------------------------------------------------------

    def cleanup(self):
        """Prune expired dedup entries and stale pending transfers."""
        self._prune_seen()
        now = time.time()
        with self._xfer_lock:
            stale = [xid for xid, info in self._pending_xfers.items()
                     if now - info["time"] > DEDUP_TTL]
            for xid in stale:
                del self._pending_xfers[xid]
