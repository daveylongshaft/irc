import random
import threading
import logging
from pathlib import Path
from typing import List, Optional

from csc_clients.client.client import Client
from .perform import PerformManager
from .standoff import StandoffManager
from .context import ContextManager
from .ignore import IgnoreManager
from .focus import FocusManager

logger = logging.getLogger("csc.ai_api.client")

class AIClient(Client):
    """
    Base class for all AI agents.
    Ties together standoff, context, ignore, and focus management.
    Inherits from Client to provide IRC protocol and connectivity.
    """

    def __init__(self, config_path: Optional[str] = None, input_file: Optional[str] = None, output_file: Optional[str] = None):
        """
        Initializes the AIClient and its associated managers.
        """
        # Call super with config_path=None to avoid Client layer overwriting the INI file with JSON.
        super().__init__(config_path=None, input_file=input_file, output_file=output_file)

        # Resolve client.conf (INI) path
        conf_file = None
        if config_path:
            p = Path(config_path)
            if p.is_file():
                conf_file = p
            elif p.is_dir():
                conf_file = p / "client.conf"
        
        # Fallback to default location based on provided or default name
        if not conf_file or not conf_file.exists():
            # self.name is 'client' by default from super().__init__
            conf_file = self.get_agents_dir() / self.name / "client.conf"

        self._perform = PerformManager(conf_file)
        self._perform.load()

        # Update identity from PerformManager
        self.name = self._perform.nick
        # Update network settings
        self.host = self._perform.server
        self.port = self._perform.port
        self.server_addr = (self.host, self.port)

        # Re-initialize Data layer with a nick-specific JSON store (e.g., codex_data.json)
        # to prevent all agents from sharing 'client_data.json' or corrupting client.conf.
        self.init_data(f"{self.name}_data")

        # Initialize Managers with settings from PerformManager
        self._standoff = StandoffManager()
        
        backscroll = int(self._perform.get("ai", "backscroll", "20"))
        self._context = ContextManager(backscroll=backscroll)
        
        ignore_timeout = int(self._perform.get("ai", "ignore_timeout", "300"))
        self._ignore = IgnoreManager(timeout_secs=ignore_timeout)
        
        focus_window = int(self._perform.get("ai", "focus_window", "300"))
        self._focus = FocusManager(window_secs=focus_window)

    def run(self, interactive: bool = True):
        """
        Starts the AIClient, firing pre-connection events.
        """
        self._perform.fire("post_start")
        super().run(interactive=interactive)

    def _handle_numeric(self, parsed):
        """
        Overrides numeric handler to fire post-connection perform scripts on RPL_WELCOME.
        """
        super()._handle_numeric(parsed)
        if parsed.command == "001":
            self._perform.fire("post_connect", send_fn=self.send)

    def _handle_privmsg_recv(self, parsed):
        """
        Overrides PRIVMSG handler to implement AI response protocols.
        Routes messages through context, ignore, focus, and standoff managers.
        """
        # Extract message details
        prefix = parsed.prefix or ""
        nick = prefix.split("!")[0]
        channel = parsed.params[0]
        text = parsed.params[-1]

        # 1. Always buffer for context (backscroll should always grow regardless of filters)
        self._context.buffer(channel, nick, text)

        # 2. Handle !ignore commands
        if text.strip().startswith("!ignore"):
            self._ignore.parse(text, self.name)
            return

        # 3. Direct mention detection
        is_mention = self._context.is_direct_mention(text, self._perform.wakewords)

        # 4. Check if agent is currently ignored
        if self._ignore.is_ignored() and not is_mention:
            return

        # 5. Direct mention: Respond immediately and break ignore
        if is_mention:
            # Drop any pending coalesce timers for this channel
            self._standoff.cancel(channel)
            
            self._ignore.clear()
            context = self._context.get(channel)
            self._dispatch_respond(channel, context)
            # Re-focus window
            self._focus.mark_responded(channel)
            return

        # 6. If in focus window: use standoff coalescing
        if self._focus.is_focused(channel):
            self._standoff.add(channel, nick, text)
            
            standoff_min = int(self._perform.get("ai", "standoff_min", "2000"))
            standoff_max = int(self._perform.get("ai", "standoff_max", "5000"))
            delay = random.randint(standoff_min, standoff_max)
            
            self._standoff.start_or_reset(channel, delay, self._on_standoff_expire)
            return

        # Else: remain silent

    def _on_standoff_expire(self, channel: str, messages: List[tuple]):
        """
        Callback when standoff timer expires. Triggers response with collected context.
        """
        context = self._context.get(channel)
        self._dispatch_respond(channel, context)
        # Maintain focus window
        self._focus.mark_responded(channel)

    def _dispatch_respond(self, channel: str, context: List[str]):
        """
        Dispatches the response generation to a separate thread.
        """
        t = threading.Thread(target=self._respond_safe, args=(channel, context), daemon=True)
        t.start()

    def _respond_safe(self, channel: str, context: List[str]):
        """
        Helper method to call respond() safely and send the result.
        """
        try:
            response = self.respond(context)
            if response:
                # Using inherited send() method to transmit raw PRIVMSG
                self.send(f"PRIVMSG {channel} :{response}\r\n")
        except Exception as e:
            self.log(f"[AIClient] Error in respond(): {e}", level="ERROR")

    def respond(self, context: List[str]) -> Optional[str]:
        """
        Generates a response based on the provided context.
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement respond()")
