import sys
import threading
import time
import traceback
from csc_service.server.service import Service
from csc_service.server.server_message_handler import MessageHandler
from csc_service.server.server_file_handler import FileHandler
from csc_service.server.server_console import ServerConsole
from csc_service.shared.channel import ChannelManager
from csc_service.shared.chat_buffer import ChatBuffer
from csc_service.shared.irc import SERVER_NAME
from csc_service.shared.crypto import is_encrypted, decrypt, encrypt


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
          its component modules (FileHandler, MessageHandler, ServerConsole).
          It binds the socket, starts the network listener, and loads
          persistent data.
        - Arguments:
            - `host` (str): Host/IP to bind to.
            - `port` (int): UDP port number.
            - `timeout` (int): Inactivity timeout (seconds) for clients.
        - What calls it: The `if __name__ == "__main__":` block.
        - What it calls: `super().__init__()`, `self.init_data()`, `FileHandler()`,
          `MessageHandler()`, `ServerConsole()`, `self.sock.bind()`,
          `self.start_listener()`, `self.log()`, `self.connect()`, `self.get_data()`.
        """
        super().__init__()
        self.name = "Server"
        self.log_file = f"{self.name}.log"
        #self.log("TEST LOG ENTRY")
        self.init_data()
        self.server_addr = (host, port)
        self.timeout = timeout

        self._running = True

        # File and message handling components
        self.file_handler = FileHandler(self)
        self.message_handler = MessageHandler(self, self.file_handler)
        self.console = ServerConsole(self)

        # Bind and start listening
        self.log_file = f"{self.name}.log"
        self.sock.bind(self.server_addr)
        self.start_listener()  # ensure we can receive data immediately
        self.log(f"[{self.name}] Bound to {self.server_addr} and listening.")

        # Load persistent client registry
        self.clients = {}  # Active connections (runtime memory)
        self.clients_lock = threading.Lock()
        self.client_registry = self.get_data("clients") or {}
        self.log(f"[INIT] Loaded {len(self.client_registry)} persistent clients from data store.")

        # IRC channel management
        self.channel_manager = ChannelManager()
        self.server_name = SERVER_NAME

        # Chat buffer for message logging and replay
        self.chat_buffer = ChatBuffer()

        # Oper (IRC operator) credentials and active opers
        self.oper_credentials = self.get_data("oper_credentials") or {
            "admin": "changeme",
            "Gemini": "gemini_oper_key",
            "Claude": "claude_oper_key",
        }
        self.opers = set()  # nicks with current oper status
        self.encryption_keys = {} # addr -> aes_key

    # ======================================================================
    # Network Loop
    # ======================================================================

    def _thread_worker(self, data, addr):
        """
        Worker thread to process each incoming packet.
        """
        try:
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

        - What it does: Iterates through the list of active clients, checks for
          timeouts, and sends the message to all non-excluded clients.
        - Arguments:
            - `message` (str or bytes): The message to send.
            - `exclude` (tuple, optional): An address to skip.
        - What calls it: `ServerMessageHandler.process()`, `ServerConsole.run_loop()`.
        - What it calls: `time.time()`, `list()`, `dict.items()`, `isinstance()`,
          `self.log()`, `dict.get()`, `dict.pop()`, `self.sock_send()`.
        """
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
                self.log( f"[Timeout] Dropping inactive client {addr}" )

                # --- FIX ---
                # This command can crash if another thread deletes the key first.
                # del self.clients[addr]

                # This command does the same thing, but will not crash if the key is already gone.
                self.clients.pop( addr, None )
                # -----------

                continue

            if addr != exclude:
                self.sock_send( message, addr )

    def broadcast_to_channel(self, channel_name, message, exclude=None):
        """
        Send a message to all members of a channel.

        Args:
            channel_name: The channel name (e.g. '#general')
            message: The message string to send
            exclude: An address tuple to skip (usually the sender)
        """
        channel = self.channel_manager.get_channel(channel_name)
        if not channel:
            self.log(f"[BROADCAST_CHAN] ERROR: Channel '{channel_name}' not found!")
            return
        msg_bytes = message.encode("utf-8") if isinstance(message, str) else message
        sent_count = 0
        for nick, info in list(channel.members.items()):
            addr = info.get("addr")
            if addr and addr != exclude:
                try:
                    self.sock_send(msg_bytes, addr)
                    sent_count += 1
                except Exception as e:
                    self.log(f"[BROADCAST_CHAN] Error sending to {nick}@{addr}: {e}")
        self.log(f"[BROADCAST_CHAN] Broadcast to '{channel_name}': sent to {sent_count} members (total members: {len(channel.members)})")

    def send_to_nick(self, nick, message):
        """
        Send a message to a specific nick by looking up their address.

        Args:
            nick: The target nick
            message: The message string to send
        """
        msg_bytes = message.encode("utf-8") if isinstance(message, str) else message
        # Search active clients for the nick
        for addr, info in list(self.clients.items()):
            if info.get("name") == nick:
                try:
                    self.sock_send(msg_bytes, addr)
                except Exception as e:
                    self.log(f"[SEND_NICK] Error sending to {nick}@{addr}: {e}")
                return True
        return False

    def send_wallops(self, message):
        """Send a WALLOPS message to all connected IRC operators."""
        wallops_msg = f":{SERVER_NAME} WALLOPS :{message}\r\n"
        for addr, info in list(self.clients.items()):
            nick = info.get("name")
            if nick and nick in self.opers:
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
        """
        Writes the in-memory client registry back to persistent storage.

        - What it does: Saves the `client_registry` from the `MessageHandler`
          to the persistent data store.
        - Arguments: None.
        - What calls it: `self.run()`.
        - What it calls: `self.put_data()`, `self.log()`.
        """
        try:
            self.put_data("clients", self.message_handler.client_registry)
            self.log(
                f"[SYNC] Persisted {len(self.message_handler.client_registry)} clients to disk."
            )
        except Exception as e:
            self.log(f"[SYNC ERROR] Could not save clients: {e}")

    # ======================================================================
    # Run / Shutdown
    # ======================================================================

    def run(self):
        """
        Starts the server's main network loop and console interface.

        - What it does: The main entry point for the server. It starts the network
          loop in a background thread and runs the interactive console in the
          main thread (unless --daemon flag is set). Handles graceful shutdown.
        - Arguments: None.
        - What calls it: The `if __name__ == "__main__":` block.
        - What it calls: `self.log()`, `threading.Thread()`, `thread.start()`,
          `self.console.run_loop()`, `thread.join()`,
          `self.sync_persistent_clients()`, `self.close()`, `print()`.
        """
        self.log(f"[STARTUP] Server listening on {self.server_addr}")
        network_thread = threading.Thread(target=self._network_loop, daemon=True)
        network_thread.start()

        # Launch interactive admin console in the main thread (unless running as daemon)
        if "--daemon" not in sys.argv:
            self.console.run_loop()
        else:
            self.log("[DAEMON] Running in daemon mode, skipping interactive console.")
            # Keep the network thread alive by waiting indefinitely
            try:
                while self._running:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.log("[SHUTDOWN] Keyboard interrupt received.")

        # Graceful shutdown
        self._running = False
        network_thread.join(timeout=2)
        self.sync_persistent_clients()
        self.close()
        self.log("[SHUTDOWN] Server closed sockets and persisted data.")
        print("Server has shut down.")

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
        - What calls it: `self.__init__()`, `ServerConsole.list_clients()`.
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
        - What calls it: `self.sync_persistent_clients()`, `ServerConsole.set_motd()`.
        - What it calls: `super().put_data()`, `self.log()`.
        """
        try:
            super().put_data(key, value)
        except Exception as e:
            self.log(f"[DATA ERROR] put_data({key}): {e}")


if __name__ == "__main__":
    server = Server()
    server.run()
