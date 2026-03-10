"""Status commands: status, show."""
import json
import os
from pathlib import Path

# Map config keys to display names
SERVICE_NAMES = {
    "enable_queue_worker": "queue-worker",
    "enable_test_runner": "test-runner",
    "enable_pm": "pm",
    "enable_pr_review": "pr-reviewer",
    "enable_server": "server",
    "enable_bridge": "bridge",
}


def status(args, config_manager):
    """Show service status."""
    cfg = config_manager.config

    if args.service:
        # Show specific service
        _show_service_status(args.service, cfg)
    else:
        # Show all services
        print("CSC Service Status")
        print("=" * 40)

        for key, name in SERVICE_NAMES.items():
            enabled = cfg.get(key, False)
            status_str = "enabled" if enabled else "disabled"
            print(f"  {name:20s} {status_str}")

        # Show clients
        clients = cfg.get("clients", {})
        if clients:
            print()
            print("Clients:")
            for client_name, client_cfg in clients.items():
                enabled = client_cfg.get("enabled", False)
                auto = client_cfg.get("auto_start", False)
                status_str = "enabled" if enabled else "disabled"
                if enabled and auto:
                    status_str += " (auto-start)"
                print(f"  {client_name:20s} {status_str}")

        # Show poll interval
        poll = cfg.get("poll_interval", 60)
        print(f"\nPoll interval: {poll}s")

        # Show config file path
        print(f"Config file: {config_manager.config_file}")


def _show_service_status(service, cfg):
    """Show status for a single service."""
    key_map = {v: k for k, v in SERVICE_NAMES.items()}

    if service in key_map:
        key = key_map[service]
        enabled = cfg.get(key, False)
        print(f"{service}: {'enabled' if enabled else 'disabled'}")
    elif service in cfg.get("clients", {}):
        client_cfg = cfg["clients"][service]
        print(json.dumps({service: client_cfg}, indent=2))
    else:
        print(f"Unknown service: {service}")
        print(f"Known: {', '.join(list(SERVICE_NAMES.values()) + list(cfg.get('clients', {}).keys()))}")


def show(args, config_manager):
    """Display service configuration details."""
    cfg = config_manager.config

    if args.setting:
        # Show specific setting
        value = config_manager.get_value(args.setting)
        if value is not None:
            print(json.dumps({args.setting: value}, indent=2))
        else:
            print(f"Setting '{args.setting}' not found")
    else:
        # Show all config for a service
        service = args.service
        if service in cfg.get("clients", {}):
            print(json.dumps(cfg["clients"][service], indent=2))
        else:
            # Show the enable key and any related config
            key_map = {v: k for k, v in SERVICE_NAMES.items()}
            if service in key_map:
                key = key_map[service]
                print(json.dumps({service: {"enabled": cfg.get(key, False)}}, indent=2))
            else:
                print(f"Unknown service: {service}")
