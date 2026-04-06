import os
import sys
import inspect
import importlib
import datetime
from pathlib import Path

class ClientServiceHandler:
    """
    Handles local service execution for the client.
    Supports dynamic loading of plugins from 'client/plugins/'.
    """
    def __init__(self, client):
        self.client = client
        self.loaded_plugins = {}
        
        # Ensure plugins directory exists
        self.plugins_dir = Path(self.client.project_root_dir) / "client" / "plugins"
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        
        # Add plugins dir to sys.path
        sys.path.insert(0, str(self.plugins_dir.parent)) # Add 'client' so we can import 'plugins.xxx'
        
        self.client.log(f"[ClientServiceHandler] Initialized. Plugins dir: {self.plugins_dir}")

    def execute(self, cmd_text, nick):
        """
        Parses and executes a service command locally.
        Uses Service.parse_service_command() from csc_services for shared parsing.
        Accepts both forms:
          AI <token> <plugin> <method> [args...]
          <target> AI <token> <plugin> <method> [args...]
        """
        from csc_services import Service
        parsed = Service.parse_service_command(cmd_text)
        if parsed is None:
            return "0", "Error: Invalid service command. Expected: AI <token> <plugin> <method> [args...]"

        token = parsed["token"]
        plugin_name_raw = parsed["class_name"]
        method_name_raw = parsed["method"]
        args = parsed["args"]

        # Built-in handlers (echo, time, ping)
        if plugin_name_raw.lower() == "builtin":
            return token, self._handle_builtin(method_name_raw, args)

        # Dynamic Plugin Loading
        try:
            return token, self._handle_plugin(plugin_name_raw, method_name_raw, args)
        except Exception as e:
            return token, f"Error executing plugin '{plugin_name_raw}': {e}"

    def _handle_builtin(self, method, args):
        """Handles core built-in services."""
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

    def _handle_plugin(self, plugin_name_raw, method_name, args):
        """Mirror of server/service.py dynamic loading logic."""
        # Convention: plugins/<name>_plugin.py -> class <Name>
        module_name = f"plugins.{plugin_name_raw.lower()}_plugin"
        class_name = plugin_name_raw.capitalize()

        try:
            if module_name in sys.modules:
                module = importlib.reload(sys.modules[module_name])
            else:
                module = importlib.import_module(module_name)

            if not hasattr(module, class_name):
                return f"Error: Class '{class_name}' not found in module '{module_name}'."

            plugin_class = getattr(module, class_name)

            if plugin_name_raw not in self.loaded_plugins:
                # Instantiate with client context
                self.loaded_plugins[plugin_name_raw] = plugin_class(self.client)

            instance = self.loaded_plugins[plugin_name_raw]

            # Method resolution
            method_to_call = None
            if hasattr(instance, method_name) and not method_name.startswith('_'):
                attr = getattr(instance, method_name)
                if inspect.ismethod(attr) or inspect.isfunction(attr):
                    method_to_call = attr

            if not method_to_call and hasattr(instance, "default"):
                method_to_call = instance.default
                args.insert(0, method_name)

            if not method_to_call:
                return f"Error: Method '{method_name}' not found in plugin '{class_name}'."

            result = method_to_call(*args)
            return str(result) if result is not None else "OK"

        except ImportError:
            return f"Error: Plugin '{plugin_name_raw}' not found."
        except Exception as e:
            return f"Plugin Error: {e}"

    def get_help(self):
        return "Local AI Commands: Builtin (echo, time, ping) or Plugins in client/plugins/"