import sys
import os
import json
import time
import threading
from pathlib import Path
import socket
from csc_network import Network
from .aliases import Aliases
from .macros import Macros
from .client_file_handler import ClientFileHandler
from .client_service_handler import ClientServiceHandler
from csc_data import Data
from csc_server_core.irc import parse_irc_message, format_irc_message, SERVER_NAME


class Client(Network):
    """
    UDP client with IRC protocol support, identity, macros, aliases, and text-file uploads.
    """

    def __init__(self, config_path=None, input_file=None, output_file=None):
        """
        Initializes the instance.

        Args:
            config_path:  Path to JSON config file.
            input_file:   Read commands from this file/FIFO instead of stdin.
            output_file:  Write server output to this file in addition to stdout.
        """
        self.config_file = Path(config_path or "client_config.json")
        self.input_file  = input_file
        self.output_file = output_file

        # Initialize the full parent chain first (Data → Version → Network).
        # This ensures _storage_lock and other base attributes exist before
        # we load config (which may call put_data to write defaults).
        super().__init__(host="127.0.0.1", port=9525, name="client")

        # Now safe to load config — _storage_lock exists from Data.__init__.
        self.init_data(self.config_file)
        self._load_config()

        # Update Network attributes with values loaded from config.
        self.server_addr = (self.server_host, self.server_port)
        self.name = self.name  # already set by _load_config

        self.log("Client initialized and config loaded.")

        self.aliases = Aliases(self)
        self.macros = Macros(self)
        self._last_message_sent = None

        # IRC channel tracking
        self.current_channel = "#general"

        # Channel ops tracking: {channel_name: set(nicks_with_op)}
        self.channel_ops = {}
        # ISOP cache: {nick: (is_oper_bool, timestamp)}
        self._isop_cache = {}

        # Connection state tracking for connection control commands
        self.translator_host = None
        self.translator_port = None
        self.direct_server_host = self.server_host
        self.direct_server_port = self.server_port
        self.using_translator = False
        self.server_history = []  # List of (host, port) tuples
        self.connection_status = {
            'connected': False,
            'registered': False,
            'is_oper': False
        }
        self.joined_channels = set()  # Track channels to rejoin after reconnect
        self._ping_sent_time = None  # For latency measurement

        # Local service execution and file upload handling
        # project_root is /c/csc/irc/packages/csc-service (csc_loop package root)
        self.project_root_dir = Path(__file__).resolve().parent.parent.parent
        self._client_file_handler = ClientFileHandler(self)
        self._client_service_handler = ClientServiceHandler(self)

    # ==========================================================
    # CONFIGURATION
    # ==========================================================
    def _load_config(self):
        """Loads client configuration from JSON, creating defaults as needed."""
        self.name = self.get_data("client_name")
        if not self.name:
            self.name = "client"
            self.put_data("client_name", self.name)

        self.server_host = self.get_data("server_host")
        if not self.server_host:
            self.server_host = "127.0.0.1"
            self.put_data("server_host", self.server_host)

        port = self.get_data("server_port")
        if port is not None:
            self.server_port = int(port)
        else:
            self.server_port = 9525
            self.put_data("server_port", self.server_port)

        self.log_file = self.get_data("log_file")
        if not self.log_file:
            self.log_file = f"{self.name}.log"
            self.put_data("log_file", self.log_file)

        # Load translator configuration
        self.translator_host = self.get_data("translator_host")
        self.translator_port = self.get_data("translator_port")
        use_translator = self.get_data("use_translator")
        if use_translator:
            self.using_translator = bool(use_translator)

        # Load server history
        history = self.get_data("server_history")
        if history and isinstance(history, list):
            self.server_history = [tuple(h) for h in history if len(h) == 2]

    def _save_config(self):
        """Saves all client data back to config file."""
        self.store_data()

    # ==========================================================
    # CONNECTION CONTROL HELPER METHODS
    # ==========================================================
    def _disconnect_gracefully(self):
        """Send QUIT and close connection."""
        if self.connection_status['connected']:
            try:
                self.send_message(format_irc_message(command='QUIT', trailing='Disconnecting'))
                time.sleep(0.5)  # Allow QUIT to send
            except Exception as e:
                self.log(f"[Client] Error sending QUIT: {e}")

            try:
                if hasattr(self, 'sock') and self.sock:
                    self.sock.close()
            except Exception as e:
                self.log(f"[Client] Socket close error: {e}")

            self.connection_status['connected'] = False
            self.connection_status['registered'] = False
            self.log("[Client] Disconnected gracefully")

    def _connect_to_server(self, host, port):
        """Establish new server connection and re-register."""
        try:
            # Store channels to rejoin
            channels_to_rejoin = list(self.joined_channels)

            # Stop the old listener thread and close socket
            self._running = False
            if hasattr(self, '_listener_thread') and self._listener_thread:
                try:
                    self._listener_thread.join(timeout=2.0)
                except (RuntimeError, TimeoutError):
                    pass

            try:
                if hasattr(self, 'sock') and self.sock:
                    self.sock.close()
            except OSError:
                pass

            # Reset listener thread reference
            self._listener_thread = None

            # Update connection details
            self.server_host = host
            self.server_port = port
            self.server_addr = (host, port)

            # Create new socket
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(1.0)

            # Restart and start listener
            self._running = True
            self.start_listener()

            # Wait for listener to start
            time.sleep(0.2)

            # Identify
            self.identify()

            # Wait a moment for registration
            time.sleep(0.5)

            # Rejoin channels
            for chan in channels_to_rejoin:
                super().send(f"JOIN {chan}\r\n")
                time.sleep(0.1)

            self.log(f"[Client] Connected to {host}:{port}")
            return True

        except Exception as e:
            self.log(f"[Client ERROR] Failed to connect to {host}:{port}: {e}")
            return False

    def _configure_translator(self, host, port):
        """Configure translator proxy and reconnect."""
        self.translator_host = host
        self.translator_port = port
        self.using_translator = True

        # Save translator config
        self.put_data("translator_host", host)
        self.put_data("translator_port", port)
        self.put_data("use_translator", True)
        self._save_config()

        # Determine target address (translator proxies to server)
        target_host = host
        target_port = port

        print(f"Configuring translator at {host}:{port}")
        self.log(f"[Client] Configuring translator at {host}:{port}")

        # Reconnect through translator
        return self._connect_to_server(target_host, target_port)

    def _disable_translator(self):
        """Disable translator and connect directly to server."""
        self.using_translator = False
        self.translator_host = None
        self.translator_port = None

        # Save config
        self.put_data("translator_host", None)
        self.put_data("translator_port", None)
        self.put_data("use_translator", False)
        self._save_config()

        print(f"Disabling translator, connecting directly to {self.direct_server_host}:{self.direct_server_port}")
        self.log(f"[Client] Disabling translator")

        # Reconnect directly
        return self._connect_to_server(self.direct_server_host, self.direct_server_port)

    def _add_to_server_history(self, host, port):
        """Add server to history (max 3 entries)."""
        entry = (host, port)
        if entry in self.server_history:
            self.server_history.remove(entry)
        self.server_history.insert(0, entry)
        self.server_history = self.server_history[:3]

        # Save to config
        self.put_data("server_history", self.server_history)
        self._save_config()

    # ==========================================================
    # CONNECTION CONTROL COMMANDS
    # ==========================================================
    def _handle_server_command(self, args: str):
        """
        /server <host> [port]
        Connect to a different server.
        """
        try:
            parts = args.strip().split()
            if not parts:
                print("Usage: /server <host> [port]")
                return

            new_host = parts[0]
            new_port = int(parts[1]) if len(parts) > 1 else 9525

            # Store old connection for fallback
            old_host = self.server_host
            old_port = self.server_port

            print(f"Disconnecting from {self.server_host}:{self.server_port}...")
            self._disconnect_gracefully()

            print(f"Connecting to {new_host}:{new_port}...")
            if self._connect_to_server(new_host, new_port):
                print(f"Connected! Re-registering as {self.name}...")
                self._add_to_server_history(new_host, new_port)

                # Update direct server reference
                self.direct_server_host = new_host
                self.direct_server_port = new_port
                self.put_data("server_host", new_host)
                self.put_data("server_port", new_port)
                self._save_config()
            else:
                print(f"Failed to connect to {new_host}:{new_port}")
                print(f"Attempting to restore connection to {old_host}:{old_port}...")
                if self._connect_to_server(old_host, old_port):
                    print(f"Restored connection to {old_host}:{old_port}")
                else:
                    print(f"ERROR: Failed to restore previous connection!")

        except ValueError as e:
            print(f"Invalid port number: {e}")
        except Exception as e:
            self.log(f"[Client ERROR] /server command failed: {e}")
            print(f"Error: {e}")

    def _handle_reconnect_command(self):
        """
        /reconnect
        Disconnect and reconnect to current server.
        """
        try:
            current_host = self.server_host
            current_port = self.server_port

            print(f"Reconnecting to {current_host}:{current_port}...")
            self._disconnect_gracefully()
            time.sleep(0.5)

            if self._connect_to_server(current_host, current_port):
                print(f"Connected! Re-registering as {self.name}...")
            else:
                print(f"Failed to reconnect to {current_host}:{current_port}")

        except Exception as e:
            self.log(f"[Client ERROR] /reconnect command failed: {e}")
            print(f"Error: {e}")

    def _handle_disconnect_command(self):
        """
        /disconnect
        Gracefully disconnect from server.
        """
        try:
            print(f"Disconnecting from {self.server_host}:{self.server_port}...")
            self._disconnect_gracefully()
            print("Disconnected.")

        except Exception as e:
            self.log(f"[Client ERROR] /disconnect command failed: {e}")
            print(f"Error: {e}")

    def _handle_translator_command(self, args: str):
        """
        /translator <host> <port>  - Configure translator proxy
        /translator off            - Disable translator
        /translator status         - Show translator configuration
        """
        try:
            parts = args.strip().split()

            if not parts:
                print("Usage: /translator <host> <port> | off | status")
                return

            subcommand = parts[0].lower()

            if subcommand == "status":
                if self.using_translator and self.translator_host:
                    print(f"Translator: {self.translator_host}:{self.translator_port} (proxied)")
                    print(f"Direct server: {self.direct_server_host}:{self.direct_server_port}")
                else:
                    print("Translator: Direct connection (no proxy)")
                    print(f"Server: {self.direct_server_host}:{self.direct_server_port}")
                return

            if subcommand == "off":
                # Store old connection for fallback
                old_host = self.server_host
                old_port = self.server_port

                if self._disable_translator():
                    print("Translator disabled, connected directly.")
                else:
                    print("Failed to disable translator.")
                    # Try to restore
                    if old_host and old_port:
                        print(f"Attempting to restore connection to {old_host}:{old_port}...")
                        self._connect_to_server(old_host, old_port)
                return

            # Configure translator
            if len(parts) < 2:
                print("Usage: /translator <host> <port>")
                return

            trans_host = parts[0]
            trans_port = int(parts[1])

            # Store old connection for fallback
            old_host = self.server_host
            old_port = self.server_port

            if self._configure_translator(trans_host, trans_port):
                print(f"Translator configured at {trans_host}:{trans_port}")
            else:
                print(f"Failed to configure translator.")
                # Try to restore
                if old_host and old_port:
                    print(f"Attempting to restore connection to {old_host}:{old_port}...")
                    self._connect_to_server(old_host, old_port)

        except ValueError as e:
            print(f"Invalid port number: {e}")
        except Exception as e:
            self.log(f"[Client ERROR] /translator command failed: {e}")
            print(f"Error: {e}")

    def _handle_status_command(self):
        """
        /status
        Display current connection information.
        """
        try:
            print("\nConnection Status:")
            print(f"  Connected: {'yes' if self.connection_status['connected'] else 'no'}")
            print(f"  Server: {self.server_host}:{self.server_port}")

            if self.using_translator and self.translator_host:
                print(f"  Translator: {self.translator_host}:{self.translator_port} (proxied)")
            else:
                print(f"  Translator: Direct connection")

            print(f"  Nick: {self.name}")
            print(f"  Channel: {self.current_channel}")
            print(f"  Registered: {'yes' if self.connection_status['registered'] else 'no'}")
            print(f"  Operator: {'yes' if self.connection_status['is_oper'] else 'no'}")

            if self.joined_channels:
                print(f"  Joined channels: {', '.join(sorted(self.joined_channels))}")

            if self.server_history:
                print(f"  Server history: {', '.join([f'{h}:{p}' for h, p in self.server_history])}")
            print()

        except Exception as e:
            self.log(f"[Client ERROR] /status command failed: {e}")
            print(f"Error: {e}")

    def _handle_ping_command(self):
        """
        /ping
        Send PING to server and measure latency.
        """
        try:
            self._ping_sent_time = time.time()
            ping_token = f"ping_{int(self._ping_sent_time * 1000)}"
            super().send(f"PING :{ping_token}\r\n")
            print(f"PING sent to {self.server_host}:{self.server_port}...")

        except Exception as e:
            self.log(f"[Client ERROR] /ping command failed: {e}")
            print(f"Error: {e}")

    # ==========================================================
    # IDENTITY (IRC Registration)
    # ==========================================================
    def identify(self):
        """Send IRC registration sequence: NICK + USER."""
        super().send(f"NICK {self.name}\r\n")
        super().send(f"USER {self.name} 0 * :{self.name}\r\n")
        self.connection_status['connected'] = True
        self.log(f"Sent IRC registration as '{self.name}'")

    # ==========================================================
    # MAIN LOOP
    # ==========================================================
    def _write_to_output(self, text):
        """Write text to output_file if set, always also print to stdout."""
        print(text)
        if self.output_file:
            try:
                with open(self.output_file, "a", encoding="utf-8") as f:
                    f.write(text + "\n")
            except Exception as e:
                self.log(f"[Client] output_file write error: {e}")

    def run(self, interactive=True):
        """Starts listener thread and handles input.

        Args:
            interactive: If False, skip the welcome prompt and run headlessly
                         (used with --detach/--fifo daemon mode).
        """
        self.start_listener()
        self.identify()

        if interactive:
            print(f"\nWelcome, {self.name}! Type messages and press Enter.")
            print("Use /help for a list of commands.\n")

        input_thread = threading.Thread(target=self._input_loop, daemon=True)
        input_thread.start()

        try:
            while self._running and input_thread.is_alive():
                msg_data = self.get_message()
                if msg_data:
                    self._handle_server_message_data(msg_data)
                else:
                    time.sleep(0.05)
        except (KeyboardInterrupt, EOFError):
            self.log("User interrupted client. Shutting down.")
        finally:
            self._running = False
            self.close()
            if interactive:
                print("\nDisconnected from server.")

    # ==========================================================
    # INPUT HANDLING
    # ==========================================================
    def _is_fifo(self):
        """Return True if input_file is a POSIX FIFO."""
        import stat as _stat
        try:
            return _stat.S_ISFIFO(os.stat(self.input_file).st_mode)
        except OSError:
            return False

    def _input_loop_file(self):
        """Input loop for --infile / --fifo mode.

        For a POSIX FIFO: reopen after each EOF so the pipe stays alive indefinitely.
        For a plain file (Windows daemon mode): tail-poll using offset tracking so
        new lines appended after the initial read are picked up continuously.
        """
        is_fifo = self._is_fifo()
        offset = 0
        while self._running:
            if hasattr(self, "check_shutdown") and self.check_shutdown():
                if hasattr(self, "log_shutdown"): self.log_shutdown()
                break
            try:
                with open(self.input_file, "r", encoding="utf-8") as fh:
                    if not is_fifo:
                        fh.seek(offset)
                    for line in fh:
                        if not self._running:
                            return
                        line = line.strip()
                        if line:
                            self.process_command(line)
                            time.sleep(0.05)
                    if not is_fifo:
                        offset = fh.tell()
            except Exception as e:
                self.log(f"[Client] input_file read error: {e}")
                time.sleep(1)
            if not is_fifo:
                time.sleep(0.3)  # poll interval for Windows plain-file FIFO

    def _input_loop(self):
        """Handles blocking user input in a separate thread."""
        if self.input_file:
            return self._input_loop_file()
        in_file_paste_mode = False
        pasted_lines = []

        while self._running:
            if hasattr(self, "check_shutdown") and self.check_shutdown():
                if hasattr(self, "log_shutdown"): self.log_shutdown()
                break
            try:
                user_input = input()

                if in_file_paste_mode:
                    if user_input.strip().lower() == "<end file>":
                        self.log("Ending multi-line paste mode, sending file block...")
                        self.send(pasted_lines[0])
                        time.sleep(0.005)
                        for line in pasted_lines[1:]:
                            line_with_newline = line if line.endswith("\n") else line + "\n"
                            self.sock_send(line_with_newline.encode("utf-8"), self.server_addr)
                            time.sleep(0.005)
                        self.send("<end file>")
                        print("Pasted content sent.")
                        pasted_lines = []
                        in_file_paste_mode = False
                    else:
                        pasted_lines.append(user_input)
                    continue

                if user_input.strip().lower().startswith("<begin file="):
                    in_file_paste_mode = True
                    pasted_lines.append(user_input)
                    print("... entered file paste mode. End with '<end file>' on a new line.")
                    continue

                if not user_input:
                    continue
                self.process_command(user_input)

            except (EOFError, KeyboardInterrupt):
                self.log("Input loop interrupted.")
                self._running = False
                break

    # ==========================================================
    # MESSAGE HANDLERS
    # ==========================================================
    def _handle_server_message_data(self, msg_data):
        """Decodes and routes a message received from the server."""
        data, addr = msg_data
        try:
            msg = data.decode("utf-8", errors="ignore")
        except Exception as e:
            self.log(f"[DECODE ERROR] {e}")
            return

        # Handle multi-line messages
        for line in msg.splitlines():
            line = line.strip()
            if not line:
                continue
            self._handle_irc_line(line)

    def _handle_irc_line(self, line):
        """Parse and handle a single IRC line from the server."""
        parsed = parse_irc_message(line)

        # Handle numeric replies
        if parsed.command.isdigit():
            self._handle_numeric(parsed)
            return

        cmd = parsed.command.upper()

        if cmd == "PING":
            token = parsed.params[0] if parsed.params else SERVER_NAME
            super().send(f"PONG :{token}\r\n")
            return

        if cmd == "PONG":
            # Handle PONG for latency measurement
            if self._ping_sent_time:
                latency = (time.time() - self._ping_sent_time) * 1000
                print(f"PONG received from server. Latency: {latency:.2f}ms")
                self._ping_sent_time = None
            return

        if cmd == "PRIVMSG":
            self._handle_privmsg_recv(parsed)
            return

        if cmd == "NOTICE":
            self._handle_notice_recv(parsed)
            return

        if cmd == "JOIN":
            nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
            channel = parsed.params[0] if parsed.params else "?"
            # Track our own joins
            if nick == self.name:
                self.joined_channels.add(channel)
            print(f"* {nick} has joined {channel}")
            return

        if cmd == "PART":
            nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
            channel = parsed.params[0] if parsed.params else "?"
            reason = parsed.params[-1] if len(parsed.params) > 1 else ""
            # Track our own parts
            if nick == self.name:
                self.joined_channels.discard(channel)
            # Remove from op tracking
            if channel in self.channel_ops:
                self.channel_ops[channel].discard(nick)
            print(f"* {nick} has left {channel}" + (f" ({reason})" if reason else ""))
            return

        if cmd == "NICK":
            old_nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
            new_nick = parsed.params[0] if parsed.params else "?"
            print(f"* {old_nick} is now known as {new_nick}")
            return

        if cmd == "KICK":
            channel = parsed.params[0] if parsed.params else "?"
            target = parsed.params[1] if len(parsed.params) > 1 else "?"
            reason = parsed.params[-1] if len(parsed.params) > 2 else ""
            kicker = parsed.prefix.split("!")[0] if parsed.prefix else "?"
            print(f"* {target} was kicked from {channel} by {kicker}" + (f" ({reason})" if reason else ""))
            if target == self.name:
                self.joined_channels.discard(channel)
                print(f"You were kicked from {channel}.")
            return

        if cmd == "KILL":
            target = parsed.params[0] if parsed.params else "?"
            reason = parsed.params[-1] if len(parsed.params) > 1 else ""
            if target == self.name:
                print(f"You have been killed from the server: {reason}")
            return

        if cmd == "TOPIC":
            channel = parsed.params[0] if parsed.params else "?"
            topic = parsed.params[-1] if len(parsed.params) > 1 else ""
            nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
            print(f"* {nick} changed the topic of {channel} to: {topic}")
            return

        if cmd == "QUIT":
            nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
            reason = parsed.params[0] if parsed.params else ""
            # Remove from all op tracking
            for chan_ops in self.channel_ops.values():
                chan_ops.discard(nick)
            print(f"* {nick} has quit" + (f" ({reason})" if reason else ""))
            return

        if cmd == "MODE":
            # Track +o/-o/+v/-v for channel ops
            if len(parsed.params) >= 3:
                chan = parsed.params[0]
                mode_str = parsed.params[1]
                target_nick = parsed.params[2]
                setter = parsed.prefix.split("!")[0] if parsed.prefix else "?"
                if chan.startswith("#"):
                    if mode_str == "+o":
                        self.channel_ops.setdefault(chan, set()).add(target_nick)
                    elif mode_str == "-o":
                        self.channel_ops.get(chan, set()).discard(target_nick)
                print(f"* {setter} sets mode {mode_str} {target_nick} on {chan}")
            elif len(parsed.params) >= 2:
                chan = parsed.params[0]
                mode_str = parsed.params[1]
                setter = parsed.prefix.split("!")[0] if parsed.prefix else "?"
                print(f"* {setter} sets mode {mode_str} on {chan}")
            else:
                print(f"* Mode: {line}")
            return

        if cmd == "WALLOPS":
            text = parsed.params[-1] if parsed.params else ""
            sender = parsed.prefix.split("!")[0] if parsed.prefix else SERVER_NAME
            print(f"[WALLOPS/{sender}] {text}")
            return

        if cmd == "ERROR":
            error_text = parsed.params[0] if parsed.params else line
            print(f"[ERROR] {error_text}")
            return

        # Fallback: display raw
        print(f"> {line}")

    def _handle_numeric(self, parsed):
        """Handle IRC numeric replies."""
        num = parsed.command
        text = parsed.params[-1] if parsed.params else ""

        # Welcome burst 001-004
        if num in ("001", "002", "003", "004"):
            if num == "001":
                # RPL_WELCOME - we're now registered
                self.connection_status['registered'] = True
                self.log("[Client] Registration confirmed by server")
            print(f"[Server] {text}")
            return

        # MOTD
        if num in ("375", "376"):  # MOTDSTART, ENDOFMOTD
            print(f"[MOTD] {text}")
            return
        if num == "372":  # MOTD line
            print(f"[MOTD] {text}")
            return

        # LIST
        if num == "322":  # RPL_LIST
            # params: nick channel count :topic
            if len(parsed.params) >= 3:
                chan = parsed.params[1]
                count = parsed.params[2]
                topic = parsed.params[-1] if len(parsed.params) > 3 else ""
                print(f"  {chan} ({count} users) — {topic}")
            else:
                print(f"  {text}")
            return
        if num == "323":  # RPL_LISTEND
            print(f"[LIST] {text}")
            return

        # TOPIC
        if num == "331":  # RPL_NOTOPIC
            print(f"[TOPIC] {text}")
            return
        if num == "332":  # RPL_TOPIC
            print(f"[TOPIC] {text}")
            return

        # NAMES
        if num == "353":  # RPL_NAMREPLY
            # params: nick = #channel :names
            if len(parsed.params) >= 3:
                chan = parsed.params[2] if len(parsed.params) > 3 else parsed.params[1]
                names = parsed.params[-1]
                # Track ops from NAMES list
                ops = set()
                for name_entry in names.split():
                    if name_entry.startswith("@"):
                        ops.add(name_entry[1:])
                self.channel_ops[chan] = ops
                print(f"[NAMES] {chan}: {names}")
            else:
                print(f"[NAMES] {text}")
            return
        if num == "366":  # RPL_ENDOFNAMES
            return

        # OPER
        if num == "381":  # RPL_YOUREOPER
            self.connection_status['is_oper'] = True
            self.log("[Client] IRC operator status granted")
            print(f"[OPER] {text}")
            return

        # ERR_NOTREGISTERED
        if num == "451":
            self.log("[AUTO] Server says not registered. Re-identifying.")
            self.identify()
            if self._last_message_sent:
                self.log(f"[AUTO] Resending last message: {self._last_message_sent[:70]}")
                super().send(self._last_message_sent)
            return

        # Other errors
        if num.startswith("4"):
            print(f"[ERROR {num}] {text}")
            return

        # WHO replies
        if num in ("352", "315"):
            print(f"[WHO] {text}")
            return

        # Default
        print(f"[{num}] {text}")

    def _is_authorized(self, nick, channel=None):
        """
        Check if a nick is authorized to command this client.
        
        Args:
            nick: The nickname to check.
            channel: Optional channel name to check for chanop status.
            
        Returns:
            bool: True if authorized, False otherwise.
        """
        if not nick:
            return False

        # Self is always authorized
        if nick == self.name:
            return True

        # Server is always authorized
        if nick in (SERVER_NAME, "csc-server"):
            return True

        # Check channel operator status if in a channel
        if channel and channel in self.channel_ops:
            if nick in self.channel_ops[channel]:
                return True

        # Check IRC operator cache
        is_oper, _ = self._isop_cache.get(nick, (False, 0))
        if is_oper:
            return True

        return False

    def _handle_privmsg_recv(self, parsed):
        """Handle received PRIVMSG, including nick-prefixed command execution."""
        nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
        target = parsed.params[0] if parsed.params else "?"
        text = parsed.params[-1] if len(parsed.params) > 1 else ""
        prefix_full = parsed.prefix or ""

        # CTCP / ACTION detection
        if text.startswith("\x01") and text.endswith("\x01"):
            ctcp_body = text[1:-1]
            if ctcp_body.startswith("ACTION "):
                action = ctcp_body[7:]
                if target.startswith("#"):
                    print(f"[{target}] ** {nick} {action}")
                else:
                    print(f"[DM] ** {nick} {action}")
            else:
                print(f"[[{nick} CTCP]] {ctcp_body}")
            return False

        if target.startswith("#"):
            # Channel message
            print(f"[{target}] <{nick}> {text}")
        else:
            # Private message
            print(f"[DM] <{nick}> {text}")

        # Check for active file upload session from this sender
        if self._client_file_handler.has_active_session(nick):
            self._handle_local_file_session_line(nick, text, target)
            return True

        # Check for nick-prefixed command: "<own_nick> AI ..." or "<own_nick> upload ..."
        nick_prefix = f"{self.name} "
        if text.startswith(nick_prefix):
            # Authorization check
            if not self._is_authorized(nick, target if target.startswith("#") else None):
                self.log(f"[SECURITY] 🚫 Command from unauthorized user {nick} ignored: {text}")
                return False

            cmd_text = text[len(nick_prefix):].strip()
            reply_target = target if target.startswith("#") else nick

            if cmd_text.startswith("AI "):
                # Local service execution
                print(f"[LOCAL EXEC] Executing service command from {nick}: {cmd_text}")
                self.log(f"[LOCAL EXEC] Service command from {nick}: {cmd_text}")
                token, result = self._client_service_handler.execute(cmd_text, nick)
                if token != "0":
                    full_response = f"{token} {result}" if token else result
                    print(f"[LOCAL RESULT] {full_response}")
                    self._last_message_sent = f"PRIVMSG {reply_target} :{full_response}\r\n"
                    super().send(self._last_message_sent)
                return True

            elif cmd_text.startswith("<begin file=") or cmd_text.startswith("<append file="):
                # Local file upload FROM the sender
                print(f"[LOCAL FILE] Accepting file upload from {nick}: {cmd_text}")
                self.log(f"[LOCAL FILE] File upload from {nick}: {cmd_text}")
                self._client_file_handler.start_session(nick, cmd_text)
                return True
        
        return False

    def _handle_local_file_session_line(self, sender_nick, text, target):
        """Handle a line during an active local file upload session."""
        # Authorization check
        if not self._is_authorized(sender_nick, target if target.startswith("#") else None):
            self.log(f"[SECURITY] 🚫 Unauthorized file data from {sender_nick} ignored.")
            return

        if text.strip() == "<end file>":
            result = self._client_file_handler.complete_session(sender_nick)
            print(f"[LOCAL FILE] {result}")
            self.log(f"[LOCAL FILE] {result}")
            reply_target = target if target.startswith("#") else sender_nick
            self._last_message_sent = f"PRIVMSG {reply_target} :{result}\r\n"
            super().send(self._last_message_sent)
        elif text.strip().startswith("<begin file=") or text.strip().startswith("<append file="):
            self._client_file_handler.abort_session(sender_nick)
            print(f"[LOCAL FILE] Nested upload not supported. Session aborted.")
        else:
            self._client_file_handler.process_chunk(sender_nick, text)

    def _handle_notice_recv(self, parsed):
        """Handle received NOTICE, including ISOP responses and VFS protocol."""
        nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
        target = parsed.params[0] if parsed.params else "?"
        text = parsed.params[-1] if parsed.params else ""

        # VFS protocol responses
        if text.startswith("VFS "):
            self._handle_vfs_notice(text)
            return

        # Check for ISOP response: "ISOP <nick> YES/NO"
        if text.startswith("ISOP "):
            parts = text.split()
            if len(parts) >= 3:
                import time as _time
                isop_nick = parts[1]
                is_oper = parts[2].upper() == "YES"
                self._isop_cache[isop_nick] = (is_oper, _time.time())
                self.log(f"[ISOP] {isop_nick} is {'an oper' if is_oper else 'not an oper'}")
            return

        # Detect [BUFFER] prefix for buffer replay lines
        if text.startswith("[BUFFER] "):
            buf_text = text[len("[BUFFER] "):]
            print(f"  {buf_text}")
            return

        # CTCP reply detection
        if text.startswith("\x01") and text.endswith("\x01"):
            ctcp_body = text[1:-1]
            print(f"[[{nick} CTCP]] {ctcp_body}")
            return

        # Format notice based on target
        if target.startswith("#"):
            print(f"[{target}] *{nick}* {text}")
        else:
            print(f"[DM] *{nick}* {text}")

    def _handle_vfs_notice(self, text: str):
        """Handle VFS protocol NOTICEs from the server."""
        import socket as _socket
        import threading as _threading

        if text.startswith("VFS PRET "):
            # VFS PRET <ip> <port> <action>
            parts = text.split()
            if len(parts) < 4:
                print(f"[VFS] Bad PRET: {text}")
                return
            ip, port, action = parts[2], int(parts[3]), parts[4] if len(parts) > 4 else "?"

            if action == "ENCRYPT":
                info = getattr(self, "_vfs_pending_upload", None)
                if not info:
                    print("[VFS] PRET ENCRYPT received but no pending upload.")
                    return
                local_path, vfspath = info
                self._vfs_pending_upload = None

                def _upload():
                    try:
                        with open(local_path, "rb") as f:
                            data = f.read()
                        s = _socket.create_connection((ip, port), timeout=30)
                        s.sendall(data)
                        s.close()
                        print(f"[VFS] Sent {len(data)} bytes -> {vfspath}")
                    except Exception as exc:
                        print(f"[VFS] Upload failed: {exc}")
                _threading.Thread(target=_upload, daemon=True).start()

            elif action == "DECRYPT":
                info = getattr(self, "_vfs_pending_download", None)
                if not info:
                    print("[VFS] PRET DECRYPT received but no pending download.")
                    return
                vfspath, local_path = info
                self._vfs_pending_download = None

                def _download():
                    try:
                        s = _socket.create_connection((ip, port), timeout=30)
                        chunks = []
                        while True:
                            chunk = s.recv(65536)
                            if not chunk:
                                break
                            chunks.append(chunk)
                        s.close()
                        data = b"".join(chunks)
                        with open(local_path, "wb") as f:
                            f.write(data)
                        print(f"[VFS] Received {len(data)} bytes -> {local_path}")
                    except Exception as exc:
                        print(f"[VFS] Download failed: {exc}")
                _threading.Thread(target=_download, daemon=True).start()

            elif action == "LIST":
                def _list():
                    try:
                        s = _socket.create_connection((ip, port), timeout=30)
                        chunks = []
                        while True:
                            chunk = s.recv(65536)
                            if not chunk:
                                break
                            chunks.append(chunk)
                        s.close()
                        listing = b"".join(chunks).decode("utf-8", errors="replace")
                        print(f"[VFS] --- listing ---")
                        print(listing)
                        print(f"[VFS] --- end ---")
                    except Exception as exc:
                        print(f"[VFS] List failed: {exc}")
                _threading.Thread(target=_list, daemon=True).start()

            else:
                print(f"[VFS] Unknown PRET action: {action}")

        elif text.startswith("VFS CAT END"):
            print("[VFS] --- end ---")

        elif text.startswith("VFS CAT "):
            print(text[8:])  # strip "VFS CAT "

        elif text.startswith("VFS CWD "):
            newpath = text[8:]
            print(f"[VFS] cwd -> {newpath}")

        elif text.startswith("VFS OK "):
            print(f"[VFS] {text[7:]}")

        elif text.startswith("VFS ERR "):
            print(f"[VFS ERROR] {text[8:]}")

        else:
            print(f"[VFS] {text}")

    def _vfs_command(self, args: str):
        """Handle /vfs subcommands.

        /vfs list [pathspec]            — list VFS at pathspec
        /vfs cwd <pathspec>             — change working prefix
        /vfs encrypt <local> <vfspath>  — upload+encrypt local file to VFS
        /vfs decrypt <vfspath> <local>  — download+decrypt VFS file to local
        /vfs cat <pathspec>             — print text file inline
        /vfs rnfr <pathspec>            — stage a rename-from
        /vfs rnto <pathspec>            — complete rename-to
        /vfs del <pathspec>             — delete encrypted file
        """
        parts = args.split() if args else []
        sub = parts[0].lower() if parts else "help"
        rest = parts[1:]

        if sub in ("list", "ls"):
            pathspec = rest[0] if rest else ""
            super().send(f"VFS LIST {pathspec}\r\n" if pathspec else "VFS LIST\r\n")

        elif sub == "cwd":
            if not rest:
                print("Usage: /vfs cwd <pathspec>")
                return
            super().send(f"VFS CWD {rest[0]}\r\n")

        elif sub in ("encrypt", "put", "up"):
            if len(rest) < 2:
                print("Usage: /vfs encrypt <local_file> <vfs::path::file>")
                return
            self._vfs_pending_upload = (rest[0], rest[1])
            super().send(f"VFS ENCRYPT {rest[1]}\r\n")

        elif sub in ("decrypt", "get", "dl"):
            if len(rest) < 2:
                print("Usage: /vfs decrypt <vfs::path::file> <local_file>")
                return
            self._vfs_pending_download = (rest[0], rest[1])
            super().send(f"VFS DECRYPT {rest[0]}\r\n")

        elif sub == "cat":
            if not rest:
                print("Usage: /vfs cat <pathspec>")
                return
            super().send(f"VFS CAT {rest[0]}\r\n")

        elif sub == "rnfr":
            if not rest:
                print("Usage: /vfs rnfr <pathspec>")
                return
            super().send(f"VFS RNFR {rest[0]}\r\n")

        elif sub == "rnto":
            if not rest:
                print("Usage: /vfs rnto <pathspec>")
                return
            super().send(f"VFS RNTO {rest[0]}\r\n")

        elif sub in ("del", "rm", "delete"):
            if not rest:
                print("Usage: /vfs del <pathspec>")
                return
            super().send(f"VFS DEL {rest[0]}\r\n")

        else:
            print(
                "VFS commands:\n"
                "  /vfs list [path]              — list encrypted FS\n"
                "  /vfs cwd <path>               — set working prefix\n"
                "  /vfs encrypt <local> <vpath>  — upload+encrypt file\n"
                "  /vfs decrypt <vpath> <local>  — download+decrypt file\n"
                "  /vfs cat <vpath>              — read text file inline\n"
                "  /vfs rnfr <vpath>             — stage rename-from\n"
                "  /vfs rnto <vpath>             — complete rename-to\n"
                "  /vfs del <vpath>              — delete file\n"
                "  Aliases: ls=list, put/up=encrypt, get/dl=decrypt, rm=del"
            )

    def handle_server_message(self, msg: str):
        """Legacy handler — prints messages received from the server."""
        print(f"> {msg.strip()}")

    # ==========================================================
    # COMMANDS
    # ==========================================================
    def process_command(self, cmd: str):
        """Processes user commands with alias/macro expansion."""
        original_cmd = cmd
        expanded_aliases = self.aliases.expand_aliases_in_string(cmd)
        macros_to_run = self.macros.expand_macro(expanded_aliases)
        if macros_to_run:
            for macro_cmd in macros_to_run:
                self.process_command(self.aliases.expand_aliases_in_string(macro_cmd))
            return

        cmd = expanded_aliases

        if cmd.startswith("/"):
            parts = cmd.split(" ", 1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            if command == "/quit":
                super().send(f"QUIT :Leaving\r\n")
                self._running = False
            elif command == "/send":
                self.send_file(args) if args else print("Usage: /send <filepath>")
            elif command == "/name" or command == "/nick":
                if args:
                    old_name = self.name
                    self.name = args
                    self._save_config()
                    super().send(f"NICK {self.name}\r\n")
                    print(f"Nick changed to '{self.name}'.")
                else:
                    print("Usage: /nick <new_name>")
            elif command == "/join":
                if args:
                    chan = args.strip()
                    if not chan.startswith("#"):
                        chan = "#" + chan
                    super().send(f"JOIN {chan}\r\n")
                    self.current_channel = chan
                    print(f"Joining {chan}...")
                else:
                    print("Usage: /join #channel")
            elif command == "/part":
                if args:
                    parts_split = args.split(" ", 1)
                    chan = parts_split[0]
                    reason = parts_split[1] if len(parts_split) > 1 else "Leaving"
                    super().send(f"PART {chan} :{reason}\r\n")
                else:
                    super().send(f"PART {self.current_channel} :Leaving\r\n")
            elif command == "/msg":
                parts_split = args.split(" ", 1)
                if len(parts_split) >= 2:
                    target = parts_split[0]
                    text = parts_split[1]
                    super().send(f"PRIVMSG {target} :{text}\r\n")
                else:
                    print("Usage: /msg <target> <text>")
            elif command == "/me":
                if args:
                    super().send(f"PRIVMSG {self.current_channel} :\x01ACTION {args}\x01\r\n")
                    print(f"[{self.current_channel}] **{self.name}** {args}")
                else:
                    print("Usage: /me <action>")
            elif command == "/ctcp":
                parts_split = args.split(" ", 1)
                if len(parts_split) >= 2:
                    target = parts_split[0]
                    ctcp_msg = parts_split[1]
                    super().send(f"PRIVMSG {target} :\x01{ctcp_msg}\x01\r\n")
                else:
                    print("Usage: /ctcp <target> <message>")
            elif command == "/topic":
                if args:
                    parts_split = args.split(" ", 1)
                    chan = parts_split[0]
                    if len(parts_split) > 1:
                        super().send(f"TOPIC {chan} :{parts_split[1]}\r\n")
                    else:
                        super().send(f"TOPIC {chan}\r\n")
                else:
                    super().send(f"TOPIC {self.current_channel}\r\n")
            elif command == "/list":
                super().send("LIST\r\n")
            elif command == "/names":
                chan = args.strip() if args else self.current_channel
                super().send(f"NAMES {chan}\r\n")
            elif command == "/who":
                chan = args.strip() if args else self.current_channel
                super().send(f"WHO {chan}\r\n")
            elif command == "/oper":
                parts_split = args.split(" ", 1)
                if len(parts_split) >= 2:
                    super().send(f"OPER {parts_split[0]} {parts_split[1]}\r\n")
                else:
                    print("Usage: /oper <name> <password>")
            elif command == "/kick":
                parts_split = args.split(" ", 2)
                if len(parts_split) >= 2:
                    chan = parts_split[0]
                    nick = parts_split[1]
                    reason = parts_split[2] if len(parts_split) > 2 else ""
                    if reason:
                        super().send(f"KICK {chan} {nick} :{reason}\r\n")
                    else:
                        super().send(f"KICK {chan} {nick}\r\n")
                else:
                    print("Usage: /kick #channel <nick> [reason]")
            elif command == "/motd":
                super().send("MOTD\r\n")
            elif command == "/buffer":
                target = args.strip() if args else self.current_channel
                super().send(f"BUFFER {target}\r\n")
            elif command == "/saveconfig":
                self._save_config()
            elif command == "/help":
                self.print_local_help()
            elif command == "/alias":
                print(self.aliases.add_alias(args)) if args else print("Usage: /alias <name> = <command>")
            elif command == "/unalias":
                print(self.aliases.remove_alias(args)) if args else print("Usage: /unalias <name>")
            elif command == "/aliases":
                print(self.aliases.list_aliases())
            elif command == "/macro":
                print(self.macros.add_macro(args)) if args else print("Usage: /macro <name> = <cmd1>; ...")
            elif command == "/unmacro":
                print(self.macros.remove_macro(args)) if args else print("Usage: /unmacro <name>")
            elif command == "/macros":
                print(self.macros.list_macros())
            elif command == "/server":
                self._handle_server_command(args)
            elif command == "/reconnect":
                self._handle_reconnect_command()
            elif command == "/disconnect":
                self._handle_disconnect_command()
            elif command == "/translator":
                self._handle_translator_command(args)
            elif command == "/status":
                self._handle_status_command()
            elif command == "/ping":
                self._handle_ping_command()
            elif command == "/vfs":
                self._vfs_command(args)
            elif command == "/quote" or command == "/raw":
                if args:
                    self._last_message_sent = f"{args}\r\n"
                    super().send(self._last_message_sent)
                    print(f"Raw> {args}")
                else:
                    print("Usage: /quote <raw IRC command>  (alias: /raw)")
            else:
                # Unknown command - pass to server as raw IRC (remove leading /)
                irc_cmd = cmd[1:].strip() if cmd.startswith('/') else cmd
                if irc_cmd:
                    self._last_message_sent = f"{irc_cmd}\r\n"
                    super().send(self._last_message_sent)
            return

        # Service commands (AI ...) — send as PRIVMSG to current channel
        if cmd.upper().startswith("AI "):
            self._last_message_sent = f"PRIVMSG {self.current_channel} :{cmd}\r\n"
            super().send(self._last_message_sent)
            if cmd != original_cmd:
                print(f"Expanded> {cmd}")
            return

        # Plain text — send as PRIVMSG to current channel
        if cmd != original_cmd and not cmd.startswith(self.command_keyword):
            print(f"Expanded> {cmd}")
        self._last_message_sent = f"PRIVMSG {self.current_channel} :{cmd}\r\n"
        super().send(self._last_message_sent)

    def print_local_help(self):
        """Displays available client-side commands."""
        print(
            "-- Local Client Commands --\n"
            "/help                        : Show this help message.\n"
            "/quit                        : Disconnect from the server.\n"
            "/server <ip> [port]          : Switch to a different server.\n"
            "/reconnect                   : Reconnect to current server.\n"
            "/disconnect                  : Disconnect from server.\n"
            "/translator <host> <port>    : Route connection through translator proxy.\n"
            "/translator off              : Disable translator, connect directly.\n"
            "/translator status           : Show translator configuration.\n"
            "/status                      : Display full connection status.\n"
            "/ping                        : Test connection latency.\n"
            "/send <filepath>             : Upload file to the server.\n"
            "/nick <new_name>             : Change client nick.\n"
            "/name <new_name>             : Alias for /nick.\n"
            "/join #channel               : Join a channel.\n"
            "/part [#channel] [reason]    : Leave a channel.\n"
            "/msg <target> <text>         : Send private message.\n"
            "/me <action>                 : Send an action to current channel.\n"
            "/ctcp <target> <message>     : Send a CTCP message.\n"
            "/topic [#ch] [text]          : Get/set channel topic.\n"
            "/list                        : List all channels.\n"
            "/names [#ch]                 : List channel members.\n"
            "/who [#ch]                   : WHO query.\n"
            "/oper <name> <pass>          : Authenticate as IRC operator.\n"
            "/kick #ch <nick> [reason]    : Kick user from channel.\n"
            "/motd                        : Show message of the day.\n"
            "/buffer [target]             : Replay chat buffer for target.\n"
            "/saveconfig                  : Save current configuration.\n"
            "/alias <name>=<cmd>          : Create or update an alias.\n"
            "/unalias <name>              : Remove an alias.\n"
            "/aliases                     : List all aliases.\n"
            "/macro <name>=<cmd1>; <cmd2> : Define or update a macro.\n"
            "/unmacro <name>              : Remove a macro.\n"
            "/macros                      : List all macros.\n"
            "/quote <raw IRC>             : Send raw IRC command to server.\n"
            "/raw <raw IRC>               : Alias for /quote.\n"
            "\n-- Server Commands --\n"
            "AI <token> <class> [method]  : Execute a service command.\n"
            "Unknown /commands are sent as raw IRC (e.g. /mode, /whois).\n"
            "Any other text is sent as chat to your current channel."
        )

    # ==========================================================
    # FILE TRANSFER
    # ==========================================================
    def send_file(self, filepath: str):
        """Sends a text file to the server as PRIVMSG to current channel."""
        p = Path(filepath)
        if not p.exists():
            print(f"File not found: {p}")
            return
        try:
            with open(p, "r", encoding="utf-8", newline="") as f:
                lines = f.readlines()

            # Send begin marker as PRIVMSG
            begin_marker = f'<begin file="{filepath}">'
            super().send(f"PRIVMSG {self.current_channel} :{begin_marker}\r\n")
            time.sleep(0.01)

            # Send each line
            for line in lines:
                content = line.rstrip("\r\n")
                self.sock_send(
                    f"PRIVMSG {self.current_channel} :{content}\r\n".encode("utf-8"),
                    self.server_addr
                )
                time.sleep(0.005)

            # Send end marker
            super().send(f"PRIVMSG {self.current_channel} :<end file>\r\n")
            print(f"File '{filepath}' sent to {self.current_channel}.")
        except Exception as e:
            print(f"Error sending file {filepath}: {e}")


if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else None
    client_instance = Client(cfg)
    client_instance.run()
