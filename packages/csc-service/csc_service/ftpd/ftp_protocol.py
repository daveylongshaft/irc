"""Master-slave JSON-over-TLS wire protocol.

All messages are newline-delimited JSON objects with a "cmd" field.
Serialization/deserialization helpers and command constants live here.
"""

import json
import logging
import time

log = logging.getLogger(__name__)


class FtpProtocol:
    """Wire protocol constants and serialization for master-slave comms.

    Protocol: Each message is a single JSON object terminated by newline (\\n).
    Messages are sent over a TLS socket (ssl.SSLSocket).

    Slave -> Master commands:
        REGISTER, INVENTORY, INVENTORY_DELTA, HEARTBEAT, TRANSFER_COMPLETE

    Master -> Slave commands:
        REGISTER_ACK, SEND_FILE, RECV_FILE, MIRROR_FILE, DELETE_FILE,
        INVENTORY_REQUEST
    """

    # -- Slave -> Master --
    CMD_REGISTER = "REGISTER"
    CMD_INVENTORY = "INVENTORY"
    CMD_INVENTORY_DELTA = "INVENTORY_DELTA"
    CMD_HEARTBEAT = "HEARTBEAT"
    CMD_TRANSFER_COMPLETE = "TRANSFER_COMPLETE"

    # -- Master -> Slave --
    CMD_REGISTER_ACK = "REGISTER_ACK"
    CMD_SEND_FILE = "SEND_FILE"
    CMD_RECV_FILE = "RECV_FILE"
    CMD_MIRROR_FILE = "MIRROR_FILE"
    CMD_DELETE_FILE = "DELETE_FILE"
    CMD_RENAME_FILE = "RENAME_FILE"
    CMD_LOCK_FILE = "LOCK_FILE"
    CMD_UNLOCK_FILE = "UNLOCK_FILE"
    CMD_INVENTORY_REQUEST = "INVENTORY_REQUEST"

    @staticmethod
    def encode(cmd, **kwargs):
        """Encode a protocol message as newline-terminated bytes.

        Args:
            cmd: Command string (one of the CMD_* constants).
            **kwargs: Payload fields.

        Returns:
            bytes: JSON + newline, UTF-8 encoded.
        """
        msg = {"cmd": cmd, "ts": time.time()}
        msg.update(kwargs)
        return (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")

    @staticmethod
    def decode(data):
        """Decode a single protocol message from bytes or str.

        Args:
            data: bytes or str containing one JSON message (with or without newline).

        Returns:
            dict: Parsed message with at least a "cmd" key.

        Raises:
            ValueError: If data is not valid protocol JSON.
        """
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        data = data.strip()
        if not data:
            raise ValueError("Empty message")
        try:
            msg = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e
        if "cmd" not in msg:
            raise ValueError("Missing 'cmd' field")
        return msg

    @staticmethod
    def make_register(slave_id, serve_root, capacity_bytes):
        """Build a REGISTER message."""
        return FtpProtocol.encode(
            FtpProtocol.CMD_REGISTER,
            slave_id=slave_id,
            serve_root=serve_root,
            capacity_bytes=capacity_bytes,
        )

    @staticmethod
    def make_register_ack(accepted, master_id, reason=""):
        """Build a REGISTER_ACK message."""
        return FtpProtocol.encode(
            FtpProtocol.CMD_REGISTER_ACK,
            accepted=accepted,
            master_id=master_id,
            reason=reason,
        )

    @staticmethod
    def make_inventory(files):
        """Build an INVENTORY message.

        Args:
            files: List of dicts with keys: path, size, mtime, md5.
        """
        return FtpProtocol.encode(
            FtpProtocol.CMD_INVENTORY,
            files=files,
        )

    @staticmethod
    def make_inventory_delta(added=None, removed=None, modified=None):
        """Build an INVENTORY_DELTA message."""
        return FtpProtocol.encode(
            FtpProtocol.CMD_INVENTORY_DELTA,
            added=added or [],
            removed=removed or [],
            modified=modified or [],
        )

    @staticmethod
    def make_heartbeat(disk_free, active_transfers, load_avg):
        """Build a HEARTBEAT message."""
        return FtpProtocol.encode(
            FtpProtocol.CMD_HEARTBEAT,
            disk_free=disk_free,
            active_transfers=active_transfers,
            load_avg=load_avg,
        )

    @staticmethod
    def make_transfer_complete(transfer_id, bytes_transferred, success, error=""):
        """Build a TRANSFER_COMPLETE message."""
        return FtpProtocol.encode(
            FtpProtocol.CMD_TRANSFER_COMPLETE,
            transfer_id=transfer_id,
            bytes=bytes_transferred,
            success=success,
            error=error,
        )

    @staticmethod
    def make_send_file(transfer_id, path, client_host, client_port):
        """Build a SEND_FILE command (master -> slave, for RETR)."""
        return FtpProtocol.encode(
            FtpProtocol.CMD_SEND_FILE,
            transfer_id=transfer_id,
            path=path,
            client_host=client_host,
            client_port=client_port,
        )

    @staticmethod
    def make_recv_file(transfer_id, path, client_host, client_port):
        """Build a RECV_FILE command (master -> slave, for STOR)."""
        return FtpProtocol.encode(
            FtpProtocol.CMD_RECV_FILE,
            transfer_id=transfer_id,
            path=path,
            client_host=client_host,
            client_port=client_port,
        )

    @staticmethod
    def make_mirror_file(transfer_id, path, target_slave_id, target_host):
        """Build a MIRROR_FILE command (master -> slave, for FXP)."""
        return FtpProtocol.encode(
            FtpProtocol.CMD_MIRROR_FILE,
            transfer_id=transfer_id,
            path=path,
            target_slave_id=target_slave_id,
            target_host=target_host,
        )

    @staticmethod
    def make_delete_file(path):
        """Build a DELETE_FILE command."""
        return FtpProtocol.encode(
            FtpProtocol.CMD_DELETE_FILE,
            path=path,
        )

    @staticmethod
    def make_rename_file(path, new_path):
        """Build a RENAME_FILE command."""
        return FtpProtocol.encode(
            FtpProtocol.CMD_RENAME_FILE,
            path=path,
            new_path=new_path,
        )

    @staticmethod
    def make_lock_file(path, lock_id, ttl):
        """Build a LOCK_FILE command."""
        return FtpProtocol.encode(
            FtpProtocol.CMD_LOCK_FILE,
            path=path,
            lock_id=lock_id,
            ttl=ttl,
        )

    @staticmethod
    def make_unlock_file(path, lock_id):
        """Build an UNLOCK_FILE command."""
        return FtpProtocol.encode(
            FtpProtocol.CMD_UNLOCK_FILE,
            path=path,
            lock_id=lock_id,
        )

    @staticmethod
    def make_inventory_request():
        """Build an INVENTORY_REQUEST command."""
        return FtpProtocol.encode(FtpProtocol.CMD_INVENTORY_REQUEST)

    @staticmethod
    def recv_line(sock):
        """Read one newline-terminated message from a socket.

        Reads byte-by-byte until newline. Returns decoded dict.
        Returns None on connection close.

        Args:
            sock: ssl.SSLSocket or socket.socket.

        Returns:
            dict or None: Parsed message, or None on EOF.
        """
        buf = bytearray()
        while True:
            try:
                chunk = sock.recv(1)
            except (OSError, ConnectionError):
                return None
            if not chunk:
                return None
            if chunk == b"\n":
                break
            buf.extend(chunk)
        if not buf:
            return None
        try:
            return FtpProtocol.decode(buf)
        except ValueError as e:
            log.warning("Protocol decode error: %s", e)
            return None

    @staticmethod
    def send_msg(sock, data):
        """Send pre-encoded message bytes over a socket.

        Args:
            sock: ssl.SSLSocket or socket.socket.
            data: bytes from encode() or make_*().
        """
        sock.sendall(data)
