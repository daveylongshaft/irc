"""Status commands: status, show."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

IS_WINDOWS = os.name == 'nt'

# Services managed as threads inside csc-service.service (user unit)
# key = csc-service.json flag, value = display name
INPROC_SERVICES = {
    "enable_queue_worker": "queue-worker",
    "enable_test_runner":  "test-runner",
    "enable_pm":           "pm",
    "enable_pr_review":    "pr-reviewer",
    "enable_pki":          "pki",
}

# Services with their own systemd user units
# name -> (unit_name, scope, config_key)
UNIT_SERVICES = {
    "server": ("csc-server.service", "user", "enable_server"),
    "bridge": ("csc-bridge.service", "user", "enable_bridge"),
}

# Parent unit wrapping the in-proc services
PARENT_UNIT = ("csc-service.service", "user")


def _is_pid_alive(pid):
    """Check if a process is running."""
    if IS_WINDOWS:
        try:
            # Using shell=True sometimes avoids the access violation crash on this host
            cmd = f'tasklist /fi "pid eq {pid}" /nh'
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5, shell=True)
            return str(pid) in r.stdout
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _get_csc_loop_pid():
    """Read PID from run/csc-service.pid if it exists and is alive."""
    try:
        from csc_platform import Platform
        pid_file = Platform().run_dir / "csc-service.pid"
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            # Use _is_pid_alive which has Windows-specific tasklist check
            if _is_pid_alive(pid):
                return pid
    except Exception as e:
        print(f"[status] Failed to load config: {e}")
    return None


def _systemd_active(unit, scope="user"):
    """Return 'active', 'inactive', 'failed', or 'unknown'."""
    try:
        if IS_WINDOWS:
            # Check system service first
            state = _windows_service_state(unit.replace(".service", ""))
            if state == "active":
                return state
            
            # Fall back to PID file check for csc-service
            if unit == "csc-service.service":
                pid = _get_csc_loop_pid()
                return "active" if pid else "inactive"
            
            return state

        try:
            cmd = ["systemctl"]
            if scope == "user":
                cmd.append("--user")
            cmd += ["is-active", "--quiet", unit]
            r = subprocess.run(cmd, capture_output=True, timeout=5)
            if r.returncode == 0:
                return "active"
            cmd2 = ["systemctl"]
            if scope == "user":
                cmd2.append("--user")
            cmd2 += ["show", unit, "--property=ActiveState", "--value"]
            r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=5)
            return r2.stdout.strip() or "inactive"
        except Exception:
            return "unknown"
    except Exception as e:
        print(f"CRASH AVOIDED in _systemd_active: {e}")
        return "unknown"


def _systemd_pid(unit, scope="user"):
    """Return MainPID for a systemd unit, or PID from file on Windows."""
    try:
        if IS_WINDOWS:
            if unit == "csc-service.service":
                return _get_csc_loop_pid()
            # For server/bridge, they might also have PID files if we add them
            return None

        try:
            cmd = ["systemctl"]
            if scope == "user":
                cmd.append("--user")
            cmd += ["show", unit, "--property=MainPID", "--value"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            pid = r.stdout.strip()
            return int(pid) if pid and pid != "0" else None
        except Exception:
            return None
    except Exception as e:
        print(f"CRASH AVOIDED in _systemd_pid: {e}")
        return None


def _windows_service_state(svc_name):
    try:
        # Use shell=True and be very defensive to avoid access violations
        cmd = f'sc query "{svc_name}"'
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5, shell=True)
        if r.returncode != 0:
            return "inactive"
        if "RUNNING" in r.stdout:
            return "active"
        if "STOPPED" in r.stdout:
            return "inactive"
        return "inactive"
    except Exception:
        return "unknown"


def _ss_ports_for_pid(pid):
    """Return list of (proto, local_addr) tuples for a PID using ss."""
    if IS_WINDOWS or pid is None:
        return []
    results = []
    try:
        r = subprocess.run(["ss", "-Hnlup"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if f"pid={pid}" not in line:
                continue
            parts = line.split()
            local = parts[3] if len(parts) > 3 else "?"
            results.append(("udp", local))
        r2 = subprocess.run(["ss", "-Hnltp"], capture_output=True, text=True, timeout=5)
        for line in r2.stdout.splitlines():
            if f"pid={pid}" not in line:
                continue
            parts = line.split()
            local = parts[3] if len(parts) > 3 else "?"
            results.append(("tcp", local))
    except Exception as e:
        print(f"CRASH AVOIDED in _ss_ports_for_pid: {e}")
    return results


def _server_stats():
    """Read server state files and return a dict of stats."""
    stats = {"clients": 0, "channels": 0, "links": 0, "shortname": "csc-server", "uptime": None}
    try:
        from csc_services import SERVER_NAME
        stats["shortname"] = SERVER_NAME
    except Exception:
        SERVER_NAME = "unknown"

    # Uptime from systemd
    if not IS_WINDOWS:
        try:
            r = subprocess.run(
                ["systemctl", "--user", "show", "csc-server.service",
                 "--property=ActiveEnterTimestamp", "--value"],
                capture_output=True, text=True, timeout=5
            )
            ts_str = r.stdout.strip()
            if ts_str:
                from datetime import datetime
                import locale
                parts = ts_str.split()
                if len(parts) >= 3:
                    try:
                        dt = datetime.strptime(f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M:%S")
                        elapsed = time.time() - dt.timestamp()
                        h = int(elapsed // 3600)
                        m = int((elapsed % 3600) // 60)
                        s = int(elapsed % 60)
                        if h >= 24:
                            d = h // 24
                            h = h % 24
                            stats["uptime"] = f"{d}d {h}h {m}m"
                        elif h > 0:
                            stats["uptime"] = f"{h}h {m}m {s}s"
                        else:
                            stats["uptime"] = f"{m}m {s}s"
                    except Exception:
                        stats["uptime"] = ts_str
        except Exception as e:
            print(f"CRASH AVOIDED in _server_stats systemctl: {e}")

    # Read from run-dir JSON files
    try:
        from csc_platform import Platform
        run_dir = Platform.PROJECT_ROOT / "tmp" / "csc" / "run"

        ch_file = run_dir / "channels.json"
        if ch_file.exists():
            d = json.loads(ch_file.read_text())
            channels = d.get("channels", {})
            stats["channels"] = len(channels)
            # Count connected clients: unique nicks across all channel member lists
            connected = set()
            for ch in channels.values():
                for nick in ch.get("members", {}):
                    connected.add(nick)
            stats["clients"] = len(connected)

        # S2S links - check for a links state file
        links_file = run_dir / "links.json"
        if links_file.exists():
            d = json.loads(links_file.read_text())
            stats["links"] = len(d.get("links", {}))
    except Exception:
        links = []

    return stats


def _net_info_server(state):
    """Return port and stats lines for csc-server."""
    if state != "active":
        return []
    pid = _systemd_pid("csc-server.service", "user")
    ports = _ss_ports_for_pid(pid)
    lines = []
    if ports:
        for proto, local in ports:
            if proto == "udp":
                lines.append(f"    UDP {local}  (IRC server)")
    else:
        lines.append("    UDP 0.0.0.0:9525  (IRC server)")

    s = _server_stats()
    uptime_str = f"  up {s['uptime']}" if s["uptime"] else ""
    lines.append(f"    {s['shortname']}  "
                 f"{s['clients']} client(s)  {s['channels']} channel(s)  "
                 f"{s['links']} link(s){uptime_str}")
    return lines


def _net_info_bridge(state):
    """Return port info lines for csc-bridge."""
    if state != "active":
        return []
    pid = _systemd_pid("csc-bridge.service", "user")
    raw = _ss_ports_for_pid(pid)

    # Determine upstream target from live UDP connections (non-listening bound sockets)
    upstream = "127.0.0.1:9525"
    try:
        r = subprocess.run(["ss", "-Hunp"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if pid and f"pid={pid}" in line:
                parts = line.split()
                # udp UNCONN local peer  -> peer is upstream
                if len(parts) >= 5 and parts[4] not in ("0.0.0.0:*", "*:*", "[::]:*"):
                    upstream = parts[4]
                    break
    except Exception:
        import logging
        logging.getLogger(__name__).debug('Ignored exception', exc_info=True)

    lines = []
    if raw:
        for proto, local in raw:
            if proto == "tcp":
                lines.append(f"    TCP {local}  ->  UDP {upstream}")
            elif proto == "udp":
                lines.append(f"    UDP {local}  ->  UDP {upstream}")
    else:
        lines = [
            f"    TCP 0.0.0.0:9667  ->  UDP {upstream}  (IRC clients)",
            f"    TCP 0.0.0.0:9666  ->  UDP {upstream}  (IRC clients)",
            f"    UDP 127.0.0.1:9526  ->  UDP {upstream}  (native CSC)",
        ]
    return lines


def _fifo_clients():
    """Scan /proc for running csc-client --fifo processes.
    Returns list of dicts: {pid, server, infile, outfile}
    """
    if IS_WINDOWS:
        return []
    clients = []
    try:
        proc_dirs = [d for d in os.listdir("/proc") if d.isdigit()]
    except Exception:
        return []

    for pid_str in proc_dirs:
        try:
            cmdline_path = f"/proc/{pid_str}/cmdline"
            with open(cmdline_path, "rb") as f:
                raw = f.read()
            args = raw.decode(errors="replace").split("\x00")
            if not any("csc-client" in a for a in args):
                continue

            infile = None
            outfile = None
            server = None
            is_fifo = "--fifo" in args

            for i, a in enumerate(args):
                if a == "--infile" and i + 1 < len(args):
                    infile = args[i + 1]
                if a == "--outfile" and i + 1 < len(args):
                    outfile = args[i + 1]

            if is_fifo and infile is None:
                # Default FIFO path
                from pathlib import Path
                try:
                    from csc_platform import Platform
                    run_dir = Platform.PROJECT_ROOT / "tmp" / "csc" / "run"
                except Exception:
                    run_dir = Path("/opt/csc/tmp/csc/run")
                infile = str(run_dir / "client.in")
                if outfile is None:
                    outfile = str(run_dir / "client.out")

            # Try to find server connection from /proc/pid/net/udp or config
            try:
                from csc_platform import Platform
                cfg_path = Platform.PROJECT_ROOT / "tmp" / "csc" / "run" / "settings.json"
                if cfg_path.exists():
                    cfg = json.loads(cfg_path.read_text())
                    host = cfg.get("server_host", "127.0.0.1")
                    port = cfg.get("server_port", 9525)
                    server = f"{host}:{port}"
            except Exception:
                pass  # Ignored exception

            if server is None:
                server = "127.0.0.1:9525"

            if is_fifo or infile:
                clients.append({
                    "pid": pid_str,
                    "server": server,
                    "infile": infile,
                    "outfile": outfile,
                })
        except Exception:
            continue
    return clients


def status(args, config_manager):
    """Show service status - real runtime state from systemd."""
    try:
        _do_status(args, config_manager)
    except Exception as e:
        print(f"FATAL ERROR in status command: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def _do_status(args, config_manager):
    cfg = config_manager.config

    if args.service:
        _show_service_status(args.service, cfg)
        return

    print("CSC Service Status")
    print("=" * 50)

    # Parent unit
    parent_state = _systemd_active(*PARENT_UNIT)
    parent_pid = _systemd_pid(*PARENT_UNIT)
    pid_str = f"(PID {parent_pid})" if parent_pid else ""
    print(f"\n  {'csc-service':22s} {parent_state:10s} {pid_str}")

    # In-process services
    print()
    for key, name in INPROC_SERVICES.items():
        enabled = cfg.get(key, False)
        cfg_str = "enabled" if enabled else "disabled"
        if parent_state == "active":
            rt = "running" if enabled else "idle"
        else:
            rt = "stopped (parent down)"
        print(f"  {name:22s} {cfg_str:10s}  [{rt}]")

    # Standalone user units with port info
    print()
    for name, (unit, scope, cfg_key) in UNIT_SERVICES.items():
        enabled = cfg.get(cfg_key, False)
        cfg_str = "enabled" if enabled else "disabled"
        
        # On Windows, these run as threads in the parent process
        if IS_WINDOWS:
            if parent_state == "active":
                state = "active" if enabled else "inactive"
                pid = parent_pid # Threaded services share parent PID
            else:
                state = "inactive"
                pid = None
        else:
            state = _systemd_active(unit, scope)
            pid = _systemd_pid(unit, scope)
            
        pid_str = f"(PID {pid})" if pid else ""
        print(f"  {name:22s} {cfg_str:10s}  [{state}] {pid_str}")
        if state == "active":
            if name == "server":
                for line in _net_info_server(state):
                    print(line)
            elif name == "bridge":
                for line in _net_info_bridge(state):
                    print(line)

    # FIFO / file-mode clients
    fifo_clients = _fifo_clients()
    if fifo_clients:
        print()
        print("  FIFO Clients:")
        for c in fifo_clients:
            print(f"    PID {c['pid']:8s}  connected -> {c['server']}")
            if c['infile']:
                print(f"               in:  {c['infile']}")
            if c['outfile']:
                print(f"               out: {c['outfile']}")

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
        unit, scope, cfg_key = UNIT_SERVICES[service]
        enabled = cfg.get(cfg_key, False)
        state = _systemd_active(unit, scope)
        print(f"{service}: {'enabled' if enabled else 'disabled'}  [{state}]  (user unit: {unit})")
        if state == "active":
            if service == "server":
                for line in _net_info_server(state):
                    print(line)
            elif service == "bridge":
                for line in _net_info_bridge(state):
                    print(line)
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
        unit, scope, cfg_key = UNIT_SERVICES[service]
        print(json.dumps({service: {"unit": unit, "scope": scope, "enabled": cfg.get(cfg_key, False)}}, indent=2))
        return

    print(f"Unknown service: {service}")
