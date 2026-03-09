import os
import sys
import time
from pathlib import Path
from csc_service.clients.client.client import Client
from csc_service.shared.irc import parse_irc_message, format_irc_message, SERVER_NAME
from csc_service.clients.client.client_service_handler import ClientServiceHandler

class ScriptBot(Client):
    """
    Non-AI Script Runner Bot.
    Dedicated to executing service commands and receiving module uploads.
    """
    def __init__(self, config_path=None, host=None, port=None):
        # Default config filename if none provided
        cfg = config_path or "scriptbot_config.json"
        super().__init__(config_path=cfg, host=host, port=port)
        
        # Use shared service handler
        self._client_service_handler = ClientServiceHandler(self)
        self.log(f"[ScriptBot] Initialized with nick '{self.name}'")

    def _handle_privmsg_recv(self, parsed):
        """Handle received PRIVMSG - focus on commands and uploads."""
        nick = parsed.prefix.split("!")[0] if parsed.prefix else "?"
        target = parsed.params[0] if parsed.params else "?"
        text = parsed.params[-1] if len(parsed.params) > 1 else ""
        prefix_full = parsed.prefix or ""

        # Handle DCC (SEND/DATA/EOF/ACK)
        if text.startswith("\x01") and text.endswith("\x01"):
            ctcp_body = text[1:-1]
            if ctcp_body.upper().startswith("DCC "):
                self._handle_dcc_recv(nick, ctcp_body)
            return True

        # Log incoming messages to console (optional for headless but good for debugging)
        if target.startswith("#"):
            print(f"[{target}] <{nick}> {text}")
        else:
            print(f"[PM from {nick}] {text}")

        # Check for active inline upload session
        if self._client_service_handler.upload_sessions.get(nick):
            filename, message = self._client_service_handler.handle_inline_upload(nick, text)
            if message:
                self.log(f"[DCC] {message}")
                if filename:
                    reply_target = target if target.startswith("#") else nick
                    super().send(f"PRIVMSG {reply_target} :{message}\r\n")
            return True

        # Check for nick-prefixed command: "<own_nick> do <service> <method> [args]"
        # Or simple: "<own_nick> <token> <service> <method>"
        nick_prefix = f"{self.name} "
        if text.startswith(nick_prefix):
            # Auth check: sender must be authorized (from client.py)
            if not self._is_authorized(nick, target if target.startswith("#") else None):
                self.log(f"[SECURITY] ???? Unauthorized command from {nick} ignored.")
                return True

            cmd_text = text[len(nick_prefix):].strip()
            reply_target = target if target.startswith("#") else nick

            # Handle "do" prefix for consistency with AI command style
            if cmd_text.lower().startswith("do "):
                cmd_text = cmd_text[3:].strip()
                # Ensure it has a token (ScriptBot commands don't strictly need one, but handler expects it)
                if not cmd_text.split()[0].isdigit():
                    cmd_text = f"0 {cmd_text}" # Default token 0

            # Execute via shared handler
            token, result = self._client_service_handler.execute(cmd_text, nick)
            
            if token != "0":
                full_response = f"{token} {result}"
                super().send(f"PRIVMSG {reply_target} :{full_response}\r\n")
            elif result:
                # Even with token 0, we might want to return result for ScriptBot
                super().send(f"PRIVMSG {reply_target} :{result}\r\n")
            
            return True

        return False
