"""
Server-to-Server (S2S) linking protocol for CSC IRC server federation.

Implements:
  - ServerLink: A single UDP connection to a peer CSC server with DH key exchange
  - ServerNetwork: Manages all peer links and network-wide operations

S2S Commands (encrypted with AES-256-GCM):
  CRYPTOINIT DH <p> <g> <pubkey> - Initiate DH key exchange
  CRYPTOINIT DHREPLY <pubkey>     - Reply with server's public key
  SLINK <password>                - Request server link
  SLINKACK <server_id> <ts>       - Acknowledge link with server identity
  SYNCUSER <nick> <host> <modes>  - Sync a user across servers
  SYNPART <nick> <channel>        - Sync a user parting a channel
  SYNCNICK <old> <new>            - Sync a nickname change
  SYNCCHAN <channel> <modes> <members_json> - Sync channel state
  SYNCTOPIC <channel> <topic>     - Sync a channel topic
  SYNCMSG <source> <target> <text> - Route a message between servers
  SYNCLINE <target> <line>        - Route a raw IRC line to a user
  DESYNC <nick|channel>           - Remove a nick or channel from remote
  SQUIT <server_id> <reason>      - Server disconnect notification

Uses UDP with DH-derived AES-256-GCM encryption for server-to-server communication.
All traffic after key exchange is authenticated and encrypted.
"""

import base64
import json
import socket
import threading
import time
from pathlib import Path
import time
import hashlib
import os
from pathlib import Path
from csc_server_core.crypto import DHExchange, encrypt, decrypt, is_encrypted

def _project_root():
    """Return CSC project root for kill switch file checks. Cached after first call."""
    if not hasattr(_project_root, '_cached'):
        try:
            from csc_platform import Platform
            _project_root._cached = Path(Platform.PROJECT_ROOT)
        except Exception:
            _project_root._cached = Path(__file__).resolve().parents[4]
    return _project_root._cached

def _killswitch(name):
    """Check if a kill switch file exists. Called at most every 20s — not per-packet."""
    return (_project_root() / name).exists()


def _verify_cert_pem(cert_pem: str, ca_cert_path: str) -> tuple:
    """Verify a PEM cert against a CA cert file.

    Returns (ok: bool, cn: str, reason: str).
    cn is the CommonName of the cert on success.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.x509.oid import NameOID

        cert = x509.load_pem_x509_certificate(cert_pem.encode(), default_backend())
        ca_cert = x509.load_pem_x509_certificate(
            Path(ca_cert_path).read_bytes(), default_backend()
        )

        # Verify signature
        ca_cert.public_key().verify(
            cert.signature,
            cert.tbs_certificate_bytes,
            padding.PKCS1v15(),
            cert.signature_hash_algorithm,
        )

        # Check not expired (compat: not_valid_before_utc added in cryptography 42.x)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        not_before = getattr(cert, 'not_valid_before_utc', cert.not_valid_before.replace(tzinfo=timezone.utc))
        not_after = getattr(cert, 'not_valid_after_utc', cert.not_valid_after.replace(tzinfo=timezone.utc))
        if now < not_before or now > not_after:
            return (False, "", "certificate expired or not yet valid")

        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        return (True, cn, "ok")
    except Exception as e:
        return (False, "", f"cert verification failed: {e}")


# S2S protocol line terminator
S2S_CRLF = b"\r\n"
S2S_MAX_LINE = 8192


class ServerLink:
    """Represents a single UDP connection to a peer CSC server with DH encryption."""

    def __init__(self, local_server, remote_host, remote_port, password,
                 remote_server_id=None, sock=None,
                 cert_path="", key_path="", ca_path=""):
        """Initialize a server link.

        Args:
            local_server: Reference to the local Server instance.
            remote_host: Hostname or IP of the remote server.
            remote_port: UDP port of the remote S2S listener.
            password: Shared secret for link auth (empty string when using certs).
            remote_server_id: ID of the remote server (set after handshake).
            sock: Pre-connected socket (for inbound links accepted by listener).
            cert_path: Path to our cert chain PEM (for cert-based auth).
            key_path: Path to our private key PEM (for cert-based auth).
            ca_path: Path to CA cert PEM used to verify peer certs.
        """
        self.local_server = local_server
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.password = password
        self.remote_server_id = remote_server_id
        self.cert_path = cert_path
        self.key_path = key_path
        self.ca_path = ca_path
        self._sock = sock
        self._connected = sock is not None
        self._authenticated = False
        self._encrypted = False  # Whether DH key exchange completed
        self._lock = threading.Lock()
        self._recv_buffer = b""
        self._reader_thread = None
        self._running = False
        self.link_time = None  # timestamp when link was established
        self.remote_timestamp = None  # remote server's startup time
        self.direction = "outbound"  # or "inbound", set by caller

        # Crypto state
        self._dh_exchange = None  # Local DHExchange instance
        self._aes_key = None  # Derived AES-256 key after key exchange
        self._remote_address = None  # Peer address for UDP replies

        # Handshake synchronization (for outbound connections)
        self._slinkack_received = threading.Event()  # Signaled when SLINKACK arrives
        self._slinkack_error = None  # Error message if SLINKACK validation failed

        # Reliable delivery
        self._send_seq = 0
        self._recv_seq = 0
        self._peer_ack_seq = 0
        self._outbound_queue = []    # [(seq, timestamp, encrypted_bytes)]
        self._queue_lock = threading.Lock()
        self._max_queue = 1000
        self._max_age = 30.0         # seconds
        self._retransmit_interval = 2.0
        self._last_retransmit = 0.0

        # Per-link remote state tracking (users/channels learned from THIS peer)
        self.remote_users = {}   # nick_lower -> {nick, server_id, host, modes, connect_time, channels}
        self.remote_channels = {}  # chan_lower -> {name, server_id, modes, members}
        self._state_lock = threading.Lock()  # Lock for accessing remote_users/remote_channels

    def connect(self):
        """Establish UDP connection to remote server and initiate DH key exchange.

        Returns:
            True on success, False on failure.
        """
        if self._connected:
            return True
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(10)
            # Bind to any available local address
            self._sock.bind(('0.0.0.0', 0))
            self._remote_address = (self.remote_host, self.remote_port)
            self._connected = True
            self.link_time = time.time()
            self._log(f"UDP connected to {self.remote_host}:{self.remote_port}")

            # Initiate DH key exchange
            if not self._initiate_dh_exchange():
                self._connected = False
                self._sock.close()
                self._sock = None
                return False

            return True
        except Exception as e:
            self._log(f"Failed to connect to {self.remote_host}:{self.remote_port}: {e}")
            self._sock = None
            self._connected = False
            return False

    def _initiate_dh_exchange(self):
        """Send CRYPTOINIT DH message to initiate key exchange.

        Returns:
            True if DH init sent successfully, False on error.
        """
        try:
            self._dh_exchange = DHExchange()
            init_msg = self._dh_exchange.format_init_message()
            self._sock.sendto(init_msg.encode(), self._remote_address)
            self._log("Sent CRYPTOINIT DH")
            return True
        except Exception as e:
            self._log(f"Failed to send DH init: {e}")
            return False

    def _handle_dh_reply(self, pubkey_hex):
        """Process CRYPTOINIT DHREPLY message and derive AES key.

        Args:
            pubkey_hex: Hex-encoded public key from remote server.

        Returns:
            True if key derivation succeeded, False on error.
        """
        try:
            remote_pubkey = int(pubkey_hex, 16)
            self._aes_key = self._dh_exchange.compute_shared_key(remote_pubkey)
            self._encrypted = True
            self._log("DH key exchange completed, AES-256 key derived")
            return True
        except Exception as e:
            self._log(f"Failed to complete DH exchange: {e}")
            return False

    def _send_dh_reply(self, pubkey_hex):
        """Process incoming CRYPTOINIT DH and send DHREPLY with AES derivation.

        Args:
            pubkey_hex: Hex-encoded public key from remote server.

        Returns:
            True if reply sent successfully, False on error.
        """
        try:
            # Parse remote DH parameters
            remote_pubkey = int(pubkey_hex, 16)

            # Initiate our DH exchange
            self._dh_exchange = DHExchange()

            # Derive shared AES key
            self._aes_key = self._dh_exchange.compute_shared_key(remote_pubkey)
            self._encrypted = True

            # Send our public key
            reply_msg = self._dh_exchange.format_reply_message()
            data = reply_msg.encode()
            if self._remote_address:
                self._sock.sendto(data, self._remote_address)
            self._log("Sent CRYPTOINIT DHREPLY, AES-256 key derived")
            return True
        except Exception as e:
            self._log(f"Failed to process DH init: {e}")
            return False

    def _handle_slinkack_response(self, line):
        """Process SLINKACK response during outbound handshake.

        This is called from the reader thread when SLINKACK arrives.
        Sets _slinkack_received event or _slinkack_error for authenticate() to check.

        Args:
            line: The full "SLINKACK ..." line.
        """
        try:
            parts = line.split()
            if len(parts) < 3:
                self._slinkack_error = f"SLINKACK with {len(parts)} args (need 3+)"
                self._slinkack_received.set()
                return

            # Cert-based auth check (SLINKACK CERT ...)
            if len(parts) >= 5 and parts[1] == "CERT":
                remote_cert_b64 = parts[2]
                self.remote_server_id = parts[3]
                try:
                    self.remote_timestamp = int(parts[4])
                except ValueError:
                    self.remote_timestamp = int(time.time())

                # Verify certificate
                try:
                    remote_cert_pem = base64.b64decode(remote_cert_b64).decode()
                    ok, cn, reason = _verify_cert_pem(remote_cert_pem, self.ca_path)
                    if not ok:
                        self._slinkack_error = f"Remote cert rejected: {reason}"
                        self._slinkack_received.set()
                        return
                    if cn != self.remote_server_id:
                        # Cert CN is authoritative — use it as the real server_id
                        self._log(f"Cert CN {cn!r} overrides claimed server_id {self.remote_server_id!r}")
                        self.remote_server_id = cn
                except Exception as e:
                    self._slinkack_error = f"Failed to verify cert: {e}"
                    self._slinkack_received.set()
                    return
            else:
                # Password-based auth (SLINKACK <server_id> <ts>)
                self.remote_server_id = parts[1]
                try:
                    self.remote_timestamp = int(parts[2])
                except ValueError:
                    self.remote_timestamp = int(time.time())

            # Successfully processed SLINKACK
            self._slinkack_received.set()
        except Exception as e:
            self._slinkack_error = str(e)
            self._slinkack_received.set()

    def authenticate(self):
        """Exchange SLINK/SLINKACK handshake after DH key exchange.

        Waits for DH completion, then performs SLINK/SLINKACK over encrypted channel.

        Returns:
            True if handshake succeeds, False otherwise.
        """
        if not self._connected:
            return False

        # Wait for DH key exchange to complete (outbound)
        # (For inbound, DH is handled when processing CRYPTOINIT DH)
        if not self._encrypted and self._dh_exchange is None:
            # We're the ones initiating - wait for DH reply
            for _ in range(100):  # ~10 second timeout
                if self._encrypted:
                    break
                time.sleep(0.1)

            if not self._encrypted:
                self._log("DH key exchange timeout")
                return False

        try:
            local_id = self._get_local_server_id()
            local_ts = str(int(getattr(self.local_server, 'startup_time', time.time())))

            # DEBUG: Log what server_id we're claiming
            self._log(f"Authenticating as server_id={local_id}, local_server has server_id attribute: {hasattr(self.local_server, 'server_id')}")
            if hasattr(self.local_server, 'server_id'):
                self._log(f"local_server.server_id is: {self.local_server.server_id}")

            if self.cert_path and self.ca_path:
                # Cert-based auth: send our cert chain, verify theirs
                cert_pem = Path(self.cert_path).read_text()
                cert_b64 = base64.b64encode(cert_pem.encode()).decode()
                self.send_message("SLINK", "CERT", cert_b64, local_id, local_ts)

                # Wait for SLINKACK to be processed by reader thread
                self._slinkack_received.clear()
                if not self._slinkack_received.wait(timeout=10):
                    self._log("Timeout waiting for SLINKACK during cert handshake")
                    return False

                if self._slinkack_error:
                    self._log(f"Invalid cert handshake response: {self._slinkack_error}")
                    return False
            else:
                # Password-based auth
                self.send_message("SLINK", self.password, local_id, local_ts)

                # Wait for SLINKACK to be processed by reader thread
                self._slinkack_received.clear()
                if not self._slinkack_received.wait(timeout=10):
                    self._log("Timeout waiting for SLINKACK during password handshake")
                    return False

                if self._slinkack_error:
                    self._log(f"Invalid handshake response: {self._slinkack_error}")
                    return False

            self._authenticated = True
            self._log(f"Authenticated with {self.remote_server_id} (encrypted)")

            drift = abs(time.time() - self.remote_timestamp)
            if drift > 10:
                self._log(f"WARNING: Time drift with {self.remote_server_id} is {drift:.1f}s")

            return True

        except Exception as e:
            self._log(f"Authentication failed: {e}")
            return False

    def handle_inbound_handshake(self):
        """Handle authentication for an inbound (accepted) connection.

        Expects SLINK from the remote, validates password, sends SLINKACK back.

        Returns:
            True if handshake succeeds, False otherwise.
        """
        try:
            line = self._recv_line(timeout=10)
            if not line:
                self._log("No SLINK received from inbound connection")
                return False

            parts = line.split()
            if len(parts) < 4 or parts[0] != "SLINK":
                self._log(f"Invalid inbound handshake: {line}")
                return False

            remote_password = parts[1]
            self.remote_server_id = parts[2]
            try:
                self.remote_timestamp = int(parts[3])
            except ValueError:
                self.remote_timestamp = int(time.time())

            if remote_password != self.password:
                self._log(f"Password mismatch from {self.remote_server_id}")
                self.send_message("ERROR", "Authentication failed")
                return False

            # Send SLINKACK
            local_id = self._get_local_server_id()
            local_ts = str(int(getattr(self.local_server, 'startup_time', time.time())))
            self.send_message("SLINKACK", local_id, local_ts)

            self._authenticated = True
            self._log(f"Inbound link authenticated from {self.remote_server_id}")
            return True

        except Exception as e:
            self._log(f"Inbound handshake failed: {e}")
            return False

    def start_reader(self, callback):
        """Start a background thread that reads S2S messages and calls callback.

        Args:
            callback: Function(link, command, args_list) called for each message.
        """
        self._running = True
        self._reader_thread = threading.Thread(
            target=self._reader_loop, args=(callback,), daemon=True
        )
        self._reader_thread.start()

    def _reader_loop(self, callback):
        """Background loop reading UDP datagrams and processing S2S messages."""
        while self._running and self._connected:
            try:
                if not self._sock:
                    break

                # Receive UDP datagram (blocking with timeout)
                self._sock.settimeout(2)
                try:
                    data, addr = self._sock.recvfrom(65535)
                except socket.timeout:
                    self._retransmit_unacked()
                    continue

                if not data:
                    continue

                # Store remote address for replies
                if not self._remote_address:
                    self._remote_address = addr

                # Decrypt if encrypted
                if self._encrypted and is_encrypted(data):
                    try:
                        plaintext = decrypt(self._aes_key, data)
                        data = plaintext
                    except Exception as e:
                        self._log(f"Decryption failed: {e}")
                        continue

                # Parse as text message
                try:
                    line = data.decode('utf-8').strip()
                except UnicodeDecodeError:
                    continue

                if not line:
                    continue

                # Parse SEQ/ACK header if present (reliable delivery)
                if line.startswith("SEQ "):
                    parts = line.split(" ", 5)
                    if len(parts) >= 4:
                        try:
                            msg_seq = int(parts[1])
                            ack_seq = int(parts[3])
                        except (ValueError, IndexError):
                            continue
                        line = parts[4] if len(parts) > 4 else ""
                        self._process_ack(ack_seq)
                        if msg_seq == 0:
                            continue  # Pure ACK, no payload
                        if msg_seq <= self._recv_seq:
                            continue  # Duplicate, already processed
                        self._recv_seq = msg_seq
                        if not line:
                            continue

                # Check for crypto handshake messages first
                if line.startswith("CRYPTOINIT DH "):
                    parts = line.split()
                    if len(parts) >= 5:
                        # Remote is initiating DH
                        self._send_dh_reply(parts[4])
                    continue

                if line.startswith("CRYPTOINIT DHREPLY "):
                    parts = line.split()
                    if len(parts) >= 3:
                        # Remote replied to our DH
                        self._handle_dh_reply(parts[2])
                    continue

                if line.startswith("SLINKACK "):
                    # Handle SLINKACK during handshake
                    self._handle_slinkack_response(line)
                    continue

                # Parse S2S line: COMMAND arg1 arg2 ... :trailing
                parts = line.split(" ", 1)
                command = parts[0]
                rest = parts[1] if len(parts) > 1 else ""
                callback(self, command, rest)

            except Exception as e:
                if self._running:
                    self._log(f"Reader error: {e}")
                    self._connected = False
                break

        # Notify network of disconnect
        if hasattr(self.local_server, 's2s_network'):
            self.local_server.s2s_network._handle_link_lost(self)

    def send_message(self, command, *args):
        """Send an S2S command to the remote server (encrypted if key available).

        Args:
            command: S2S command string (e.g. "SYNCUSER").
            *args: Arguments for the command. The last arg with spaces
                   gets trailing syntax automatically.
        """
        parts = [command] + [str(a) for a in args]
        line = " ".join(parts)
        # SEQ/ACK disabled until both peers support it (Linux drops SEQ as unknown cmd)
        return self._send_raw_direct(line)

    def send_raw(self, line):
        """Send a raw line to the remote server (encrypted if key available).

        Args:
            line: Complete S2S line (without CRLF).
        """
        # SEQ/ACK disabled until both peers support it (Linux drops SEQ as unknown cmd)
        return self._send_raw_direct(line)

    def _send_raw_direct(self, line):
        """Send a raw line without seq/ack wrapping (used for pre-auth messages)."""
        with self._lock:
            if not self._connected or not self._sock or not self._remote_address:
                return False
            try:
                data = line.encode("utf-8")
                if self._encrypted and self._aes_key:
                    data = encrypt(self._aes_key, data)
                self._sock.sendto(data, self._remote_address)
                return True
            except Exception as e:
                self._log(f"Raw send failed: {e}")
                self._connected = False
                return False

    def _send_with_seq(self, line):
        """Send a line with SEQ/ACK header for reliable delivery."""
        with self._queue_lock:
            self._send_seq += 1
            seq = self._send_seq
            header = f"SEQ {seq} ACK {self._recv_seq} {line}"
        with self._lock:
            if not self._connected or not self._sock or not self._remote_address:
                return False
            try:
                data = header.encode("utf-8")
                if self._encrypted and self._aes_key:
                    data = encrypt(self._aes_key, data)
                self._sock.sendto(data, self._remote_address)
                with self._queue_lock:
                    self._outbound_queue.append((seq, time.time(), data))
                    # Trim queue if too large
                    if len(self._outbound_queue) > self._max_queue:
                        self._outbound_queue = self._outbound_queue[-self._max_queue:]
                return True
            except Exception as e:
                self._log(f"Seq send failed to {self.remote_server_id}: {e}")
                self._connected = False
                return False

    def _process_ack(self, ack_seq):
        """Remove all queue entries with seq <= ack_seq."""
        with self._queue_lock:
            self._peer_ack_seq = max(self._peer_ack_seq, ack_seq)
            self._outbound_queue = [
                (s, t, d) for s, t, d in self._outbound_queue if s > ack_seq
            ]

    def _retransmit_unacked(self):
        """Retransmit unacked messages, dropping those older than max_age."""
        now = time.time()
        if now - self._last_retransmit < self._retransmit_interval:
            return
        self._last_retransmit = now
        with self._queue_lock:
            # Drop messages older than max_age
            self._outbound_queue = [
                (s, t, d) for s, t, d in self._outbound_queue
                if now - t < self._max_age
            ]
            to_send = list(self._outbound_queue)
        # Retransmit remaining (already encrypted)
        with self._lock:
            if not self._connected or not self._sock or not self._remote_address:
                return
            for seq, ts, data in to_send:
                try:
                    self._sock.sendto(data, self._remote_address)
                except Exception:
                    break

    def is_connected(self):
        """Check if this link is alive and authenticated."""
        return self._connected and self._authenticated

    def close(self):
        """Gracefully close the link."""
        self._running = False
        self._connected = False
        self._authenticated = False
        # Only close socket for outbound links (they own their socket).
        # Inbound links share the listener socket — closing it would kill
        # ALL S2S reception.
        if self._sock and self.direction != "inbound":
            try:
                self._sock.close()
            except Exception:
                if hasattr(self, 'log'):
                    self.log('Ignored exception', level='DEBUG')
            self._sock = None
        elif self.direction == "inbound":
            self._sock = None  # Release reference without closing
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2)
        self._log(f"Link to {self.remote_server_id or 'unknown'} closed")

    def _recv_line(self, timeout=None):
        """Read one CRLF-terminated line from the socket.

        Returns:
            str: The line (without CRLF), or None on timeout, or "" on disconnect.
        """
        if not self._sock:
            return ""
        if timeout:
            self._sock.settimeout(timeout)
        try:
            while S2S_CRLF not in self._recv_buffer:
                chunk = self._sock.recv(S2S_MAX_LINE)
                if not chunk:
                    return ""  # Connection closed
                self._recv_buffer += chunk
            idx = self._recv_buffer.index(S2S_CRLF)
            line = self._recv_buffer[:idx].decode("utf-8", errors="ignore")
            self._recv_buffer = self._recv_buffer[idx + len(S2S_CRLF):]
            return line
        except socket.timeout:
            return None
        except Exception as e:
            self._log(f"Recv error: {e}")
            return ""
        finally:
            if self._sock:
                try:
                    self._sock.settimeout(None)
                except Exception:
                    if hasattr(self, 'log'):
                        self.log('Ignored exception', level='DEBUG')

    def _get_local_server_id(self):
        """Return the local server's unique ID."""
        result = getattr(self.local_server, 'server_id',
                       os.environ.get('CSC_SERVER_ID', 'server_001'))
        # DEBUG: Log what we're returning
        if not hasattr(self, '_get_local_server_id_logged'):
            print(f"[S2S-ID] _get_local_server_id: result={result}, has_attr={hasattr(self.local_server, 'server_id')}")
            self._get_local_server_id_logged = True
        return result

    def _log(self, message):
        """Log via the local server's logger."""
        if hasattr(self.local_server, 'log'):
            self.local_server.log(f"[S2S:{self.remote_server_id or '?'}] {message}")


class ServerNetwork:
    """Manages all linked servers and network-wide operations."""

    def __init__(self, local_server):
        """Initialize the server network manager.

        Args:
            local_server: Reference to the local Server instance.
        """
        self.local_server = local_server
        self._links = {}  # server_id -> ServerLink
        self._lock = threading.RLock()
        self._listener_sock = None
        self._listener_thread = None
        self._running = False

        # S2S configuration
        self.s2s_port = int(os.environ.get('CSC_S2S_PORT', '9520'))
        self.s2s_password = os.environ.get('CSC_SERVER_LINK_PASSWORD', '')
        self.server_id = getattr(local_server, 'server_id', os.environ.get('CSC_SERVER_ID', 'server_001'))

        # Cert-based auth: load paths from csc-service.json
        self.s2s_cert_path = ""   # chain PEM (our cert + CA)
        self.s2s_key_path = ""    # our private key
        self.s2s_ca_path = ""     # CA cert for verifying peers
        self.s2s_peers = []       # List of {host, port} dicts for outbound connections

        debug_file = Path("/tmp/s2s_init_debug.log")
        try:
            self._load_cert_config()
            debug_file.write_text(f"Config loaded: {len(self.s2s_peers)} peers, cert={bool(self.s2s_cert_path)}\n")
        except Exception as e:
            debug_file.write_text(f"Config load error: {e}\n")

        # If no explicit server_id, derive from cert CN so S2S auth matches
        if self.server_id in ('server_001', '') and self.s2s_cert_path:
            cn = self._cn_from_cert(self.s2s_cert_path)
            if cn:
                self.server_id = cn
                self._log(f"Server ID derived from cert CN: {cn}")

        # Track which servers have been seen (loop prevention)
        self._seen_servers = {self.server_id}

        # Peer linking
        self._peer_link_thread = None
        self._last_peer_link_attempt = {}

    def _load_cert_config(self):
        """Load S2S cert paths, password, and peers from csc-service.json (CSC_ROOT/csc-service.json)."""
        try:
            # Try CSC_HOME, then fall back to current directory
            csc_root = os.environ.get('CSC_HOME', '')
            if not csc_root:
                csc_root = os.getcwd()
            
            # DEBUG
            self._log(f"Loading config from {csc_root}/csc-service.json (CSC_HOME={os.environ.get('CSC_HOME', 'unset')}, CWD={os.getcwd()})")
            
            if not csc_root:
                return
            cfg_path = Path(csc_root) / "csc-service.json"
            if not cfg_path.exists():
                return
            import json as _json
            cfg = _json.loads(cfg_path.read_text())
            self.s2s_cert_path = cfg.get("s2s_cert", "")
            self.s2s_key_path = cfg.get("s2s_key", "")
            self.s2s_ca_path = cfg.get("s2s_ca", "")
            self.s2s_peers = cfg.get("s2s_peers", [])
            # Load s2s_password from config if not already set from environment
            if not self.s2s_password:
                self.s2s_password = cfg.get("s2s_password", "")
            if self.s2s_cert_path:
                self._log(f"Cert auth configured: {Path(self.s2s_cert_path).name}")
            if self.s2s_password:
                self._log(f"S2S password configured")
            if self.s2s_peers:
                self._log(f"S2S peers configured: {len(self.s2s_peers)}")
        except Exception as e:
            self._log(f"WARNING: Could not load cert config: {e}")

    @staticmethod
    def _cn_from_cert(cert_path):
        """Extract Common Name from a PEM certificate file."""
        try:
            import subprocess, re
            result = subprocess.run(
                ['openssl', 'x509', '-noout', '-subject', '-in', str(cert_path)],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                m = re.search(r'CN\s*=\s*(\S+)', result.stdout)
                if m:
                    return m.group(1)
        except Exception:
            pass
        return None

    def attach_fxp_bridge(self, bridge):
        """Attach an FtpS2sBridge to receive SYNCFILE/RSYNCFILE/SYNCINVENTORY messages."""
        self._fxp_bridge = bridge
        self._log("FXP bridge attached")

    def start_listener(self):
        """Start the UDP listener for inbound S2S connections with DH encryption."""
        print(f"[S2S] start_listener called. password={bool(self.s2s_password)}, cert={bool(self.s2s_cert_path)}, ca={bool(self.s2s_ca_path)}, peers={len(self.s2s_peers)}")

        if not self.s2s_password and not (self.s2s_cert_path and self.s2s_ca_path):
            print(f"[S2S] Listener disabled - no auth configured")
            self._log("No S2S password or certs configured, S2S listener disabled")
            return False

        try:
            self._listener_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._listener_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._listener_sock.bind(('0.0.0.0', self.s2s_port))
            self._listener_sock.settimeout(2)
            self._running = True
            self._listener_thread = threading.Thread(
                target=self._receive_loop, daemon=True
            )
            self._listener_thread.start()
            self._log(f"S2S UDP listener started on port {self.s2s_port}")
            self._start_peer_linker()
            return True
        except Exception as e:
            self._log(f"Failed to start S2S listener: {e}")
            return False

    def _start_peer_linker(self):
        """Start a thread that periodically tries to link to configured S2S peers."""
        if not self.s2s_peers:
            return
        self._peer_link_thread = threading.Thread(target=self._peer_link_loop, daemon=True)
        self._peer_link_thread.start()
        self._log(f"S2S peer linker started, will try to link to {len(self.s2s_peers)} peer(s)")

    def _peer_link_loop(self):
        """Periodically attempt to link to configured S2S peers."""
        print(f"[S2S-LINKER] Thread started at {time.time()}")

        while self._running:
            try:
                for peer in self.s2s_peers:
                    host = peer.get("host")
                    port = peer.get("port", self.s2s_port)
                    if not host:
                        continue
                    peer_key = f"{host}:{port}"

                    # Try to link every 30 seconds per peer
                    now = time.time()
                    last_attempt = self._last_peer_link_attempt.get(peer_key, 0)
                    if now - last_attempt < 30:
                        continue

                    print(f"[S2S-LINKER] Attempting to link to {peer_key}")
                    self._last_peer_link_attempt[peer_key] = now
                    self._try_link_to_peer(host, port)
            except Exception as e:
                print(f"[S2S-LINKER] Error: {e}")
                self._log(f"Peer linker error: {e}")

            time.sleep(5)

    def _try_link_to_peer(self, host, port):
        """Attempt to establish an outbound S2S link to a peer."""
        peer_key = f"{host}:{port}"
        try:
            # Check if we're already linked (by host:port or by any active link)
            with self._lock:
                for sid, link in self._links.items():
                    if link.is_connected():
                        if (link.remote_host, link.remote_port) == (host, port):
                            return  # Already linked by address
                        if link.remote_host == host:
                            return  # Already linked to this host

            # Create ServerLink for outbound connection
            print(f"[S2S-LINKER] Creating link to {peer_key}...")
            link = ServerLink(
                self.local_server,
                host,
                port,
                self.s2s_password,
                cert_path=self.s2s_cert_path,
                key_path=self.s2s_key_path,
                ca_path=self.s2s_ca_path
            )

            # Establish connection
            print(f"[S2S-LINKER] Connecting to {peer_key}...")
            if not link.connect():
                print(f"[S2S-LINKER] Failed to connect to {peer_key}")
                self._log(f"Failed to connect to {peer_key}")
                return

            # Register link BEFORE authenticating (so reader thread can process responses)
            remote_id = link.remote_server_id or peer_key
            with self._lock:
                self._links[remote_id] = link

            # Start reader thread BEFORE authenticating (to receive DH responses)
            print(f"[S2S-LINKER] Starting reader thread for {peer_key}...")
            link.start_reader(self._dispatch_s2s_message)

            # Now authenticate
            print(f"[S2S-LINKER] Connected, authenticating with {peer_key}...")
            if not link.authenticate():
                print(f"[S2S-LINKER] Failed to authenticate with {peer_key}")
                self._log(f"Failed to authenticate with {peer_key}")
                # Remove from links and close socket to avoid leaking UDP sockets
                with self._lock:
                    self._links.pop(remote_id, None)
                link.close()
                return

            # Re-register under real server_id with tiebreaker
            actual_id = link.remote_server_id
            with self._lock:
                # Remove placeholder key (was "host:port" before auth)
                self._links.pop(remote_id, None)

                # Tiebreaker: lower server_id is the designated connector
                local_id = self._get_local_server_id()
                existing = self._links.get(actual_id)
                if existing and existing.is_connected():
                    if local_id < actual_id:
                        # We win as connector — close their inbound, keep ours
                        self._log(f"Tiebreaker: closing inbound from {actual_id}, keeping outbound")
                        existing.close()
                    else:
                        # They win — keep their link, drop ours
                        self._log(f"Tiebreaker: keeping inbound from {actual_id}, dropping outbound")
                        link.close()
                        return

                self._links[actual_id] = link
                self._seen_servers.add(actual_id)
            print(f"[S2S-LINKER] Successfully linked to {peer_key} as {actual_id}")
            self._log(f"Successfully linked to peer {peer_key} as {actual_id}")

            # Send our users/channels to the remote so sync is bidirectional
            self._send_full_sync(link)

        except Exception as e:
            print(f"[S2S-LINKER] Exception linking to {peer_key}: {e}")
            self._log(f"Failed to link to peer {peer_key}: {e}")

    def _receive_loop(self):
        """Receive inbound S2S UDP datagrams from peers with DH and SLINK auth."""
        # Track peer connections by address: addr -> (link, authenticated_flag)
        peer_links = {}  # addr -> ServerLink

        # DISCONNECT kill switch: check disk at most every 20s, not per-packet.
        _disconnect_checked_at = 0.0
        _disconnect_active = False

        while self._running:
            if hasattr(self, "check_shutdown") and self.check_shutdown():
                if hasattr(self, "log_shutdown"): self.log_shutdown()
                break
            # Check DISCONNECT file every 20s (disk stat is not free)
            now = time.monotonic()
            if now - _disconnect_checked_at >= 20:
                _disconnect_checked_at = now
                _disconnect_active = _killswitch("DISCONNECT")
                if _disconnect_active:
                    # Drop all inbound peer state immediately
                    for link in list(peer_links.values()):
                        try:
                            link.close()
                        except Exception:
                            if hasattr(self, 'log'):
                                self.log('Ignored exception', level='DEBUG')
                    peer_links.clear()
                    with self._lock:
                        for link in list(self._links.values()):
                            try:
                                link.close()
                            except Exception:
                                if hasattr(self, 'log'):
                                    self.log('Ignored exception', level='DEBUG')
                        self._links.clear()
                    self._log("[DISCONNECT] Kill switch active — all inbound S2S links dropped.")

            try:
                data, addr = self._listener_sock.recvfrom(65535)  # full UDP datagram
                if not data:
                    continue

                # Decrypt if encrypted
                plaintext = data
                if is_encrypted(data):
                    # Peek to see if this is an authenticated link
                    if addr in peer_links and peer_links[addr]._encrypted:
                        try:
                            plaintext = decrypt(peer_links[addr]._aes_key, data)
                        except Exception as e:
                            self._log(f"Decryption failed from {addr}: {e}")
                            continue

                # Decode message
                try:
                    line = plaintext.decode('utf-8').strip()
                except UnicodeDecodeError:
                    continue

                if not line:
                    continue

                # Refuse all new connections while DISCONNECT is active
                if _disconnect_active and addr not in peer_links:
                    continue

                # Get or create ServerLink for this peer
                if addr not in peer_links:
                    self._log(f"Inbound S2S datagram from {addr}")
                    link = ServerLink(
                        self.local_server,
                        remote_host=addr[0],
                        remote_port=addr[1],
                        password=self.s2s_password,
                        sock=None,
                        cert_path=self.s2s_cert_path,
                        key_path=self.s2s_key_path,
                        ca_path=self.s2s_ca_path,
                    )
                    link._remote_address = addr
                    link._connected = True
                    link._sock = self._listener_sock  # For sending replies
                    link.direction = "inbound"
                    peer_links[addr] = link

                link = peer_links[addr]

                # Parse SEQ/ACK header if present (reliable delivery)
                if line.startswith("SEQ "):
                    parts = line.split(" ", 5)
                    if len(parts) >= 4:
                        try:
                            msg_seq = int(parts[1])
                            ack_seq = int(parts[3])
                        except (ValueError, IndexError):
                            continue
                        line = parts[4] if len(parts) > 4 else ""
                        link._process_ack(ack_seq)
                        if msg_seq == 0:
                            continue  # Pure ACK, no payload
                        if msg_seq <= link._recv_seq:
                            continue  # Duplicate, already processed
                        link._recv_seq = msg_seq
                        if not line:
                            continue

                # Handle DH exchange
                if line.startswith("CRYPTOINIT DH "):
                    parts = line.split()
                    if len(parts) >= 5:
                        link._send_dh_reply(parts[4])
                    continue

                if line.startswith("CRYPTOINIT DHREPLY "):
                    parts = line.split()
                    if len(parts) >= 3:
                        link._handle_dh_reply(parts[2])
                    continue

                # Before SLINK, DH must be complete
                if not link._encrypted and not line.startswith("SLINK"):
                    self._log(f"Dropping unencrypted message before DH: {line[:50]}")
                    continue

                # Handle SLINK (link request)
                if line.startswith("SLINK "):
                    print(f"[S2S-INBOUND] Received SLINK from {addr}: {line[:80]}")
                    if link._authenticated:
                        continue  # Already authenticated
                    parts = line.split()
                    local_id = self._get_local_server_id()
                    local_ts = str(int(getattr(self.local_server, 'startup_time', time.time())))
                    print(f"[S2S-INBOUND] Processing SLINK: parts={len(parts)}, local_id={local_id}")

                    if len(parts) >= 5 and parts[1] == "CERT":
                        # Cert-based auth
                        remote_cert_b64 = parts[2]
                        remote_id = parts[3]
                        try:
                            remote_ts = int(parts[4])
                        except ValueError:
                            remote_ts = int(time.time())

                        if not (self.s2s_cert_path and self.s2s_ca_path):
                            self._log(f"Cert auth from {addr} but no certs configured")
                            reply = "ERROR Cert auth not configured"
                            reply_data = encrypt(link._aes_key, reply.encode()) if link._encrypted else reply.encode()
                            self._listener_sock.sendto(reply_data, addr)
                            continue

                        try:
                            remote_cert_pem = base64.b64decode(remote_cert_b64).decode()
                            ok, cn, reason = _verify_cert_pem(remote_cert_pem, self.s2s_ca_path)
                        except Exception as e:
                            ok, cn, reason = False, "", str(e)

                        if not ok:
                            self._log(f"Cert rejected from {addr}: {reason}")
                            reply = "ERROR Cert rejected"
                            reply_data = encrypt(link._aes_key, reply.encode()) if link._encrypted else reply.encode()
                            self._listener_sock.sendto(reply_data, addr)
                            continue

                        if cn != remote_id:
                            self._log(f"Cert CN {cn!r} != claimed id {remote_id!r} from {addr}")
                            reply = "ERROR Cert CN mismatch"
                            reply_data = encrypt(link._aes_key, reply.encode()) if link._encrypted else reply.encode()
                            self._listener_sock.sendto(reply_data, addr)
                            continue

                        link.remote_server_id = remote_id
                        link.remote_timestamp = remote_ts
                        link._authenticated = True

                        our_cert_pem = Path(self.s2s_cert_path).read_text()
                        our_cert_b64 = base64.b64encode(our_cert_pem.encode()).decode()
                        reply = f"SLINKACK CERT {our_cert_b64} {local_id} {local_ts}"
                        reply_data = encrypt(link._aes_key, reply.encode()) if link._encrypted else reply.encode()
                        print(f"[S2S-INBOUND] Sending SLINKACK CERT to {addr}, encrypted={link._encrypted}, data_len={len(reply_data)}")
                        self._listener_sock.sendto(reply_data, addr)
                        print(f"[S2S-INBOUND] SLINKACK sent")

                        with self._lock:
                            existing = self._links.get(remote_id)
                            if existing and existing.is_connected():
                                local_id_check = self._get_local_server_id()
                                if local_id_check < remote_id:
                                    # We are designated connector — reject inbound
                                    self._log(f"Tiebreaker: rejecting inbound cert link from {remote_id}")
                                    link._authenticated = False
                                    link._connected = False
                                    reply = "ERROR Already linked"
                                    reply_data = encrypt(link._aes_key, reply.encode()) if link._encrypted else reply.encode()
                                    self._listener_sock.sendto(reply_data, addr)
                                    peer_links.pop(addr, None)
                                    continue
                                else:
                                    # They are designated connector — close our outbound, accept theirs
                                    self._log(f"Tiebreaker: closing outbound to {remote_id}, accepting inbound")
                                    existing.close()
                            self._links[remote_id] = link
                            self._seen_servers.add(remote_id)
                        self._log(f"Inbound cert link authenticated from {remote_id} (CN={cn})")
                        self._send_full_sync(link)

                    elif len(parts) >= 4:
                        # Password-based auth
                        remote_password = parts[1]
                        remote_id = parts[2]
                        try:
                            remote_ts = int(parts[3])
                        except ValueError:
                            remote_ts = int(time.time())

                        if remote_password != self.s2s_password:
                            self._log(f"Password mismatch from {addr}")
                            reply = "ERROR Authentication failed"
                            reply_data = encrypt(link._aes_key, reply.encode()) if link._encrypted else reply.encode()
                            self._listener_sock.sendto(reply_data, addr)
                            continue

                        link.remote_server_id = remote_id
                        link.remote_timestamp = remote_ts
                        link._authenticated = True

                        reply = f"SLINKACK {local_id} {local_ts}"
                        reply_data = encrypt(link._aes_key, reply.encode()) if link._encrypted else reply.encode()
                        self._listener_sock.sendto(reply_data, addr)

                        with self._lock:
                            existing = self._links.get(remote_id)
                            if existing and existing.is_connected():
                                local_id_check = self._get_local_server_id()
                                if local_id_check < remote_id:
                                    # We are designated connector — reject inbound
                                    self._log(f"Tiebreaker: rejecting inbound link from {remote_id}")
                                    link._authenticated = False
                                    link._connected = False
                                    reply = "ERROR Already linked"
                                    reply_data = encrypt(link._aes_key, reply.encode()) if link._encrypted else reply.encode()
                                    self._listener_sock.sendto(reply_data, addr)
                                    peer_links.pop(addr, None)
                                    continue
                                else:
                                    # They are designated connector — close our outbound, accept theirs
                                    self._log(f"Tiebreaker: closing outbound to {remote_id}, accepting inbound")
                                    existing.close()
                            self._links[remote_id] = link
                            self._seen_servers.add(remote_id)
                        self._log(f"Inbound link authenticated from {remote_id}")
                        self._send_full_sync(link)
                    continue

                # For authenticated links, dispatch to message handler
                if link._authenticated:
                    parts = line.split(" ", 1)
                    command = parts[0]
                    rest = parts[1] if len(parts) > 1 else ""
                    try:
                        self._dispatch_s2s_message(link, command, rest)
                    except Exception as e:
                        self._log(f"Error dispatching S2S message: {e}")

            except socket.timeout:
                for link in list(peer_links.values()):
                    link._retransmit_unacked()
                continue
            except Exception as e:
                if self._running:
                    self._log(f"Receive error: {e}")

    def _handle_inbound_link(self, link):
        """Handle a newly established inbound UDP S2S link.

        The link is already connected and has a remote address.
        Wait for DH completion, then SLINK handshake.
        """
        link.link_time = time.time()

        if not link.handle_inbound_handshake():
            link.close()
            return

        remote_id = link.remote_server_id
        if not remote_id:
            link.close()
            return

        # Loop prevention
        if remote_id in self._seen_servers and remote_id != self.server_id:
            # Already linked to this server
            if remote_id in self._links and self._links[remote_id].is_connected():
                self._log(f"Duplicate link from {remote_id}, rejecting")
                link.send_message("ERROR", "Already linked")
                link.close()
                return

        with self._lock:
            self._links[remote_id] = link
            self._seen_servers.add(remote_id)

        self._log(f"Inbound link established with {remote_id}")
        link.start_reader(self._dispatch_s2s_message)
        self._send_full_sync(link)

    def link_to(self, host, port, password=None):
        """Initiate an outbound link to a remote server.

        Args:
            host: Remote server hostname or IP.
            port: Remote server S2S TCP port.
            password: Link password (uses configured default if None).

        Returns:
            True if link established, False otherwise.
        """
        # DISCONNECT hardcoded override — refuse all outbound links until file is removed
        if _killswitch("DISCONNECT"):
            self._log("[DISCONNECT] Kill switch active — refusing outbound link to " + host)
            return False

        password = password or self.s2s_password
        if not password:
            self._log("No S2S password configured")
            return False

        link = ServerLink(self.local_server, host, port, password,
                          cert_path=self.s2s_cert_path,
                          key_path=self.s2s_key_path,
                          ca_path=self.s2s_ca_path)
        if not link.connect():
            return False

        # Start reader thread to handle DH reply and subsequent S2S messages
        link.start_reader(self._dispatch_s2s_message)
        time.sleep(0.1)  # Give reader thread time to start

        if not link.authenticate():
            link.close()
            return False

        remote_id = link.remote_server_id
        if not remote_id:
            link.close()
            return False

        # Loop prevention
        if remote_id == self.server_id:
            self._log("Cannot link to self")
            link.close()
            return False

        with self._lock:
            # Close existing link to same server if any
            old = self._links.get(remote_id)
            if old:
                old.close()
            self._links[remote_id] = link
            self._seen_servers.add(remote_id)

        self._log(f"Outbound link established with {remote_id}")
        self._send_full_sync(link)
        return True

    def get_peer_servers(self):
        """List all connected peer server IDs.

        Returns:
            List of server_id strings for all active links.
        """
        with self._lock:
            return [sid for sid, link in self._links.items() if link.is_connected()]

    def get_link(self, server_id):
        """Get the ServerLink for a specific peer.

        Returns:
            ServerLink or None.
        """
        with self._lock:
            link = self._links.get(server_id)
            if link and link.is_connected():
                return link
            return None

    def broadcast_to_network(self, command, args_str="", exclude_server=None):
        """Send an S2S command to all connected peers.

        Args:
            command: S2S command string.
            args_str: Pre-formatted argument string.
            exclude_server: Server ID to exclude (prevent echo).
        """
        line = f"{command} {args_str}".strip() if args_str else command
        with self._lock:
            link_count = len(self._links)
            if link_count == 0:
                self._log(f"broadcast_to_network({command}): no links!")
            for server_id, link in list(self._links.items()):
                if server_id == exclude_server:
                    continue
                connected = link.is_connected()
                self._log(f"broadcast_to_network({command}) -> {server_id}: connected={connected}, has_sock={link._sock is not None}, has_addr={link._remote_address is not None}")
                if connected:
                    ok = link.send_raw(line)
                    self._log(f"broadcast_to_network({command}) -> {server_id}: send_raw returned {ok}")

    def get_user_from_network(self, nick):
        """Find a user on any server in the network and which link has them.

        Args:
            nick: Nickname to search for.

        Returns:
            Tuple of (ServerLink, user_info_dict) or (None, None) if not found.
        """
        nick_lower = nick.lower()
        with self._lock:
            for server_id, link in list(self._links.items()):
                with link._state_lock:
                    info = link.remote_users.get(nick_lower)
                    if info:
                        return link, dict(info)
        return None, None

    def get_channel_from_network(self, channel):
        """Find a channel on any server in the network and which link has it.

        Args:
            channel: Channel name to search for.

        Returns:
            Tuple of (ServerLink, channel_info_dict) or (None, None) if not found.
        """
        chan_lower = channel.lower()
        with self._lock:
            for server_id, link in list(self._links.items()):
                with link._state_lock:
                    info = link.remote_channels.get(chan_lower)
                    if info:
                        return link, dict(info)
        return None, None

    def route_message(self, source_nick, target, text, exclude_server=None):
        """Route a PRIVMSG/NOTICE across the network.

        Broadcasts to all connected servers. Smart routing will optimize once
        user/channel state is synced across the S2S link.

        Args:
            source_nick: Sender's nickname.
            target: Target channel or nick.
            text: Message text.
            exclude_server: Server to exclude from broadcast.
        """
        args = f"{source_nick} {target} :{text}"
        self.broadcast_to_network("SYNCMSG", args, exclude_server=exclude_server)

    def route_notice(self, source_nick, target, text, exclude_server=None):
        """Route a NOTICE across the network."""
        args = f"{source_nick} {target} :{text}"
        self.broadcast_to_network("SYNCNOTICE", args, exclude_server=exclude_server)

    def sync_line(self, target_nick, line, exclude_server=None):
        """Route a raw IRC line to a specific user on the network.

        Args:
            target_nick: Target user's nickname.
            line: Raw IRC message line.
            exclude_server: Server to exclude.
        """
        args = f"{target_nick} :{line}"
        self.broadcast_to_network("SYNCLINE", args, exclude_server=exclude_server)

    def sync_user_join(self, nick, host, modes, channel=None, exclude_server=None):
        """Notify the network that a user joined/connected.

        Args:
            nick: User's nickname.
            host: User's hostname.
            modes: User's mode string.
            channel: Channel joined (optional).
            exclude_server: Server to exclude.
        """
        connect_time = str(int(time.time()))
        args = f"{nick} {host} {modes} {connect_time}"
        if channel:
            args += f" {channel}"
        self.broadcast_to_network("SYNCUSER", args, exclude_server=exclude_server)

    def sync_user_quit(self, nick, reason="", exclude_server=None):
        """Notify the network that a user disconnected.

        Args:
            nick: User's nickname.
            reason: Quit reason.
            exclude_server: Server to exclude.
        """
        args = f"{nick}"
        if reason:
            args += f" :{reason}"
        self.broadcast_to_network("DESYNC", args, exclude_server=exclude_server)

        # Remove from remote tracking on all links
        with self._lock:
            for link in list(self._links.values()):
                with link._state_lock:
                    link.remote_users.pop(nick.lower(), None)

    def sync_user_part(self, nick, channel, reason="", exclude_server=None):
        """Notify the network that a user parted a channel.

        Args:
            nick: User's nickname.
            channel: Channel name.
            reason: Part reason.
            exclude_server: Server to exclude.
        """
        args = f"{nick} {channel}"
        if reason:
            args += f" :{reason}"
        self.broadcast_to_network("SYNPART", args, exclude_server=exclude_server)

    def sync_nick_change(self, old_nick, new_nick, exclude_server=None):
        """Notify the network that a user changed their nickname.

        Args:
            old_nick: Previous nickname.
            new_nick: New nickname.
            exclude_server: Server to exclude.
        """
        args = f"{old_nick} {new_nick}"
        self.broadcast_to_network("SYNCNICK", args, exclude_server=exclude_server)

    def sync_channel(self, channel_name, modes_str, members_json, exclude_server=None):
        """Broadcast channel state to the network.

        Args:
            channel_name: Channel name.
            modes_str: Channel mode string.
            members_json: JSON-encoded member list.
            exclude_server: Server to exclude.
        """
        args = f"{channel_name} {modes_str} {members_json}"
        self.broadcast_to_network("SYNCCHAN", args, exclude_server=exclude_server)

    def sync_topic(self, channel_name, topic, exclude_server=None):
        """Broadcast channel topic to the network.

        Args:
            channel_name: Channel name.
            topic: New topic.
            exclude_server: Server to exclude.
        """
        args = f"{channel_name} :{topic}"
        self.broadcast_to_network("SYNCTOPIC", args, exclude_server=exclude_server)

    def sync_channel_mode(self, chan_name, setter_nick, mode_str, params=None, exclude_server=None):
        """Notify the network of a channel mode change.

        Args:
            chan_name: Channel name.
            setter_nick: Nick that set the mode.
            mode_str: Mode string (e.g. '+m', '-n+k').
            params: List of mode params (e.g. ['key'] for +k).
            exclude_server: Server to exclude.
        """
        params_str = (" " + " ".join(params)) if params else ""
        args = f"{chan_name} {setter_nick} {mode_str}{params_str}"
        self.broadcast_to_network("SYNCMODE", args, exclude_server=exclude_server)

    def sync_channel_state(self, chan_name, exclude_server=None):
        """Helper to sync current state of a local channel to the network.

        Args:
            chan_name: Channel name.
            exclude_server: Server to exclude.
        """
        ch = self.local_server.channel_manager.get_channel(chan_name)
        if not ch:
            return

        modes_str = "+" + "".join(sorted(ch.modes)) if ch.modes else "+"
        members = {}
        for m_nick_lower, m_info in ch.members.items():
            # Only sync display nicks and their modes
            m_display_nick = m_info.get("nick", m_nick_lower)
            m_modes = list(m_info.get("modes", set()))
            members[m_display_nick] = m_modes

        self.sync_channel(chan_name, modes_str, json.dumps(members), exclude_server=exclude_server)

    def _send_full_sync(self, link):
        """Send complete local state to a newly linked peer.

        Args:
            link: The ServerLink to sync to.
        """
        server = self.local_server

        # Sync all local users
        for addr, info in list(server.clients.items()):
            nick = info.get("name")
            if not nick:
                continue
            host = f"{addr[0]}:{addr[1]}" if isinstance(addr, tuple) else str(addr)
            modes = info.get("modes", "+")
            connect_time = str(int(info.get("last_seen", time.time())))

            # Find user's channels
            channels = []
            for ch in server.channel_manager.list_channels():
                if nick.lower() in ch.members:
                    channels.append(ch.name)

            chan_str = ",".join(channels) if channels else "*"
            link.send_message("SYNCUSER", nick, host, modes, connect_time, chan_str)

        # Sync all local channels
        for ch in server.channel_manager.list_channels():
            modes_str = "+" + "".join(sorted(ch.modes)) if ch.modes else "+"
            members = {}
            for nick_lower, member_info in ch.members.items():
                display_nick = member_info.get("nick", nick_lower)
                member_modes = list(member_info.get("modes", set()))
                members[display_nick] = member_modes
            members_json = json.dumps(members)
            link.send_message("SYNCCHAN", ch.name, modes_str, members_json)

            # Sync topic if set
            if ch.topic:
                link.send_message("SYNCTOPIC", ch.name, ":" + ch.topic)

    def _dispatch_s2s_message(self, link, command, rest):
        """Route an incoming S2S command to the appropriate handler.

        Args:
            link: The ServerLink that received the message.
            command: The S2S command string.
            rest: The remaining arguments as a string.
        """
        command = command.upper()

        # Handle SLINKACK responses (for outbound link authentication)
        if command == "SLINKACK":
            link._handle_slinkack_response(f"SLINKACK {rest}")
            return

        handlers = {
            "SYNCUSER": self._handle_syncuser,
            "SYNPART":  self._handle_synpart,
            "SYNCNICK": self._handle_syncnick,
            "SYNCCHAN": self._handle_syncchan,
            "SYNCTOPIC": self._handle_synctopic,
            "SYNCMSG":  self._handle_syncmsg,
            "SYNCNOTICE": self._handle_syncnotice,
            "SYNCMODE": self._handle_syncmode,
            "SYNCLINE": self._handle_syncline,
            "DESYNC":   self._handle_desync,
            "SQUIT":    self._handle_squit,
            "ERROR":    self._handle_error,
        }
        # FXP bridge commands
        bridge = getattr(self, '_fxp_bridge', None)
        if bridge:
            handlers.update({
                "SYNCFILE":      bridge.handle_syncfile,
                "RSYNCFILE":     bridge.handle_rsyncfile,
                "SYNCFILE_ACK":  bridge.handle_syncfile_ack,
                "SYNCINVENTORY": bridge.handle_syncinventory,
                "SYNCRENAME":    bridge.handle_syncrename,
            })
        handler = handlers.get(command)
        if handler:
            try:
                handler(link, rest)
            except Exception as e:
                self._log(f"Error handling {command}: {e}")
        else:
            self._log(f"Unknown S2S command from {link.remote_server_id}: {command}")

    def _handle_syncuser(self, link, rest):
        """Handle SYNCUSER: add/update a remote user in tracking.

        Format: SYNCUSER <nick> <host> <modes> <connect_time> [channels]
        """
        parts = rest.split()
        if len(parts) < 4:
            return

        nick = parts[0]
        host = parts[1]
        modes = parts[2]
        try:
            connect_time = int(parts[3])
        except ValueError:
            connect_time = int(time.time())
        channels_str = parts[4] if len(parts) > 4 else "*"

        nick_lower = nick.lower()
        try:
            from .collision_resolver import detect_collision, resolve_collision
        except ImportError:
            from collision_resolver import detect_collision, resolve_collision

        # Check for collision with local users
        local_collision = False
        for addr, info in list(self.local_server.clients.items()):
            if info.get("name", "").lower() == nick_lower:
                local_collision = True
                break

        if local_collision:
            winner_server, new_nick = resolve_collision(
                nick, self.server_id, link.remote_server_id,
                local_connect_time=int(time.time()),
                remote_connect_time=connect_time
            )
            if winner_server != link.remote_server_id:
                # Remote user loses - tell them to rename
                link.send_message("NICK_COLLISION", nick, new_nick, self.server_id)
                nick = new_nick
                nick_lower = nick.lower()
            else:
                # Local user loses - rename locally
                self._rename_local_user(nick, resolve_collision(
                    nick, link.remote_server_id, self.server_id,
                    local_connect_time=connect_time,
                    remote_connect_time=int(time.time())
                )[1])

        with link._state_lock:
            existing = link.remote_users.get(nick_lower)
            new_channels = channels_str.split(",") if channels_str != "*" else []

            if existing and channels_str != "*":
                # Append only new channels
                current_chans = existing.get("channels", [])
                for c in new_channels:
                    if c not in current_chans:
                        current_chans.append(c)
                new_channels = current_chans

            link.remote_users[nick_lower] = {
                "nick": nick,
                "server_id": link.remote_server_id,
                "host": host,
                "modes": modes,
                "connect_time": connect_time,
                "channels": new_channels
            }

        # Update local channels if specified
        if channels_str != "*":
            from csc_server_core.irc import format_irc_message
            prefix = f"{nick}!{nick}@{link.remote_server_id}"

            for chan_name in channels_str.split(","):
                ch = self.local_server.channel_manager.get_channel(chan_name)
                if ch:
                    if nick_lower not in ch.members:
                        ch.members[nick_lower] = {
                            "nick": nick,
                            "addr": None,  # remote user
                            "modes": set(),
                            "remote_server": link.remote_server_id
                        }
                        # Broadcast JOIN to local clients
                        join_msg = format_irc_message(prefix, "JOIN", [chan_name]) + "\r\n"
                        self.local_server.broadcast_to_channel(chan_name, join_msg)

        self._log(f"Synced remote user {nick} from {link.remote_server_id}")

        # Re-broadcast to other peers (but not back to source)
        self.broadcast_to_network(
            "SYNCUSER", rest, exclude_server=link.remote_server_id
        )

    def _handle_synpart(self, link, rest):
        """Handle SYNPART: remote user leaves a channel.

        Format: SYNPART <nick> <channel> [:reason]
        """
        parts = rest.split(" ", 2)
        if len(parts) < 2:
            return

        nick = parts[0]
        channel_name = parts[1]
        reason = parts[2][1:] if len(parts) > 2 and parts[2].startswith(":") else ""

        nick_lower = nick.lower()
        chan_lower = channel_name.lower()

        # Update remote tracking
        with link._state_lock:
            if nick_lower in link.remote_users:
                chans = link.remote_users[nick_lower].get("channels", [])
                if channel_name in chans:
                    chans.remove(channel_name)
                    link.remote_users[nick_lower]["channels"] = chans

        # Remove from local channel if present
        ch = self.local_server.channel_manager.get_channel(channel_name)
        if ch and nick_lower in ch.members:
            if ch.members[nick_lower].get("remote_server") == link.remote_server_id:
                del ch.members[nick_lower]
                # Broadcast PART to local clients
                from csc_server_core.irc import format_irc_message
                prefix = f"{nick}!{nick}@{link.remote_server_id}"
                part_msg = format_irc_message(prefix, "PART", [channel_name], reason) + "\r\n"
                self.local_server.broadcast_to_channel(channel_name, part_msg)

        self._log(f"Synced remote PART: {nick} from {channel_name}")

        # Re-broadcast
        self.broadcast_to_network("SYNPART", rest, exclude_server=link.remote_server_id)

    def _handle_syncnick(self, link, rest):
        """Handle SYNCNICK: remote user changes nickname.

        Format: SYNCNICK <old_nick> <new_nick>
        """
        parts = rest.split()
        if len(parts) < 2:
            return

        old_nick = parts[0]
        new_nick = parts[1]
        old_lower = old_nick.lower()
        new_lower = new_nick.lower()

        # Update remote tracking
        with link._state_lock:
            if old_lower in link.remote_users:
                info = link.remote_users.pop(old_lower)
                info["nick"] = new_nick
                link.remote_users[new_lower] = info

        # Update local channels
        for ch in self.local_server.channel_manager.list_channels():
            if old_lower in ch.members:
                member = ch.members[old_lower]
                if member.get("remote_server") == link.remote_server_id:
                    del ch.members[old_lower]
                    member["nick"] = new_nick
                    ch.members[new_lower] = member

        # Broadcast NICK to local clients
        prefix = f"{old_nick}!{old_nick}@{link.remote_server_id}"
        nick_msg = f":{prefix} NICK {new_nick}\r\n"
        self.local_server.broadcast(nick_msg)

        self._log(f"Synced remote NICK: {old_nick} -> {new_nick}")

        # Re-broadcast
        self.broadcast_to_network("SYNCNICK", rest, exclude_server=link.remote_server_id)

    def _handle_syncchan(self, link, rest):
        """Handle SYNCCHAN: merge remote channel state.

        Format: SYNCCHAN <channel> <modes> <members_json>
        """
        parts = rest.split(" ", 2)
        if len(parts) < 3:
            return

        channel_name = parts[0]
        modes_str = parts[1]
        try:
            members = json.loads(parts[2])
        except (json.JSONDecodeError, IndexError):
            members = {}

        chan_lower = channel_name.lower()
        with link._state_lock:
            link.remote_channels[chan_lower] = {
                "name": channel_name,
                "server_id": link.remote_server_id,
                "modes": modes_str,
                "members": members
            }

        # Ensure local channel exists for shared channels
        server = self.local_server
        ch = server.channel_manager.get_channel(channel_name)
        if ch:
            # Merge remote members as virtual entries
            for nick, nick_modes in members.items():
                nick_lower = nick.lower()
                if nick_lower not in ch.members:
                    ch.members[nick_lower] = {
                        "nick": nick,
                        "addr": None,  # remote user, no local addr
                        "modes": set(nick_modes) if nick_modes else set(),
                        "remote_server": link.remote_server_id
                    }

        self._log(f"Synced remote channel {channel_name} from {link.remote_server_id}")

        # Re-broadcast
        self.broadcast_to_network(
            "SYNCCHAN", rest, exclude_server=link.remote_server_id
        )

    def _handle_synctopic(self, link, rest):
        """Handle SYNCTOPIC: remote channel topic update.

        Format: SYNCTOPIC <channel> :<topic>
        """
        parts = rest.split(" ", 1)
        if len(parts) < 2:
            return
        channel_name = parts[0]
        topic = parts[1]
        if topic.startswith(":"):
            topic = topic[1:]

        chan_lower = channel_name.lower()
        with link._state_lock:
            if chan_lower in link.remote_channels:
                link.remote_channels[chan_lower]["topic"] = topic

        # Update local channel if exists
        ch = self.local_server.channel_manager.get_channel(channel_name)
        if ch:
            ch.topic = topic
            # Broadcast TOPIC to local clients
            from csc_server_core.irc import format_irc_message
            prefix = f"{link.remote_server_id}!{link.remote_server_id}@{link.remote_server_id}"
            topic_msg = format_irc_message(prefix, "TOPIC", [channel_name], topic) + "\r\n"
            self.local_server.broadcast_to_channel(channel_name, topic_msg)

        self._log(f"Synced remote TOPIC: {channel_name} -> {topic}")

        # Re-broadcast
        self.broadcast_to_network("SYNCTOPIC", rest, exclude_server=link.remote_server_id)

    def _handle_syncmsg(self, link, rest):
        """Handle SYNCMSG: deliver a message from the network locally.

        Format: SYNCMSG <source_nick> <target> :<text>
        """
        parts = rest.split(" ", 2)
        if len(parts) < 3:
            return

        source_nick = parts[0]
        target = parts[1]
        text = parts[2]
        if text.startswith(":"):
            text = text[1:]

        server = self.local_server
        from csc_server_core.irc import format_irc_message, SERVER_NAME

        # Build IRC PRIVMSG
        source_host = f"{source_nick}!{source_nick}@{link.remote_server_id}"
        irc_msg = format_irc_message(source_host, "PRIVMSG", [target], text) + "\r\n"

        if target.startswith("#") or target.startswith("&"):
            # Channel message - broadcast to local members
            server.broadcast_to_channel(target, irc_msg)
            # Log to chat buffer
            server.chat_buffer.append(target, source_nick, "PRIVMSG", text)
        else:
            # PM to local user
            server.send_to_nick(target, irc_msg)
            # Log to chat buffer
            pm_key = "".join(sorted([source_nick.lower(), target.lower()]))
            server.chat_buffer.append(pm_key, source_nick, "PRIVMSG", text)

        # NOTE: Do NOT re-broadcast SYNCMSG to other peers
        # User messages route only to their destination, not flooded across the network
        # State messages (SYNCUSER, SYNPART, etc.) are re-broadcast, but not SYNCMSG

    def _handle_syncnotice(self, link, rest):
        """Handle SYNCNOTICE: deliver a NOTICE from the network locally.

        Format: SYNCNOTICE <source_nick> <target> :<text>
        """
        parts = rest.split(" ", 2)
        if len(parts) < 3:
            return

        source_nick = parts[0]
        target = parts[1]
        text = parts[2]
        if text.startswith(":"):
            text = text[1:]

        server = self.local_server
        from csc_server_core.irc import format_irc_message
        source_host = f"{source_nick}!{source_nick}@{link.remote_server_id}"
        irc_msg = format_irc_message(source_host, "NOTICE", [target], text) + "\r\n"

        if target.startswith("#") or target.startswith("&"):
            server.broadcast_to_channel(target, irc_msg)
        else:
            server.send_to_nick(target, irc_msg)

    def _handle_syncmode(self, link, rest):
        """Handle SYNCMODE: apply a remote channel mode change.

        Format: SYNCMODE <channel> <setter_nick> <modestr> [params...]
        """
        parts = rest.split(" ", 3)
        if len(parts) < 3:
            return

        channel_name = parts[0]
        setter_nick = parts[1]
        mode_str = parts[2]
        params_str = parts[3] if len(parts) > 3 else ""

        server = self.local_server
        ch = server.channel_manager.get_channel(channel_name)
        if ch:
            # Apply mode changes locally
            adding = True
            for c in mode_str:
                if c == "+":
                    adding = True
                elif c == "-":
                    adding = False
                else:
                    if adding:
                        ch.modes.add(c)
                    else:
                        ch.modes.discard(c)

            # Broadcast MODE to local clients
            from csc_server_core.irc import format_irc_message
            prefix = f"{setter_nick}!{setter_nick}@{link.remote_server_id}"
            params_part = (" " + params_str) if params_str else ""
            mode_msg = f":{prefix} MODE {channel_name} {mode_str}{params_part}\r\n"
            server.broadcast_to_channel(channel_name, mode_msg)

        self._log(f"Synced remote MODE: {channel_name} {mode_str} from {link.remote_server_id}")

        # Re-broadcast
        self.broadcast_to_network("SYNCMODE", rest, exclude_server=link.remote_server_id)

    def _handle_syncline(self, link, rest):
        """Handle SYNCLINE: deliver a raw IRC line to a local user.

        Format: SYNCLINE <target_nick> :<raw_line>
        """
        parts = rest.split(" ", 1)
        if len(parts) < 2:
            return
        target_nick = parts[0]
        line = parts[1]
        if line.startswith(":"):
            line = line[1:]

        # Deliver locally
        self.local_server.send_to_nick(target_nick, line)

        # Re-broadcast to other peers
        self.broadcast_to_network(
            "SYNCLINE", rest, exclude_server=link.remote_server_id
        )

    def _handle_desync(self, link, rest):
        """Handle DESYNC: remove a nick or channel from remote tracking.

        Format: DESYNC <nick|channel> [:reason]
        """
        parts = rest.split(" ", 1)
        name = parts[0]
        reason = parts[1][1:] if len(parts) > 1 and parts[1].startswith(":") else ""

        name_lower = name.lower()

        if name.startswith("#") or name.startswith("&"):
            # Channel desync
            with link._state_lock:
                link.remote_channels.pop(name_lower, None)
            # Remove remote members from local channel
            ch = self.local_server.channel_manager.get_channel(name)
            if ch:
                for nick_lower in list(ch.members.keys()):
                    member = ch.members[nick_lower]
                    if member.get("remote_server") == link.remote_server_id:
                        del ch.members[nick_lower]
        else:
            # User desync (quit)
            with link._state_lock:
                link.remote_users.pop(name_lower, None)

            # Remove from any local channel member lists
            for ch in self.local_server.channel_manager.list_channels():
                if name_lower in ch.members:
                    member = ch.members[name_lower]
                    if member.get("remote_server"):
                        del ch.members[name_lower]

            # Broadcast QUIT to local clients
            from csc_server_core.irc import SERVER_NAME
            quit_msg = f":{name}!{name}@{link.remote_server_id} QUIT :{reason or 'Remote server disconnect'}\r\n"
            self.local_server.broadcast(quit_msg)

        self._log(f"Desynced {name} from {link.remote_server_id}")

        # Re-broadcast
        self.broadcast_to_network(
            "DESYNC", rest, exclude_server=link.remote_server_id
        )

    def _handle_squit(self, link, rest):
        """Handle SQUIT: a server is disconnecting.

        Format: SQUIT <server_id> :<reason>
        """
        parts = rest.split(" ", 1)
        server_id = parts[0]
        reason = parts[1][1:] if len(parts) > 1 and parts[1].startswith(":") else ""

        self._log(f"Server {server_id} quit: {reason}")
        self._remove_server_state(server_id)

        # Re-broadcast
        self.broadcast_to_network(
            "SQUIT", rest, exclude_server=link.remote_server_id
        )

    def _handle_error(self, link, rest):
        """Handle ERROR message from a peer."""
        self._log(f"Error from {link.remote_server_id}: {rest}")

    def _handle_link_lost(self, link):
        """Called when a link's reader thread detects a disconnect."""
        server_id = link.remote_server_id
        if not server_id:
            return

        self._log(f"Link lost to {server_id}")
        with self._lock:
            self._links.pop(server_id, None)

        self._remove_server_state(server_id)

        # Notify remaining peers
        reason = f"Connection lost to {server_id}"
        self.broadcast_to_network("SQUIT", f"{server_id} :{reason}")

    def _remove_server_state(self, server_id):
        """Remove all remote state belonging to a disconnected server."""
        to_remove = []
        to_remove_ch = []

        with self._lock:
            # Remove remote users and channels from that server across all links
            for link in list(self._links.values()):
                with link._state_lock:
                    # Collect users to remove
                    nicks_to_remove = [
                        nick for nick, info in link.remote_users.items()
                        if info.get("server_id") == server_id
                    ]
                    for nick in nicks_to_remove:
                        del link.remote_users[nick]
                        to_remove.append(nick)

                    # Collect channels to remove
                    chans_to_remove = [
                        ch for ch, info in link.remote_channels.items()
                        if info.get("server_id") == server_id
                    ]
                    for ch in chans_to_remove:
                        del link.remote_channels[ch]
                        to_remove_ch.append(ch)

        # Clean up virtual members in local channels
        for ch in self.local_server.channel_manager.list_channels():
            for nick_lower in list(ch.members.keys()):
                member = ch.members[nick_lower]
                if member.get("remote_server") == server_id:
                    del ch.members[nick_lower]

        # Broadcast QUITs for all users from that server
        from csc_server_core.irc import SERVER_NAME
        for nick in to_remove:
            quit_msg = f":{nick}!{nick}@{server_id} QUIT :Server {server_id} disconnected\r\n"
            self.local_server.broadcast(quit_msg)

    def _rename_local_user(self, old_nick, new_nick):
        """Rename a local user due to nick collision.

        Args:
            old_nick: Current nickname.
            new_nick: New nickname to assign.
        """
        server = self.local_server
        old_lower = old_nick.lower()
        new_lower = new_nick.lower()

        for addr, info in list(server.clients.items()):
            if info.get("name", "").lower() == old_lower:
                # Notify the user
                from csc_server_core.irc import SERVER_NAME
                collision_msg = (
                    f":{SERVER_NAME} NOTICE {old_nick} "
                    f":Nick collision - you have been renamed to {new_nick}\r\n"
                )
                server.sock_send(collision_msg.encode(), addr)

                # Send NICK change
                nick_msg = f":{old_nick}!{old_nick}@{SERVER_NAME} NICK {new_nick}\r\n"
                server.broadcast(nick_msg)

                # Update state
                info["name"] = new_nick
                server.clients[addr] = info

                # Update channel membership
                for ch in server.channel_manager.list_channels():
                    if old_lower in ch.members:
                        member_info = ch.members.pop(old_lower)
                        member_info["nick"] = new_nick
                        ch.members[new_lower] = member_info
                break

    def shutdown(self):
        """Shut down all S2S connections and the listener."""
        self._running = False

        # Notify peers
        reason = "Server shutting down"
        self.broadcast_to_network("SQUIT", f"{self.server_id} :{reason}")

        # Close all links
        with self._lock:
            for link in list(self._links.values()):
                link.close()
            self._links.clear()

        # Close listener
        if self._listener_sock:
            try:
                self._listener_sock.close()
            except Exception:
                if hasattr(self, 'log'):
                    self.log('Ignored exception', level='DEBUG')
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=2)

        self._log("S2S network shut down")

    def _get_local_server_id(self):
        """Return the local server's unique ID."""
        return getattr(self.local_server, 'server_id', self.server_id)

    def _log(self, message):
        """Log via the local server's logger."""
        if hasattr(self.local_server, 'log'):
            self.local_server.log(f"[S2S] {message}")
