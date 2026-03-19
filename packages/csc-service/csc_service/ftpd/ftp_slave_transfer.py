"""Slave-side data transfer handler.

Opens data connections for RETR/STOR on master's command.
When master sends SEND_FILE, the slave reads the file from local disk
and streams it to the relay socket. For RECV_FILE, the slave receives
data from the relay and writes it to local disk.
"""

import logging
import os
import socket
import threading
from pathlib import Path

log = logging.getLogger(__name__)

TRANSFER_BUFSIZE = 65536


class FtpSlaveTransfer:
    """Slave-side: handles individual data transfers.

    Each transfer runs in its own thread. Connects to the master's
    relay socket and streams file data in/out.
    """

    def __init__(self, slave):
        """Initialize the transfer handler.

        Args:
            slave: Reference to the FtpSlave instance.
        """
        self.slave = slave
        self._active = {}  # transfer_id -> thread
        self._lock = threading.Lock()

    @property
    def active_count(self):
        """Number of currently active transfers."""
        with self._lock:
            return len(self._active)

    def handle_send_file(self, transfer_id, path, client_host, client_port):
        """Handle SEND_FILE: read local file, stream to relay.

        Args:
            transfer_id: Unique transfer identifier.
            path: Virtual path of the file to send.
            client_host: Master relay host to connect to.
            client_port: Master relay port to connect to.
        """
        t = threading.Thread(
            target=self._do_send,
            args=(transfer_id, path, client_host, client_port),
            daemon=True,
            name=f"ftpd-send-{transfer_id}",
        )
        with self._lock:
            self._active[transfer_id] = t
        t.start()

    def handle_recv_file(self, transfer_id, path, client_host, client_port):
        """Handle RECV_FILE: receive data from relay, write to local disk.

        Args:
            transfer_id: Unique transfer identifier.
            path: Virtual path where the file will be stored.
            client_host: Master relay host to connect to.
            client_port: Master relay port to connect to.
        """
        t = threading.Thread(
            target=self._do_recv,
            args=(transfer_id, path, client_host, client_port),
            daemon=True,
            name=f"ftpd-recv-{transfer_id}",
        )
        with self._lock:
            self._active[transfer_id] = t
        t.start()

    def _do_send(self, transfer_id, vpath, relay_host, relay_port):
        """Send a local file to the master relay socket."""
        local_path = self._vpath_to_local(vpath)
        total = 0
        success = False
        error = ""

        try:
            if not local_path.exists():
                raise FileNotFoundError(f"Local file not found: {local_path}")

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(30)
            sock.connect((relay_host, relay_port))

            with open(local_path, "rb") as f:
                while True:
                    chunk = f.read(TRANSFER_BUFSIZE)
                    if not chunk:
                        break
                    sock.sendall(chunk)
                    total += len(chunk)

            sock.close()
            success = True
            log.info("SEND %s complete: %d bytes (xfer %s)",
                     vpath, total, transfer_id)
        except Exception as e:
            error = str(e)
            log.error("SEND %s failed: %s (xfer %s)", vpath, e, transfer_id)
        finally:
            self._finish_transfer(transfer_id, total, success, error)

    def _do_recv(self, transfer_id, vpath, relay_host, relay_port):
        """Receive a file from the master relay socket and write to disk."""
        local_path = self._vpath_to_local(vpath)
        total = 0
        success = False
        error = ""

        try:
            # Ensure parent directory exists
            local_path.parent.mkdir(parents=True, exist_ok=True)

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(30)
            sock.connect((relay_host, relay_port))

            # Write to a temp file first, then rename (atomic)
            tmp_path = local_path.with_suffix(".ftpd.tmp")
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = sock.recv(TRANSFER_BUFSIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    total += len(chunk)
                f.flush()
                os.fsync(f.fileno())

            sock.close()

            # Atomic rename
            if os.name == "nt" and local_path.exists():
                local_path.unlink()
            tmp_path.rename(local_path)

            success = True
            log.info("RECV %s complete: %d bytes (xfer %s)",
                     vpath, total, transfer_id)
        except Exception as e:
            error = str(e)
            log.error("RECV %s failed: %s (xfer %s)", vpath, e, transfer_id)
            # Clean up temp file on failure
            tmp_path = local_path.with_suffix(".ftpd.tmp")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        finally:
            self._finish_transfer(transfer_id, total, success, error)

    def _finish_transfer(self, transfer_id, total, success, error):
        """Report transfer completion to master and clean up."""
        with self._lock:
            self._active.pop(transfer_id, None)

        # Report to master
        from .ftp_protocol import FtpProtocol
        self.slave.send_to_master(
            FtpProtocol.make_transfer_complete(transfer_id, total, success, error)
        )

        # If a file was received, trigger a delta update
        if success:
            self.slave.schedule_inventory_delta()

    def _vpath_to_local(self, vpath):
        """Convert a virtual path to a local filesystem path.

        Args:
            vpath: Virtual path (e.g., "/ops/wo/ready/task.md").

        Returns:
            Path: Local path under serve_root.
        """
        # Strip leading slash and normalize
        rel = vpath.lstrip("/").replace("/", os.sep)
        return Path(self.slave.config.serve_root) / rel

    def delete_file(self, vpath):
        """Delete a local file by virtual path."""
        local_path = self._vpath_to_local(vpath)
        if local_path.exists():
            try:
                local_path.unlink()
                log.info("Deleted local file: %s", local_path)
                self.slave.schedule_inventory_delta()
            except OSError as e:
                log.error("Failed to delete %s: %s", local_path, e)

    def rename_file(self, vpath, new_vpath):
        """Rename a local file by virtual path."""
        local_path = self._vpath_to_local(vpath)
        local_newpath = self._vpath_to_local(new_vpath)
        if not local_path.exists():
            log.warning("Rename source not found: %s", local_path)
            return
        try:
            local_newpath.parent.mkdir(parents=True, exist_ok=True)
            if os.name == "nt" and local_newpath.exists():
                local_newpath.unlink()
            local_path.rename(local_newpath)
            log.info("Renamed %s -> %s", local_path, local_newpath)
            self.slave.schedule_inventory_delta()
        except OSError as e:
            log.error("Failed to rename %s -> %s: %s", local_path, local_newpath, e)
