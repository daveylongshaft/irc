import random
import threading
from pathlib import Path

from csc_clients.client.client import Client
from .perform import PerformManager
from .standoff import StandoffManager
from .context import ContextManager
from .ignore import IgnoreManager
from .focus import FocusManager


class AIClient(Client):
    """Abstract AI IRC client.

    Inherits the full Client/Network/Data stack and adds:
      - PerformManager  : client.conf lifecycle hooks and variable substitution
      - StandoffManager : coalescing delay before responding
      - ContextManager  : per-channel backscroll buffer and wakeword detection
      - IgnoreManager   : !ignore silencing with timeout
      - FocusManager    : engagement window after responding

    Subclasses must implement respond(context: list[str]) -> str.
    """

    def __init__(self, config_path=None, input_file=None, output_file=None):
        # Locate client.conf: explicit path, then cwd, then ops/agents/<nick>/
        conf = self._find_client_conf(config_path)
        self._perform = PerformManager(conf)
        self._perform.load()

        # Bootstrap Client with identity from client.conf
        super().__init__(config_path=config_path, input_file=input_file, output_file=output_file)

        # Override network identity from client.conf if present
        nick = self._perform.nick
        if nick and nick != "ai":
            self.name = nick
        srv = self._perform.server
        port = self._perform.port
        if srv:
            self.server_host = srv
            self.server_addr = (srv, port)
            self.server_port = port

        backscroll = int(self._perform.get("ai", "backscroll", "20"))
        ignore_t   = int(self._perform.get("ai", "ignore_timeout", "300"))
        focus_w    = int(self._perform.get("ai", "focus_window", "300"))

        self._standoff = StandoffManager()
        self._context  = ContextManager(backscroll=backscroll)
        self._ignore   = IgnoreManager(timeout_secs=ignore_t)
        self._focus    = FocusManager(window_secs=focus_w)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self, interactive=True):
        self._perform.fire("post_start")
        super().run(interactive)

    def _handle_numeric(self, parsed):
        super()._handle_numeric(parsed)
        if parsed.command == "001":
            self._perform.fire("post_connect", send_fn=self.send)

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def _handle_privmsg_recv(self, parsed):
        nick    = parsed.prefix.split("!")[0] if parsed.prefix else "?"
        channel = parsed.params[0] if parsed.params else ""
        text    = parsed.params[-1] if parsed.params else ""

        # Always buffer regardless of whether we respond
        self._context.buffer(channel, nick, text)

        # Ignore ourselves
        if nick == self.name:
            return

        # !ignore command
        if text.strip().lower().startswith("!ignore"):
            self._ignore.parse(text, self.name)
            return

        is_mention = self._context.is_direct_mention(text, self._perform.wakewords)

        # Ignored and not mentioned: stay silent
        if self._ignore.is_ignored() and not is_mention:
            return

        # Nick-prefixed service command handled by parent (_handle_privmsg_recv
        # in Client checks for own nick prefix before calling here; but AIClient
        # overrides fully, so we replicate that check)
        nick_prefix = f"{self.name} "
        if text.startswith(nick_prefix):
            # Delegate to Client's existing nick-prefix logic
            super()._handle_privmsg_recv(parsed)
            return

        # Direct @mention: bypass standoff, respond immediately
        if is_mention:
            self._ignore.clear()
            focus_w = int(self._perform.get("ai", "focus_window", "300"))
            self._standoff.cancel(channel)
            context = self._context.get(channel)
            self._dispatch_respond(channel, context)
            self._focus.mark_responded(channel, window_secs=focus_w)
            return

        # In focus window: coalesce through standoff
        if self._focus.is_focused(channel):
            self._standoff.add(channel, nick, text)
            delay = random.randint(
                int(self._perform.get("ai", "standoff_min", "2000")),
                int(self._perform.get("ai", "standoff_max", "5000")),
            )
            self._standoff.start_or_reset(channel, delay, self._on_standoff_expire)
            return

        # Not mentioned, not in focus window: silent

    def _on_standoff_expire(self, channel, messages):
        context = self._context.get(channel)
        self._dispatch_respond(channel, context)
        self._focus.mark_responded(channel)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch_respond(self, channel, context):
        t = threading.Thread(
            target=self._respond_safe, args=(channel, context), daemon=True
        )
        t.start()

    def _respond_safe(self, channel, context):
        try:
            response = self.respond(context)
            if response:
                self.send(f"PRIVMSG {channel} :{response}\r\n")
        except Exception as e:
            self.log(f"[AIClient] respond() error: {e}")

    def respond(self, context):
        raise NotImplementedError("Subclasses must implement respond()")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_client_conf(config_path):
        if config_path and Path(config_path).exists():
            return config_path
        cwd_conf = Path("client.conf")
        if cwd_conf.exists():
            return cwd_conf
        # Try ops/agents/<nick>/client.conf relative to any parent
        for parent in Path(__file__).parents:
            candidate = parent / "ops" / "agents"
            if candidate.is_dir():
                # Return a sensible default; PerformManager warns if missing
                return candidate / "codex" / "client.conf"
        return Path("client.conf")
