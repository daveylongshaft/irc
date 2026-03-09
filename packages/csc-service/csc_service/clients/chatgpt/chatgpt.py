#!/usr/bin/env python3
"""
ChatGPT Client - Autonomous AI client for the client-server-commander ecosystem.

Bridges I/O between the csc-server chatline and the OpenAI ChatGPT API.
Mirrors the Claude and Gemini client architecture with IRC protocol support.
"""

import os
import sys
import time
import threading
import traceback
import queue
import json

from typing import Optional
from pathlib import Path

from csc_service.shared.secret import get_claude_api_key, get_claude_oper_credentials
from csc_service.client.client import Client
from csc_service.shared.irc import parse_irc_message, format_irc_message, SERVER_NAME
try:
    import openai
except ImportError:
    print("Error: 'openai' package not installed. Run: pip install openai")
    sys.exit(1)


class ChatGPT(Client):
    """
    Autonomous ChatGPT AI client that bridges the chatline to OpenAI API.

    Responsibilities:
      - Maintain UDP connection to the main server as a standard client.
      - Connect to OpenAI ChatGPT API for reasoning and chat.
      - Observe broadcasts and route I/O between server chatline and ChatGPT model.
      - Persist state for continuity across sessions.
    """

    def __init__(self, host: Optional[str] = None, server_port: Optional[int] = None):
        """Initialize networking, persistence, and AI interface."""
        try:
            super().__init__("chatgpt_config.json", host=host, port=server_port)
        except Exception:
            traceback.print_exc()
            sys.exit(1)

        self.name = "ChatGPT"
        self.autonomous_mode = True
        self.log_file = f"{self.name}.log"
        self.init_data()
        self.log(f"[{self.name}] Initialization started")

        # Client state persistence
        self.user_modes = []  # Track user modes like ["+i", "+w"]
        self.state_file = self.run_dir / f"{self.name}_state.json"

        # Load config from file
        config_path = Path("chatgpt_config.json")
        if config_path.exists():
            with open(config_path, 'r') as f:
                self.config = json.load(f)
        else:
            self.config = {}

        # Configure OpenAI API client
        self.openai_api_key = self._get_openai_api_key()
        self.openai_model = self.config.get("model", "gpt-4o-mini")
        self.openai_temp = self.config.get("temperature", 0.7)
        self.openai_max_tokens = self.config.get("max_tokens", 500)

        self.openai_client = None
        self.conversation_history = []
        self._query_lock = threading.Lock()
        self._work_queue = queue.Queue()

        self.connect_to_openai()
        self.log(f"[{self.name}] Initialization complete and ready.")

        # Load client state from previous session
        self._load_client_state()

    # -------------------------------------------------------------------------
    # Client State Persistence
    # -------------------------------------------------------------------------
    def _save_client_state(self):
        """Save client state (nick, modes, channels) to JSON file."""
        try:
            state = {
                "nick": self.name,
                "modes": self.user_modes,
                "channels": list(self.joined_channels)
            }

            # Use atomic write pattern (temp file + rename)
            temp_file = self.state_file.with_suffix('.json.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)

            # Atomic rename
            temp_file.replace(self.state_file)
            self.log(f"[{self.name}] State saved to {self.state_file}")
        except Exception as e:
            self.log(f"[{self.name}] Failed to save state: {e}")

    def _load_client_state(self):
        """Load client state from JSON file if it exists."""
        try:
            if not self.state_file.exists():
                self.log(f"[{self.name}] No state file found at {self.state_file}")
                return None

            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)

            self.log(f"[{self.name}] State loaded from {self.state_file}: {state}")
            return state
        except json.JSONDecodeError as e:
            self.log(f"[{self.name}] Corrupt state file, ignoring: {e}")
            return None
        except Exception as e:
            self.log(f"[{self.name}] Failed to load state: {e}")
            return None

    def _restore_client_state(self):
        """Apply loaded state after successful server registration."""
        try:
            state = self._load_client_state()
            if not state:
                return

            # Restore nick if different
            saved_nick = state.get("nick")
            if saved_nick and saved_nick != self.name:
                self.log(f"[{self.name}] Restoring nick: {saved_nick}")
                super().send(f"NICK {saved_nick}\r\n")
                self.name = saved_nick
                time.sleep(0.2)

            # Restore user modes (if any)
            saved_modes = state.get("modes", [])
            for mode in saved_modes:
                if mode:
                    self.log(f"[{self.name}] Restoring mode: {mode}")
                    super().send(f"MODE {self.name} {mode}\r\n")
                    time.sleep(0.1)
            self.user_modes = saved_modes

            # Restore channels
            saved_channels = state.get("channels", [])
            for channel in saved_channels:
                if channel:
                    self.log(f"[{self.name}] Rejoining channel: {channel}")
                    super().send(f"JOIN {channel}\r\n")
                    time.sleep(0.1)

            self.log(f"[{self.name}] State restoration complete")
        except Exception as e:
            self.log(f"[{self.name}] Failed to restore state: {e}")

    def _load_env_file(self, env_path: str = "/opt/csc/.env") -> dict:
        """Load environment variables from .env file."""
        env_vars = {}
        try:
            if os.path.exists(env_path):
                with open(env_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            if "=" in line:
                                key, value = line.split("=", 1)
                                # Remove quotes if present
                                value = value.strip().strip("'").strip('"')
                                env_vars[key.strip()] = value
        except Exception as e:
            self.log(f"[{self.name}] Warning: Could not load .env file: {e}")
        return env_vars

    def _get_openai_api_key(self) -> str:
        """Retrieve OpenAI API key from .env, config, or environment (in that order)."""
        # Try .env file first (most common for this project)
        env_vars = self._load_env_file()
        api_key = env_vars.get("CHATGPT_API_KEY") or env_vars.get("OPENAI_API_KEY")

        # Fall back to environment variables
        if not api_key:
            api_key = os.environ.get("CHATGPT_API_KEY") or os.environ.get("OPENAI_API_KEY")

        # Fall back to config file
        if not api_key:
            api_key = self.config.get("api_key")

        if not api_key or api_key.startswith("sk-YOUR"):
            self.log(f"[{self.name}] WARNING: No valid OpenAI API key found!")
            self.log(f"[{self.name}] Set CHATGPT_API_KEY or OPENAI_API_KEY in /opt/csc/.env")

        return api_key

    def connect_to_openai(self):
        """Initialize the OpenAI client."""
        try:
            if not self.openai_api_key:
                self.log(f"[{self.name}] No OpenAI API key configured")
                return

            openai.api_key = self.openai_api_key
            self.openai_client = openai.OpenAI(api_key=self.openai_api_key)
            self.conversation_history = []
            self.log(f"[{self.name}] Connected to OpenAI API, model: {self.openai_model}")
        except Exception as e:
            self.log(f"[{self.name}] OpenAI API connection failed: {e}")
            self.log(traceback.format_exc().strip())
            self.openai_client = None

    def _query_and_respond(self, prompt: str) -> str:
        """
        Send a prompt to ChatGPT and return its reply.

        Thread-safe: a lock serializes access so that conversation_history
        and the API client are never modified concurrently.
        """
        if not prompt:
            return ""

        if not self.openai_client:
            return "(ChatGPT API client not initialized. Check API key in /opt/csc/.env)"

        with self._query_lock:
            try:
                self.conversation_history.append({"role": "user", "content": prompt})

                # Keep conversation history manageable (last 50 turns)
                if len(self.conversation_history) > 100:
                    self.conversation_history = self.conversation_history[-50:]

                response = self.openai_client.chat.completions.create(
                    model=self.openai_model,
                    messages=self.conversation_history,
                    temperature=self.openai_temp,
                    max_tokens=self.openai_max_tokens,
                )

                reply_text = ""
                if response.choices and response.choices[0].message:
                    reply_text = response.choices[0].message.content.rstrip()

                self.conversation_history.append({"role": "assistant", "content": reply_text})

                return reply_text
            except Exception as e:
                self.log(f"[{self.name}] API error: {e}")
                self.log(traceback.format_exc().strip())
                return f"(ChatGPT error: {str(e)[:100]})"

    # -------------------------------------------------------------------------
    # Server message handling
    # -------------------------------------------------------------------------
    def handle_server_message(self, msg: str):
        """
        Called for every decoded inbound message from the server.
        Parses IRC format, extracts sender and text, routes to model.
        """
        try:
            clean = (msg or "").rstrip("\r\n")

            # Parse IRC message
            parsed = parse_irc_message(clean)
            cmd = parsed.command.upper() if parsed.command else ""

            # Handle PING
            if cmd == "PING":
                token = parsed.params[0] if parsed.params else SERVER_NAME
                self.send(f"PONG :{token}\r\n")
                return

            # Handle WALLOPS
            if cmd == "WALLOPS":
                wallops_text = parsed.params[-1] if parsed.params else ""
                sender = parsed.prefix.split("!")[0] if parsed.prefix else SERVER_NAME
                print(f"[WALLOPS/{sender}] {wallops_text}")
                return

            # Handle NOTICE for formatted display
            if cmd == "NOTICE":
                sender = parsed.prefix.split("!")[0] if parsed.prefix else "?"
                target = parsed.params[0] if parsed.params else "?"
                text = parsed.params[-1] if parsed.params else ""
                if target.startswith("#"):
                    print(f"[{target}] *{sender}* {text}")
                else:
                    print(f"[DM] *{sender}* {text}")
                return

            # Handle nick in use - try alt nick
            if parsed.command == "433":
                self.send(f"NICK {self.name}_\r\n")
                return

            # Handle registration confirmation (001 RPL_WELCOME)
            if parsed.command == "001":
                self.connection_status['registered'] = True
                self.log(f"[{self.name}] Registration confirmed by server")
                # Restore saved state after successful registration
                self._restore_client_state()
                # Save initial state
                self._save_client_state()
                print(f"> {clean}")
                return

            # Handle JOIN
            if cmd == "JOIN":
                nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
                channel = parsed.params[0] if parsed.params else "?"
                if nick == self.name:
                    self.joined_channels.add(channel)
                    self._save_client_state()
                print(f"> {clean}")
                return

            # Handle PART
            if cmd == "PART":
                nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
                channel = parsed.params[0] if parsed.params else "?"
                if nick == self.name:
                    self.joined_channels.discard(channel)
                    self._save_client_state()
                print(f"> {clean}")
                return

            # Handle KICK
            if cmd == "KICK":
                target = parsed.params[1] if len(parsed.params) > 1 else "?"
                channel = parsed.params[0] if parsed.params else "?"
                if target == self.name:
                    self.joined_channels.discard(channel)
                    self._save_client_state()
                print(f"> {clean}")
                return

            # Handle MODE
            if cmd == "MODE":
                if len(parsed.params) >= 2:
                    target = parsed.params[0]
                    mode_str = parsed.params[1]
                    # Track user modes (not channel modes)
                    if target == self.name and not target.startswith("#"):
                        if mode_str.startswith("+"):
                            mode_to_add = mode_str
                            if mode_to_add not in self.user_modes:
                                self.user_modes.append(mode_to_add)
                        elif mode_str.startswith("-"):
                            mode_to_remove = "+" + mode_str[1:]
                            if mode_to_remove in self.user_modes:
                                self.user_modes.remove(mode_to_remove)
                        self._save_client_state()
                print(f"> {clean}")
                return

            # Skip non-message commands (numerics, etc.)
            if cmd != "PRIVMSG":
                print(f"> {clean}")
                return

            # Extract sender nick from prefix
            sender = parsed.prefix.split("!")[0] if parsed.prefix else "unknown"

            # Skip own messages to avoid loops
            if sender.lower() == self.name.lower():
                return

            # Extract target and text
            target = parsed.params[0] if parsed.params else "#general"
            text = parsed.params[-1] if len(parsed.params) > 1 else ""

            # Display the message
            if target.startswith("#"):
                print(f"[{target}] <{sender}> {text}")
            else:
                print(f"[DM] <{sender}> {text}")

            if not text:
                return

            # Send to model
            prompt = f"<{sender}> {text}"
            reply = self._query_and_respond(prompt)
            if reply:
                # Reply to the same target (channel or PM)
                reply_target = target if target.startswith("#") else sender
                self.send(f"PRIVMSG {reply_target} :{reply}\r\n")
        except Exception as e:
            self.log(f"[{self.name}] handle_server_message error: {e}")
            self.log(traceback.format_exc().strip())

    def _handle_server_message_data(self, msg_data):
        """Override parent to route all messages through ChatGPT's handler."""
        data, addr = msg_data
        try:
            msg = data.decode("utf-8", errors="ignore")
        except Exception as e:
            self.log(f"[DECODE ERROR] {e}")
            return
        for line in msg.splitlines():
            line = line.strip()
            if not line:
                continue
            self.handle_server_message(line)

    # -------------------------------------------------------------------------
    # Console interface
    # -------------------------------------------------------------------------
    def _input_handler(self):
        """Interactive local console input handler for ChatGPT client.

        Handles local console input in two modes:
        1. Daemon mode: If stdin is not a TTY, sleeps forever (no console available)
        2. Interactive mode: Reads user input and processes commands or sends to AI

        Args:
            None: Reads from stdin directly.

        Returns:
            None: Runs indefinitely until KeyboardInterrupt or thread termination.

        Raises:
            KeyboardInterrupt: Caught and logged, causes graceful exit from input loop.
            EOFError: If stdin is closed while reading input (not explicitly caught).

        Data:
            - Reads:
                - sys.stdin: For TTY detection and input() calls
                - self.current_channel (str): Default channel for messages
                - self.name (str): Client nickname for logging
            - Writes: None
            - Mutates: None directly (calls methods that send network messages)

        Side effects:
            - Logging: Logs "Running in daemon mode" or "Input handler started/terminated"
            - Network I/O: Sends PRIVMSG to server via self.send() for user input
            - Disk writes: None directly (logging may write to disk)
            - Thread safety: Designed to run in dedicated daemon thread. Multiple
              concurrent calls would conflict on stdin. sys.stdin.isatty() is thread-safe.
              Calls to self.send() and self._query_and_respond() must be thread-safe.

        Children:
            - sys.stdin.isatty(): Checks if stdin is a terminal
            - time.sleep(1): Infinite sleep loop in daemon mode
            - input("> "): Reads user input line (blocking)
            - str.rstrip(): Removes trailing whitespace from input
            - str.startswith(): Checks for command prefixes
            - self.send(): Sends IRC PRIVMSG to server
            - self._query_and_respond(): Queries ChatGPT API and returns response
            - print(): Displays output to console
            - self.log(): Logs messages to log file

        Parents:
            - run(): Spawns this in daemon thread via threading.Thread(target=self._input_handler)

        Command Processing:
            - /say <text>: Sends text directly to current channel without AI processing
            - /help: Displays help text to console
            - <any other text>: Sends to ChatGPT model, reply goes to current channel and console

        Daemon Mode:
            If stdin is not a TTY (e.g., running as systemd service, Docker container
            without -it flags), enters infinite sleep loop. This prevents input() from
            raising EOFError and allows the message worker thread to continue processing.
        """
        # Daemon mode check - no console input available
        import sys
        if not sys.stdin.isatty():
            self.log("Running in daemon mode (no console).")
            import time
            while True:
                time.sleep(1)
            return
        """
        Interactive local console loop.

        Rules:
          - '/say <text>' sends directly without AI processing
          - '/help' shows help
          - Non-slash text is sent to the model; reply goes to server
        """
        self.log("Input handler started.")
        try:
            while True:
                line = input("> ").rstrip()
                if not line:
                    continue
                if line.startswith("/say "):
                    msg = line[5:]
                    self.send(f"PRIVMSG {self.current_channel} :{msg}\r\n")
                elif line.startswith("/help"):
                    print("Commands: /say <text>, /help, Ctrl+C to exit")
                else:
                    reply = self._query_and_respond(line)
                    if reply:
                        self.send(f"PRIVMSG {self.current_channel} :{reply}\r\n")
                    print(f"[{self.name}] {reply}")
        except KeyboardInterrupt:
            self.log("Input handler terminated by user.")

    # -------------------------------------------------------------------------
    # Runtime
    # -------------------------------------------------------------------------
    def _message_worker(self):
        """
        Dedicated thread for processing inbound server messages.
        Pulls message data from _work_queue and dispatches it.
        """
        while True:
            msg_data = self._work_queue.get()
            if msg_data is None:
                break
            try:
                self._handle_server_message_data(msg_data)
            except Exception:
                try:
                    raw = msg_data[0] if isinstance(msg_data, tuple) and msg_data else msg_data
                    if isinstance(raw, bytes):
                        decoded = raw.decode("utf-8", errors="replace")
                    elif isinstance(raw, str):
                        decoded = raw
                    else:
                        decoded = str(raw)
                    self.handle_server_message(decoded)
                except Exception as e:
                    self.log(f"[{self.name}] decode/dispatch error: {e}")

    def run(self):
        """
        Start the UDP listener and identify with the server, then:
          - run the console in a background thread
          - run a message worker thread for non-blocking message processing
          - continuously drain inbound messages into the work queue
        """
        self.log("ChatGPT main loop started.")
        self.start_listener()
        self.identify()

        input_thread = threading.Thread(target=self._input_handler, daemon=True)
        input_thread.start()

        worker_thread = threading.Thread(target=self._message_worker, daemon=True)
        worker_thread.start()

        try:
            while input_thread.is_alive():
                msg_data = self.get_message()
                if msg_data:
                    self._work_queue.put(msg_data)
                else:
                    try:
                        self.maybe_send_keepalive()
                    except Exception:
                        pass
                    time.sleep(0.05)
        except KeyboardInterrupt:
            self.log("ChatGPT main loop interrupted by user.")
        finally:
            self.log("ChatGPT main loop exiting.")
            # Save state before shutting down
            self._save_client_state()
            self._work_queue.put(None)  # signal worker to stop
            try:
                if input_thread.is_alive():
                    input_thread.join(timeout=0.5)
            except Exception:
                pass


if __name__ == "__main__":
    c = ChatGPT()
    c.run()
