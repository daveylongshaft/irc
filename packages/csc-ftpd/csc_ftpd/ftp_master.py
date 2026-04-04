"""Master FTP daemon.

Runs two listeners:
1. TLS listener on port 9527 for slave control connections.
2. pyftpdlib FTP server on port 9521 for FTP clients.

Maintains a registry of connected slaves, dispatches transfers,
and provides the merged virtual namespace.
"""

import logging
import os
import socket
import ssl
import threading
import time

from .ftp_config import FtpConfig
from .ftp_master_index import FtpMasterIndex
from .ftp_protocol import FtpProtocol
from .ftp_slave_connection import FtpSlaveConnection

log = logging.getLogger(__name__)


class FtpMaster:
    """Master daemon: TLS listener for slaves + pyftpdlib FTP server.

    Attributes:
        config: FtpConfig instance.
        index: FtpMasterIndex instance (virtual file index).
        slaves: dict mapping slave_id -> FtpSlaveConnection.
    """

    def __init__(self, config):
        """Initialize the master.

        Args:
            config: FtpConfig instance (must have role='master').
        """
        self.config = config
        self.index = FtpMasterIndex(config.index_path)
        self.slaves = {}
        self._slaves_lock = threading.Lock()
        self._transfers = {}  # transfer_id -> {slave_id, status, ...}
        self._transfers_lock = threading.Lock()
        self._shutdown = threading.Event()
        self._slave_listener = None
        self._ftp_server = None

    def start(self):
        """Start both the slave listener and FTP server in daemon threads."""
        log.info("FtpMaster starting (slave port=%d, ftp port=%d)",
                 self.config.master_control_port, self.config.ftp_control_port)

        # Ensure serve_root exists (for local temp files if needed)
        os.makedirs(self.config.serve_root, exist_ok=True)

        # Start slave TLS listener
        t1 = threading.Thread(
            target=self._run_slave_listener,
            daemon=True,
            name="ftpd-master-slaves",
        )
        t1.start()

        # Start pyftpdlib FTP server
        t2 = threading.Thread(
            target=self._run_ftp_server,
            daemon=True,
            name="ftpd-master-ftp",
        )
        t2.start()

        log.info("FtpMaster started")

    def stop(self):
        """Signal shutdown."""
        self._shutdown.set()
        if self._ftp_server:
            self._ftp_server.close_all()
        if self._slave_listener:
            try:
                self._slave_listener.close()
            except Exception:
                if hasattr(self, 'log'):
                    self.log('Ignored exception', level='DEBUG')
        # Disconnect all slaves
        with self._slaves_lock:
            for conn in list(self.slaves.values()):
                conn.disconnect()
            self.slaves.clear()

    def get_slave(self, slave_id):
        """Get a slave connection by ID."""
        with self._slaves_lock:
            return self.slaves.get(slave_id)

    def pick_slave_for_upload(self):
        """Pick the best slave for an upload (most free disk space).

        Returns:
            str or None: slave_id, or None if no slaves connected.
        """
        with self._slaves_lock:
            connected = [
                (sid, conn) for sid, conn in self.slaves.items()
                if conn.connected
            ]
        if not connected:
            return None
        # Pick slave with most free disk space
        return max(connected, key=lambda x: x[1].disk_free)[0]

    def on_slave_disconnect(self, slave_id):
        """Called when a slave disconnects."""
        with self._slaves_lock:
            self.slaves.pop(slave_id, None)
        # Don't remove index entries immediately -- files are still there,
        # slave just lost connectivity. Remove after a configurable timeout.
        log.info("FtpMaster: slave %s disconnected (%d remaining)",
                 slave_id, len(self.slaves))

    def on_transfer_complete(self, transfer_id, slave_id, success, nbytes, error):
        """Called when a slave reports transfer completion."""
        with self._transfers_lock:
            info = self._transfers.pop(transfer_id, None)
        if success:
            log.info("Transfer %s complete: %d bytes from %s",
                     transfer_id, nbytes, slave_id)
        else:
            log.warning("Transfer %s failed on %s: %s",
                        transfer_id, slave_id, error)

    # ------------------------------------------------------------------
    # Slave TLS Listener
    # ------------------------------------------------------------------

    def _run_slave_listener(self):
        """Accept TLS connections from slaves on the control port."""
        ctx = self._build_ssl_context()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.config.master_control_port))
        sock.listen(16)
        sock.settimeout(1.0)
        self._slave_listener = sock

        log.info("FtpMaster: slave listener on port %d", self.config.master_control_port)

        while not self._shutdown.is_set():
            try:
                raw_conn, addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._shutdown.is_set():
                    break
                raise

            log.info("FtpMaster: incoming slave connection from %s:%d", *addr)
            threading.Thread(
                target=self._handle_slave_connect,
                args=(raw_conn, addr, ctx),
                daemon=True,
                name=f"ftpd-slave-accept-{addr[0]}",
            ).start()

    def _handle_slave_connect(self, raw_conn, addr, ctx):
        """Handle a new slave connection: TLS handshake + REGISTER."""
        try:
            tls_conn = ctx.wrap_socket(raw_conn, server_side=True)
        except ssl.SSLError as e:
            log.warning("FtpMaster: TLS handshake failed from %s: %s", addr, e)
            raw_conn.close()
            return

        # Read REGISTER message
        msg = FtpProtocol.recv_line(tls_conn)
        if msg is None or msg.get("cmd") != FtpProtocol.CMD_REGISTER:
            log.warning("FtpMaster: expected REGISTER from %s, got %s", addr, msg)
            tls_conn.close()
            return

        slave_id = msg.get("slave_id", "")
        if not slave_id:
            log.warning("FtpMaster: REGISTER without slave_id from %s", addr)
            FtpProtocol.send_msg(tls_conn, FtpProtocol.make_register_ack(
                False, "", reason="Missing slave_id"
            ))
            tls_conn.close()
            return

        # Send ACK
        master_id = socket.gethostname()
        FtpProtocol.send_msg(tls_conn, FtpProtocol.make_register_ack(
            True, master_id
        ))

        # Create slave connection object
        conn = FtpSlaveConnection(tls_conn, addr, slave_id, self)
        conn.serve_root = msg.get("serve_root", "")
        conn.capacity_bytes = msg.get("capacity_bytes", 0)

        with self._slaves_lock:
            # Close old connection if slave is reconnecting
            old = self.slaves.pop(slave_id, None)
            if old:
                old.disconnect()
            self.slaves[slave_id] = conn

        conn.start()
        log.info("FtpMaster: slave %s registered (serve_root=%s, capacity=%d)",
                 slave_id, conn.serve_root, conn.capacity_bytes)

    # ------------------------------------------------------------------
    # pyftpdlib FTP Server
    # ------------------------------------------------------------------

    def _run_ftp_server(self):
        """Run the pyftpdlib FTP server for clients."""
        from pyftpdlib.servers import FTPServer

        from .ftp_authorizer import FtpAuthorizer
        from .ftp_handler import FtpHandler

        authorizer = FtpAuthorizer(
            self.config.users_path,
            default_home="/",
        )

        handler = FtpHandler
        handler.authorizer = authorizer

        # TLS config for FTP client connections
        if self.config.has_tls:
            ftp_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ftp_ctx.load_cert_chain(self.config.s2s_cert, self.config.s2s_key)
            handler.ssl_context = ftp_ctx
        else:
            handler.ssl_context = None

        # Passive port range
        low, high = self.config.passive_range
        handler.passive_ports = range(low, high + 1)

        # Banner
        handler.banner = "CSC-FTPD Master ready."

        server = FTPServer(
            ("0.0.0.0", self.config.ftp_control_port),
            handler,
        )

        # Attach our references so FtpHandler and FtpVirtualFs can access them
        server._ftpd_master = self
        server._ftpd_index = self.index
        server._ftpd_config = self.config

        self._ftp_server = server

        log.info("FtpMaster: FTP server on port %d", self.config.ftp_control_port)
        server.serve_forever()

    # ------------------------------------------------------------------
    # SSL Context
    # ------------------------------------------------------------------

    def _build_ssl_context(self):
        """Build SSL context for slave listener (mTLS)."""
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        if self.config.has_tls:
            ctx.load_cert_chain(self.config.s2s_cert, self.config.s2s_key)
            ctx.load_verify_locations(self.config.s2s_ca)
            ctx.verify_mode = ssl.CERT_REQUIRED
        else:
            log.warning("FtpMaster: running without TLS (insecure)")
            ctx.verify_mode = ssl.CERT_NONE
        ctx.check_hostname = False
        return ctx
