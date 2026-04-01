"""Service lifecycle commands: restart, install, remove, cycle.

Windows: uses NSSM (bin/nssm.EXE) — no popup windows, real Windows services.
Linux:   uses systemctl --user (systemd units).
"""
import os
import sys
import subprocess
import time
from pathlib import Path

IS_WINDOWS = os.name == 'nt'

# Windows service name -> (python module, display name)
WIN_SERVICES = {
    "CSC-SERVER": ("csc_server_core.server",      "CSC IRC Server"),
    "CSC-LOOP":   ("csc_loop.infra.queue_worker", "CSC Loop Worker"),
    "CSC-BRIDGE": ("csc_bridge.main",             "CSC Bridge"),
    "CSC-FTPD":   ("csc_ftpd.ftp_master",         "CSC FTP Daemon"),
    "CSC-PKI":    ("csc_pki.main",                "CSC PKI Service"),
}

# Old service names to remove during migration
OLD_WIN_SERVICES = ["CSC-CSC-SERVER", "CSC-CSC-BRIDGE", "CSC-CSC-SERVICE", "csc-service"]

# Linux systemd unit name -> (unit file, scope)
LINUX_UNITS = {
    "csc-server": ("csc-server.service", "user"),
    "csc-loop":   ("csc-loop.service",   "user"),
    "csc-bridge": ("csc-bridge.service", "user"),
    "csc-ftpd":   ("csc-ftpd.service",   "user"),
    "csc-pki":    ("csc-pki.service",    "user"),
}


def _nssm():
    """Return path to nssm.EXE."""
    here = Path(__file__).resolve()
    # Walk up to project root (contains csc-service.json)
    p = here
    for _ in range(12):
        if (p / "csc-service.json").exists() or (p / "etc" / "csc-service.json").exists():
            break
        if p == p.parent:
            break
        p = p.parent
    candidate = p / "bin" / "nssm.EXE"
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError(f"nssm.EXE not found (looked in {p / 'bin'})")


def _python():
    """Return path to Python executable (same one running this process)."""
    return sys.executable


def _project_root():
    """Return project root path."""
    here = Path(__file__).resolve()
    p = here
    for _ in range(12):
        if (p / "csc-service.json").exists() or (p / "etc" / "csc-service.json").exists():
            return p
        if p == p.parent:
            break
        p = p.parent
    return Path("C:/csc")


def _nssm_run(*args, check=False):
    nssm = _nssm()
    r = subprocess.run([nssm] + list(args), capture_output=True, text=True, timeout=30)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def _net(action, svc_name):
    r = subprocess.run(["net", action, svc_name], capture_output=True, text=True, timeout=30)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def _systemctl(scope, *args):
    cmd = ["systemctl"]
    if scope == "user":
        cmd.append("--user")
    cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


# ── Windows install/remove ──────────────────────────────────────────────────

def _win_remove_service(svc_name, silent=False):
    _net("stop", svc_name)
    ok, msg = _nssm_run("remove", svc_name, "confirm")
    if not silent:
        print(f"  {'OK' if ok else 'SKIP'} remove {svc_name}: {msg}")


def _win_install_service(svc_name, module, display):
    root = _project_root()
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = str(logs_dir / f"{svc_name.lower()}.log")
    python = _python()

    # Remove first so install is idempotent
    _nssm_run("remove", svc_name, "confirm")

    ok, msg = _nssm_run("install", svc_name, python, "-m", module)
    if not ok:
        print(f"  FAIL install {svc_name}: {msg}")
        return False

    _nssm_run("set", svc_name, "AppDirectory",      str(root))
    _nssm_run("set", svc_name, "AppStdout",          log_file)
    _nssm_run("set", svc_name, "AppStderr",          log_file)
    _nssm_run("set", svc_name, "AppStdoutCreationDisposition", "4")  # append
    _nssm_run("set", svc_name, "AppStderrCreationDisposition", "4")
    _nssm_run("set", svc_name, "DisplayName",        display)
    _nssm_run("set", svc_name, "Start",              "SERVICE_AUTO_START")
    _nssm_run("set", svc_name, "AppRestartDelay",    "5000")   # 5s before restart
    _nssm_run("set", svc_name, "AppThrottle",        "1500")   # slow restart loop
    print(f"  OK install {svc_name} -> {module}")
    return True


# ── Public commands ──────────────────────────────────────────────────────────

def install(args, config_manager):
    service = getattr(args, "service", "all") or "all"
    list_only = getattr(args, "list_only", False)

    if IS_WINDOWS:
        targets = WIN_SERVICES.items() if service == "all" else \
            [(service, WIN_SERVICES[service])] if service in WIN_SERVICES else []

        if list_only:
            for svc, (module, display) in targets:
                print(f"  {svc}: python -m {module}  ({display})")
            return

        # Remove old services first
        if service == "all":
            print("[Step 1] Removing legacy services...")
            for old in OLD_WIN_SERVICES:
                _win_remove_service(old, silent=False)

        print("\n[Step 2] Installing new services...")
        for svc, (module, display) in targets:
            _win_install_service(svc, module, display)

        print("\n[Step 3] Starting services...")
        for svc, _ in targets:
            ok, msg = _net("start", svc)
            print(f"  {'OK' if ok else 'FAIL'} start {svc}: {msg}")

    else:
        targets = LINUX_UNITS.items() if service == "all" else \
            [(service, LINUX_UNITS[service])] if service in LINUX_UNITS else []

        if list_only:
            for name, (unit, scope) in targets:
                print(f"  {unit} ({scope})")
            return

        for name, (unit, scope) in targets:
            r = _systemctl(scope, "enable", "--now", unit)
            print(f"  {'OK' if r.returncode==0 else 'FAIL'} enable+start {unit}")


def remove(args, config_manager):
    service = getattr(args, "service", "all") or "all"

    if IS_WINDOWS:
        targets = list(WIN_SERVICES.keys()) if service == "all" else \
            [service] if service in WIN_SERVICES else []

        if service == "all":
            targets += OLD_WIN_SERVICES

        for svc in targets:
            _win_remove_service(svc)

    else:
        targets = LINUX_UNITS.items() if service == "all" else \
            [(service, LINUX_UNITS[service])] if service in LINUX_UNITS else []

        for name, (unit, scope) in targets:
            r = _systemctl(scope, "disable", "--now", unit)
            print(f"  {'OK' if r.returncode==0 else 'FAIL'} disable+stop {unit}")


def restart(args, config_manager):
    service = args.service

    if IS_WINDOWS:
        targets = list(WIN_SERVICES.keys()) if service == "all" else \
            [service] if service in WIN_SERVICES else []

        for svc in targets:
            _net("stop", svc)
            time.sleep(1)
            ok, msg = _net("start", svc)
            print(f"  {'OK' if ok else 'FAIL'} restart {svc}: {msg}")

    else:
        targets = LINUX_UNITS.items() if service == "all" else \
            [(service, LINUX_UNITS[service])] if service in LINUX_UNITS else []

        for name, (unit, scope) in targets:
            r = _systemctl(scope, "restart", unit)
            print(f"  {'OK' if r.returncode==0 else 'FAIL'} restart {unit}")


def cycle(args, config_manager):
    service = args.service
    if service == "queue-worker":
        from csc_loop.infra.queue_worker import run_cycle
        run_cycle()
    elif service == "test-runner":
        from csc_loop.infra.test_runner import run_cycle
        run_cycle()
    elif service == "pm":
        from csc_loop.infra.pm import run_cycle
        run_cycle()
    print(f"Cycle complete for {service}")
