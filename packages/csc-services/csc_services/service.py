import importlib
import sys
import inspect
from csc_crypto import Crypto
from csc_services.irc import IRCProtocolMixin


class Service(IRCProtocolMixin, Crypto):
    """Base class for all CSC services, supporting MVC-like dynamic execution."""

    SERVICE_KEYWORDS = {"ai"}

    @staticmethod
    def parse_service_command(text):
        """Parse a service command from channel text.

        Accepts one canonical form:
          <target> <keyword> <token> <class> [method] [args...]

        Returns a dict with keys: target, keyword, token, class_name, method, args, raw
        or None if the text is not a service command.
        """
        parts = text.split()
        if len(parts) < 4:
            return None
        if parts[1].lower() not in Service.SERVICE_KEYWORDS:
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

    def __init__(self, server_instance=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

        # Try multiple namespaces: csc_loop (infra) and csc_services (implementations)
        namespaces = ["csc_loop.infra", "csc_services", "csc_version.services"]
        module_candidates = [class_name_raw.lower()]
        service_module = f"{class_name_raw.lower()}_service"
        if service_module not in module_candidates:
            module_candidates.append(service_module)
        module = None
        module_name_used = None

        for ns in namespaces:
            for module_basename in module_candidates:
                module_name = f"{ns}.{module_basename}"
                try:
                    if module_name in sys.modules:
                        module = importlib.reload( sys.modules[module_name] )
                    else:
                        module = importlib.import_module( module_name )
                    module_name_used = module_name
                    break
                except ImportError:
                    continue
            if module:
                break

        if not module:
            return (
                f"Error: Module for '{class_name_raw}' not found in "
                f"{[f'{ns}.{name}' for ns in namespaces for name in module_candidates]}."
            )

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
