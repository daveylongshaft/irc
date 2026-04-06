"""Transparent FTP control-channel proxy for slave nodes.

When a client connects to the slave's FTP port (9521), this proxy opens
a connection to the master (10.10.10.1:9521) and bridges the control
channel bidirectionally.

PASV responses from the master are intercepted:
  Master sends:  227 Entering Passive Mode (10,10,10,1,p1,p2)
  Proxy rewrites: 227 Entering Passive Mode (SLAVE_IP,p1,p2)
  Proxy opens a local listener on the rewritten port.
  When the client connects to that port, proxy bridges it to master's
  actual PASV port.

PORT (active mode) commands from the client are similarly intercepted:
  Client sends:  PORT SLAVE_IP,p1,p2
  Proxy rewrites: PORT MASTER_IP,p1,p2 (master connects back to proxy)
  Proxy opens a local listener to bridge active data from master back
  to the client.

The existing FtpSlave (port 9527 TLS sync) is untouched by this module.
"""

import logging
import re
import select
import socket
import threading

log = logging.getLogger(__name__)

# How long (seconds) to wait for a data connection to arrive
_DATA_TIMEOUT = 30
# Buffer size for relay
_BUF = 65536


def _ip_to_ftp(ip_str):
    """Convert '10.10.10.3' to '10,10,10,3'."""
    return ip_str.replace(".", ",")


def _ftp_to_ip_port(ftp_addr):
    """Parse FTP PASV address '10,10,10,1,195,149' -> ('10.10.10.1', 50069)."""
    parts = [int(x) for x in ftp_addr.split(",")]
    ip = ".".join(str(p) for p in parts[:4])
    port = parts[4] * 256 + parts[5]
    return ip, port


def _port_to_ftp(port):
    """Convert port int to FTP p1,p2 notation."""
    return f"{port >> 8},{port & 0xff}"


def _relay(src, dst, label="relay"):
    """Relay bytes from src to dst until EOF or error."""
    try:
        while True:
            r, _, _ = select.select([src], [], [], 5)
            if not r:
                continue
            data = src.recv(_BUF)
            if not data:
                break
            dst.sendall(data)
    except Exception as e:
        log.debug("%s: relay ended: %s", label, e)
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except Exception:
            pass


def _bridge_data(client_sock, master_host, master_pasv_port):
    """Bridge a PASV data connection: client_sock <-> master_host:master_pasv_port."""
    try:
        master_data = socket.create_connection((master_host, master_pasv_port), timeout=_DATA_TIMEOUT)
        t1 = threading.Thread(
            target=_relay,
            args=(client_sock, master_data, "client->master-data"),
            daemon=True,
        )
        t2 = threading.Thread(
            target=_relay,
            args=(master_data, client_sock, "master->client-data"),
            daemon=True,
        )
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except Exception as e:
        log.warning("Data bridge error: %s", e)
    finally:
        for s in (client_sock,):
            try:
                s.close()
            except Exception:
                pass


class FtpControlProxy:
    """Proxy one client's FTP control session to the master.

    Intercepts PASV responses to redirect data connections through
    the slave.
    """

    # 227 Entering Passive Mode (h1,h2,h3,h4,p1,p2)
    _PASV_RE = re.compile(
        rb"227[^(]*\((\d+,\d+,\d+,\d+,\d+,\d+)\)",
        re.IGNORECASE,
    )
    # PORT h1,h2,h3,h4,p1,p2
    _PORT_RE = re.compile(
        rb"PORT\s+(\d+,\d+,\d+,\d+,\d+,\d+)",
        re.IGNORECASE,
    )

    def __init__(self, client_sock, client_addr, master_host, master_port, slave_ip):
        self._client = client_sock
        self._client_addr = client_addr
        self._master_host = master_host
        self._master_port = master_port
        self._slave_ip = slave_ip  # IP presented to FTP clients for PASV

    def run(self):
        """Run the proxy until the session ends."""
        try:
            master = socket.create_connection(
                (self._master_host, self._master_port), timeout=15
            )
        except Exception as e:
            log.warning("FtpControlProxy: cannot connect to master %s:%d: %s",
                        self._master_host, self._master_port, e)
            try:
                self._client.sendall(b"421 Service unavailable, master unreachable.\r\n")
            except Exception:
                pass
            self._client.close()
            return

        log.debug("FtpControlProxy: client %s -> master %s:%d",
                  self._client_addr, self._master_host, self._master_port)

        # master->client thread (intercepts PASV)
        t = threading.Thread(
            target=self._relay_master_to_client,
            args=(master,),
            daemon=True,
        )
        t.start()

        # client->master (intercepts PORT)
        self._relay_client_to_master(master)
        t.join(timeout=2)

        for s in (self._client, master):
            try:
                s.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # client -> master
    # ------------------------------------------------------------------

    def _relay_client_to_master(self, master):
        buf = b""
        try:
            while True:
                r, _, _ = select.select([self._client], [], [], 5)
                if not r:
                    continue
                data = self._client.recv(_BUF)
                if not data:
                    break
                buf += data
                # Process complete lines
                while b"\r\n" in buf or b"\n" in buf:
                    sep = b"\r\n" if b"\r\n" in buf else b"\n"
                    idx = buf.index(sep)
                    line = buf[: idx + len(sep)]
                    buf = buf[idx + len(sep):]
                    line = self._rewrite_client_line(line, master)
                    master.sendall(line)
                # Pass any remaining partial data through
                if buf and not (b"\r\n" in buf or b"\n" in buf):
                    # Flush non-command data (could be ABOR etc)
                    pass
        except Exception as e:
            log.debug("FtpControlProxy client->master ended: %s", e)

    def _rewrite_client_line(self, line, master):
        """Intercept PORT commands so the master connects back to us."""
        m = self._PORT_RE.match(line.strip())
        if not m:
            return line

        # Client wants active mode to its own IP/port — we intercept
        client_addr_str = m.group(1).decode()
        _client_ip, client_port = _ftp_to_ip_port(client_addr_str)

        # Open a local listener; master will connect here
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("", 0))
        listener.listen(1)
        listen_port = listener.getsockname()[1]

        def _active_bridge():
            try:
                listener.settimeout(_DATA_TIMEOUT)
                master_data, _ = listener.accept()
                listener.close()
                # Forward to client
                client_data = socket.create_connection(
                    (_ftp_to_ip_port(client_addr_str)[0], client_port),
                    timeout=_DATA_TIMEOUT,
                )
                t1 = threading.Thread(
                    target=_relay, args=(master_data, client_data, "active-m->c"), daemon=True)
                t2 = threading.Thread(
                    target=_relay, args=(client_data, master_data, "active-c->m"), daemon=True)
                t1.start(); t2.start()
                t1.join(); t2.join()
            except Exception as e:
                log.debug("Active bridge ended: %s", e)
            finally:
                try:
                    listener.close()
                except Exception:
                    pass

        threading.Thread(target=_active_bridge, daemon=True).start()

        slave_ip_ftp = _ip_to_ftp(self._slave_ip)
        rewritten = f"PORT {slave_ip_ftp},{_port_to_ftp(listen_port)}\r\n".encode()
        log.debug("FtpProxy: PORT rewrite -> port %d", listen_port)
        return rewritten

    # ------------------------------------------------------------------
    # master -> client
    # ------------------------------------------------------------------

    def _relay_master_to_client(self, master):
        buf = b""
        try:
            while True:
                r, _, _ = select.select([master], [], [], 5)
                if not r:
                    continue
                data = master.recv(_BUF)
                if not data:
                    break
                buf += data
                # Scan for complete lines
                while b"\r\n" in buf or b"\n" in buf:
                    sep = b"\r\n" if b"\r\n" in buf else b"\n"
                    idx = buf.index(sep)
                    line = buf[: idx + len(sep)]
                    buf = buf[idx + len(sep):]
                    line = self._rewrite_master_line(line)
                    self._client.sendall(line)
                if buf:
                    # Partial — forward as-is to avoid stalling
                    self._client.sendall(buf)
                    buf = b""
        except Exception as e:
            log.debug("FtpControlProxy master->client ended: %s", e)

    def _rewrite_master_line(self, line):
        """Intercept 227 PASV response; spawn local data listener."""
        m = self._PASV_RE.search(line)
        if not m:
            return line

        master_addr_str = m.group(1).decode()
        master_ip, master_pasv_port = _ftp_to_ip_port(master_addr_str)

        # Open local listener on an ephemeral port
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("", 0))
        listener.listen(1)
        local_port = listener.getsockname()[1]

        def _accept_and_bridge():
            try:
                listener.settimeout(_DATA_TIMEOUT)
                client_data, _ = listener.accept()
                listener.close()
                _bridge_data(client_data, master_ip, master_pasv_port)
            except Exception as e:
                log.debug("PASV listener ended: %s", e)
            finally:
                try:
                    listener.close()
                except Exception:
                    pass

        threading.Thread(target=_accept_and_bridge, daemon=True).start()

        # Rewrite response IP to slave's IP
        slave_ftp = f"{_ip_to_ftp(self._slave_ip)},{_port_to_ftp(local_port)}".encode()
        rewritten = self._PASV_RE.sub(
            b"227 Entering Passive Mode (" + slave_ftp + b")", line
        )
        log.debug("FtpProxy: PASV rewrite -> %s:%d", self._slave_ip, local_port)
        return rewritten


class FtpProxyListener:
    """Listen on ftp_control_port and spawn FtpControlProxy per client.

    Intended to run on slave nodes.  The master_host and master_port
    are read from FtpConfig.  slave_ip is this node's VPN IP (used
    in rewritten PASV responses).
    """

    def __init__(self, config, slave_ip=None):
        """
        Args:
            config: FtpConfig instance.
            slave_ip: This slave's IP address for PASV rewrites.
                      Auto-detected from a connection to master if not given.
        """
        self._config = config
        self._slave_ip = slave_ip or self._detect_local_ip(config.master_host)
        self._shutdown = threading.Event()
        self._server_sock = None

    def start(self):
        """Start listener in a daemon thread."""
        t = threading.Thread(target=self._run, daemon=True, name="ftpd-proxy")
        t.start()
        log.info(
            "FtpProxyListener: listening on :%d, proxying to %s:%d (slave_ip=%s)",
            self._config.ftp_control_port,
            self._config.master_host,
            self._config.ftp_control_port,
            self._slave_ip,
        )

    def stop(self):
        self._shutdown.set()
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass

    def _run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", self._config.ftp_control_port))
            sock.listen(32)
        except OSError as e:
            log.error("FtpProxyListener: cannot bind port %d: %s",
                      self._config.ftp_control_port, e)
            return

        self._server_sock = sock
        sock.settimeout(2)

        while not self._shutdown.is_set():
            try:
                client_sock, client_addr = sock.accept()
            except socket.timeout:
                continue
            except Exception as e:
                if not self._shutdown.is_set():
                    log.error("FtpProxyListener: accept error: %s", e)
                break

            proxy = FtpControlProxy(
                client_sock=client_sock,
                client_addr=client_addr,
                master_host=self._config.master_host,
                master_port=self._config.ftp_control_port,
                slave_ip=self._slave_ip,
            )
            threading.Thread(
                target=proxy.run,
                daemon=True,
                name=f"ftpd-proxy-{client_addr[0]}",
            ).start()

    @staticmethod
    def _detect_local_ip(master_host):
        """Find local IP used to reach master_host."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((master_host, 1))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
