"""csc-ctl: Cross-platform CLI for managing CSC services."""
import argparse
import sys
from .commands import status_cmd, config_cmd, service_cmd, pki_cmd
from ..config import ConfigManager


def main():
    parser = argparse.ArgumentParser(
        prog="csc-ctl",
        description="CSC service management CLI"
    )
    parser.add_argument(
        "--config", help="Path to csc-service.json config file"
    )
    subparsers = parser.add_subparsers(dest="command")

    # Status
    status_parser = subparsers.add_parser("status", help="Show service status")
    status_parser.add_argument("service", nargs="?", help="Specific service name")
    status_parser.set_defaults(func=status_cmd.status)

    # Show
    show_parser = subparsers.add_parser("show", help="Display service configuration")
    show_parser.add_argument("service", help="Service to show config for")
    show_parser.add_argument("setting", nargs="?", help="Specific setting to display")
    show_parser.set_defaults(func=status_cmd.show)

    # Enable / Disable
    enable_parser = subparsers.add_parser("enable", help="Enable a service")
    enable_parser.add_argument("service", help="Service to enable")
    enable_parser.set_defaults(func=config_cmd.enable)

    disable_parser = subparsers.add_parser("disable", help="Disable a service")
    disable_parser.add_argument("service", help="Service to disable")
    disable_parser.set_defaults(func=config_cmd.disable)

    # Config get/set
    config_parser = subparsers.add_parser("config", help="Get or set config values")
    config_parser.add_argument("service", help="Service to configure")
    config_parser.add_argument("setting", help="Setting name")
    config_parser.add_argument("value", nargs="?", help="Value to set (omit to get)")
    config_parser.set_defaults(func=config_cmd.config)

    # Set (shorthand)
    set_parser = subparsers.add_parser("set", help="Set a config value")
    set_parser.add_argument("key", help="Config key (e.g. poll_interval)")
    set_parser.add_argument("value", help="Value to set")
    set_parser.set_defaults(func=config_cmd.set_value)

    # Dump / Import
    dump_parser = subparsers.add_parser("dump", help="Export config to stdout")
    dump_parser.add_argument("service", nargs="?", help="Service to dump")
    dump_parser.set_defaults(func=config_cmd.dump)

    import_parser = subparsers.add_parser("import", help="Import config from stdin")
    import_parser.add_argument("service", nargs="?", help="Service to import for")
    import_parser.set_defaults(func=config_cmd.import_cmd)

    # Service lifecycle
    restart_parser = subparsers.add_parser("restart", help="Restart a service")
    restart_parser.add_argument("service", help="Service to restart")
    restart_parser.add_argument("--force", action="store_true", help="Force kill")
    restart_parser.set_defaults(func=service_cmd.restart)

    install_parser = subparsers.add_parser("install", help="Install background services")
    install_parser.add_argument("service", nargs="?", default="all", help="Service to install (default: all)")
    install_parser.add_argument("--list", action="store_true", dest="list_only", help="Show what would be installed")
    install_parser.set_defaults(func=service_cmd.install)

    remove_parser = subparsers.add_parser("remove", help="Remove background services")
    remove_parser.add_argument("service", nargs="?", default="all", help="Service to remove (default: all)")
    remove_parser.add_argument("--list", action="store_true", dest="list_only", help="Show what would be removed")
    remove_parser.set_defaults(func=service_cmd.remove)

    # Cycle (manual run)
    cycle_parser = subparsers.add_parser("cycle", help="Run one processing cycle")
    cycle_parser.add_argument("service", help="Service to cycle (queue-worker, test-runner, pm)")
    cycle_parser.set_defaults(func=service_cmd.cycle)

    # Run (synonym for cycle)
    run_parser = subparsers.add_parser("run", help="Run one processing cycle (alias for cycle)")
    run_parser.add_argument("service", help="Service to run (queue-worker, test-runner, pm)")
    run_parser.set_defaults(func=service_cmd.cycle)

    # PKI: enroll
    enroll_parser = subparsers.add_parser("enroll", help="Enroll for a TLS certificate")
    enroll_parser.add_argument("ca_url", help="CA enrollment URL (e.g. https://facingaddictionwithhope.com/csc/pki/)")
    enroll_parser.add_argument("token", nargs="?", default="", help="One-time enrollment token (omit if pre-approved)")
    enroll_parser.set_defaults(func=pki_cmd.enroll)

    # PKI: cert (with sub-subcommand 'status')
    cert_parser = subparsers.add_parser("cert", help="Certificate management")
    cert_sub = cert_parser.add_subparsers(dest="cert_command")
    cert_status_parser = cert_sub.add_parser("status", help="Show local certificate status")
    cert_status_parser.set_defaults(func=pki_cmd.cert_status)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Handle 'cert' with no subcommand
    if args.command == "cert" and not getattr(args, "cert_command", None):
        cert_parser.print_help()
        sys.exit(1)

    config_manager = ConfigManager(args.config)
    args.func(args, config_manager)


if __name__ == "__main__":
    main()
