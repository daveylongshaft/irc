"""Master-side representation of one connected slave.

Each FtpSlaveConnection wraps a TLS socket to a slave, handles incoming
protocol messages, and dispatches transfer commands.
"""

import logging
import select
import threading
import time

from .ftp_protocol import FtpProtocol

log = logging.getLogger(__name__)


class FtpSlaveConnection:
    """Master-side: represents one connected slave.

    Manages the TLS control socket, processes incoming messages (heartbeat,
    inventory, transfer results), and sends commands (SEND_FILE, RECV_FILE).
    """

    def __init__(self, sock, addr, slave_id, master):
        """Initialize a slave connection.

        Args:
            sock: ssl.SSLSocket for the control channel.
            addr: (host, port) tuple of the slave.
            slave_id: Slave's identifier (from REGISTER message).
            master: Reference to the FtpMaster instance.
        """
        self.sock = sock
        self.addr = addr
        self.slave_id = slave_id
        self.master = master

        self.serve_root = ""
        self.capacity_bytes = 0
        self.disk_free = 0
        self.active_transfers = 0
        self.load_avg = 0.0
        self.connected = True
        self.last_heartbeat = time.time()
        self.registered_at = time.time()

        self._lock = threading.Lock()
        self._reader_thread = None

    def start(self):
        """Start the background reader thread for this slave."""
        self._reader_thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
            name=f"ftpd-slave-{self.slave_id}",
        )
        self._reader_thread.start()

    def _read_loop(self):
        """Continuously read protocol messages from the slave."""
        while self.connected:
            try:
                # Use select with a 1-second timeout for clean shutdown
                ready, _, _ = select.select([self.sock], [], [], 1.0)
                if not ready:
                    # Check for heartbeat timeout (3x interval)
                    if time.time() - self.last_heartbeat > 90:
                        log.warning("Slave %s heartbeat timeout", self.slave_id)
                        self.disconnect()
                    continue

                msg = FtpProtocol.recv_line(self.sock)
                if msg is None:
                    log.info("Slave %s disconnected (EOF)", self.slave_id)
                    self.disconnect()
                    break

                self._handle_message(msg)
            except Exception as e:
                if self.connected:
                    log.error("Slave %s read error: %s", self.slave_id, e)
                    self.disconnect()
                break

    def _handle_message(self, msg):
        """Dispatch an incoming protocol message from the slave."""
        cmd = msg.get("cmd", "")
        self.last_heartbeat = time.time()

        if cmd == FtpProtocol.CMD_HEARTBEAT:
            self.disk_free = msg.get("disk_free", 0)
            self.active_transfers = msg.get("active_transfers", 0)
            self.load_avg = msg.get("load_avg", 0.0)

        elif cmd == FtpProtocol.CMD_INVENTORY:
            files = msg.get("files", [])
            self.master.index.update_from_inventory(self.slave_id, files)
            log.info("Slave %s inventory: %d files", self.slave_id, len(files))

        elif cmd == FtpProtocol.CMD_INVENTORY_DELTA:
            self.master.index.apply_delta(
                self.slave_id,
                added=msg.get("added"),
                removed=msg.get("removed"),
                modified=msg.get("modified"),
            )

        elif cmd == FtpProtocol.CMD_TRANSFER_COMPLETE:
            transfer_id = msg.get("transfer_id", "")
            success = msg.get("success", False)
            nbytes = msg.get("bytes", 0)
            error = msg.get("error", "")
            self.master.on_transfer_complete(
                transfer_id, self.slave_id, success, nbytes, error
            )

        else:
            log.warning("Slave %s: unknown command %r", self.slave_id, cmd)

    def send_command(self, data):
        """Send a pre-encoded command to this slave.

        Args:
            data: bytes from FtpProtocol.encode() or make_*().
        """
        with self._lock:
            if not self.connected:
                log.warning("Cannot send to disconnected slave %s", self.slave_id)
                return
            try:
                FtpProtocol.send_msg(self.sock, data)
            except Exception as e:
                log.error("Slave %s send error: %s", self.slave_id, e)
                self.disconnect()

    def request_inventory(self):
        """Ask this slave to send a full inventory rescan."""
        self.send_command(FtpProtocol.make_inventory_request())

    def send_file(self, transfer_id, path, client_host, client_port):
        """Instruct the slave to send (RETR) a file."""
        self.send_command(FtpProtocol.make_send_file(
            transfer_id, path, client_host, client_port
        ))

    def recv_file(self, transfer_id, path, client_host, client_port):
        """Instruct the slave to receive (STOR) a file."""
        self.send_command(FtpProtocol.make_recv_file(
            transfer_id, path, client_host, client_port
        ))

    def mirror_file(self, transfer_id, path, target_slave_id, target_host):
        """Instruct the slave to mirror a file to another slave."""
        self.send_command(FtpProtocol.make_mirror_file(
            transfer_id, path, target_slave_id, target_host
        ))

    def delete_file(self, path):
        """Instruct the slave to delete a file."""
        self.send_command(FtpProtocol.make_delete_file(path))

    def rename_file(self, path, new_path):
        """Instruct the slave to rename a file."""
        self.send_command(FtpProtocol.make_rename_file(path, new_path))

    def lock_file(self, path, lock_id, ttl):
        """Instruct the slave to lock a file."""
        self.send_command(FtpProtocol.make_lock_file(path, lock_id, ttl))

    def unlock_file(self, path, lock_id):
        """Instruct the slave to unlock a file."""
        self.send_command(FtpProtocol.make_unlock_file(path, lock_id))

    def disconnect(self):
        """Close the connection and clean up."""
        if not self.connected:
            return
        self.connected = False
        try:
            self.sock.close()
        except Exception:
            pass
        # Notify master to remove this slave
        self.master.on_slave_disconnect(self.slave_id)
        log.info("Slave %s disconnected", self.slave_id)

    @property
    def uptime(self):
        return time.time() - self.registered_at

    def __repr__(self):
        return (
            f"FtpSlaveConnection(slave_id={self.slave_id!r}, "
            f"addr={self.addr}, connected={self.connected})"
        )
