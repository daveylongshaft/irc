"""TCP data server for S2S file transfers.

Opens TCP listeners for outbound file offers (SYNCFILE) and handles
both pull (receiver connects to us) and push (we connect out for RSYNCFILE).
"""

import logging
import os
import socket
import threading
from pathlib import Path

log = logging.getLogger(__name__)

TRANSFER_BUFSIZE = 65536
CONNECT_TIMEOUT = 10
ACCEPT_TIMEOUT = 60
DATA_PORT_BASE = 9541


class FtpDataServer:
    """TCP data channel for a single file transfer.

    Supports two modes:
      - serve(): open listener, wait for receiver to connect, send file
      - push(): connect OUT to a receiver's listener, send file
      - pull(): connect to a source's listener, receive file
      - accept_and_recv(): open listener, wait for source to connect, receive file
    """

    def __init__(self, serve_root, bind_host="0.0.0.0"):
        self.serve_root = Path(serve_root)
        self.bind_host = bind_host
        self._port_lock = threading.Lock()
        self._next_port = DATA_PORT_BASE

    def _alloc_port(self):
        """Allocate the next available data port."""
        with self._port_lock:
            port = self._next_port
            self._next_port += 1
            if self._next_port > 9560:
                self._next_port = DATA_PORT_BASE
            return port

    def vpath_to_local(self, vpath):
        """Convert virtual path to local filesystem path."""
        rel = vpath.lstrip("/").replace("/", os.sep)
        return self.serve_root / rel

    def serve_file(self, vpath, callback_port=None):
        """Open a TCP listener and wait for one connection to pull the file.

        Args:
            vpath: Virtual path of file to serve.
            callback_port: Specific port to bind, or None to auto-allocate.

        Returns:
            (port, thread) - the port being listened on and the server thread.
            Returns (None, None) if the file doesn't exist.
        """
        local_path = self.vpath_to_local(vpath)
        if not local_path.exists():
            log.error("serve_file: %s not found", local_path)
            return None, None

        port = callback_port or self._alloc_port()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Try a few ports if the first is busy
        bound = False
        for attempt in range(20):
            try:
                sock.bind((self.bind_host, port))
                bound = True
                break
            except OSError:
                port = self._alloc_port()

        if not bound:
            log.error("serve_file: no available port for %s", vpath)
            sock.close()
            return None, None

        sock.listen(1)
        sock.settimeout(ACCEPT_TIMEOUT)

        def _serve():
            try:
                conn, addr = sock.accept()
                log.info("serve_file: %s connected from %s", vpath, addr)
                conn.settimeout(60)
                total = 0
                with open(local_path, "rb") as f:
                    while True:
                        chunk = f.read(TRANSFER_BUFSIZE)
                        if not chunk:
                            break
                        conn.sendall(chunk)
                        total += len(chunk)
                conn.close()
                log.info("serve_file: sent %s (%d bytes)", vpath, total)
            except socket.timeout:
                log.warning("serve_file: no connection for %s (timeout)", vpath)
            except Exception as e:
                log.error("serve_file: error serving %s: %s", vpath, e)
            finally:
                sock.close()

        t = threading.Thread(target=_serve, daemon=True,
                             name=f"ftpd-serve-{port}")
        t.start()
        return port, t

    def pull_file(self, vpath, source_host, source_port):
        """Connect to a remote source and pull a file.

        Args:
            vpath: Virtual path to save the file to.
            source_host: Remote host to connect to.
            source_port: Remote port to connect to.

        Returns:
            (success, bytes_received)
        """
        local_path = self.vpath_to_local(vpath)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = local_path.with_suffix(".s2s.tmp")
        total = 0

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(CONNECT_TIMEOUT)
            sock.connect((source_host, int(source_port)))
            sock.settimeout(60)

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

            log.info("pull_file: received %s (%d bytes) from %s:%s",
                     vpath, total, source_host, source_port)
            return True, total

        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            log.warning("pull_file: connect failed %s:%s for %s: %s",
                        source_host, source_port, vpath, e)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return False, 0

        except Exception as e:
            log.error("pull_file: error receiving %s: %s", vpath, e)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return False, 0

    def push_file(self, vpath, target_host, target_port):
        """Connect OUT to a receiver's listener and push a file.

        Used for RSYNCFILE reverse fallback.

        Args:
            vpath: Virtual path of the file to send.
            target_host: Receiver's host.
            target_port: Receiver's listener port.

        Returns:
            (success, bytes_sent)
        """
        local_path = self.vpath_to_local(vpath)
        if not local_path.exists():
            log.error("push_file: %s not found", local_path)
            return False, 0

        total = 0
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(CONNECT_TIMEOUT)
            sock.connect((target_host, int(target_port)))
            sock.settimeout(60)

            with open(local_path, "rb") as f:
                while True:
                    chunk = f.read(TRANSFER_BUFSIZE)
                    if not chunk:
                        break
                    sock.sendall(chunk)
                    total += len(chunk)

            sock.close()
            log.info("push_file: sent %s (%d bytes) to %s:%s",
                     vpath, total, target_host, target_port)
            return True, total

        except Exception as e:
            log.error("push_file: error pushing %s to %s:%s: %s",
                      vpath, target_host, target_port, e)
            return False, 0

    def accept_and_recv(self, vpath, callback_port=None):
        """Open a TCP listener and wait for source to connect and push file.

        Used for RSYNCFILE reverse fallback (receiver side).

        Args:
            vpath: Virtual path to save file to.
            callback_port: Specific port, or None to auto-allocate.

        Returns:
            (port, thread) - port and the receiver thread.
        """
        local_path = self.vpath_to_local(vpath)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        port = callback_port or self._alloc_port()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        bound = False
        for attempt in range(20):
            try:
                sock.bind((self.bind_host, port))
                bound = True
                break
            except OSError:
                port = self._alloc_port()

        if not bound:
            log.error("accept_and_recv: no available port for %s", vpath)
            sock.close()
            return None, None

        sock.listen(1)
        sock.settimeout(ACCEPT_TIMEOUT)

        result = {"success": False, "total": 0}

        def _recv():
            tmp_path = local_path.with_suffix(".s2s.tmp")
            try:
                conn, addr = sock.accept()
                log.info("accept_and_recv: %s connected from %s", vpath, addr)
                conn.settimeout(60)
                total = 0
                with open(tmp_path, "wb") as f:
                    while True:
                        chunk = conn.recv(TRANSFER_BUFSIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        total += len(chunk)
                    f.flush()
                    os.fsync(f.fileno())

                conn.close()

                if os.name == "nt" and local_path.exists():
                    local_path.unlink()
                tmp_path.rename(local_path)

                result["success"] = True
                result["total"] = total
                log.info("accept_and_recv: received %s (%d bytes)", vpath, total)
            except socket.timeout:
                log.warning("accept_and_recv: no push for %s (timeout)", vpath)
            except Exception as e:
                log.error("accept_and_recv: error for %s: %s", vpath, e)
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
            finally:
                sock.close()

        t = threading.Thread(target=_recv, daemon=True,
                             name=f"ftpd-rrecv-{port}")
        t.start()
        return port, t
