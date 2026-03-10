"""Config commands: config get/set, enable, disable, set, dump, import."""
import json
import sys


# Map service names to config keys in csc-service.json
SERVICE_KEY_MAP = {
    "queue-worker": "enable_queue_worker",
    "test-runner": "enable_test_runner",
    "pm": "enable_pm",
    "server": "enable_server",
    "bridge": "enable_bridge",
}


def _resolve_key(service, setting):
    """Resolve a service+setting to a config key."""
    # Direct top-level keys
    if setting in ("poll_interval", "local_mode"):
        return setting
    # Service enable flags
    if setting == "enabled":
        key = SERVICE_KEY_MAP.get(service)
        if key:
            return key
    # Client configs
    if service in ("gemini", "claude", "dmrbot", "chatgpt"):
        return f"clients.{service}.{setting}"
    # Try direct service key mapping
    mapped = SERVICE_KEY_MAP.get(service)
    if mapped and setting == "enabled":
        return mapped
    # Fallback: try as dotted path
    return f"{service}.{setting}"


def enable(args, config_manager):
    """Enable a service."""
    service = args.service
    key = SERVICE_KEY_MAP.get(service)
    if key:
        config_manager.set_value(key, True)
        print(f"Enabled {service}")
    elif service in ("gemini", "claude", "dmrbot", "chatgpt"):
        config_manager.set_value(f"clients.{service}.enabled", True)
        print(f"Enabled client {service}")
    else:
        print(f"Unknown service: {service}")
        print(f"Known services: {', '.join(SERVICE_KEY_MAP.keys())}")
        sys.exit(1)


def disable(args, config_manager):
    """Disable a service."""
    service = args.service
    key = SERVICE_KEY_MAP.get(service)
    if key:
        config_manager.set_value(key, False)
        print(f"Disabled {service}")
    elif service in ("gemini", "claude", "dmrbot", "chatgpt"):
        config_manager.set_value(f"clients.{service}.enabled", False)
        print(f"Disabled client {service}")
    else:
        print(f"Unknown service: {service}")
        sys.exit(1)


def config(args, config_manager):
    """Get or set a config value."""
    key = _resolve_key(args.service, args.setting)

    if args.value is None:
        # Get
        value = config_manager.get_value(key)
        if value is not None:
            print(json.dumps({args.setting: value}, indent=2))
        else:
            print(f"Setting '{args.setting}' not found for '{args.service}'")
            sys.exit(1)
    else:
        # Set - auto-convert types
        value = _parse_value(args.value)
        config_manager.set_value(key, value)
        print(f"{args.service}.{args.setting} = {value}")


def set_value(args, config_manager):
    """Set a top-level config value (shorthand)."""
    value = _parse_value(args.value)
    config_manager.set_value(args.key, value)
    print(f"{args.key} = {value}")


def dump(args, config_manager):
    """Export config to stdout as JSON."""
    if args.service:
        key = SERVICE_KEY_MAP.get(args.service)
        if key:
            value = config_manager.get_value(key)
            print(json.dumps({args.service: {"enabled": value}}, indent=2))
        elif args.service in ("gemini", "claude", "dmrbot", "chatgpt"):
            value = config_manager.get_value(f"clients.{args.service}")
            print(json.dumps({args.service: value}, indent=2))
        else:
            print(f"Unknown service: {args.service}")
            sys.exit(1)
    else:
        print(json.dumps(config_manager.config, indent=2))


def import_cmd(args, config_manager):
    """Import config from stdin JSON."""
    try:
        new_config = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("Invalid JSON on stdin")
        sys.exit(1)

    if args.service:
        # Import config for a specific service
        if args.service in ("gemini", "claude", "dmrbot", "chatgpt"):
            config_manager.set_value(f"clients.{args.service}", new_config)
        else:
            # Merge top-level keys
            for k, v in new_config.items():
                config_manager.set_value(k, v)
        print(f"Imported config for {args.service}")
    else:
        # Full config import
        config_manager.config = new_config
        config_manager.save_config()
        print("Imported full configuration")


def _parse_value(s):
    """Parse a string value to int, float, bool, or string."""
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    if s.lower() == 'true':
        return True
    if s.lower() == 'false':
        return False
    return s
