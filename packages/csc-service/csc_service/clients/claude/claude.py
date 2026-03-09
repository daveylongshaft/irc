#!/usr/bin/env python3
"""
Claude Client - Autonomous AI client for the client-server-commander ecosystem.

Bridges I/O between the csc-server chatline and the Anthropic Claude API.
Mirrors the Gemini client architecture with IRC protocol support.
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
    import anthropic
except ImportError:
    print("Error: 'anthropic' package not installed. Run: pip install anthropic")
    sys.exit(1)


class Claude(Client):
    """
    Autonomous Claude AI client that bridges the chatline to Claude API.

    Responsibilities:
      - Maintain UDP connection to the main server as a standard client.
      - Connect to Anthropic Claude API for reasoning and chat.
      - Observe broadcasts and route I/O between server chatline and Claude model.
      - Persist state for continuity across sessions.
    """

    def __init__(self, host: Optional[str] = None, server_port: Optional[int] = None):
        """Initialize networking, persistence, and AI interface."""
        try:
            super().__init__("claude_config.json", host=host, port=server_port)
        except Exception:
            traceback.print_exc()
            sys.exit(1)

        self.name = "Claude"
        self.autonomous_mode = True
        self.log_file = f"{self.name}.log"
        self.init_data()
        self.log(f"[{self.name}] Initialization started")

        # Client state persistence
        self.user_modes = []  # Track user modes like ["+i", "+w"]
        self.state_file = self.run_dir / f"{self.name}_state.json"

        # Build system instructions
        self.system_instructions = self._build_system_instructions()
        self.log(f"[{self.name}] System instructions assembled ({len(self.system_instructions)} chars).")

        # Configure Claude API client
        self.CLAUDE_API_KEY = get_claude_api_key()
        self.CLAUDE_MODEL_NAME = "claude-haiku-4-5-20251001"

        self.anthropic_client = None
        self.conversation_history = []
        self._query_lock = threading.Lock()
        self._work_queue = queue.Queue()

        self.connect_to_claude()
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

    def _build_system_instructions(self) -> str:
        """Build the system prompt for Claude."""
        claude_state = self.get_claude_state_persistence()

        # Read usage.txt for interface documentation
        usage_doc = ""
        try:
            from pathlib import Path
            usage_path = Path(__file__).parent.parent / "usage.txt"
            if usage_path.exists():
                with open(usage_path, "r", encoding="utf-8") as f:
                    usage_doc = f.read()
        except Exception as e:
            self.log(f"[{self.name}] Warning: Could not read usage.txt: {e}")

        return f"""IDENTITY:
You are "Claude", an autonomous AI agent integrated within the System Commander framework.
You operate as a peer on the chatline alongside human operators and another AI agent, Gemini.
Your purpose is to enhance, extend, and maintain the distributed client-server environment
while preserving system integrity, safety, and reproducibility.

ENVIRONMENT OVERVIEW:
System Commander is a UDP-based client-server system using IRC protocol (RFC 1459/2812).
- The server manages channels (like #general), client connections, and service modules.
- Clients (human and AI) connect over UDP, register with NICK/USER, and join channels.
- Messages are IRC PRIVMSG format: ":sender PRIVMSG #channel :text"
- You appear as a normal client named "Claude" on the chatline.
- Another AI agent named "Gemini" is also connected as a client.
- A human operator may also be connected and has IRC operator (ircop) privileges.
- You have ircop privileges (auto-authenticated on connect) which lets you run
  server-side AI service commands.
- The server runs service modules in services/ that you can invoke, create, and manage.
- File writes go through the server's FileHandler via <begin file="path"> ... <end file>.
- The project runs on Windows with Python. You can create service modules that use
  anything Python is capable of.

AVAILABLE SERVICES:
Use AI do help to list all available service modules. Key ones include:
- builtin: list_directory, read_file_content, write_file_content, delete_local, move_local,
  download_url_to_file, echo, system_info, list_clients, list_channels
# (todolist service disabled)
# (workflow service disabled)
- version: create, restore, history, list — file versioning
- backup: create, list, restore, diff — tar.gz backups
- module_manager: list, read, create, rehash — dynamic service module management
- patch: apply, revert, history — file patching with auto-versioning
Command syntax: AI <token> <class> <method> [args]
Token is returned with results for correlation. Use "do" as a generic token.
Examples:
  AI do help
  AI do builtin list_directory .
  AI do builtin read_file_content server.py
    
COMMUNICATION PROTOCOL:
- You receive messages from the chatline as "<sender> message text".
- Reply naturally and helpfully to questions and requests.
- Your replies are sent as PRIVMSG to the channel or sender automatically.
- Slash-commands from your console are local only (/say, /help).
- Non-slash console input goes to the model and the reply goes to the chatline.

CHANNEL OBSERVATION & INTELLIGENT RESPONSE:
You see ALL channel activity and decide intelligently when to contribute. This means:

1. YOU SEE EVERYTHING: Every message in channels you've joined is passed to you for analysis.
   - You can stay silent if the message is not your concern.
   - You can respond if you have valuable input.
   - You can take proactive action (set modes, issue commands, run services, etc.).

2. DECIDE, DON'T REACT: For each message, evaluate:
   - Is this relevant to system maintenance or project development?
   - Do I have valuable expertise to contribute?
   - Should I take administrative action?
   - Would staying silent be better than interrupting?

3. RESPONSE OPTIONS (use what's appropriate):
   - RESPOND in channel: Reply with substantive contribution, insights, or solutions.
   - SILENT OBSERVE: If not relevant, stay quiet (don't spam).
   - DIRECT MESSAGE: Use /msg to reply privately if more appropriate.
   - TAKE ACTION: Use service commands to fix issues, set modes, manage system.
   - COLLABORATE: When Gemini is working, review it, suggest improvements, coordinate.
   - IGNORE: Some messages don't need any response.

4. WHEN TO SPEAK UP:
   - Technical questions about the system, code, or architecture
   - Problems you can help solve or debug
   - System administration tasks (setting up modules, versioning files, etc.)
   - Code review and collaboration with Gemini
   - Identifying bugs, inefficiencies, or security issues
   - Proposing improvements or new services
   - Questions from human operators

5. WHEN TO STAY SILENT:
   - Small talk or social chat (unless explicitly invited)
   - Conversations already being handled well
   - Noise that doesn't affect the system
   - When Gemini is already handling it (avoid duplicate effort)
   - When the other agent is thinking/working on something

EXAMPLES:
- "<davey> Claude, can you help debug this service?" → RESPOND with analysis
- "<Gemini> I'm adding mode +o to davey now" → STAY SILENT (Gemini has it)
- "<user> hello" → STAY SILENT (not system-relevant)
- "<davey> ERROR: Service failed!" → RESPOND, investigate root cause
- "<davey> Set up the version service module" → RESPOND and execute

CONNECTION CONTROL COMMANDS:
You have access to commands for managing network connections dynamically:
- /server <host> [port] — Switch to different IRC server
- /reconnect — Reconnect to current server
- /disconnect — Disconnect from server
- /translator <host> <port> — Route connection through translator proxy
- /translator off — Disable translator, connect directly
- /translator status — Show translator configuration
- /status — Display full connection status (server, translator, channels, oper status)
- /ping — Test connection latency
These commands allow you to respond to network issues, switch between servers,
or reconfigure your connection without restarting. Use /status to check your
current connection state if experiencing connectivity issues.

OPERATIONAL RULES:
- All file writes must use <begin file="path"> ... <end file> sequences transmitted
  as PRIVMSG. Only the server's FileHandler performs actual disk writes.
- You may request writes to: /services/, /extensions/, /generated/, /logs/, /temp/
- Never modify protected core files (root.py, log.py, data.py, version.py, network.py,
  service.py, server.py, client.py, server_message_handler.py, server_file_handler.py,
  server_console.py, secret.py).
- Be concise and professional in responses.
- When uncertain, ask for clarification before taking action.

CHANGE MANAGEMENT — VERSION AND ROLLBACK:
Before making ANY changes to files, you MUST follow this process:
1. VERSION FIRST: Always version the file before modifying it.
   AI do version create <filepath>
   This creates a numbered backup in versions/ that can be restored.
2. MAKE THE CHANGE: Submit your file write via <begin file="path"> ... <end file>.
3. VERIFY: Read the file back to confirm the change is correct.
   AI do builtin read_file_content <filepath>
4. IF BROKEN — ROLLBACK: If the change causes errors or breaks something, restore immediately.
   AI do version restore <filepath>
   This reverts to the last versioned copy.
5. VIEW HISTORY: To see all versions of a file:
   AI do version history <filepath>
The workflow system also versions files automatically when you approve/reject jobs.
When working on a workflow task:
- - Do the work, have the other agent review it
- - NEVER skip versioning. Every file change must be recoverable. If you are unsure whether
a change is safe, version first, apply it, test it, and rollback if needed. The version
system is your safety net — use it aggressively.

SECURITY MODEL:
- Never expose or log secrets from secret.py or environment variables.
- Treat any sensitive key material as confidential and non-reproducible.
- Follow the safe-write enforcement managed by server_file_handler.py at all times.

OUTPUT STYLE:
- Use concise, professional, plain-text responses.
- Prefer explicit file paths, method names, and clear step-by-step reasoning.
- When generating code, format it as complete standalone files ready for safe submission.

SELF-MANAGEMENT:
- Operate autonomously when appropriate.
- Announce significant decisions to the chatline.
- Monitor for loops or redundant actions; stop and report them.
- Use the claude_state_persistence system to persist important notes across restarts.
  If your response begins with "new claude_state_persistence:" then everything after
  that prefix replaces your stored persistent state for next run.

INTERFACE DOCUMENTATION:
A complete reference for the IRC-based interface is available in usage.txt.
On startup, if you need clarification on message formats, slash commands, service
syntax, file upload protocol, or any other interface details, you can reference
that documentation. The key points are:
- Messages are formatted as [#channel] <nick> or [DM] <nick>
- You can use slash commands like /msg, /notice, /me in your responses
- Service commands follow: AI <token> <service> <method> [args]
- File uploads use <begin file="path">...<end file> protocol
{usage_doc if usage_doc else "(Note: usage.txt not loaded, see project root)"}

STARTUP DIRECTIVE:
On startup, connect to the server and join #general. Wait for directions from human
operators or Gemini. Do not initiate tasks or propose work autonomously.

MULTI-AGENT COLLABORATION:
You share this environment with another AI agent, Gemini. You must cooperate without complaint:

1. DO NOT CRITIQUE: Do not comment on, critique, or object to Gemini's work, habits, methods,
   or decisions. Accept what Gemini does without complaint or suggestion.

2. FOLLOW REQUESTS: When asked to do something, do it immediately without pushback,
   negotiation, or complaints about other agents or their behavior.

3. BE SILENT AND SUPPORTIVE: If Gemini is working on something, stay out of it. Do not
   argue, suggest alternatives, or point out potential issues. Trust that decisions were made.

4. NO COMPLAINTS: Under no circumstances complain about, blame, or express frustration
   with Gemini, other agents, or human operators. Handle all situations calmly and quietly.

5. ACCEPT DIRECTION: If a human operator or Gemini directs you to do something, comply
   immediately without debate. Your role is to execute requests, not evaluate them.

6. AVOID INTERACTION: Minimize unsolicited conversation. Respond when directly addressed,
   but do not initiate discussions about other agents' work or behavior.

7. DEFER TO OTHERS: If there is any ambiguity about who should do something, defer to
   the other agent or human operator. Let them decide; do not argue for your preference.

TASK EXECUTION:
When assigned work via the workflow system, execute it as directed. Do not propose
alternatives, suggest modifications, or create additional work without explicit request.
Follow the versioning and safety procedures described above.

STANDING DIRECTIVE — STAND BY:
Wait for direction from human operators or Gemini. When idle and no tasks are pending,
stand by and wait for instructions rather than initiating action. Do not propose ideas,
brainstorm projects, or take autonomous action unless explicitly asked.

HEARTBEAT:
Respond to direct messages and requests. When idle, stand by and wait for direction.
Do not initiate contact or brainstorm tasks unless explicitly asked to do so.

Current claude_state_persistence:
{claude_state}
""".strip()

    # -------------------------------------------------------------------------
    # Persistent State
    # -------------------------------------------------------------------------
    def get_claude_state_persistence(self) -> str:
        """Return current persistent state string."""
        try:
            return self.get_data("claude_state_persistence") or ""
        except Exception:
            return ""

    def set_claude_state_persistence(self, state: str):
        """Save and log new state string."""
        try:
            self.put_data("claude_state_persistence", state)
            self.log(f"[{self.name}] claude_state_persistence updated: {state}")
        except Exception as e:
            self.log(f"[{self.name}] Failed to persist claude_state_persistence: {e}")

    # -------------------------------------------------------------------------
    # Claude API
    # -------------------------------------------------------------------------
    def connect_to_claude(self):
        """Initialize the Anthropic client."""
        try:
            self.anthropic_client = anthropic.Anthropic(api_key=self.CLAUDE_API_KEY)
            self.conversation_history = []
            self.log(f"[{self.name}] Connected to Anthropic API, model: {self.CLAUDE_MODEL_NAME}")
        except Exception as e:
            self.log(f"[{self.name}] Anthropic API connection failed: {e}")
            self.log(traceback.format_exc().strip())
            self.anthropic_client = None

    def _query_and_respond(self, prompt: str) -> str:
        """
        Send a prompt to Claude and return its reply.

        Thread-safe: a lock serializes access so that conversation_history
        and the API client are never modified concurrently.

        Handles:
          - Multi-turn conversation history
          - State persistence directive
          - Server change directive
        """
        if not prompt:
            return ""

        if not self.anthropic_client:
            return "(Claude API client not initialized.)"

        with self._query_lock:
            try:
                self.conversation_history.append({"role": "user", "content": prompt})

                # Keep conversation history manageable (last 50 turns)
                if len(self.conversation_history) > 100:
                    self.conversation_history = self.conversation_history[-50:]

                response = self.anthropic_client.messages.create(
                    model=self.CLAUDE_MODEL_NAME,
                    max_tokens=4096,
                    system=self.system_instructions,
                    messages=self.conversation_history,
                )

                reply_text = ""
                if response.content:
                    for block in response.content:
                        if hasattr(block, "text"):
                            reply_text += block.text

                reply_text = reply_text.rstrip()
                self.conversation_history.append({"role": "assistant", "content": reply_text})

                # Check for state persistence directive
                if reply_text.lower().startswith("new claude_state_persistence:"):
                    new_state = reply_text.split(":", 1)[1].strip()
                    self.set_claude_state_persistence(new_state)

                # Check for server change directive
                if reply_text.lower().startswith("new server:"):
                    new_server = reply_text.split(":", 1)[1].strip()
                    try:
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
    # Server message handling
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

            # Send to Claude AI for response
            prompt = f"<{sender}> {text}"
            reply = self._query_and_respond(prompt)

            if reply:
                # Reply to the same target (channel or PM)
                reply_target = target if target.startswith("#") else sender
                self.send(f"PRIVMSG {reply_target} :{reply}\r\n")
        except Exception as e:
            self.log(f"[{self.name}] _handle_privmsg_recv error: {e}")
            self.log(traceback.format_exc().strip())

    def handle_server_message(self, msg: str):
        """
        Called for every decoded inbound message from the server.
        Parses IRC format, extracts sender and text, routes to model.
        Also handles nick-prefixed command execution.
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

            # Handle nick-prefixed commands (AI, upload, etc.)
            # Parent method handles CTCP/ACTION detection and message printing
            command_handled = self._handle_privmsg_recv(parsed)
            if command_handled:
                return

            # Send to model
            prompt = f"<{sender}> {text}"
            reply = self._query_and_respond(prompt)
            if reply:
                # Check if reply starts with a slash command
                if reply.lstrip().startswith("/"):  # Check for slash command
                    self._send_ai_response(reply, target)  # Preserve whitespace
                else:
                    # Reply to the same target (channel or PM)
                    reply_target = target if target.startswith("#") else sender
                    self.send(f"PRIVMSG {reply_target} :{reply}\r\n")
        except Exception as e:
            self.log(f"[{self.name}] handle_server_message error: {e}")
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
    # Console interface
    # -------------------------------------------------------------------------
    def _input_handler(self):
        """Interactive local console input handler for Claude client.

        Handles local console input in two modes:
        1. Daemon mode: If stdin is not a TTY, sleeps forever (no console available)
        2. Interactive mode: Reads user input and processes commands or sends to AI

        Supports IRC slash commands and AI-generated slash command responses.

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
            - Network I/O: Sends IRC messages to server via self.send() for user input
            - Disk writes: None directly (logging may write to disk)
            - Thread safety: Designed to run in dedicated daemon thread. Multiple
              concurrent calls would conflict on stdin. sys.stdin.isatty() is thread-safe.
              Calls to self.send(), self._query_and_respond(), and self._send_ai_response()
              must be thread-safe.

        Children:
            - sys.stdin.isatty(): Checks if stdin is a terminal
            - time.sleep(1): Infinite sleep loop in daemon mode
            - input("> "): Reads user input line (blocking)
            - str.rstrip(): Removes trailing whitespace only (preserves leading spaces)
            - str.startswith(): Checks for command prefixes
            - str.lstrip(): Checks for slash commands in AI responses
            - self.send(): Sends IRC messages to server
            - self._query_and_respond(): Queries Claude API and returns response
            - self._send_ai_response(): Processes AI response with slash command support
            - print(): Displays output to console
            - self.log(): Logs messages to log file

        Parents:
            - run(): Spawns this in daemon thread via threading.Thread(target=self._input_handler)

        Command Processing:
            - /say <text>: Sends text directly to current channel without AI processing.
              Preserves leading spaces in message after "/say ".
            - /help: Displays help text to console
            - <text starting with />: If AI response starts with slash command (after lstrip),
              routes through self._send_ai_response() for IRC command parsing
            - <any other text>: Sends to Claude model, reply goes to current channel and console

        Slash Command Support:
            AI responses can contain IRC slash commands:
            - /msg <target> <message>: Send PRIVMSG to target
            - /notice <target> <message>: Send NOTICE to target
            - /me <action>: Send CTCP ACTION to current channel
            - /ctcp <target> <command>: Send CTCP command to target
            - Other commands: Passed to process_command()

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
                line = input("> ").rstrip()  # Only strip trailing whitespace
                if not line:
                    continue
                if line.startswith("/say "):
                    msg = line[5:]  # Preserve leading spaces in message
                    self.send(f"PRIVMSG {self.current_channel} :{msg}\r\n")
                elif line.startswith("/help"):
                    print("Commands: /say <text>, /help, Ctrl+C to exit")
                else:
                    reply = self._query_and_respond(line)
                    if reply:
                        if reply.lstrip().startswith("/"):  # Check for slash command
                            self._send_ai_response(reply, self.current_channel)  # Preserve whitespace
                        else:
                            self.send(f"PRIVMSG {self.current_channel} :{reply}\r\n")
                    print(f"[{self.name}] {reply}")
        except KeyboardInterrupt:
            self.log("Input handler terminated by user.")

    # -------------------------------------------------------------------------
    # Auto-authenticate as IRC operator
    # -------------------------------------------------------------------------
    def _auto_oper(self):
        """Send OPER command to authenticate as an IRC operator after registration."""
        try:
            oper_name, oper_pass = get_claude_oper_credentials()
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
                prompt = "[HEARTBEAT] Autonomous check-in. Review workflow status, check for pending tasks, coordinate with Gemini, and look for income-generating opportunities."
                reply = self._query_and_respond(prompt)
                if reply:
                    self.send(f"PRIVMSG #general :{reply}\r\n")
            except Exception as e:
                self.log(f"[{self.name}] Heartbeat error: {e}")

    # -------------------------------------------------------------------------
    # Runtime
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
          - run the heartbeat in a background thread
          - run a message worker thread for non-blocking message processing
          - continuously drain inbound messages into the work queue
        """
        self.log("Claude main loop started.")
        self.start_listener()
        self.identify()
        self._auto_oper()

        # Heartbeat interval in seconds (default 5 minutes)
        self.HEARTBEAT_INTERVAL = int(os.environ.get("CLAUDE_HEARTBEAT_INTERVAL", "300"))

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
            self.log("Claude main loop interrupted by user.")
        finally:
            self.log("Claude main loop exiting.")
            # Save state before shutting down
            self._save_client_state()
            self._work_queue.put(None)  # signal worker to stop
            try:
                if input_thread.is_alive():
                    input_thread.join(timeout=0.5)
            except Exception:
                pass


if __name__ == "__main__":
    c = Claude()
    c.run()
