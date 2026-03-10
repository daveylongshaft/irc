"""Status commands: status, show."""
import json
import os
import subprocess

IS_WINDOWS = os.name == 'nt'

# Services managed as threads inside csc-service.service (user unit)
# key = csc-service.json flag, value = display name
INPROC_SERVICES = {
    "enable_queue_worker": "queue-worker",
    "enable_test_runner":  "test-runner",
    "enable_pm":           "pm",
    "enable_pr_review":    "pr-reviewer",
}

# Services with their own systemd units (system scope, need sudo)
# name -> (unit_name, scope)  scope: "system" or "user"
UNIT_SERVICES = {
    "server": ("csc-server.service", "system"),
    "bridge": ("csc-bridge.service", "system"),
}

# Parent unit wrapping the in-proc services
PARENT_UNIT = ("csc-service.service", "user")


def _systemd_active(unit, scope="user"):
    """Return 'active', 'inactive', 'failed', or 'unknown'."""
    if IS_WINDOWS:
        return _windows_service_state(unit.replace(".service", ""))
    try:
        cmd = ["systemctl"]
        if scope == "user":
            cmd.append("--user")
        cmd += ["is-active", "--quiet", unit]
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        if r.returncode == 0:
            return "active"
        # Get actual state string
        cmd2 = ["systemctl"]
        if scope == "user":
            cmd2.append("--user")
        cmd2 += ["show", unit, "--property=ActiveState", "--value"]
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=5)
        return r2.stdout.strip() or "inactive"
    except Exception:
        return "unknown"


def _windows_service_state(svc_name):
    """Check Windows service state via sc query."""
    try:
        r = subprocess.run(
            ["sc", "query", svc_name],
            capture_output=True, text=True, timeout=5
        )
        if "RUNNING" in r.stdout:
            return "active"
        if "STOPPED" in r.stdout:
            return "inactive"
        return "unknown"
    except Exception:
        return "unknown"


def _fmt(name, runtime_state, cfg_enabled=None):
    """Format one status line."""
    state_color = {
        "active":   "active",
        "inactive": "inactive",
        "failed":   "FAILED",
        "unknown":  "unknown",
    }.get(runtime_state, runtime_state)

    parts = [f"  {name:22s} {state_color}"]
    if cfg_enabled is not None and not cfg_enabled and runtime_state == "active":
        parts.append("(config: disabled — restart to apply)")
    elif cfg_enabled is not None and cfg_enabled and runtime_state != "active":
        parts.append("(config: enabled — may need restart)")
    return "".join(parts)


def status(args, config_manager):
    """Show service status — real runtime state from systemd."""
    cfg = config_manager.config

    if args.service:
        _show_service_status(args.service, cfg)
        return

    print("CSC Service Status")
    print("=" * 50)

    # Parent unit
    parent_state = _systemd_active(*PARENT_UNIT)
    print(f"\n  {'csc-service':22s} {parent_state}  (user unit — wraps in-proc services)")

    # In-process services (config-controlled threads inside csc-service)
    print()
    for key, name in INPROC_SERVICES.items():
        enabled = cfg.get(key, False)
        cfg_str = "enabled" if enabled else "disabled"
        # Runtime = only meaningful if parent is active
        if parent_state == "active":
            rt = "running" if enabled else "idle"
        else:
            rt = "stopped (parent down)"
        print(f"  {name:22s} {cfg_str:10s}  [{rt}]")

    # Standalone system units
    print()
    for name, (unit, scope) in UNIT_SERVICES.items():
        state = _systemd_active(unit, scope)
        print(f"  {name:22s} {state:10s}  [{scope} unit: {unit}]")

    # AI clients
    clients = cfg.get("clients", {})
    if clients:
        print()
        print("  Clients:")
        for client_name, client_cfg in clients.items():
            enabled = client_cfg.get("enabled", False)
            print(f"    {client_name:20s} {'enabled' if enabled else 'disabled'}")

    poll = cfg.get("poll_interval", 60)
    print(f"\nPoll interval: {poll}s")
    print(f"Config:        {config_manager.config_file}")


def _show_service_status(service, cfg):
    """Show status for a single named service."""
    if service in UNIT_SERVICES:
        unit, scope = UNIT_SERVICES[service]
        state = _systemd_active(unit, scope)
        print(f"{service}: {state}  ({scope} unit: {unit})")
        return

    key_map = {v: k for k, v in INPROC_SERVICES.items()}
    if service in key_map:
        key = key_map[service]
        enabled = cfg.get(key, False)
        parent = _systemd_active(*PARENT_UNIT)
        print(f"{service}: {'enabled' if enabled else 'disabled'} in config  (parent csc-service: {parent})")
        return

    if service in ("csc-service", "parent"):
        state = _systemd_active(*PARENT_UNIT)
        print(f"csc-service: {state}")
        return

    if service in cfg.get("clients", {}):
        print(json.dumps({service: cfg["clients"][service]}, indent=2))
        return

    known = list(INPROC_SERVICES.values()) + list(UNIT_SERVICES.keys()) + list(cfg.get("clients", {}).keys())
    print(f"Unknown service: {service}")
    print(f"Known: {', '.join(known)}")


def show(args, config_manager):
    """Display service configuration details."""
    cfg = config_manager.config
    service = args.service

    if args.setting:
        value = config_manager.get_value(args.setting)
        if value is not None:
            print(json.dumps({args.setting: value}, indent=2))
        else:
            print(f"Setting '{args.setting}' not found")
        return

    if service in cfg.get("clients", {}):
        print(json.dumps(cfg["clients"][service], indent=2))
        return

    key_map = {v: k for k, v in INPROC_SERVICES.items()}
    if service in key_map:
        key = key_map[service]
        print(json.dumps({service: {"enabled": cfg.get(key, False)}}, indent=2))
        return

    if service in UNIT_SERVICES:
        unit, scope = UNIT_SERVICES[service]
        print(json.dumps({service: {"unit": unit, "scope": scope}}, indent=2))
        return

    print(f"Unknown service: {service}")
