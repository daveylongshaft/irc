"""pyftpdlib FTPHandler subclass for the master.

Overrides RETR/STOR/LIST/DELE to route through slaves via the master index.
Data transfers use master relay: master opens passive sockets and bridges
bytes between FTP client and slave using select().

Note: pyftpdlib 2.x removed TLS_FTPHandler as a separate class. TLS for
FTP client connections is configured via ssl_context on FTPHandler. TLS for
slave control connections uses raw ssl module (handled in ftp_master.py).
"""

import logging
import select
import socket
import ssl
import threading
import time
import uuid

from pyftpdlib.handlers import FTPHandler

from .ftp_protocol import FtpProtocol
from .ftp_virtual_fs import FtpVirtualFs

log = logging.getLogger(__name__)

# Buffer size for relay byte pump
RELAY_BUFSIZE = 65536


class FtpHandler(FTPHandler):
    """FTP handler with slave-routed transfers.

    Overrides key FTP commands to work with the virtual filesystem
    and slave transfer dispatch. TLS is configured via ssl_context
    class attribute (set by FtpMaster before starting).
    """

    # Use our virtual FS instead of real filesystem
    abstracted_fs = FtpVirtualFs

    # TLS context (set by FtpMaster if TLS is configured)
    ssl_context = None

    def ftp_RETR(self, file):
        """Handle RETR: download a file from a slave.

        Instead of reading from local disk, we:
        1. Look up which slave has the file
        2. Open a relay socket pair
        3. Tell the slave to SEND_FILE to our relay
        4. Bridge bytes from slave -> FTP client
        """
        vpath = self._resolve_vpath(file)
        index = self.server._ftpd_index
        master = self.server._ftpd_master

        slave_id = index.pick_slave(vpath)
        if slave_id is None:
            self.respond("550 File not found.")
            return

        slave_conn = master.get_slave(slave_id)
        if slave_conn is None or not slave_conn.connected:
            self.respond("421 Slave holding file is offline.")
            return

        transfer_id = str(uuid.uuid4())[:8]
        log.info("RETR %s -> slave %s (xfer %s)", vpath, slave_id, transfer_id)

        # Set up the relay
        relay_sock = self._create_relay_listener()
        if relay_sock is None:
            self.respond("425 Can't open relay connection.")
            return

        relay_host, relay_port = relay_sock.getsockname()

        # Tell slave to connect to our relay and send the file
        slave_conn.send_file(transfer_id, vpath, relay_host, relay_port)

        # Start relay in a thread: slave -> FTP client data channel
        def _relay_retr():
            try:
                relay_sock.settimeout(30)
                slave_data, _ = relay_sock.accept()
                slave_data.settimeout(60)

                # Open DTP (data transfer process) to FTP client
                if not self._open_data_channel():
                    slave_data.close()
                    return

                # Pump bytes: slave -> FTP client
                total = 0
                while True:
                    ready, _, _ = select.select([slave_data], [], [], 30)
                    if not ready:
                        break
                    chunk = slave_data.recv(RELAY_BUFSIZE)
                    if not chunk:
                        break
                    self.data_channel.sendall(chunk)
                    total += len(chunk)

                slave_data.close()
                self._close_data_channel()
                self.respond("226 Transfer complete (%d bytes)." % total)
                log.info("RETR %s complete: %d bytes", vpath, total)
            except Exception as e:
                log.error("RETR relay error: %s", e)
                self.respond("426 Transfer aborted.")
            finally:
                relay_sock.close()

        threading.Thread(target=_relay_retr, daemon=True,
                         name=f"ftpd-retr-{transfer_id}").start()

    def ftp_STOR(self, file, mode='w'):
        """Handle STOR: upload a file to a slave.

        We:
        1. Pick a slave with the most free space
        2. Open a relay socket pair
        3. Tell the slave to RECV_FILE from our relay
        4. Bridge bytes from FTP client -> slave
        """
        vpath = self._resolve_vpath(file)
        master = self.server._ftpd_master

        slave_id = master.pick_slave_for_upload()
        if slave_id is None:
            self.respond("421 No slaves available for upload.")
            return

        slave_conn = master.get_slave(slave_id)
        if slave_conn is None or not slave_conn.connected:
            self.respond("421 Target slave is offline.")
            return

        transfer_id = str(uuid.uuid4())[:8]
        log.info("STOR %s -> slave %s (xfer %s)", vpath, slave_id, transfer_id)

        relay_sock = self._create_relay_listener()
        if relay_sock is None:
            self.respond("425 Can't open relay connection.")
            return

        relay_host, relay_port = relay_sock.getsockname()

        # Tell slave to connect to our relay and receive the file
        slave_conn.recv_file(transfer_id, vpath, relay_host, relay_port)

        def _relay_stor():
            try:
                relay_sock.settimeout(30)
                slave_data, _ = relay_sock.accept()
                slave_data.settimeout(60)

                if not self._open_data_channel():
                    slave_data.close()
                    return

                # Pump bytes: FTP client -> slave
                total = 0
                while True:
                    ready, _, _ = select.select([self.data_channel], [], [], 30)
                    if not ready:
                        break
                    chunk = self.data_channel.recv(RELAY_BUFSIZE)
                    if not chunk:
                        break
                    slave_data.sendall(chunk)
                    total += len(chunk)

                slave_data.close()
                self._close_data_channel()
                self.respond("226 Transfer complete (%d bytes)." % total)
                log.info("STOR %s complete: %d bytes", vpath, total)
            except Exception as e:
                log.error("STOR relay error: %s", e)
                self.respond("426 Transfer aborted.")
            finally:
                relay_sock.close()

        threading.Thread(target=_relay_stor, daemon=True,
                         name=f"ftpd-stor-{transfer_id}").start()

    def ftp_DELE(self, path):
        """Handle DELE: delete a file from all slaves that hold it."""
        vpath = self._resolve_vpath(path)
        index = self.server._ftpd_index
        master = self.server._ftpd_master

        slaves = index.lookup(vpath)
        if not slaves:
            self.respond("550 File not found.")
            return

        for sid in slaves:
            conn = master.get_slave(sid)
            if conn and conn.connected:
                conn.delete_file(vpath)

        # Remove from index immediately (slaves will confirm via delta)
        for sid in slaves:
            index.apply_delta(sid, removed=[vpath])

        self.respond("250 File deleted.")
        log.info("DELE %s from %d slaves", vpath, len(slaves))

    def ftp_RNFR(self, path):
        """Handle RNFR: rename-from (first half of two-step rename)."""
        vpath = self._resolve_vpath(path)
        index = self.server._ftpd_index

        slaves = index.lookup(vpath)
        if not slaves:
            self.respond("550 File not found.")
            return

        self._rnfr_source = vpath
        self.respond("350 Ready for RNTO.")

    def ftp_RNTO(self, path):
        """Handle RNTO: rename-to (second half of two-step rename)."""
        if not hasattr(self, '_rnfr_source') or self._rnfr_source is None:
            self.respond("503 RNFR required first.")
            return

        src_vpath = self._rnfr_source
        self._rnfr_source = None

        dst_vpath = self._resolve_vpath(path)
        index = self.server._ftpd_index
        master = self.server._ftpd_master

        slaves = index.lookup(src_vpath)
        if not slaves:
            self.respond("550 Source file not found.")
            return

        for sid in slaves:
            conn = master.get_slave(sid)
            if conn and conn.connected:
                conn.rename_file(src_vpath, dst_vpath)

        index.rename_entry(src_vpath, dst_vpath)

        self.respond("250 Rename successful.")
        log.info("RNFR/RNTO %s -> %s on %d slaves", src_vpath, dst_vpath, len(slaves))

        # Announce to IRC #ftp feed
        cb = getattr(self.server, '_ftpd_announce_callback', None)
        if cb:
            try:
                cb(f"FTP RNFR/RNTO {src_vpath} -> {dst_vpath}")
            except Exception:
                pass

    def ftp_SIZE(self, path):
        """Handle SIZE: return file size from index."""
        vpath = self._resolve_vpath(path)
        slaves = self.server._ftpd_index.lookup(vpath)
        if not slaves:
            self.respond("550 File not found.")
            return
        best = max(slaves.values(), key=lambda s: s.get("mtime", 0))
        self.respond("213 %d" % best.get("size", 0))

    def ftp_MDTM(self, path):
        """Handle MDTM: return file modification time from index."""
        vpath = self._resolve_vpath(path)
        slaves = self.server._ftpd_index.lookup(vpath)
        if not slaves:
            self.respond("550 File not found.")
            return
        best = max(slaves.values(), key=lambda s: s.get("mtime", 0))
        mtime = best.get("mtime", 0)
        ts = time.strftime("%Y%m%d%H%M%S", time.gmtime(mtime))
        self.respond("213 %s" % ts)

    def _resolve_vpath(self, ftppath):
        """Resolve an FTP path to a virtual path."""
        fs = self.fs  # FtpVirtualFs instance
        return fs.ftp2fs(ftppath)

    def _create_relay_listener(self):
        """Create a TCP listener socket for relay on the passive port range."""
        low, high = self.server._ftpd_config.passive_range
        for port in range(low, high + 1):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", port))
                sock.listen(1)
                return sock
            except OSError:
                continue
        log.error("No available relay port in range %d-%d", low, high)
        return None

    def _open_data_channel(self):
        """Open the pyftpdlib data channel to the FTP client.

        Returns True if successful, False otherwise.
        """
        if self.data_channel is not None:
            return True
        return False

    def _close_data_channel(self):
        """Close the pyftpdlib data channel."""
        if self.data_channel is not None:
            try:
                self.data_channel.close()
            except Exception:
                pass
            self.data_channel = None
