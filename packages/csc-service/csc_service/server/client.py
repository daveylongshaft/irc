import sys
import json
import time
import threading
from pathlib import Path
import socket
from network import Network
from aliases import Aliases
from macros import Macros
from csc_service.shared.data import Data
from csc_service.shared.irc import parse_irc_message, format_irc_message, SERVER_NAME


class Client(Network):
    """
    UDP client with IRC protocol support, identity, macros, aliases, and text-file uploads.
    """

    def __init__(self, config_path=None):
        """
        Initializes the instance.
        """
        self.config_file = Path(config_path or "client_config.json")

        # Initialize the full parent chain first (Data → Version → Network).
        # This ensures _storage_lock and other base attributes exist before
        # we load config (which may call put_data to write defaults).
        super().__init__(host="127.0.0.1", port=9525, name="client")

        # Now safe to load config — _storage_lock exists from Data.__init__.
        self.init_data(self.config_file)
        self._load_config()

        # Update Network attributes with values loaded from config.
        self.server_addr = (self.server_host, self.server_port)

        self.aliases = Aliases(self)
        self.macros = Macros(self)
        self._last_message_sent = None

        # IRC channel tracking
        self.current_channel = "#general"

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

    def _save_config(self):
        """Saves all client data back to config file."""
        self.store_data()

    # ==========================================================
    # SERVER SWITCH COMMAND
    # ==========================================================
    def command_server(self, args: str):
        """
        /server <ip> [port]
        Switches to a new server and re-identifies.
        """
        try:
            parts = args.strip().split()
            if not parts:
                print("Usage: /server <ip> [port]")
                return

            new_host = parts[0]
            new_port = int(parts[1]) if len(parts) > 1 else self.server_port
            new_server = f"{new_host}:{new_port}"

            try:
                self.put_data("server-3", self.get_data("server-2"))
                self.put_data("server-2", self.get_data("server-1"))
                self.put_data("server-1", self.get_data("server"))
            except Exception as e:
                self.log(f"[Client] Warning while backing up servers: {e}")

            self.put_data("server", new_server)
            self.put_data("server_host", new_host)
            self.put_data("server_port", new_port)
            self._save_config()

            self.log(f"[Client] Closing current connection to {self.server_addr}")
            try:
                self.sock.close()
            except Exception as e:
                self.log(f"[Client] Socket close error: {e}")

            self.server_host = new_host
            self.server_port = new_port
            self.server_addr = (new_host, new_port)
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(1.0)

            self.start_listener()
            self.identify()

            self.log(f"[Client] Switched to new server {self.server_addr}")
            print(f"Switched to new server {new_host}:{new_port}")

        except Exception as e:
            self.log(f"[Client ERROR] Failed to switch server: {e}")
            print(f"Error switching server: {e}")

    # ==========================================================
    # IDENTITY (IRC Registration)
    # ==========================================================
    def identify(self):
        """Send IRC registration sequence: NICK + USER."""
        super().send(f"NICK {self.name}\r\n")
        super().send(f"USER {self.name} 0 * :{self.name}\r\n")
        self.log(f"Sent IRC registration as '{self.name}'")

    # ==========================================================
    # MAIN LOOP
    # ==========================================================
    def run(self):
        """Starts listener thread and handles input."""
        self.start_listener()
        self.identify()

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
            print("\nDisconnected from server.")

    # ==========================================================
    # INPUT HANDLING
    # ==========================================================
    def _input_loop(self):
        """Handles blocking user input in a separate thread."""
        in_file_paste_mode = False
        pasted_lines = []

        while self._running:
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
            print(f"* {nick} has joined {channel}")
            return

        if cmd == "PART":
            nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
            channel = parsed.params[0] if parsed.params else "?"
            reason = parsed.params[-1] if len(parsed.params) > 1 else ""
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
            print(f"* {nick} has quit" + (f" ({reason})" if reason else ""))
            return

        if cmd == "MODE":
            print(f"* Mode: {line}")
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
                print(f"[NAMES] {chan}: {names}")
            else:
                print(f"[NAMES] {text}")
            return
        if num == "366":  # RPL_ENDOFNAMES
            return

        # OPER
        if num == "381":  # RPL_YOUREOPER
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

    def _handle_privmsg_recv(self, parsed):
        """Handle received PRIVMSG."""
        nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
        target = parsed.params[0] if parsed.params else "?"
        text = parsed.params[-1] if len(parsed.params) > 1 else ""

        # CTCP / ACTION detection
        if text.startswith("\x01") and text.endswith("\x01"):
            ctcp_body = text[1:-1]
            if ctcp_body.startswith("ACTION "):
                action = ctcp_body[7:]
                if target.startswith("#"):
                    print(f"[{target}] **{nick}** {action}")
                else:
                    print(f"[PM] **{nick}** {action}")
            else:
                print(f"[[{nick} CTCP]] {ctcp_body}")
            return

        if target.startswith("#"):
            # Channel message
            print(f"[{target}] <{nick}> {text}")
        else:
            # Private message
            print(f"[PM from {nick}] {text}")

    def _handle_notice_recv(self, parsed):
        """Handle received NOTICE."""
        nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
        text = parsed.params[-1] if parsed.params else ""

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

        print(f"-{nick}- {text}")

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
            elif command == "/whois":
                if args:
                    parts_split = args.split()
                    if len(parts_split) == 1:
                        # WHOIS <nick>
                        super().send(f"WHOIS {parts_split[0]}\r\n")
                    elif len(parts_split) >= 2:
                        # WHOIS [server] <nick>
                        super().send(f"WHOIS {parts_split[0]} {parts_split[1]}\r\n")
                else:
                    print("Usage: /whois [server] <nick>")
            elif command == "/whowas":
                if args:
                    parts_split = args.split()
                    nick = parts_split[0]
                    count = parts_split[1] if len(parts_split) > 1 else ""
                    server = parts_split[2] if len(parts_split) > 2 else ""
                    if count and server:
                        super().send(f"WHOWAS {nick} {count} {server}\r\n")
                    elif count:
                        super().send(f"WHOWAS {nick} {count}\r\n")
                    else:
                        super().send(f"WHOWAS {nick}\r\n")
                else:
                    print("Usage: /whowas <nick> [count] [server]")
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
                self.command_server(args)
            else:
                print(f"Unknown local command: {command}")
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
            "/server <ip> [port]          : Change to a new server.\n"
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
            "/whois <nick>                : Get information about a user.\n"
            "/whowas <nick>               : Get information about disconnected user.\n"
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
            "\n-- Server Commands --\n"
            "AI <token> <class> [method]  : Execute a service command.\n"
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
