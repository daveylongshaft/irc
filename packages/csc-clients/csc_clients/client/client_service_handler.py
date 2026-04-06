import datetime
import sys
from pathlib import Path


class ClientServiceHandler:
    """Handles local service execution for the client.

    Delegates module lookup and dispatch to ServiceDispatcher (csc-services),
    using the same lookup chain as the server:
      csc_loop.infra.<name> -> csc_services.<name> -> bare <name> -> <name>_service
    """

    def __init__(self, client):
        self.client = client
        self._dispatcher = None

        # Ensure plugins dir exists and is on sys.path for legacy compatibility
        plugins_dir = Path(self.client.project_root_dir) / "client" / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        client_dir = str(plugins_dir.parent)
        if client_dir not in sys.path:
            sys.path.insert(0, client_dir)

        self.client.log("[ClientServiceHandler] Initialized.")

    def _get_dispatcher(self):
        if self._dispatcher is None:
            from csc_services.service_dispatcher import ServiceDispatcher
            from csc_platform import Platform
            Platform.get_services_dir()  # ensures PROJECT_ROOT/services is on sys.path
            self._dispatcher = ServiceDispatcher(self.client)
        return self._dispatcher

    def execute(self, cmd_text, nick):
        """Parse and execute a service command locally.

        Accepts both forms:
          AI <token> <plugin> <method> [args...]
          <target> AI <token> <plugin> <method> [args...]
        """
        from csc_services.service import Service
        parsed = Service.parse_service_command(cmd_text)
        if parsed is None:
            return "0", "Error: Invalid service command. Expected: AI <token> <plugin> <method> [args...]"

        token = parsed["token"]
        class_name = parsed["class_name"]
        method_name = parsed["method"]
        args = parsed["args"]

        if class_name.lower() == "builtin":
            return token, self._handle_builtin(method_name, args)

        result = self._get_dispatcher().dispatch(class_name, method_name, args)
        return token, result

    def _handle_builtin(self, method, args):
        method = method.lower()
        if method == "echo":
            return " ".join(args)
        elif method == "time":
            return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elif method == "ping":
            return "pong"
        elif method == "help":
            return "Builtin methods: echo, time, ping"
        else:
            return f"Unknown builtin method: {method}"

    def get_help(self):
        return "Local AI Commands: Builtin (echo, time, ping) or shared service modules"
