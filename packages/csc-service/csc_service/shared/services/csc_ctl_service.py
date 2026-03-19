"""IRC service module wrapping csc-ctl for remote service management.

Usage from IRC:
    :ai <token> csc_ctl status
    :ai <token> csc_ctl cycle pm
    :ai <token> csc_ctl cycle queue-worker
    :ai <token> csc_ctl show server
    :ai <token> csc_ctl enable pr-review
    :ai <token> csc_ctl disable jules
"""

import io
import sys
from contextlib import redirect_stdout
from csc_service.server.service import Service
from csc_service.config import ConfigManager


class csc_ctl(Service):

    def _get_config_manager(self):
        """Get a ConfigManager pointing at the live config file."""
        return ConfigManager(None)

    def _capture(self, func, *args, **kwargs):
        """Call a function and capture its stdout as a string."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                func(*args, **kwargs)
            except SystemExit:
                pass
            except Exception as e:
                buf.write(f"Error: {e}")
        return buf.getvalue().strip() or "(no output)"

    def status(self, *args) -> str:
        """Show service status. Usage: status [service]"""
        from csc_service.cli.commands import status_cmd

        cm = self._get_config_manager()

        class FakeArgs:
            service = args[0] if args else None

        return self._capture(status_cmd.status, FakeArgs(), cm)

    def cycle(self, *args) -> str:
        """Run one processing cycle. Usage: cycle <queue-worker|test-runner|pm|pr-reviewer>"""
        if not args:
            return "Usage: cycle <queue-worker|test-runner|pm|pr-reviewer>"

        from csc_service.cli.commands import service_cmd

        cm = self._get_config_manager()

        class FakeArgs:
            service = args[0]

        return self._capture(service_cmd.cycle, FakeArgs(), cm)

    def show(self, *args) -> str:
        """Show service configuration. Usage: show <service> [setting]"""
        if not args:
            return "Usage: show <service> [setting]"

        from csc_service.cli.commands import status_cmd

        cm = self._get_config_manager()

        class FakeArgs:
            service = args[0]
            setting = args[1] if len(args) > 1 else None

        return self._capture(status_cmd.show, FakeArgs(), cm)

    def enable(self, *args) -> str:
        """Enable a service. Usage: enable <service>"""
        if not args:
            return "Usage: enable <service>"

        from csc_service.cli.commands import config_cmd

        cm = self._get_config_manager()

        class FakeArgs:
            service = args[0]

        return self._capture(config_cmd.enable, FakeArgs(), cm)

    def disable(self, *args) -> str:
        """Disable a service. Usage: disable <service>"""
        if not args:
            return "Usage: disable <service>"

        from csc_service.cli.commands import config_cmd

        cm = self._get_config_manager()

        class FakeArgs:
            service = args[0]

        return self._capture(config_cmd.disable, FakeArgs(), cm)

    def config(self, *args) -> str:
        """Get or set config value. Usage: config <service> <setting> [value]"""
        if len(args) < 2:
            return "Usage: config <service> <setting> [value]"

        from csc_service.cli.commands import config_cmd

        cm = self._get_config_manager()

        class FakeArgs:
            service = args[0]
            setting = args[1]
            value = args[2] if len(args) > 2 else None

        return self._capture(config_cmd.config, FakeArgs(), cm)

    def help(self) -> str:
        """List available csc-ctl commands."""
        return (
            "csc-ctl IRC service commands:\n"
            "  status [service]              - Show service status\n"
            "  cycle <service>               - Run one processing cycle\n"
            "  show <service> [setting]      - Show service config\n"
            "  enable <service>              - Enable a service\n"
            "  disable <service>             - Disable a service\n"
            "  config <svc> <key> [value]    - Get/set config value\n"
            "\n"
            "Services: queue-worker, test-runner, pm, pr-reviewer,\n"
            "          server, bridge, pki, jules, codex"
        )
