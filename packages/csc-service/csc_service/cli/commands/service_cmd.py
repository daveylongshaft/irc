"""Service lifecycle commands: restart, install, remove, cycle.

On Linux: uses systemctl (--user for in-proc services, system for server/bridge).
On Windows: uses 'net start/stop' for system services.
"""
import os
import sys
import subprocess

IS_WINDOWS = os.name == 'nt'

# Map service name -> (unit_name, scope)
# scope "user"   -> systemctl --user  (no sudo needed)
# scope "system" -> systemctl         (may need sudo)
UNIT_MAP = {
    "csc-service":  ("csc-service.service",  "user"),
    "queue-worker": ("csc-service.service",  "user"),   # in-proc thread, restart parent
    "test-runner":  ("csc-service.service",  "user"),
    "pm":           ("csc-service.service",  "user"),
    "pr-reviewer":  ("csc-service.service",  "user"),
    "server":       ("csc-server.service",   "user"),
    "bridge":       ("csc-bridge.service",   "user"),
}


def _systemctl(scope, *args):
    cmd = ["systemctl"]
    if scope == "user":
        cmd.append("--user")
    cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _sc_run(svc_name, action):
    try:
        r = subprocess.run(["net", action, svc_name],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def _do_restart(service, force=False):
    entry = UNIT_MAP.get(service)
    if not entry:
        print(f"Unknown service: {service}")
        return False
    unit, scope = entry

    if IS_WINDOWS:
        svc_name = unit.replace(".service", "")
        ok, msg = _sc_run(svc_name, "stop")
        print(f"Stop  {svc_name}: {msg}")
        ok, msg = _sc_run(svc_name, "start")
        print(f"Start {svc_name}: {msg}")
        return ok

    if force:
        _systemctl(scope, "kill", "-s", "SIGKILL", unit)

    r = _systemctl(scope, "restart", unit)
    if r.returncode == 0:
        print(f"Restarted {unit} ({scope})")
        return True
    else:
        print(f"Failed to restart {unit} ({scope}): {(r.stdout + r.stderr).strip()}")
        return False


def restart(args, config_manager):
    service = args.service
    force = getattr(args, 'force', False)

    if service == "all":
        seen = set()
        for svc, (unit, scope) in UNIT_MAP.items():
            if unit not in seen:
                seen.add(unit)
                r = _systemctl(scope, "restart", unit)
                state = "OK" if r.returncode == 0 else "FAIL"
                print(f"[{state}] {unit} ({scope})")
    else:
        _do_restart(service, force=force)


def install(args, config_manager):
    """Enable and start services."""
    if getattr(args, 'list_only', False):
        print("Services:")
        seen = set()
        for name, (unit, scope) in UNIT_MAP.items():
            if unit not in seen:
                seen.add(unit)
                print(f"  {unit:35s} ({scope})")
        return

    service = getattr(args, 'service', 'all') or 'all'
    targets = UNIT_MAP.items() if service == "all" else \
        [(service, UNIT_MAP[service])] if service in UNIT_MAP else []

    seen = set()
    for name, (unit, scope) in targets:
        if unit in seen:
            continue
        seen.add(unit)
        if IS_WINDOWS:
            ok, msg = _sc_run(unit.replace(".service", ""), "start")
            print(f"{'OK' if ok else 'FAIL'} {unit}: {msg}")
        else:
            r = _systemctl(scope, "enable", "--now", unit)
            print(f"{'OK' if r.returncode==0 else 'FAIL'} enable+start {unit} ({scope})")
            if r.returncode != 0:
                print(f"  {(r.stdout+r.stderr).strip()}")


def remove(args, config_manager):
    """Disable and stop services."""
    if getattr(args, 'list_only', False):
        install(args, config_manager)
        return

    service = getattr(args, 'service', 'all') or 'all'
    targets = UNIT_MAP.items() if service == "all" else \
        [(service, UNIT_MAP[service])] if service in UNIT_MAP else []

    seen = set()
    for name, (unit, scope) in targets:
        if unit in seen:
            continue
        seen.add(unit)
        if IS_WINDOWS:
            ok, msg = _sc_run(unit.replace(".service", ""), "stop")
            print(f"{'OK' if ok else 'FAIL'} stop {unit}: {msg}")
        else:
            r = _systemctl(scope, "disable", "--now", unit)
            print(f"{'OK' if r.returncode==0 else 'FAIL'} disable+stop {unit} ({scope})")
            if r.returncode != 0:
                print(f"  {(r.stdout+r.stderr).strip()}")


def cycle(args, config_manager):
    """Run one processing cycle for an in-proc subsystem."""
    service = args.service
    from pathlib import Path
    root = Path(config_manager.config_file).parent if config_manager.config_file else Path.cwd()

    if service == "queue-worker":
        try:
            from csc_service.infra.queue_worker import run_cycle
            run_cycle()
            print("Queue worker cycle complete")
        except Exception as e:
            print(f"Queue worker cycle failed: {e}")

    elif service == "test-runner":
        try:
            from csc_service.infra.test_runner import run_cycle
            run_cycle()
            print("Test runner cycle complete")
        except Exception as e:
            print(f"Test runner cycle failed: {e}")

    elif service == "pm":
        try:
            from csc_service.infra.pm import setup, run_cycle
            setup(root)
            assigned = run_cycle()
            if assigned:
                for fname, agent in (assigned or []):
                    print(f"Assigned: {fname} -> {agent}")
            else:
                print("No workorders to assign")
        except Exception as e:
            print(f"PM cycle failed: {e}")

    elif service == "pr-reviewer":
        try:
            from csc_service.infra.pr_review import run_cycle
            run_cycle(root)
            print("PR review cycle complete")
        except Exception as e:
            print(f"PR review cycle failed: {e}")

    else:
        print(f"Unknown service: {service}")
        print("In-proc: queue-worker, test-runner, pm, pr-reviewer")
        print("For server/bridge: csc-ctl restart server|bridge")
        sys.exit(1)
