# service.py

import ast
import shlex
import importlib
import importlib.util
import sys
import inspect
from pathlib import Path
from csc_network import Network


class Service( Network ):
    def __init__(self, server_instance=None):
        super().__init__()
        self.name = "service"
        self.loaded_modules = {}
        self.server = server_instance
        #print(f"{self.name}->",end=None)

    def default(self, *args):
        """
        Default command handler for a service.

        - What it does: This method is called when a command is issued for a
          service, but the specified method does not exist and the service
          does not have its own `default` method.
        - Arguments:
            - `*args`: A tuple of arguments passed with the command.
        - What calls it: `handle_command()`.
        - What it calls: None.
        - Returns:
            - A string indicating that no default command is defined.
        """
        return f"No default command defined for this service. Method and arguments received: {args}"

    def handle_command(self, class_name_raw, method_name_raw, args, source_name, source_address):
        """
        Executes a command by dynamically loading a service module.

        - What it does: Imports a service module based on the `class_name_raw`,
          instantiates the service class, and calls the specified method with
          the given arguments. If the method is not found, it falls back to a
          `default` method on the service instance.
        - Arguments:
            - `class_name_raw` (str): The name of the service class.
            - `method_name_raw` (str): The name of the method to call.
            - `args` (list): A list of arguments for the method.
            - `source_name` (str): The name of the client who sent the command.
            - `source_address` (tuple): The `(host, port)` of the client.
        - What calls it: `ServerMessageHandler.handle_service_command()`.
        - What it calls: `self.log()`, `importlib.reload()`, `importlib.import_module()`,
          `hasattr()`, `getattr()`, `inspect.ismethod()`, `list.insert()`.
        - Returns:
            - The result of the service method call as a string, or an error message.
        """
        self.log( f"Handling command for service '{class_name_raw}' from {source_name}@{source_address}" )

        module_name = f"csc_service.shared.services.{class_name_raw.lower()}_service"
        local_module_name = f"{class_name_raw.lower()}_service"

        try:
            # First try: standard package import
            if module_name in sys.modules:
                module = importlib.reload( sys.modules[module_name] )
            else:
                try:
                    module = importlib.import_module( module_name )
                except ImportError:
                    # Fallback: look in local services/ directory relative to cwd
                    services_path = Path(getattr(self, "project_root_dir", Path.cwd())) / "services" / f"{local_module_name}.py"
                    if not services_path.exists():
                        services_path = Path.cwd() / "services" / f"{local_module_name}.py"
                    if services_path.exists():
                        spec = importlib.util.spec_from_file_location(local_module_name, services_path)
                        module = importlib.util.module_from_spec(spec)
                        sys.modules[local_module_name] = module
                        spec.loader.exec_module(module)
                        module_name = local_module_name
                    else:
                        raise

            # Try multiple name variants: raw, lowercase, capitalize, then case-insensitive scan
            class_name = None
            for candidate in [class_name_raw, class_name_raw.lower(), class_name_raw.capitalize()]:
                if hasattr(module, candidate):
                    class_name = candidate
                    break
            if class_name is None:
                raw_lower = class_name_raw.lower()
                for attr in dir(module):
                    if attr.lower() == raw_lower and inspect.isclass(getattr(module, attr)):
                        class_name = attr
                        break
            if class_name is None:
                raise ImportError( f"Class '{class_name_raw}' not found in module '{module_name}'." )

            module_class = getattr( module, class_name )

            # --- FIX ---
            # Modules are now stored using their raw (lowercase) name for consistency.
            if class_name_raw not in self.loaded_modules:
                self.log( f"Creating new instance of class '{class_name}'." )
                # Pass the main server instance to the service's constructor.
                self.loaded_modules[class_name_raw] = module_class( self )

            instance = self.loaded_modules[class_name_raw]

            # --- FIX ---
            # Method resolution is now explicit and robust.
            method_to_call = None
            if hasattr(instance, method_name_raw) and not method_name_raw.startswith('_'):
                if inspect.ismethod(getattr(instance, method_name_raw)):
                    method_to_call = getattr(instance, method_name_raw)

            # If the specific method isn't found, fall back to the "default" method.
            if not method_to_call and hasattr(instance, "default"):
                if inspect.ismethod(getattr(instance, "default")):
                    self.log(f"Method '{method_name_raw}' not found. Falling back to 'default'.")
                    method_to_call = getattr(instance, "default")
                    # Prepend the original method name to the args for context.
                    args.insert(0, method_name_raw)

            if not method_to_call:
                return f"Error: Neither method '{method_name_raw}' nor a 'default' method could be found in '{class_name}'."

            self.log(f"Attempting to call {class_name}.{method_to_call.__name__} with args: {args}")
            result = method_to_call(*args)

            return str( result ) if result is not None else "Command executed successfully."

        except Exception as e:
            self.log( f"Error during command execution: {e}" )
            return f"Error during command execution: {e}"


if __name__ == '__main__':
    service = Service()
    service.run()
