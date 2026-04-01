import inspect
from csc_services import Service

class Help(Service):
    def default(self, *args):
        if not args:
            # List all available services
            services = ", ".join(self.loaded_modules.keys())
            return f"Available services: {services}"
        elif len(args) == 1:
            # List methods for the specified service
            service_name = args[0]
            if service_name in self.loaded_modules:
                service = self.loaded_modules[service_name]
                methods = [method for method in dir(service) if callable(getattr(service, method)) and not method.startswith("__")]
                return f"Methods for {service_name}: {', '.join(methods)}"
            else:
                return f"Service '{service_name}' not found."
        elif len(args) == 2:
            # Show docstring for the specified method
            service_name = args[0]
            method_name = args[1]
            if service_name in self.loaded_modules:
                service = self.loaded_modules[service_name]
                if hasattr(service, method_name) and callable(getattr(service, method_name)):
                    method = getattr(service, method_name)
                    docstring = inspect.getdoc(method)
                    if docstring:
                        return f"Docstring for {service_name}.{method_name}: {docstring}"
                    else:
                        return f"No docstring found for {service_name}.{method_name}"
                else:
                    return f"Method '{method_name}' not found in service '{service_name}'."
            else:
                return f"Service '{service_name}' not found."
        else:
            return "Invalid number of arguments. Use 'help', 'help <service>', or 'help <service> <method>'."
