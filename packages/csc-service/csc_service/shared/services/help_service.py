import re
from pathlib import Path
from csc_service.server.service import Service


class help(Service):
    """Service discovery and documentation helper.

    Scans services directory to list available modules and extract
    method signatures and docstrings without loading them.
    """

    @staticmethod
    def _get_services_dir():
        """Get the services directory path."""
        return Path(__file__).parent

    @staticmethod
    def _list_available_services():
        """Scan services dir for *_service.py files and extract class names."""
        services = {}
        services_dir = help._get_services_dir()

        for service_file in sorted(services_dir.glob("*_service.py")):
            if service_file.name.startswith("_"):
                continue
            try:
                content = service_file.read_text(encoding="utf-8")
                # Extract class name (lowercase by convention)
                class_match = re.search(r'^class\s+(\w+)\s*\(', content, re.MULTILINE)
                if class_match:
                    class_name = class_match.group(1)
                    services[class_name] = service_file.name
            except Exception as e:
                pass

        return services

    @staticmethod
    def _get_methods_for_service(service_name):
        """Extract method names and signatures from a service file via regex."""
        services_dir = help._get_services_dir()
        service_file = services_dir / f"{service_name}_service.py"

        if not service_file.exists():
            return None

        try:
            content = service_file.read_text(encoding="utf-8")
            methods = {}

            # Find all method definitions: def method_name(...) [-> ReturnType]:
            # Handles return type annotations like -> str
            # Skip __init__, __*__, and private methods
            for match in re.finditer(r'^\s+def\s+(\w+)\s*\((.*?)\)(?:\s*->\s*[^:]+)?:', content, re.MULTILINE):
                method_name = match.group(1)
                if method_name.startswith("_"):
                    continue

                params = match.group(2).strip()
                # Remove 'self' parameter
                params = re.sub(r'self\s*,?\s*', '', params).strip()

                methods[method_name] = params

            return methods
        except Exception as e:
            return None

    @staticmethod
    def _get_docstring_for_method(service_name, method_name):
        """Extract docstring for a specific method via regex."""
        services_dir = help._get_services_dir()
        service_file = services_dir / f"{service_name}_service.py"

        if not service_file.exists():
            return None

        try:
            content = service_file.read_text(encoding="utf-8")

            # Find the method definition with optional return type annotation (-> Type)
            pattern = rf'def\s+{re.escape(method_name)}\s*\([^)]*\)(?:\s*->\s*[^:]+)?:\s*"""(.*?)"""'
            match = re.search(pattern, content, re.DOTALL)

            if match:
                return match.group(1).strip()

            # Try single-quote docstring
            pattern = rf"def\s+{re.escape(method_name)}\s*\([^)]*\)(?:\s*->\s*[^:]+)?:\s*'(.*?)'"
            match = re.search(pattern, content, re.DOTALL)

            if match:
                return match.group(1).strip()

            return None
        except Exception as e:
            return None

    def default(self, *args):
        """
        Service discovery interface.

        help           - List all available services
        help service   - List methods for a service
        help service method - Show docstring for a method
        """
        if not args:
            # List all available services
            services = self._list_available_services()
            if not services:
                return "No services found."
            service_list = ", ".join(sorted(services.keys()))
            return f"Available services: {service_list}"

        elif len(args) == 1:
            # List methods for the specified service
            service_name = args[0].lower()
            methods = self._get_methods_for_service(service_name)

            if methods is None:
                return f"Service '{service_name}' not found."

            if not methods:
                return f"Service '{service_name}' has no public methods."

            method_list = ", ".join(sorted(methods.keys()))
            return f"Methods for {service_name}: {method_list}"

        elif len(args) == 2:
            # Show docstring for the specified method
            service_name = args[0].lower()
            method_name = args[1].lower()

            # Verify service exists
            methods = self._get_methods_for_service(service_name)
            if methods is None:
                return f"Service '{service_name}' not found."

            if method_name not in methods:
                return f"Method '{method_name}' not found in service '{service_name}'."

            docstring = self._get_docstring_for_method(service_name, method_name)

            if docstring:
                signature = f"{method_name}({methods[method_name]})"
                return f"{service_name}.{signature}\n\n{docstring}"
            else:
                return f"No docstring found for {service_name}.{method_name}({methods[method_name]})"

        else:
            return "Invalid usage. Use: help [service] [method]"
