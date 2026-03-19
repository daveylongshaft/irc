"""Slave FTP daemon.

Connects to the master via TLS, registers, sends file inventory,
watches serve_root for changes, and handles transfer commands.
"""

import hashlib
import logging
import os
import platform as platform_mod
import shutil
import socket
import ssl
import threading
import time
from pathlib import Path

from .ftp_config import FtpConfig
from .ftp_protocol import FtpProtocol
from .ftp_slave_transfer import FtpSlaveTransfer

log = logging.getLogger(__name__)


class FtpSlave:
    """Slave daemon: TLS connection to master, inventory, fs watcher, heartbeat.

    Lifecycle:
        1. Connect to master via TLS (mTLS with S2S certs)
        2. Send REGISTER with slave_id, serve_root, capacity
        3. Wait for REGISTER_ACK
        4. Send full INVENTORY
        5. Enter main loop: heartbeat, process commands, watch filesystem
    """

    def __init__(self, config):
        """Initialize the slave.

        Args:
            config: FtpConfig instance (must have role='slave').
        """
        self.config = config
        self.transfer_handler = FtpSlaveTransfer(self)
        self._sock = None
        self._shutdown = threading.Event()
        self._send_lock = threading.Lock()
        self._delta_pending = threading.Event()
        self._connected = False

        # S2S bridge (attached externally via set_s2s_bridge)
        self._s2s_bridge = None

        # Announce callback for FTP operations (set externally)
        self._announce_callback = None

        # File lock tracking: vpath -> {"lock_id": str, "expires": float}
        self._locked_files = {}
        self._lock_lock = threading.Lock()

        # Determine slave_id from hostname or S2S cert CN
        self._slave_id = self._get_slave_id()

    def start(self):
        """Start the slave in daemon threads (connect + heartbeat + watcher)."""
        log.info("FtpSlave starting (slave_id=%s, master=%s:%d)",
                 self._slave_id, self.config.master_host,
                 self.config.master_control_port)

        # Ensure serve_root exists
        os.makedirs(self.config.serve_root, exist_ok=True)

        # Connection + command processing thread
        t1 = threading.Thread(
            target=self._run_connection,
            daemon=True,
            name="ftpd-slave-conn",
        )
        t1.start()

        # Heartbeat thread
        t2 = threading.Thread(
            target=self._run_heartbeat,
            daemon=True,
            name="ftpd-slave-hb",
        )
        t2.start()

        # Filesystem watcher thread
        t3 = threading.Thread(
            target=self._run_fs_watcher,
            daemon=True,
            name="ftpd-slave-fswatch",
        )
        t3.start()

        log.info("FtpSlave started")

    def stop(self):
        """Signal shutdown."""
        self._shutdown.set()
        self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass

    def send_to_master(self, data):
        """Send a pre-encoded protocol message to the master.

        Args:
            data: bytes from FtpProtocol.encode() or make_*().
        """
        with self._send_lock:
            if not self._connected or not self._sock:
                log.warning("FtpSlave: not connected, cannot send")
                return
            try:
                FtpProtocol.send_msg(self._sock, data)
            except Exception as e:
                log.error("FtpSlave: send error: %s", e)
                self._connected = False

    def schedule_inventory_delta(self):
        """Signal that a filesystem change needs to be reported."""
        self._delta_pending.set()

    def set_s2s_bridge(self, bridge):
        """Attach an FtpS2sBridge for peer-to-peer file sync.

        Args:
            bridge: FtpS2sBridge instance.
        """
        self._s2s_bridge = bridge

    def set_announce_callback(self, cb):
        """Set a callback for announcing FTP operations to IRC.

        Args:
            cb: callable(str) that writes to ftp_announce.log.
        """
        self._announce_callback = cb

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _run_connection(self):
        """Main connection loop: connect, register, process commands."""
        while not self._shutdown.is_set():
            try:
                self._connect_and_register()
                if self._connected:
                    self._send_inventory()
                    self._command_loop()
            except Exception as e:
                log.error("FtpSlave: connection error: %s", e)
                self._connected = False

            if not self._shutdown.is_set():
                log.info("FtpSlave: reconnecting in 10s...")
                self._shutdown.wait(10)

    def _connect_and_register(self):
        """Establish TLS connection to master and send REGISTER."""
        ctx = self._build_ssl_context()

        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(30)
        try:
            raw.connect((self.config.master_host, self.config.master_control_port))
        except (OSError, ConnectionError) as e:
            log.warning("FtpSlave: cannot connect to master %s:%d: %s",
                        self.config.master_host, self.config.master_control_port, e)
            raw.close()
            return

        try:
            self._sock = ctx.wrap_socket(raw, server_hostname=self.config.master_host)
        except ssl.SSLError as e:
            log.warning("FtpSlave: TLS handshake failed: %s", e)
            raw.close()
            return

        # Send REGISTER
        capacity = self._get_disk_capacity()
        FtpProtocol.send_msg(
            self._sock,
            FtpProtocol.make_register(self._slave_id, self.config.serve_root, capacity),
        )

        # Wait for REGISTER_ACK
        msg = FtpProtocol.recv_line(self._sock)
        if msg is None or msg.get("cmd") != FtpProtocol.CMD_REGISTER_ACK:
            log.warning("FtpSlave: expected REGISTER_ACK, got %s", msg)
            self._sock.close()
            return

        if not msg.get("accepted", False):
            log.error("FtpSlave: registration rejected: %s", msg.get("reason", ""))
            self._sock.close()
            return

        self._connected = True
        log.info("FtpSlave: registered with master %s (master_id=%s)",
                 self.config.master_host, msg.get("master_id", ""))

    def _command_loop(self):
        """Process commands from master until disconnect."""
        while self._connected and not self._shutdown.is_set():
            msg = FtpProtocol.recv_line(self._sock)
            if msg is None:
                log.info("FtpSlave: master disconnected")
                self._connected = False
                break

            self._handle_command(msg)

    def _handle_command(self, msg):
        """Dispatch a command from the master."""
        cmd = msg.get("cmd", "")

        if cmd == FtpProtocol.CMD_SEND_FILE:
            self.transfer_handler.handle_send_file(
                msg["transfer_id"], msg["path"],
                msg["client_host"], msg["client_port"],
            )

        elif cmd == FtpProtocol.CMD_RECV_FILE:
            self.transfer_handler.handle_recv_file(
                msg["transfer_id"], msg["path"],
                msg["client_host"], msg["client_port"],
            )

        elif cmd == FtpProtocol.CMD_MIRROR_FILE:
            # Phase 4 -- for now, log and skip
            log.info("FtpSlave: MIRROR_FILE not yet implemented")

        elif cmd == FtpProtocol.CMD_DELETE_FILE:
            self.transfer_handler.delete_file(msg["path"])

        elif cmd == FtpProtocol.CMD_RENAME_FILE:
            self.transfer_handler.rename_file(msg["path"], msg["new_path"])
            if self._announce_callback:
                try:
                    self._announce_callback(f"SLAVE RENAME {msg['path']} -> {msg['new_path']}")
                except Exception:
                    pass

        elif cmd == FtpProtocol.CMD_LOCK_FILE:
            self.lock_file(msg["path"], msg["lock_id"], msg.get("ttl", 7200))

        elif cmd == FtpProtocol.CMD_UNLOCK_FILE:
            self.unlock_file(msg["path"], msg["lock_id"])

        elif cmd == FtpProtocol.CMD_INVENTORY_REQUEST:
            self._send_inventory()

        else:
            log.warning("FtpSlave: unknown command %r", cmd)

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    def _send_inventory(self):
        """Scan serve_root and send full inventory to master."""
        files = self._scan_files()
        self.send_to_master(FtpProtocol.make_inventory(files))
        log.info("FtpSlave: sent inventory (%d files)", len(files))

    def _scan_files(self):
        """Scan serve_root and return list of file metadata dicts."""
        root = Path(self.config.serve_root)
        files = []
        if not root.exists():
            return files

        for dirpath, _, filenames in os.walk(str(root)):
            for fname in filenames:
                full = Path(dirpath) / fname
                try:
                    st = full.stat()
                    rel = "/" + full.relative_to(root).as_posix()
                    md5 = self._file_md5(full)
                    files.append({
                        "path": rel,
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                        "md5": md5,
                    })
                except OSError:
                    pass
        return files

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

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def _run_heartbeat(self):
        """Send periodic heartbeat to master."""
        while not self._shutdown.is_set():
            self._shutdown.wait(self.config.heartbeat_interval)
            if self._shutdown.is_set():
                break
            if not self._connected:
                continue

            try:
                disk_free = self._get_disk_free()
                load_avg = self._get_load_avg()
                self.send_to_master(FtpProtocol.make_heartbeat(
                    disk_free=disk_free,
                    active_transfers=self.transfer_handler.active_count,
                    load_avg=load_avg,
                ))
            except Exception as e:
                log.error("FtpSlave: heartbeat error: %s", e)

    # ------------------------------------------------------------------
    # Filesystem watcher
    # ------------------------------------------------------------------

    def _run_fs_watcher(self):
        """Watch serve_root for changes and send inventory deltas."""
        root = Path(self.config.serve_root)
        last_snapshot = {}
        refresh_interval = self.config.inventory_refresh_interval

        while not self._shutdown.is_set():
            # Wait for either a manual trigger or the refresh interval
            self._delta_pending.wait(timeout=refresh_interval)
            self._delta_pending.clear()

            if self._shutdown.is_set() or not self._connected:
                continue

            new_snapshot = self._build_snapshot(root)

            # Compute delta
            added = []
            modified = []
            removed = []

            for path, info in new_snapshot.items():
                if path not in last_snapshot:
                    added.append(info)
                elif last_snapshot[path]["md5"] != info["md5"]:
                    modified.append(info)

            for path in last_snapshot:
                if path not in new_snapshot:
                    removed.append(path)

            if added or modified or removed:
                self.send_to_master(FtpProtocol.make_inventory_delta(
                    added=added, removed=removed, modified=modified,
                ))
                log.info("FtpSlave: delta sent (+%d ~%d -%d)",
                         len(added), len(modified), len(removed))

                # Notify S2S bridge about added/modified files for peer sync
                if self._s2s_bridge and (added or modified):
                    self._s2s_bridge.notify_files_changed(added + modified)

            last_snapshot = new_snapshot

    def _build_snapshot(self, root):
        """Build a {vpath: file_info} snapshot of serve_root.

        Locked files are excluded from the snapshot so they don't generate
        inventory deltas or trigger SYNCFILE broadcasts while being edited.
        """
        snapshot = {}
        if not root.exists():
            return snapshot

        for dirpath, _, filenames in os.walk(str(root)):
            for fname in filenames:
                full = Path(dirpath) / fname
                try:
                    st = full.stat()
                    rel = "/" + full.relative_to(root).as_posix()
                    if self.is_locked(rel):
                        continue
                    md5 = self._file_md5(full)
                    snapshot[rel] = {
                        "path": rel,
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                        "md5": md5,
                    }
                except OSError:
                    pass
        return snapshot

    # ------------------------------------------------------------------
    # File locking
    # ------------------------------------------------------------------

    def lock_file(self, vpath, lock_id, ttl=7200):
        """Lock a file to suppress sync during edits."""
        with self._lock_lock:
            self._locked_files[vpath] = {
                "lock_id": lock_id,
                "expires": time.time() + ttl,
            }
        log.info("FtpSlave: locked %s (lock_id=%s, ttl=%d)", vpath, lock_id, ttl)
        if self._announce_callback:
            try:
                self._announce_callback(f"LOCK {vpath} id={lock_id} ttl={ttl}s")
            except Exception:
                pass

    def unlock_file(self, vpath, lock_id):
        """Unlock a file, allowing sync to resume."""
        with self._lock_lock:
            entry = self._locked_files.get(vpath)
            if entry and entry["lock_id"] == lock_id:
                del self._locked_files[vpath]
                log.info("FtpSlave: unlocked %s (lock_id=%s)", vpath, lock_id)
                if self._announce_callback:
                    try:
                        self._announce_callback(f"UNLOCK {vpath} id={lock_id}")
                    except Exception:
                        pass
            else:
                log.warning("FtpSlave: unlock mismatch for %s (expected %s)",
                            vpath, lock_id)

    def is_locked(self, vpath):
        """Check if a file is currently locked (with TTL expiry cleanup)."""
        with self._lock_lock:
            entry = self._locked_files.get(vpath)
            if entry is None:
                return False
            if time.time() > entry["expires"]:
                del self._locked_files[vpath]
                log.info("FtpSlave: lock expired for %s", vpath)
                return False
            return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_slave_id(self):
        """Determine slave ID from Platform or hostname."""
        try:
            from csc_service.shared.platform import Platform
            p = Platform()
            sid = p.get_server_shortname()
            if sid:
                return sid
        except Exception:
            pass
        return socket.gethostname()

    def _get_disk_capacity(self):
        """Get total disk capacity of serve_root in bytes."""
        try:
            usage = shutil.disk_usage(self.config.serve_root)
            return usage.total
        except OSError:
            return 0

    def _get_disk_free(self):
        """Get free disk space of serve_root in bytes."""
        try:
            usage = shutil.disk_usage(self.config.serve_root)
            return usage.free
        except OSError:
            return 0

    def _get_load_avg(self):
        """Get system load average (1-minute)."""
        try:
            if platform_mod.system() != "Windows":
                return os.getloadavg()[0]
        except (OSError, AttributeError):
            pass
        return 0.0

    def _build_ssl_context(self):
        """Build SSL context for connecting to master (mTLS)."""
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if self.config.has_tls:
            ctx.load_cert_chain(self.config.s2s_cert, self.config.s2s_key)
            ctx.load_verify_locations(self.config.s2s_ca)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED if self.config.has_tls else ssl.CERT_NONE
        return ctx
