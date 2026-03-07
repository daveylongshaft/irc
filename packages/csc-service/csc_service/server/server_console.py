import time
import getpass
from csc_service.shared.irc import format_irc_message, SERVER_NAME


class ServerConsole:
    """
    Interactive server administration console with authentication.

    Authentication:
      On startup, prompts for oper credentials.
      Authenticated: full access to all commands.
      Unauthenticated: read-only commands only (/clients, /channels, /help).

    Commands:
      /clients         - Show all clients (persistent + active).
      /channels        - List all channels with member counts.
      /kick <name>     - Disconnect all sessions for a given client name.
      /oper add <name> <password>  - Add oper credentials.
      /oper remove <name>          - Remove oper credentials.
      /set motd <msg>  - Set Message of the Day.
      /wallops <msg>   - Send WALLOPS to all opers.
      /help            - Show this help.
      /quit            - Shut down the server.
    """

    # Commands that don't require authentication
    READ_ONLY_COMMANDS = {"/clients", "/channels", "/help"}

    def __init__(self, server):
        """
        Initializes the instance.
        """
        self.server = server
        self.authenticated = False
        self.console_nick = "ServerAdmin"

    def _authenticate(self):
        """Prompt for oper credentials at startup."""
        print("\n--- Console Authentication ---")
        print("Enter oper credentials for admin access, or press Enter to skip (read-only mode).")
        try:
            nick = input("Nick: ").strip()
            if not nick:
                print("No credentials provided. Running in read-only mode.")
                print("Read-only commands: /clients, /channels, /help\n")
                return False

            try:
                password = getpass.getpass("Password: ")
            except (EOFError, KeyboardInterrupt):
                print("\nAuthentication cancelled. Running in read-only mode.")
                return False

            creds = self.server.oper_credentials
            if nick in creds and creds[nick] == password:
                self.console_nick = nick
                self.server.opers.add(nick)
                print(f"Authenticated as '{nick}'. Full admin access granted.")
                self.server.send_wallops(f"Console authenticated as {nick}")
                return True
            else:
                print("Invalid credentials. Running in read-only mode.")
                print("Read-only commands: /clients, /channels, /help\n")
                return False
        except (EOFError, KeyboardInterrupt):
            print("\nAuthentication cancelled.")
            return False

    def run_loop(self):
        """Main loop for handling admin commands."""
        self.authenticated = self._authenticate()

        print("\nServer is running. Type /help for a list of commands.")
        while self.server._running:
            try:
                cmd = input()
                if not cmd:
                    continue

                # Check if command requires authentication
                cmd_lower = cmd.lower()
                cmd_word = cmd_lower.split()[0] if cmd_lower.split() else ""

                if not self.authenticated:
                    if cmd_word not in self.READ_ONLY_COMMANDS:
                        print("Permission denied. Authenticate first or use read-only commands: /clients, /channels, /help")
                        continue

                if cmd_lower == "/quit":
                    self.server._running = False
                elif cmd_lower == "/clients":
                    self.list_clients()
                elif cmd_lower == "/channels":
                    self.list_channels()
                elif cmd_lower.startswith("/set motd "):
                    self.set_motd(cmd)
                elif cmd_lower.startswith("/kick "):
                    self.kick_client(cmd)
                elif cmd_lower.startswith("/oper "):
                    self.manage_oper(cmd)
                elif cmd_lower.startswith("/wallops "):
                    self.send_wallops_cmd(cmd)
                elif cmd_lower == "/help":
                    self.print_help()
                else:
                    # Broadcast admin message to all channels as NOTICE
                    prefix = f"{self.console_nick}!admin@{SERVER_NAME}"
                    for channel in self.server.channel_manager.list_channels():
                        notice = format_irc_message(
                            prefix,
                            "NOTICE", [channel.name], cmd
                        ) + "\r\n"
                        self.server.broadcast_to_channel(channel.name, notice)
                    self.server.send_wallops(f"Console ({self.console_nick}): {cmd}")
            except (EOFError, KeyboardInterrupt):
                self.server._running = False

    def list_clients(self):
        """Display both active and persisted clients."""
        print("--- Active Clients ---")
        if not self.server.clients:
            print("No active clients.")
        else:
            for addr, info in self.server.clients.items():
                name = info.get("name", "Unknown")
                seconds_ago = int(time.time() - info.get("last_seen", 0))
                channels = self.server.channel_manager.find_channels_for_nick(name)
                chan_names = ", ".join(ch.name for ch in channels) if channels else "(none)"
                oper_flag = " [OPER]" if name in self.server.opers else ""
                print(f"- {name}{oper_flag} ({addr[0]}:{addr[1]}) — Last seen {seconds_ago}s ago — Channels: {chan_names}")

        print("\n--- Known Clients (Persistent) ---")
        clients_data = self.server.get_data("clients") or {}
        if not clients_data:
            print("No persisted clients.")
        else:
            for name, entry in clients_data.items():
                print(f"{name}:")
                for addr in entry.get("addresses", []):
                    key = f"{addr[0]}:{addr[1]}"
                    seen = int(time.time() - entry["last_seen"].get(key, 0))
                    print(f"  - {addr[0]}:{addr[1]} (Last seen {seen}s ago)")
        print("----------------------")

    def list_channels(self):
        """Display all channels with member counts and topics."""
        print("--- Channels ---")
        channels = self.server.channel_manager.list_channels()
        if not channels:
            print("No channels.")
        else:
            for ch in channels:
                modes_str = f" [+{''.join(sorted(ch.modes))}]" if ch.modes else ""
                topic_str = f' — Topic: "{ch.topic}"' if ch.topic else ""
                print(f"  {ch.name} ({ch.member_count()} members){modes_str}{topic_str}")
                for nick in ch.members:
                    modes = ch.members[nick].get("modes", set())
                    if "o" in modes:
                        prefix = "@"
                    elif "v" in modes:
                        prefix = "+"
                    else:
                        prefix = " "
                    print(f"    {prefix}{nick}")
        print("----------------")

    def set_motd(self, cmd):
        """Set and broadcast a new Message of the Day."""
        parts = cmd.split(" ", 2)
        if len(parts) > 2 and parts[2]:
            new_motd = parts[2]
            self.server.motd = new_motd
            self.server.put_data("motd", self.server.motd)
            print("New MOTD set and saved.")
            # Broadcast as NOTICE to all channels
            prefix = f"{self.console_nick}!admin@{SERVER_NAME}"
            for channel in self.server.channel_manager.list_channels():
                notice = format_irc_message(
                    prefix,
                    "NOTICE", [channel.name], f"MOTD updated: {new_motd}"
                ) + "\r\n"
                self.server.broadcast_to_channel(channel.name, notice)
            self.server.send_wallops(f"MOTD updated by {self.console_nick}")
        else:
            print("Error: Usage /set motd <message>")

    def kick_client(self, cmd):
        """Disconnect all sessions for a client by name, removing from channels."""
        parts = cmd.split(" ", 1)
        if len(parts) < 2:
            print("Usage: /kick <name>")
            return

        target = parts[1].strip()
        removed = False

        # Remove from all channels
        removed_channels = self.server.channel_manager.remove_nick_from_all(target)

        # Send IRC KILL message and remove from active clients
        prefix = f"{self.console_nick}!admin@{SERVER_NAME}"
        for addr, info in list(self.server.clients.items()):
            if info.get("name") == target:
                # Send KILL notification
                kill_msg = format_irc_message(
                    prefix,
                    "KILL", [target], "Kicked by server admin"
                ) + "\r\n"
                self.server.sock_send(kill_msg.encode(), addr)

                # Send ERROR
                error_msg = f"ERROR :Closing Link: {target} (Kicked by admin)\r\n"
                self.server.sock_send(error_msg.encode(), addr)

                del self.server.clients[addr]
                self.server.message_handler.registration_state.pop(addr, None)
                removed = True

        if removed:
            # Notify remaining users in affected channels
            for chan_name in removed_channels:
                quit_notice = format_irc_message(
                    f"{target}!{target}@{SERVER_NAME}",
                    "QUIT", [], "Kicked by server admin"
                ) + "\r\n"
                self.server.broadcast_to_channel(chan_name, quit_notice)
            print(f"Kicked {target} (removed from {len(removed_channels)} channels)")
            self.server.send_wallops(f"{self.console_nick} kicked {target} via console")
        else:
            print(f"No active session found for '{target}'.")

    def manage_oper(self, cmd):
        """Manage oper credentials: /oper add <name> <pass> | /oper remove <name>"""
        parts = cmd.split()
        if len(parts) < 3:
            print("Usage: /oper add <name> <password>")
            print("       /oper remove <name>")
            return

        action = parts[1].lower()

        if action == "add":
            if len(parts) < 4:
                print("Usage: /oper add <name> <password>")
                return
            oper_name = parts[2]
            oper_pass = parts[3]
            self.server.oper_credentials[oper_name] = oper_pass
            self.server.put_data("oper_credentials", self.server.oper_credentials)
            print(f"Oper credentials added for '{oper_name}'.")

        elif action == "remove":
            oper_name = parts[2]
            if oper_name in self.server.oper_credentials:
                del self.server.oper_credentials[oper_name]
                self.server.put_data("oper_credentials", self.server.oper_credentials)
                # Also remove from active opers if they had it
                self.server.opers.discard(oper_name)
                print(f"Oper credentials removed for '{oper_name}'.")
            else:
                print(f"No oper credentials found for '{oper_name}'.")

        elif action == "list":
            print("--- Oper Credentials ---")
            for name in self.server.oper_credentials:
                active = " [ACTIVE]" if name in self.server.opers else ""
                print(f"  {name}{active}")
            print("------------------------")
        else:
            print(f"Unknown oper action: {action}")

    def send_wallops_cmd(self, cmd):
        """Send a WALLOPS message from the console."""
        parts = cmd.split(" ", 1)
        if len(parts) < 2 or not parts[1].strip():
            print("Usage: /wallops <message>")
            return
        message = parts[1].strip()
        self.server.send_wallops(f"[Console/{self.console_nick}] {message}")
        print(f"WALLOPS sent: {message}")

    def print_help(self):
        """Displays the help message for the server console."""
        auth_status = "AUTHENTICATED" if self.authenticated else "READ-ONLY"
        print(f"--- Server Commands [{auth_status}] ---")
        print("/clients                    : List active and known clients.")
        print("/channels                   : List all channels with members.")
        print("/help                       : Show this help message.")
        if self.authenticated:
            print("/quit                       : Shut down the server.")
            print("/set motd <msg>             : Set the message of the day.")
            print("/kick <name>                : Disconnect all sessions for a client.")
            print("/oper add <name> <password> : Add oper credentials.")
            print("/oper remove <name>         : Remove oper credentials.")
            print("/oper list                  : List oper credentials.")
            print("/wallops <message>          : Send WALLOPS to all opers.")
            print("<text>                      : Broadcast as NOTICE to all channels.")
        else:
            print("(Authenticate for full access: /quit, /kick, /oper, /set motd, /wallops)")
        print("-----------------------")
