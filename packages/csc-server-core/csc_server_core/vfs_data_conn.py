"""VFS TCP data connection — single-use PRET-style transfer endpoint.

When a client requests a VFS transfer (encrypt/decrypt/list), the server
allocates one of these, binds a random TCP port, and returns the (ip, port)
to the client via NOTICE.  The client connects, the transfer happens, then
the connection closes.  One connection per operation, 30s timeout.
"""

from __future__ import annotations

import socket
import threading


def _detect_outbound_ip() -> str:
    """Best-effort detection of the server's outbound IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class VFSDataConn:
    """Single-use TCP listener for one VFS data transfer."""

    def __init__(self, bind_host: str = "0.0.0.0", timeout: int = 30):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((bind_host, 0))
        self._sock.listen(1)
        self._sock.settimeout(timeout)
        self.port: int = self._sock.getsockname()[1]
        self.ip: str = _detect_outbound_ip()
        self.timeout = timeout

    def serve_upload(self, on_data, on_error=None) -> None:
        """Accept one connection, receive all bytes, call on_data(bytes).
        Runs in a daemon thread — returns immediately."""
        sock = self._sock

        def _run():
            try:
                conn, _ = sock.accept()
                conn.settimeout(self.timeout)
                chunks = []
                try:
                    while True:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                finally:
                    conn.close()
                on_data(b"".join(chunks))
            except Exception as exc:
                if on_error:
                    on_error(str(exc))
            finally:
                try:
                    sock.close()
                except Exception:
                    import logging
                    logging.getLogger(__name__).debug('Ignored exception', exc_info=True)

        threading.Thread(target=_run, daemon=True).start()

    def serve_download(self, data_fn, on_done=None, on_error=None) -> None:
        """Accept one connection, send all bytes from data_fn() (or bytes).
        Runs in a daemon thread — returns immediately."""
        sock = self._sock

        def _run():
            try:
                conn, _ = sock.accept()
                conn.settimeout(self.timeout)
                try:
                    payload = data_fn() if callable(data_fn) else data_fn
                    conn.sendall(payload)
                finally:
                    conn.close()
                if on_done:
                    on_done()
            except Exception as exc:
                if on_error:
                    on_error(str(exc))
            finally:
                try:
                    sock.close()
                except Exception:
                    import logging
                    logging.getLogger(__name__).debug('Ignored exception', exc_info=True)

        threading.Thread(target=_run, daemon=True).start()
