import json
import os
import sys
import signal
import socket
import threading
import time
import traceback
import subprocess
from pathlib import Path
from csc_service_base import Service
from .server_message_handler import MessageHandler
from .server_file_handler import FileHandler
from csc_service.shared.channel import ChannelManager
from csc_service.shared.chat_buffer import ChatBuffer
from csc_service.shared.irc import SERVER_NAME
from csc_service.shared.crypto import is_encrypted, decrypt, encrypt
try:
    from csc_server_core.server_network import ServerNetwork
except ImportError:
    from .server_s2s import ServerNetwork


class IrcMessageQueue:
    """Global in-memory FIFO queue for IRC messages."""

    def __init__(self):
        self.queue = []  # List of (timestamp, addr, msg, nick, channel) tuples
        self.lock = threading.Lock()

    def enqueue(self, addr, msg, nick, channel=None):
        """Add a message to the queue."""
        with self.lock:
            self.queue.append((time.time(), addr, msg, nick, channel))

    def dequeue(self):
        """Remove and return the first message from the queue."""
        with self.lock:
            if self.queue:
                return self.queue.pop(0)
            return None

    def size(self):
        """Return the current queue size."""
        with self.lock:
            return len(self.queue)


class Server(Service):
    """
    The main UDP server for handling clients, commands, and file operations.

    Features:
      • Persistent client registry stored using Data (clients.json)
      • Multi-address tracking per client name (support for clones)
      • Command and message routing to modular handlers
      • Graceful shutdown with data persistence
    """

    def __init__(self, host="0.0.0.0", port=9525, timeout=120):
        """
        Initializes the Server.

        - What it does: Sets up the server's name, address, timeout, and all
          its component modules (FileHandler, MessageHandler).
          It binds the socket, starts the network listener, and loads
          persistent data.
        - Arguments:
            - `host` (str): Host/IP to bind to.
            - `port` (int): UDP port number.
            - `timeout` (int): Inactivity timeout (seconds) for clients.
        - What calls it: The `if __name__ == "__main__":` block.
        - What it calls: `super().__init__()`, `self.init_data()`, `FileHandler()`,
          `MessageHandler()`, `self.sock.bind()`,
          `self.start_listener()`, `self.log()`, `self.connect()`, `self.get_data()`.
        """
        super().__init__(self)
        self.name = "Server"
        # Use project root for consistent logging
        self.log_file = str(Path(__file__).resolve().parent / f"{self.name}.log")
        #self.log("TEST LOG ENTRY")
        self.init_data()
        self.server_addr = (host, port)
        self.timeout = timeout
        self.clients_lock = threading.Lock()

        self._running = True

        # Initialize message queue for federated execution
        self.message_queue = IrcMessageQueue()
        self.queue_processor_running = False

        # File and message handling components
        self.file_handler = FileHandler(self)
        self.message_handler = MessageHandler(self, self.file_handler)

        # Bind and start listening
        self.log_file = str(Path(__file__).resolve().parent / f"{self.name}.log")
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(self.server_addr)
        self.start_listener()  # ensure we can receive data immediately
        self.log(f"[{self.name}] Bound to {self.server_addr} and listening.")

        # Disconnected clients history for WHOWAS (last 100)
        self.disconnected_clients = {}  # {nick: {user, realname, host, quit_time, quit_reason}}
        self.max_disconnected_history = 100

        # IRC channel management
        self.channel_manager = ChannelManager()
        self.server_name = SERVER_NAME

        # Chat buffer for message logging and replay
        self.chat_buffer = ChatBuffer()

        self.encryption_keys = {} # addr -> aes_key

        self.clients_lock = threading.Lock()

        # NickServ: identified clients (session-only, not persisted)
        self.nickserv_identified = {}  # addr -> identified_nick

        # Start cleanup loop
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()

        # Start BotServ log monitor
        self.botserv_thread = threading.Thread(target=self._botserv_log_monitor_loop, daemon=True)
        self.botserv_thread.start()

        # Start Syslog monitor
        self.syslog_thread = threading.Thread(target=self._syslog_monitor_loop, daemon=True)
        self.syslog_thread.start()

        # Set CSC_HOME for S2S config loading (needed for standalone server)
        if not os.environ.get('CSC_HOME'):
            # Find project root (look for csc-service.json)
            csc_root = Path(__file__).resolve().parent
            while csc_root.parent != csc_root:  # until root directory
                if (csc_root / "csc-service.json").exists():
                    break
                csc_root = csc_root.parent
            os.environ['CSC_HOME'] = str(csc_root)
            self.log(f"[S2S] Set CSC_HOME={csc_root}")

        # Restore server state from disk
        self.restore_all(self)

        # Record startup time for S2S federation
        self.startup_time = time.time()

        # Run one cleanup pass immediately to prune any ghosts from previous runs
        self._run_cleanup_once()

        # Check S2S certificate before starting federation
        from csc_platform import Platform
        s2s_ok, s2s_reason = Platform.check_s2s_cert()
        if not s2s_ok:
            self.log(f"[S2S] Certificate check failed: {s2s_reason} — S2S listener will start without TLS")
            self.log(f"[S2S] To obtain a certificate, run:")
            self.log(f"[S2S]   csc-ctl enroll https://facingaddictionwithhope.com/csc/pki/")
            self.log(f"[S2S] If not pre-approved, an oper must first run: PKI APPROVE <shortname>")

        # Initialize S2S federation network
        self.s2s_network = ServerNetwork(self)
        self.s2s_network.start_listener()

        # Start S2S auto-linking thread (maintains links to configured peers)
        self._start_s2s_autolink()

        # Start queue processor thread for federated message execution
        self._start_queue_processor()

    @property
    def client_registry(self):
        """Dynamic property that reads client registry from disk."""
        return self.load_users().get("users", {})

    @property
    def oper_credentials(self):
        """Dynamic property: returns olines dict (v2) for backward compat callers."""
        return self.load_opers().get("olines", {})

    @property
    def opers(self):
        """Set of lowercase nicks currently holding any oper status."""
        active = self.load_opers().get("active_opers", [])
        result = set()
        for entry in active:
            if isinstance(entry, dict):
                result.add(entry.get("nick", "").lower())
            else:
                result.add(str(entry).lower())
        return result

    @property
    def active_opers_info(self):
        """Dynamic property: returns {nick_lower: {nick, oper_name, flags, class}}."""
        return self.get_active_opers_info()

    @property
    def protect_local_opers(self):
        """Whether remote opers without O flag can KILL local opers."""
        return self.load_opers().get("protect_local_opers", True)

    def _oper_has_flag(self, nick, flag):
        """Return True if nick is an active oper with the given flag."""
        return flag in self.get_oper_flags(nick.lower())

    def oper_has_flag(self, nick, flag):
        """Public alias for _oper_has_flag (used by message handler)."""
        return self._oper_has_flag(nick, flag)

    def get_olines(self):
        """Return the olines configuration dict."""
        return self.get_olines()

    def is_local_oper(self, nick):
        """Local oper: any oper flag (o, O, a, A)."""
        return bool(self.get_oper_flags(nick.lower()))

    def is_global_oper(self, nick):
        """Global oper: O flag."""
        return self._oper_has_flag(nick, "O")

    def is_server_admin(self, nick):
        """Server admin: a or A flag."""
        return self._oper_has_flag(nick, "a") or self._oper_has_flag(nick, "A")

    def is_net_admin(self, nick):
        """Network admin: A flag."""
        return self._oper_has_flag(nick, "A")

    @property
    def wakewords(self):
        """Dynamic property that reads wakewords from disk on every access."""
        path = os.path.join(self.base_path, "wakewords.json")
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return [w.lower() for w in data.get("words", [])]
        except (OSError, json.JSONDecodeError, KeyError):
            return []

    def sync_from_disk(self):
        """Reload state from disk ONLY if files have changed."""
        changed = False
        for key in self.FILES:
            if self._has_changed(key):
                changed = True
                break
        
        if changed:
            with self.clients_lock:
                self.log("[STORAGE] Disk change detected, syncing state...")
                self.restore_all(self)

    # ======================================================================
    # Network Loop
    # ======================================================================

    def _cleanup_loop(self):
        """Periodic background loop to remove timed-out clients."""
        self.log("[CLEANUP] Periodic cleanup loop started.")
        while self._running:
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1)
            if self._running:
                self._run_cleanup_once()

    def _start_s2s_autolink(self):
        """Initialize and start the S2S auto-linking thread."""
        # Load s2s_peers from csc-service.json
        try:
            csc_root = Path(os.environ.get('CSC_HOME', '')) or Path(__file__).resolve().parents[6]
            cfg_path = csc_root / "csc-service.json"
            if not cfg_path.exists():
                return
            import json as _json
            config = _json.loads(cfg_path.read_text())
            s2s_peers = config.get("s2s_peers", [])
            if not s2s_peers:
                return  # No peers configured
        except Exception as e:
            self.log(f"[S2S] Could not load s2s_peers from config: {e}")
            return

        autolink_thread = threading.Thread(
            target=self._s2s_autolink_loop,
            args=(s2s_peers,),
            daemon=True
        )
        autolink_thread.start()
        self.log(f"[S2S] Started auto-link thread ({len(s2s_peers)} peer(s))")

    def _s2s_autolink_loop(self, peers):
        """Background thread: maintain S2S links to configured peers."""
        time.sleep(10)  # let server and S2S listener fully start
        csc_root = Path(__file__).resolve().parents[4]
        disconnect_file = csc_root / "DISCONNECT"

        while self._running:
            try:
                # Check for DISCONNECT killswitch
                if disconnect_file.exists():
                    # DISCONNECT file present — drop all links, wait
                    for link in list(self.s2s_network._links.values()):
                        link.close()
                    self.s2s_network._links.clear()
                    self.log("[S2S] DISCONNECT file detected — all links dropped")
                    while disconnect_file.exists() and self._running:
                        time.sleep(5)
                    if self._running:
                        self.log("[S2S] DISCONNECT file removed — resuming auto-link")
                    continue

                # Check each configured peer
                for peer in peers:
                    if not self._running:
                        break
                    host = peer.get("host", "")
                    port = peer.get("port", 9520)
                    if not host:
                        continue

                    # Check if already linked to this peer
                    already_linked = False
                    for sid, link in self.s2s_network._links.items():
                        if link._connected and link.remote_host == host:
                            already_linked = True
                            break

                    if not already_linked:
                        self.log(f"[S2S] Auto-linking to {host}:{port}...")
                        self.s2s_network.link_to(host, port)

            except Exception as e:
                self.log(f"[S2S] Auto-link error: {e}")

            # Wait before next attempt
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1)

    def _botserv_log_monitor_loop(self):
        """Background loop for BotServ log monitoring and echoing.

        Uses self._tail_log_file() (from Data) instead of direct disk I/O.
        """
        self.log("[BOTSERV] Log monitor loop started.")
        # Key: (channel, botnick, log_file) -> byte offset
        file_state = {}

        while self._running:
            try:
                botserv_data = self.load_botserv()
                bots = botserv_data.get("bots", {})

                for key, bot in bots.items():
                    if not bot.get("logs_enabled") or not bot.get("logs"):
                        continue

                    chan_name = bot["channel"]
                    bot_nick = bot["botnick"]

                    for log_file in bot["logs"]:
                        state_key = (chan_name, bot_nick, log_file)
                        last_offset = file_state.get(state_key)

                        new_lines, new_offset = self._tail_log_file(
                            log_file, last_offset or 0
                        )

                        if last_offset is None:
                            # First time seeing this file, just record offset
                            file_state[state_key] = new_offset
                            continue

                        file_state[state_key] = new_offset

                        # Echo new lines to channel
                        if new_lines:
                            prefix = f"{bot_nick}!bot@{SERVER_NAME}"
                            filename = os.path.basename(log_file)
                            for line in new_lines:
                                line = line.strip()
                                if not line:
                                    continue
                                text = f"[{filename}] {line}"
                                msg = f":{prefix} PRIVMSG {chan_name} :{text}\r\n"
                                self.broadcast_to_channel(chan_name, msg)

            except Exception as e:
                self.log(f"[BOTSERV ERROR] Log monitor error: {e}")

            time.sleep(2)

    def _syslog_monitor_loop(self):
        """Background loop for monitoring syslog and echoing new lines to #syslog."""
        self.log("[SYSLOG] Syslog monitor loop started.")
        syslog_script = "/opt/csc/tools/syslog_monitor.py"
        
        # Ensure #syslog channel exists
        self.channel_manager.ensure_channel("#syslog")

        while self._running:
            try:
                if os.path.exists(syslog_script):
                    # Execute the script to get new syslog lines
                    result = subprocess.run(
                        [sys.executable, syslog_script],
                        capture_output=True,
                        text=True,
                        check=False # Don't raise exception on non-zero exit
                    )

                    if result.returncode == 0:
                        new_lines = result.stdout.strip().split('\n')
                        if new_lines and new_lines[0]: # Check for empty output
                            prefix = f"syslog!bot@{SERVER_NAME}"
                            for line in new_lines:
                                text = line.strip()
                                if not text:
                                    continue
                                # Format: [syslog] log line
                                msg = f":{prefix} PRIVMSG #syslog :{text}\r\n"
                                self.broadcast_to_channel("#syslog", msg)
                    elif result.stderr:
                        self.log(f"[SYSLOG ERROR] Syslog monitor script error: {result.stderr.strip()}")

            except Exception as e:
                self.log(f"[SYSLOG ERROR] Syslog monitor loop error: {e}")

            for _ in range(60):  # poll every 60s but exit immediately on shutdown
                if not self._running:
                    break
                time.sleep(1)

    def _run_cleanup_once(self):
        """Runs the client cleanup logic once."""
        try:
            now = time.time()
            inactive = []
            with self.clients_lock:
                for addr, info in list(self.clients.items()):
                    last_seen = info.get("last_seen", 0)
                    if now - last_seen > self.timeout:
                        nick = info.get("name", "Unknown")
                        inactive.append((addr, nick))

            for addr, nick in inactive:
                self.log(f"[CLEANUP] Removing inactive client {nick} @ {addr}")
                if nick != "Unknown":
                    # Use the canonical disconnect path: broadcasts QUIT,
                    # cleans channels, registration, NickServ, WHOWAS history
                    self.message_handler._server_kill(nick, "Ping timeout")
                else:
                    # Unregistered client — just drop the runtime entries
                    self.clients.pop(addr, None)
                    self.message_handler.registration_state.pop(addr, None)

            # Second pass: prune persisted channel members with no live connection
            # This handles ghosts from tests, crashed clients, and any other source
            pruned = False
            active_nicks = {info.get("name", "").lower() for info in self.clients.values()}

            for ch in self.channel_manager.list_channels():
                # list_channels() returns Channel objects, not names
                if not ch:
                    continue

                for nick in list(ch.members.keys()):
                    # Skip if nick has a live connection
                    if nick.lower() in active_nicks:
                        continue

                    # Check last_seen from users.json (client_registry property reads disk)
                    user_record = self.client_registry.get(nick, {})
                    last_seen = user_record.get("last_seen", 0)

                    if now - last_seen > self.timeout:
                        self.log(f"[CLEANUP] Pruning stale channel member {nick} from {ch.name}")
                        ch.remove_member(nick)
                        pruned = True

            if pruned:
                self.save_channels_from_manager(self.channel_manager)

        except Exception as e:
            import traceback
            self.log(f"[CLEANUP] Error in cleanup logic: {e}")
            self.log(f"[CLEANUP] Traceback: {traceback.format_exc()}")

    def _thread_worker(self, data, addr):
        """
        Worker thread to process each incoming packet.
        """
        try:
            # Sync from disk if any files changed (Source of Truth)
            self.sync_from_disk()

            # Decrypt if encrypted
            if is_encrypted(data):
                key = self.encryption_keys.get(addr)
                if key:
                    try:
                        data = decrypt(key, data)
                    except Exception as e:
                        self.log(f"[CRYPTO] Decryption failed from {addr}: {e}")
                        return
                else:
                    self.log(f"[CRYPTO] Received encrypted data from {addr} but no key established.")
                    return

            self.message_handler.process(data, addr)
        except Exception as e:
            self.log(f"[ERROR] Exception in client thread {addr}: {e}")
            self.log(traceback.format_exc())

    def sock_send(self, data, addr):
        """
        Override sock_send to encrypt data if a key is established for addr.
        """
        key = self.encryption_keys.get(addr)
        if key:
            try:
                # Encrypt before sending
                if isinstance(data, str):
                    data = data.encode("utf-8")
                encrypted = encrypt(key, data)
                # Send directly via super().sock_send which handles chunking/sending
                super().sock_send(encrypted, addr)
                return
            except Exception as e:
                self.log(f"[CRYPTO] Encryption failed for {addr}: {e}")
                # Fallback? No, security risk. Drop.
                return

        # Plaintext fallback
        super().sock_send(data, addr)

    def _network_loop(self):
        """
        Background loop for processing all incoming network messages.

        - What it does: Pulls packets from the listener thread's queue and spawns
          worker threads to process them concurrently.
        - Arguments: None.
        - What calls it: `self.run()`.
        - What it calls: `self.log()`, `self.get_message()`, `threading.Thread()`,
          `thread.start()`, `time.sleep()`.
        """
        self.log("[NETWORK] Network loop started.")

        while self._running:
            try:
                message_data = self.get_message()
                if message_data:
                    data_bytes, addr = message_data
                    threading.Thread(
                        target=self._thread_worker, args=(data_bytes, addr), daemon=True
                    ).start()
                else:
                    time.sleep(0.01)

            except Exception as e:
                self.log(f"[NETWORK] Loop error: {e}")
        self.log("[NETWORK] Loop stopped.")

    # ======================================================================
    # Broadcasting
    # ======================================================================
    def broadcast(self, message, exclude=None):
        """
        Sends a message to all active clients.
        """
        self.sync_from_disk()
        now = time.time()
        for addr, info in list( self.clients.items() ):
            # auto-repair legacy float entries
            if isinstance( info, float ):
                self.log( f"[WARN] Converting legacy float entry for {addr}" )
                self.clients[addr] = {"name": "unknown", "last_seen": info}
                info = self.clients[addr]

            if not isinstance( info, dict ):
                self.log( f"[WARN] Skipping malformed client record for {addr}: {info}" )
                continue

                # In: server.py
                # Inside: def broadcast(self, message, exclude=None):

            if now - info.get( "last_seen", 0 ) > self.timeout:
                # Skip stale clients during broadcast; the cleanup loop
                # handles full disconnection (QUIT broadcast, channel/nick removal).
                continue

            if addr != exclude:
                self.sock_send( message, addr )

    def broadcast_to_channel(self, channel_name, message, exclude=None):
        """
        Send a message to all members of a channel.
        """
        self.sync_from_disk()
        channel = self.channel_manager.get_channel(channel_name)
        if not channel:
            return
        msg_bytes = message.encode("utf-8") if isinstance(message, str) else message
        for nick, info in list(channel.members.items()):
            addr = info.get("addr")
            if addr and addr != exclude:
                try:
                    self.sock_send(msg_bytes, addr)
                except Exception as e:
                    self.log(f"[BROADCAST_CHAN] Error sending to {nick}@{addr}: {e}")

    def send_to_nick(self, nick, message):
        """
        Send a message to a specific nick by looking up their address.
        Falls back to S2S routing if the nick is on a remote server.
        """
        self.sync_from_disk()
        msg_bytes = message.encode("utf-8") if isinstance(message, str) else message
        # Search active clients for the nick
        for addr, info in list(self.clients.items()):
            if info.get("name", "").lower() == nick.lower():
                try:
                    self.sock_send(msg_bytes, addr)
                except Exception as e:
                    self.log(f"[SEND_NICK] Error sending to {nick}@{addr}: {e}")
                return True

        # Check if nick is on a remote server via S2S
        if hasattr(self, 's2s_network'):
            _link, remote_info = self.s2s_network.get_user_from_network(nick)
            if remote_info:
                # Route via S2S
                line = message if isinstance(message, str) else message.decode("utf-8", errors="ignore")
                self.log(f"[S2S] Routing line to remote user {nick} on {remote_info['server_id']}")
                self.s2s_network.sync_line(nick, line)
                return True

        return False

    def send_wallops(self, message):
        """Send a WALLOPS message to all connected IRC operators."""
        wallops_msg = f":{SERVER_NAME} WALLOPS :{message}\r\n"
        for addr, info in list(self.clients.items()):
            nick = info.get("name")
            if nick and nick.lower() in self.opers:
                try:
                    self.sock_send(wallops_msg.encode(), addr)
                except Exception as e:
                    self.log(f"[WALLOPS] Error sending to {nick}@{addr}: {e}")

    def old_broadcast(self, message, exclude=None):
        """
        Sends a message to all active client addresses.

        - What it does: A previous implementation of the broadcast functionality.
        - Arguments:
            - `message` (str or bytes): The message to send.
            - `exclude` (tuple, optional): Address to skip (usually sender).
        - What calls it: None.
        - What it calls: `time.time()`, `list()`, `dict.items()`, `self.log()`,
          `dict.pop()`, `self.sock_send()`.
        """
        now = time.time()

        # Clean up inactive runtime clients
        inactive = [
            addr for addr, info in self.clients.items()
            if now - info.get("last_seen", 0) > self.timeout
        ]
        for addr in inactive:
            name = self.clients[addr].get("name", "Unknown")
            self.log(f"[CLEANUP] Removing inactive client {name} @ {addr}")
            self.clients.pop(addr, None)

        # Send to all known active addresses
        for addr, info in list(self.clients.items()):
            if addr == exclude:
                continue
            try:
                self.sock_send(message, addr)
            except Exception as e:
                self.log(f"[BROADCAST ERROR] {addr}: {e}")

    # ======================================================================
    # Persistent Data Sync
    # ======================================================================

    def sync_persistent_clients(self):
        """Writes the in-memory client registry back to persistent storage."""
        try:
            self.put_data("clients", self.message_handler.client_registry)
            self.log(
                f"[SYNC] Persisted {len(self.message_handler.client_registry)} clients to disk."
            )
        except Exception as e:
            self.log(f"[SYNC ERROR] Could not save clients: {e}")

    def _persist_session_data(self):
        """Persist current session data to separate JSON files atomically.

        Called immediately after every state change (nick, join, part, topic,
        mode, oper, away, kick, kill) to ensure zero data loss on crashes.
        Delegates to ServerData.persist_all().
        """
        try:
            with self.clients_lock:
                ok = self.persist_all(self)
            if ok:
                user_count = len([a for a in self.clients.values() if a.get("name")])
                chan_count = len(self.channel_manager.list_channels())
                self.log(f"[STORAGE] Persisted: {user_count} users, {chan_count} channels")
        except Exception as e:
            self.log(f"[STORAGE ERROR] Failed to persist session data: {e}")

    # ======================================================================
    # Run / Shutdown
    # ======================================================================

    def run(self):
        """
        Starts the server's main network loop and the terminal interface.

        If a TTY is attached, spawns a standard CSC Client instance for the
        terminal. Otherwise, runs in headless/daemon mode.
        """
        self.log(f"[STARTUP] Server listening on {self.server_addr}")
        network_thread = threading.Thread(target=self._network_loop, daemon=True)
        network_thread.start()

        # --daemon flag sets CSC_HEADLESS=true in main.py; also treat no-TTY as headless
        is_headless = os.environ.get("CSC_HEADLESS", "false").lower() == "true"
        is_interactive = sys.stdin.isatty() and not is_headless

        if is_interactive:
            self.log("[STARTUP] TTY detected, spawning csc-client interface.")
            try:
                from csc_service.client import Client
                client = Client()
                client.server_host = self.server_addr[0]
                client.server_port = self.server_addr[1]
                client.run()
            except ImportError:
                self.log("[ERROR] csc-client not available. Server running headlessly.")
                self._wait_for_shutdown()
            except Exception as e:
                self.log(f"[ERROR] csc-client failed: {e}. Server running headlessly.")
                self._wait_for_shutdown()
        else:
            self.log("[STARTUP] Daemon mode: server running headlessly.")
            self._wait_for_shutdown()

        # Graceful shutdown
        self._running = False

        # Shut down S2S federation network
        if hasattr(self, 's2s_network'):
            self.s2s_network.shutdown()

        network_thread.join(timeout=2)
        self._persist_session_data()
        self.save_history_from_server(self)
        self.sync_persistent_clients()
        self.close()
        self.log("[SHUTDOWN] Server closed sockets and persisted data.")
        print("Server has shut down.")

    def _wait_for_shutdown(self):
        """Block the main thread until SIGTERM/SIGINT is received or SHUTDOWN file exists.

        Also watches for DISCONNECT file: drops all S2S links immediately and refuses
        new ones until the file is removed. Both are hardcoded overrides — no config,
        no poll delay, just the file and the consequence.
        """
        stop_event = threading.Event()

        def _handle_signal(sig, frame):
            self.log(f"[SHUTDOWN] Signal {sig} received.")
            self._running = False
            stop_event.set()

        try:
            signal.signal(signal.SIGTERM, _handle_signal)
            signal.signal(signal.SIGINT, _handle_signal)
        except ValueError:
            pass  # signal only works in main thread

        from csc_platform import Platform
        shutdown_file = Platform.PROJECT_ROOT / "SHUTDOWN"
        disconnect_file = Platform.PROJECT_ROOT / "DISCONNECT"
        _disconnect_active = False

        while not stop_event.is_set():
            if shutdown_file.exists():
                self.log("[SHUTDOWN] Kill switch file detected. Terminating.")
                self._running = False
                break

            # DISCONNECT hardcoded override: drop all S2S links on appearance,
            # refuse new ones until the file is gone.
            if disconnect_file.exists() and not _disconnect_active:
                _disconnect_active = True
                if hasattr(self, 's2s_network'):
                    self.log("[DISCONNECT] Kill switch active — dropping all S2S links.")
                    with self.s2s_network._lock:
                        for link in list(self.s2s_network._links.values()):
                            try:
                                link.close()
                            except Exception:
                                pass
                        self.s2s_network._links.clear()
            elif not disconnect_file.exists() and _disconnect_active:
                _disconnect_active = False
                self.log("[DISCONNECT] Kill switch removed — S2S links may resume.")

            stop_event.wait(timeout=20.0)  # disk stat at most every 20s

    # ======================================================================
    # Queue Processor (Federated Message Execution)
    # ======================================================================

    def _start_queue_processor(self):
        """Initialize and start the queue processor thread."""
        self.queue_processor_running = True
        processor_thread = threading.Thread(
            target=self._queue_processor_loop,
            daemon=True
        )
        processor_thread.start()
        self.log("[QUEUE] Queue processor thread started")

    def _queue_processor_loop(self):
        """Background thread: process queued messages FIFO."""
        self.log("[QUEUE] Queue processor loop started")
        while self._running and self.queue_processor_running:
            try:
                # Pull from queue every 100ms
                msg_tuple = self.message_queue.dequeue()
                if msg_tuple:
                    timestamp, addr, msg_text, nick, channel = msg_tuple
                    # Route to queue execution handler
                    self._execute_queued_message(timestamp, addr, msg_text, nick, channel)
            except Exception as e:
                self.log(f"[QUEUE ERROR] Queue processor error: {e}")

            time.sleep(0.1)  # 100ms polling interval

    def _execute_queued_message(self, timestamp, addr, msg_text, nick, channel):
        """Execute a queued message: parse, check channel, execute service."""
        try:
            # Parse: <prefix> ai token <service> <method> [args...]
            prefix, service, method, args = self.message_handler._parse_prefixed_command(msg_text)
            if prefix is None:
                # Not a prefixed command, shouldn't happen (was filtered in enqueue)
                self.log(f"[QUEUE WARN] Dequeued non-prefixed message: {msg_text}")
                return

            # Check if this server has the target channel
            chan = self.channel_manager.get_channel(channel)
            if not chan:
                # This server doesn't have the channel, another linked server has it
                self.log(f"[QUEUE] Skipping: channel {channel} not on this server")
                return

            # Check if prefix (target server) matches this server
            # Supports wildcards: * (any), *pattern*, *start, end*
            if not self._matches_target_prefix(prefix):
                self.log(f"[QUEUE] Skipping: target prefix '{prefix}' doesn't match this server")
                return

            # Execute service method via Service.handle_command()
            self.log(f"[QUEUE] Executing: service={service}, method={method}, args={args}")

            # Call the service handler - returns result as string
            result = self.handle_command(service, method, args, nick, addr)

            # Route result back to channel with prefix
            output = f"{prefix}: {result}"
            self.broadcast_to_channel(channel, f":{SERVER_NAME} PRIVMSG {channel} :{output}\r\n")
            self.log(f"[QUEUE] Result sent to {channel}: {output}")

        except Exception as e:
            self.log(f"[QUEUE ERROR] Failed to execute queued message: {e}")

    def _matches_target_prefix(self, prefix):
        """Check if target prefix matches this server. Supports wildcards."""
        if prefix == "*":
            return True  # Match any server
        if "*" not in prefix:
            return prefix.lower() == SERVER_NAME.lower()  # Exact match
        # Wildcard matching: convert glob to simple pattern
        import fnmatch
        return fnmatch.fnmatch(SERVER_NAME.lower(), prefix.lower())

    # ======================================================================
    # Helpers for Data layer
    # ======================================================================

    def get_data(self, key):
        """
        Wrapper for persistent data retrieval.

        - What it does: A convenience method that wraps the `get_data` method
          from the `Data` class with a try-except block for error logging.
        - Arguments:
            - `key` (str): The key of the data to retrieve.
        - What calls it: `self.__init__()`.
        - What it calls: `super().get_data()`, `self.log()`.
        - Returns:
            - The requested data or `None` on error.
        """
        try:
            return super().get_data(key)
        except Exception as e:
            self.log(f"[DATA ERROR] get_data({key}): {e}")
            return None

    def put_data(self, key, value):
        """
        Wrapper for persistent data writes.

        - What it does: A convenience method that wraps the `put_data` method
          from the `Data` class with a try-except block for error logging.
        - Arguments:
            - `key` (str): The key for the data to be stored.
            - `value`: The value to be stored.
        - What calls it: `self.sync_persistent_clients()`, `_handle_setmotd()`.
        - What it calls: `super().put_data()`, `self.log()`.
        """
        try:
            super().put_data(key, value)
        except Exception as e:
            self.log(f"[DATA ERROR] put_data({key}): {e}")


if __name__ == "__main__":
    server = Server()
    server.run()
