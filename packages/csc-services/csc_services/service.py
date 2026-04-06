import importlib
import sys
import inspect
from csc_network import Network


class Service( Network ):
    """Base class for all CSC services, supporting MVC-like dynamic execution."""

    SERVICE_KEYWORDS = {"ai"}

    @staticmethod
    def parse_service_command(text):
        """Parse a service command from channel text.

        Accepts two forms:
          <keyword> <token> <class> [method] [args...]
          <target> <keyword> <token> <class> [method] [args...]

        Returns a dict with keys: target, keyword, token, class_name, method, args, raw
        or None if the text is not a service command.
        """
        parts = text.split()
        if not parts:
            return None
        first = parts[0].lower()
        if first in Service.SERVICE_KEYWORDS:
            if len(parts) < 3:
                return None
            return {
                "target": None,
                "keyword": first,
                "token": parts[1],
                "class_name": parts[2],
                "method": parts[3] if len(parts) > 3 else "default",
                "args": parts[4:] if len(parts) > 4 else [],
                "raw": text,
            }
        elif len(parts) >= 2 and parts[1].lower() in Service.SERVICE_KEYWORDS:
            if len(parts) < 4:
                return None
            return {
                "target": parts[0],
                "keyword": parts[1].lower(),
                "token": parts[2],
                "class_name": parts[3],
                "method": parts[4] if len(parts) > 4 else "default",
                "args": parts[5:] if len(parts) > 5 else [],
                "raw": text,
            }
        return None

    def __init__(self, server_instance=None):
        super().__init__()
        self.name = "service"
        self.loaded_modules = {}
        self.server = server_instance # Intentional self-reference for MVC orchestration

    def default(self, *args):
        return f"No default command defined for this service. Received: {args}"

    def handle_command(self, class_name_raw, method_name_raw, args, source_name, source_address):
        """Executes a command by dynamically loading a service module.

        Supports class.method(args) pattern passed over IRC.
        Tries csc_loop.<class> then falls back to csc_services.<class>.
        """
        self.log( f"MVC Exec: {class_name_raw}.{method_name_raw}({args}) from {source_name}" )

        # Try package namespaces first, then bare name from PROJECT_ROOT/services/
        from csc_platform import Platform
        Platform.get_services_dir()  # ensures PROJECT_ROOT/services is on sys.path

        namespaces = ["csc_loop.infra", "csc_services"]
        module = None
        module_name_used = None

        for ns in namespaces:
            module_name = f"{ns}.{class_name_raw.lower()}"
            try:
                if module_name in sys.modules:
                    module = importlib.reload( sys.modules[module_name] )
                else:
                    module = importlib.import_module( module_name )
                module_name_used = module_name
                break
            except ImportError:
                continue

        if not module:
            # Fall back to bare module name from PROJECT_ROOT/services/
            bare_name = class_name_raw.lower()
            try:
                if bare_name in sys.modules:
                    module = importlib.reload( sys.modules[bare_name] )
                else:
                    module = importlib.import_module( bare_name )
                module_name_used = bare_name
            except ImportError:
                return f"Error: Module for '{class_name_raw}' not found in {namespaces} or services dir."

        try:
            class_name = None
            for candidate in [class_name_raw, class_name_raw.lower(), class_name_raw.capitalize()]:
                if hasattr(module, candidate):
                    class_name = candidate
                    break

            if class_name is None:
                for attr in dir(module):
                    if attr.lower() == class_name_raw.lower() and inspect.isclass(getattr(module, attr)):
                        class_name = attr
                        break

            if class_name is None:
                raise ImportError( f"Class '{class_name_raw}' not found in '{module_name_used}'." )

            module_class = getattr( module, class_name )

            if class_name_raw not in self.loaded_modules:
                # Pass self (the service base) as the orchestrator/server ref
                self.loaded_modules[class_name_raw] = module_class( self )

            instance = self.loaded_modules[class_name_raw]

            method_to_call = None
            if hasattr(instance, method_name_raw) and not method_name_raw.startswith('_'):
                if inspect.ismethod(getattr(instance, method_name_raw)):
                    method_to_call = getattr(instance, method_name_raw)

            if not method_to_call and hasattr(instance, "default"):
                if inspect.ismethod(getattr(instance, "default")):
                    method_to_call = getattr(instance, "default")
                    args.insert(0, method_name_raw)

            if not method_to_call:
                return f"Error: Method '{method_name_raw}' not found in '{class_name}'."

            result = method_to_call(*args)
            return str( result ) if result is not None else "OK"

        except Exception as e:
            self.log( f"MVC Error: {e}" )
            return f"Error: {e}"

if __name__ == '__main__':
    service = Service()
    service.run()
