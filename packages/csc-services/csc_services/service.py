import sys
from csc_network import Network
from csc_services.service_dispatcher import ServiceDispatcher


class Service(Network):
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
        self.server = server_instance
        self._dispatcher = None

    def default(self, *args):
        return f"No default command defined for this service. Received: {args}"

    def handle_command(self, class_name_raw, method_name_raw, args, source_name, source_address):
        """Executes a command by dynamically loading a service module."""
        self.log(f"MVC Exec: {class_name_raw}.{method_name_raw}({args}) from {source_name}")

        from csc_platform import Platform
        Platform.get_services_dir()  # ensures PROJECT_ROOT/services is on sys.path

        if self._dispatcher is None:
            self._dispatcher = ServiceDispatcher(self)

        return self._dispatcher.dispatch(class_name_raw, method_name_raw, args)


if __name__ == '__main__':
    service = Service()
    service.run()
