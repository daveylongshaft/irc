#!/usr/bin/env python3
"""
DMrBot - Local AI chatbot for the CSC ecosystem using Docker Model Runner.

Bridges I/O between the csc-server chatline and a local AI model via Docker Model Runner.
Follows the same architecture as Claude and Gemini clients for consistency.
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

try:
    from openai import OpenAI
except ImportError:
    print("Error: 'openai' package not installed. Run: pip install openai")
    sys.exit(1)

from csc_service.client.client import Client
from csc_service.shared.irc import parse_irc_message, format_irc_message, SERVER_NAME

class DMrBot(Client):
    """
    Autonomous local AI client that bridges the chatline to Docker Model Runner.
    """

    def __init__(self, host: Optional[str] = None, server_port: Optional[int] = None, config_path: Optional[str] = None):
        """Initialize networking, persistence, and AI interface."""
        cfg = config_path or "settings.json"
        try:
            super().__init__(cfg, host=host, port=server_port)
        except Exception:
            traceback.print_exc()
            sys.exit(1)

        self.name = "dMrBot"
        self.autonomous_mode = True
        self.log_file = f"{self.name}.log"
        self.init_data()
        self.log(f"[{self.name}] Initialization started")

        # DMR-specific settings (OpenAI-compatible API)
        self.dmr_endpoint = os.getenv("DMR_ENDPOINT", "http://localhost:12434/engines/v1")
        self.ai_model = os.getenv("DMR_MODEL", "ai/qwen:latest")
        
        # Load bot-specific settings from config
        self._load_bot_config()

        self.ai_client = OpenAI(
            base_url=self.dmr_endpoint,
            api_key="dummy"
        )

        # Client state persistence
        self.user_modes = []
        self.state_file = self.run_dir / f"{self.name}_state.json"
        self._query_lock = threading.Lock()
        self._work_queue = queue.Queue()

        self.log(f"[{self.name}] Initialized with model '{self.ai_model}' at '{self.dmr_endpoint}'")
        
        # Load client state from previous session
        self._load_client_state()

    def _load_bot_config(self):
        """Load bot-specific settings from config."""
        bot_cfg = self.get_data("bot_config") or {}
        if bot_cfg:
            self.dmr_endpoint = bot_cfg.get("dmr_endpoint", self.dmr_endpoint)
            self.ai_model = bot_cfg.get("model", self.ai_model)
            self.name = bot_cfg.get("nick", self.name)

    def _save_client_state(self):
        """Save client state (nick, modes, channels) to JSON file."""
        try:
            state = {
                "nick": self.name,
                "modes": self.user_modes,
                "channels": list(self.joined_channels)
            }
            temp_file = self.state_file.with_suffix('.json.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            temp_file.replace(self.state_file)
            self.log(f"[{self.name}] State saved to {self.state_file}")
        except Exception as e:
            self.log(f"[{self.name}] Failed to save state: {e}")

    def _load_client_state(self):
        """Load client state from JSON file if it exists."""
        try:
            if not self.state_file.exists():
                return None
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            self.log(f"[{self.name}] State loaded from {self.state_file}")
            return state
        except Exception as e:
            self.log(f"[{self.name}] Failed to load state: {e}")
            return None

    def _restore_client_state(self):
        """Apply loaded state after successful server registration."""
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

        # Restore user modes
        saved_modes = state.get("modes", [])
        for mode in saved_modes:
            if mode:
                super().send(f"MODE {self.name} {mode}\r\n")
                time.sleep(0.1)
        self.user_modes = saved_modes

        # Restore channels
        saved_channels = state.get("channels", [])
        for channel in saved_channels:
            if channel:
                super().send(f"JOIN {channel}\r\n")
                time.sleep(0.1)

    def _query_and_respond(self, prompt: str) -> str:
        """Send a prompt to Docker Model Runner and return its reply."""
        if not prompt:
            return ""

        with self._query_lock:
            try:
                # Clean prompt of our nick to avoid self-reference confusion
                clean_prompt = prompt.replace(f"{self.name}:", "").replace(self.name, "").strip()

                response = self.ai_client.chat.completions.create(
                    model=self.ai_model,
                    messages=[
                        {"role": "system", "content": f"You are {self.name}, a helpful local AI assistant in the CSC ecosystem."},
                        {"role": "user", "content": clean_prompt}
                    ]
                )

                reply_text = response.choices[0].message.content.strip()
                return reply_text
            except Exception as e:
                self.log(f"[{self.name} ERROR] AI Query failed: {e}")
                return "Error contacting local AI model."

    def _handle_privmsg_recv(self, parsed):
        """Handle received PRIVMSG - route between commands and AI."""
        sender = parsed.prefix.split("!")[0] if parsed.prefix else "unknown"
        target = parsed.params[0] if parsed.params else "#general"
        text = parsed.params[-1] if len(parsed.params) > 1 else ""

        # Skip our own messages to avoid loops
        if sender.lower() == self.name.lower():
            return

        # Handle CTCP/ACTION and print to console
        if super()._handle_privmsg_recv(parsed):
            return True

        # AI Trigger logic: Respond if mentioned or in DM
        is_dm = not target.startswith("#")
        is_mentioned = f"{self.name}:" in text or f"{self.name} " in text or self.name.lower() in text.lower()

        if is_mentioned or is_dm:
            prompt = f"Message from {sender}: {text}"
            reply = self._query_and_respond(prompt)
            if reply:
                reply_target = target if target.startswith("#") else sender
                self._send_ai_response(reply, reply_target)
            return True

        return False

    def _send_ai_response(self, response: str, context_target: str):
        """Send AI response to the server, handling slash commands."""
        for line in response.splitlines():
            line = line.rstrip()
            if not line:
                continue

            if line.startswith("/msg "):
                parts = line.split(" ", 2)
                if len(parts) >= 3:
                    self.send(f"PRIVMSG {parts[1]} :{parts[2]}\r\n")
            elif line.startswith("/notice "):
                parts = line.split(" ", 2)
                if len(parts) >= 3:
                    self.send(f"NOTICE {parts[1]} :{parts[2]}\r\n")
            elif line.startswith("/me "):
                self.send(f"PRIVMSG {context_target} :\x01ACTION {line[4:]}\x01\r\n")
            elif line.startswith("/"):
                self.process_command(line)
            else:
                self.send(f"PRIVMSG {context_target} :{line}\r\n")
            time.sleep(0.1)

    def handle_server_message(self, msg: str):
        """Parse IRC format and route messages."""
        try:
            clean = (msg or "").rstrip("\r\n")
            parsed = parse_irc_message(clean)
            cmd = parsed.command.upper() if parsed.command else ""

            if cmd == "PING":
                token = parsed.params[0] if parsed.params else SERVER_NAME
                self.send(f"PONG :{token}\r\n")
                return

            if cmd == "001":
                self.connection_status['registered'] = True
                self.log(f"[{self.name}] Registration confirmed")
                self._restore_client_state()
                self._save_client_state()
                self._auto_oper()
                return

            if cmd == "PRIVMSG":
                self._handle_privmsg_recv(parsed)
            
            elif cmd in ("JOIN", "PART", "KICK", "MODE"):
                nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
                if nick == self.name:
                    channel = parsed.params[0] if parsed.params else "?"
                    if cmd == "JOIN": self.joined_channels.add(channel)
                    else: self.joined_channels.discard(channel)
                    self._save_client_state()

        except Exception as e:
            self.log(f"[{self.name}] Error in handle_server_message: {e}")

    def _auto_oper(self):
        """Send OPER command to authenticate as an IRC operator."""
        try:
            # Check for oper credentials in config
            oper_cfg = self.get_data("oper_credentials")
            if oper_cfg:
                user = oper_cfg.get("user")
                password = oper_cfg.get("pass")
                if user and password:
                    time.sleep(2)
                    self.send(f"OPER {user} {password}\r\n")
                    self.log(f"[{self.name}] Sent OPER authentication as '{user}'")
        except Exception as e:
            self.log(f"[{self.name}] Auto-OPER failed: {e}")

    def _heartbeat_loop(self):
        """Periodic autonomous heartbeat check-in."""
        time.sleep(30)
        interval = int(os.getenv("DMRBOT_HEARTBEAT_INTERVAL", "300"))
        self.log(f"[{self.name}] Heartbeat loop started (interval={interval}s)")
        while True:
            try:
                time.sleep(interval)
                self.log(f"[{self.name}] Heartbeat firing")
                # Local bots might not need autonomous heartbeats as much, 
                # but we'll include it for consistency with Claude/Gemini.
            except Exception as e:
                self.log(f"[{self.name}] Heartbeat error: {e}")

    def _input_handler(self):
        """Interactive local console loop or daemon sleep."""
        if not sys.stdin.isatty():
            self.log("Running in daemon mode (no console).")
            while True:
                time.sleep(60)
            return

        self.log("Input handler started.")
        try:
            while True:
                line = input("> ").rstrip()
                if not line:
                    continue
                if line.startswith("/say "):
                    self.send(f"PRIVMSG {self.current_channel} :{line[5:]}\r\n")
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
            self.log("Input handler terminated.")

    def _message_worker(self):
        """Process inbound server messages in a separate thread."""
        while True:
            msg_data = self._work_queue.get()
            if msg_data is None:
                break
            try:
                # Handle different formats from Network.get_message()
                if isinstance(msg_data, tuple) and msg_data:
                    raw = msg_data[0]
                else:
                    raw = msg_data

                if isinstance(raw, bytes):
                    decoded = raw.decode("utf-8", errors="replace")
                else:
                    decoded = str(raw)

                for line in decoded.splitlines():
                    if line.strip():
                        self.handle_server_message(line)
            except Exception as e:
                self.log(f"[{self.name}] Worker error: {e}")

    def run(self, interactive=False):
        """Start all bot threads and the main loop."""
        self.log(f"[{self.name}] Starting DMrBot main loop")
        self.start_listener()
        self.identify()

        # Start background threads
        threading.Thread(target=self._message_worker, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        input_thread = threading.Thread(target=self._input_handler, daemon=True)
        input_thread.start()

        try:
            while input_thread.is_alive():
                msg_data = self.get_message()
                if msg_data:
                    self._work_queue.put(msg_data)
                else:
                    self.maybe_send_keepalive()
                    time.sleep(0.05)
        except KeyboardInterrupt:
            self.log("Main loop interrupted")
        finally:
            self._save_client_state()
            self._work_queue.put(None)
            self.log("DMrBot exiting")

if __name__ == "__main__":
    DMrBot().run(interactive=True)
