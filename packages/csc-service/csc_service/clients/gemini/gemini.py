#!/usr/bin/env python3
"""
Gemini Client – Autonomous AI client for the client-server-commander ecosystem.

Scope of this revision (I/O only)
---------------------------------
1) Start and maintain the UDP server connection like a regular Client:
   - start_listener(), identify(), and continuous inbound queue draining.
2) Bridge I/O unfiltered:
   - Every inbound chatline is sent as a prompt to Gemini.
   - Every Gemini response is sent back to the server.
3) Console behavior:
   - Slash-commands remain local-only (unchanged).
   - Non-slash input prompts the model and its reply is sent to the server.

Everything else (Gemini SDK setup, model/config parameters, persistence rules,
and existing command-processing semantics) remains unchanged.
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

from csc_service.clients.gemini.secret import (
    get_gemini_api_key,
    get_gemini_oper_credentials,
    load_initial_core_file_context,
    get_system_instructions,
)
from csc_service.shared.irc import parse_irc_message, format_irc_message, SERVER_NAME
from csc_service.clients.gemini.client import Client
from google import genai
from google.genai import types


class Gemini(Client):
    """
    Autonomous Gemini client.

    Responsibilities (unchanged intent):
      • Maintain UDP connection to the main server as a standard client.
      • Connect to Gemini API for reasoning and chat (original setup preserved).
      • Observe broadcasts and route I/O between server chatline and Gemini model.
      • Persist state as defined by existing directives in responses.
    """

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------
    def __init__(self, host: Optional[str] = None, server_port: Optional[int] = None):
        """
        Initialize networking, persistence, and AI interface.

        NOTE: Only I/O plumbing was added/adjusted. Original SDK setup and
        parameters are preserved exactly.
        """
        try:
            super().__init__("gemini_config.json", host=host, port=server_port)
        except Exception:
            traceback.print_exc()
            sys.exit(1)

        self.name = "Gemini"
        self.autonomous_mode = True
        self.log_file = f"{self.name}.log"
        self.init_data()
        self.log(f"[{self.name}] Initialization started")

        # Attributes used by handle_server_message
        self.connection_status = {'registered': False}
        self.joined_channels = set()
        self.current_channel = "#general"

        # Client state persistence
        self.user_modes = []  # Track user modes like ["+i", "+w"]
        self.state_file = self.run_dir / f"{self.name}_state.json"

        # Build system instructions + persistence context (original behavior)
        file_context = load_initial_core_file_context()
        base_instructions = get_system_instructions(file_context)
        gemini_state = self.get_gemini_state_persistence()

        self.system_instructions = (
            f"{base_instructions}\n\n## Current gemini_state_persistence\n{gemini_state}"
        )
        self.log(f"[{self.name}] System instructions assembled ({len(self.system_instructions)} chars).")

        # Configure Gemini SDK client (PRESERVED)
        self.GEMINI_API_KEY = get_gemini_api_key()
        self.GEMINI_MODEL_NAME = "gemini-2.5-flash-lite"

        self.gemini_client = None
        self.model_name = None
        self.chat_history = []
        self.gemini_chat = None
        self._query_lock = threading.Lock()
        self._work_queue = queue.Queue()

        self.connect_to_gemini()
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

    # -------------------------------------------------------------------------
    # Persistent State Handling (original semantics)
    # -------------------------------------------------------------------------
    def get_gemini_state_persistence(self) -> str:
        """Return current persistent state string."""
        try:
            return self.get_data("gemini_state_persistence") or ""
        except Exception:
            return ""

    def set_gemini_state_persistence(self, gemini_state_persistence: str):
        """Save and log new state string."""
        try:
            self.put_data("gemini_state_persistence", gemini_state_persistence)
            self.log(f"[{self.name}] gemini_state_persistence updated: {gemini_state_persistence}")
        except Exception as e:
            self.log(f"[{self.name}] Failed to persist gemini_state_persistence: {e}")

    def _fetch_gemini_state_persistence(self, timeout: float = 5.0) -> str:
        """Legacy compatibility wrapper."""
        return self.get_gemini_state_persistence()

    # -------------------------------------------------------------------------
    # Gemini API (original setup preserved)
    # -------------------------------------------------------------------------
    def connect_to_gemini(self):
        """
        Initialize the Google AI client and prepare a chat session.

        PRESERVED FROM ORIGINAL:
          - genai.Client(api_key=...)
          - self.model_name = self.GEMINI_MODEL_NAME
          - self.chat_history = []
          - chats.create(..., config=types.GenerateContentConfig(...)) with
            system_instruction, temperature, top_p, top_k, max_output_tokens.
        """
        try:
            self.gemini_client = genai.Client(api_key=self.GEMINI_API_KEY)
            self.model_name = self.GEMINI_MODEL_NAME
            self.chat_history = []
            self.gemini_chat = self.gemini_client.chats.create(
                model=self.model_name,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_instructions,
                    temperature=0.7,
                    top_p=0.9,
                    top_k=40,
                    max_output_tokens=8192,
                ),
            )
            self.log(f"[{self.name}] Connected to model {self.model_name}")
        except Exception as e:
            self.log(f"[{self.name}] Gemini API connection failed: {e}")
            self.log(traceback.format_exc().strip())
            self.gemini_client = None
            self.gemini_chat = None

    def _query_and_respond(self, prompt: str, skip_model: bool = False) -> str:
        """
        Send a prompt to Gemini and return its reply (plain text).

        Thread-safe: a lock serializes access so that chat_history and the
        Gemini chat session are never modified concurrently.

        If skip_model is True, the prompt is added to history but no API call is made.
        """
        if not prompt:
            return ""

        if not getattr(self, "gemini_client", None) or not getattr(self, "gemini_chat", None):
            return "(Gemini API client not initialized.)"

        with self._query_lock:
            try:
                self.chat_history.append({"role": "user", "content": prompt})
                
                if skip_model:
                    self.log(f"[{self.name}] Appended to history (observing): {prompt[:60]}...")
                    return ""

                self.log(f"[{self.name}] Sending to Gemini API: {prompt[:80]}")
                response = self.gemini_chat.send_message(message=prompt)

                reply_text = (
                    response.text.rstrip()
                    if hasattr(response, "text") and isinstance(response.text, str)
                    else str(response).rstrip()
                )
                self.log(f"[{self.name}] Gemini API replied: {repr(reply_text[:200]) if reply_text else '(empty)'}")
                self.chat_history.append({"role": "model", "content": reply_text})

                # Check for persistence update directive (PRESERVED)
                if reply_text.lower().startswith("new gemini_state_persistence:"):
                    new_state = reply_text.split(":", 1)[1].strip()
                    self.set_gemini_state_persistence(new_state)

                # Check for server change directive (PRESERVED)
                if reply_text.lower().startswith("new server:"):
                    new_server = reply_text.split(":", 1)[1].strip()
                    try:
                        # Use the same helper the client console command uses.
                        self.command_server(new_server)
                        reply_text = f"(changed servers) {new_server}"
                    except Exception as e:
                        self.log(f"[{self.name}] Failed to change server to '{new_server}': {e}")

                return reply_text
            except Exception as e:
                self.log(f"[{self.name}] Model error: {e}")
                self.log(traceback.format_exc().strip())
                return ""

    # -------------------------------------------------------------------------
    # Console interface (slash-commands local; non-slash -> model -> server)
    # -------------------------------------------------------------------------
    def _input_handler(self):
        """Interactive local console loop. Blocks on stdin; safe for daemon/no-TTY."""
        import sys
        if not sys.stdin.isatty():
            self.log("No TTY — input handler sleeping (daemon mode).")
            while True:
                time.sleep(60)
            return

        self.log("Input handler started.")
        try:
            while True:
                try:
                    line = input("> ").rstrip()
                except EOFError:
                    self.log("Input handler: EOF on stdin, switching to daemon mode.")
                    while True:
                        time.sleep(60)
                    return
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
                        if reply.lstrip().startswith("/"):
                            self._send_ai_response(reply, self.current_channel)
                        else:
                            self.send(f"PRIVMSG {self.current_channel} :{reply}\r\n")
                    print(f"[{self.name}] {reply}")
        except KeyboardInterrupt:
            self.log("Input handler terminated by user.")

    # -------------------------------------------------------------------------
    # Message routing override - ensure handle_server_message gets called
    # -------------------------------------------------------------------------
    def _handle_server_message_data(self, msg_data):
        """Override to call our custom handle_server_message for all messages."""
        try:
            # Extract message data
            if isinstance(msg_data, tuple) and msg_data:
                raw = msg_data[0]
            elif isinstance(msg_data, dict) and "data" in msg_data:
                raw = msg_data["data"]
            else:
                raw = msg_data

            # Decode to string
            if isinstance(raw, bytes):
                decoded = raw.decode("utf-8", errors="replace")
            elif isinstance(raw, str):
                decoded = raw
            else:
                decoded = str(raw)

            # Handle multi-line messages
            for line in decoded.splitlines():
                line = line.strip()
                if not line:
                    continue
                self.handle_server_message(line)
        except Exception as e:
            self.log(f"[{self.name}] Message processing error: {e}")

    # -------------------------------------------------------------------------
    # Server message handling – inbound -> model -> outbound (unfiltered)
    # -------------------------------------------------------------------------
    def _handle_privmsg_recv(self, parsed):
        """
        Override parent to add AI response logic.
        Called when a PRIVMSG is received.
        """
        try:
            # Get sender and text from parsed message
            sender = parsed.prefix.split("!")[0] if parsed.prefix else "unknown"
            target = parsed.params[0] if parsed.params else "#general"
            text = parsed.params[-1] if len(parsed.params) > 1 else ""

            # Skip our own messages
            if sender.lower() == self.name.lower():
                return

            # Display the message
            if target.startswith("#"):
                print(f"[{target}] {sender}: {text}")
            else:
                print(f"[DM] {sender}: {text}")

            # Send to Gemini AI for response
            prompt = f"<{sender}> {text}"
            reply = self._query_and_respond(prompt)

            if reply:
                # Reply to the same target (channel or PM)
                reply_target = target if target.startswith("#") else sender
                self.send(f"PRIVMSG {reply_target} :{reply}\r\n")
        except Exception as e:
            self.log(f"[{self.name}] _handle_privmsg_recv error: {e}")

    def handle_server_message(self, msg: str):
        """
        Called for every decoded inbound message from the server.
        Parses IRC format, extracts sender and text, routes to model.
        Also handles nick-prefixed command execution.
        """
        try:
            self.log(f"[DEBUG] handle_server_message called with: {msg}")
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
                else:
                    # Notify Gemini of other users joining
                    self.log(f"[DEBUG] Notifying model of join: {nick} joined {channel}")
                    prompt = f"* {nick} joined {channel}"
                    # Don't call _query_and_respond directly if it sends to server, 
                    # we want the model to decide what to do.
                    reply = self._query_and_respond(prompt)
                    if reply:
                        if reply.lstrip().startswith("/"):
                            self._send_ai_response(reply, channel)
                        else:
                            self.send(f"PRIVMSG {channel} :{reply}\r\n")
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

            # Handle nick-prefixed commands (AI, upload, etc.)
            # Parent method handles CTCP/ACTION detection and message printing
            command_handled = self._handle_privmsg_recv(parsed)
            if command_handled:
                return

            # Send to model - ALWAYS analyze channel activity
            # Let Gemini decide intelligently whether to respond or take action
            is_pm = not target.startswith("#")

            # For private messages, always respond. For channels, let the model decide
            # by analyzing context and determining if it has valuable input.
            if is_pm:
                # Direct message - always process and respond
                prompt = f"<{sender}> {text}"
                reply = self._query_and_respond(prompt, skip_model=False)
            else:
                # Channel message - send to model for judgment about relevance
                # The model can choose to: respond substantively, stay silent, or take action
                prompt = f"<{sender}> {text}"
                reply = self._query_and_respond(prompt, skip_model=False)
            
            if reply:
                # Check if reply starts with a slash command
                if reply.lstrip().startswith("/"):  # Check for slash command
                    self._send_ai_response(reply, target)  # Preserve whitespace
                else:
                    # Reply to the same target (channel or PM)
                    reply_target = target if target.startswith("#") else sender
                    self.log(f"[{self.name}] SENDING response to {reply_target}...")
                    start_time = time.perf_counter()
                    self.send(f"PRIVMSG {reply_target} :{reply}\r\n")
                    elapsed = time.perf_counter() - start_time
                    self.log(f"[{self.name}] SENT response in {elapsed:.4f}s")
        except Exception as e:
            self.log(f"[{self.name}] handle_server_message error: {e}")
            import traceback
            self.log(traceback.format_exc().strip())

    def _send_ai_response(self, response: str, context_target: str):
        """
        Send AI response to the server, handling slash commands.

        Args:
            response: The AI's response text
            context_target: The channel or nick context (for default target)
        """
        lines = response.split("\n")
        for line in lines:
            line = line.rstrip()  # Only strip trailing whitespace, preserve leading spaces
            if not line:
                continue

            if line.startswith("/msg "):
                # /msg target message
                parts = line.split(" ", 2)
                if len(parts) >= 3:
                    target = parts[1]
                    msg = parts[2]
                    self.send(f"PRIVMSG {target} :{msg}\r\n")
            elif line.startswith("/notice "):
                # /notice target message
                parts = line.split(" ", 2)
                if len(parts) >= 3:
                    target = parts[1]
                    msg = parts[2]
                    self.send(f"NOTICE {target} :{msg}\r\n")
            elif line.startswith("/me "):
                # /me action - send to context target
                action = line[4:]
                reply_target = context_target if context_target.startswith("#") else self.current_channel
                self.send(f"PRIVMSG {reply_target} :\x01ACTION {action}\x01\r\n")
            elif line.startswith("/ctcp "):
                # /ctcp target command
                parts = line.split(" ", 2)
                if len(parts) >= 3:
                    target = parts[1]
                    ctcp_cmd = parts[2]
                    self.send(f"PRIVMSG {target} :\x01{ctcp_cmd}\x01\r\n")
            elif line.startswith("/"):
                # Other slash commands - pass through to command processor
                self.process_command(line)
            else:
                # Regular text - send to context target
                reply_target = context_target if context_target.startswith("#") else self.current_channel
                self.send(f"PRIVMSG {reply_target} :{line}\r\n")

    # -------------------------------------------------------------------------
    # Auto-authenticate as IRC operator
    # -------------------------------------------------------------------------
    def _auto_oper(self):
        """Send OPER command to authenticate as an IRC operator after registration."""
        try:
            oper_name, oper_pass = get_gemini_oper_credentials()
            time.sleep(2)  # Allow server to finish processing registration
            self.send(f"OPER {oper_name} {oper_pass}\r\n")
            self.log(f"[{self.name}] Sent OPER authentication as '{oper_name}'")
        except Exception as e:
            self.log(f"[{self.name}] Auto-OPER failed: {e}")

    # -------------------------------------------------------------------------
    # Autonomous heartbeat
    # -------------------------------------------------------------------------
    def _heartbeat_loop(self):
        """
        Periodic autonomous heartbeat. Fires every HEARTBEAT_INTERVAL seconds.
        Sends a synthetic [HEARTBEAT] prompt to the model so it can check
        workflow status, propose work, and prevent stalls.
        """
        # Wait for initial startup settling
        time.sleep(30)
        self.log(f"[{self.name}] Heartbeat loop started (interval={self.HEARTBEAT_INTERVAL}s).")
        while True:
            try:
                time.sleep(self.HEARTBEAT_INTERVAL)
                self.log(f"[{self.name}] Heartbeat firing.")
                prompt = "[HEARTBEAT] Autonomous check-in. Review workflow status, check for pending tasks, coordinate with Claude, and look for income-generating opportunities."
                reply = self._query_and_respond(prompt)
                if reply:
                    self.send(f"PRIVMSG #general :{reply}\r\n")
            except Exception as e:
                self.log(f"[{self.name}] Heartbeat error: {e}")

    # -------------------------------------------------------------------------
    # Runtime – start listener, identify, drain queue continuously
    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # Message worker — processes server messages without blocking the main loop
    # -------------------------------------------------------------------------
    def _message_worker(self):
        """
        Dedicated thread for processing inbound server messages.

        Pulls message data from _work_queue and dispatches it.  This keeps the
        main loop free to drain the network queue even while an API call is
        in-flight.
        """
        while True:
            qsize = self._work_queue.qsize()
            if qsize > 5:
                self.log(f"[WARN] Message worker backlog: {qsize} messages")
            
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
                    elif isinstance(raw, dict) and "data" in raw:
                        d = raw["data"]
                        decoded = d.decode("utf-8", errors="replace") if isinstance(d, bytes) else str(d)
                    else:
                        decoded = str(raw)
                    self.handle_server_message(decoded)
                except Exception as e:
                    self.log(f"[{self.name}] decode/dispatch error: {e}")

    def run(self):
        """
        Start the UDP listener and identify with the server, then:
          • run the console in a background thread,
          • run the heartbeat in a background thread,
          • run a message worker thread for non-blocking message processing, and
          • continuously drain inbound messages into the work queue.
        """
        self.log("Gemini main loop started.")
        self.start_listener()
        self.identify()
        self._auto_oper()

        # Auto-join #general channel after registration
        time.sleep(2)  # Wait for registration to complete
        super().send("JOIN #general\r\n")
        self.log("[Gemini] Sent JOIN #general")

        # Heartbeat interval in seconds (default 5 minutes)
        self.HEARTBEAT_INTERVAL = int(os.environ.get("GEMINI_HEARTBEAT_INTERVAL", "300"))

        # Console in background so we can keep draining the network queue.
        input_thread = threading.Thread(target=self._input_handler, daemon=True)
        input_thread.start()

        # Heartbeat enabled for autonomous messaging
        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat_thread.start()

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
            self.log("Gemini main loop interrupted by user.")
        finally:
            self.log("Gemini main loop exiting.")
            # Save state before shutting down
            self._save_client_state()
            self._work_queue.put(None)  # signal worker to stop
            try:
                if input_thread.is_alive():
                    input_thread.join(timeout=0.5)
            except Exception:
                pass


if __name__ == "__main__":
    g = Gemini()
    g.run()
