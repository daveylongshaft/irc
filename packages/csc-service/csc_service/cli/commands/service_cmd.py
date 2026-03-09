"""Service lifecycle commands: restart, install, remove, cycle."""
import os
import sys
import signal
import subprocess
import tempfile
import time
from pathlib import Path

IS_WINDOWS = os.name == 'nt'


def _find_project_root():
    """Find the CSC project root by walking up from cwd."""
    p = Path.cwd()
    while p != p.parent:
        if (p / "csc-service.json").exists():
            return p
        p = p.parent
    return Path.cwd()


def _get_pid_file(service_name):
    """Get the PID file path for a service."""
    return Path(tempfile.gettempdir()) / f"csc-{service_name}.pid"


def _read_pid(service_name):
    """Read PID from file, return int or None."""
    pidfile = _get_pid_file(service_name)
    if pidfile.exists():
        try:
            return int(pidfile.read_text().strip())
        except (ValueError, OSError):
            pass
    return None


def _is_alive(pid):
    """Check if process is alive."""
    try:
        if IS_WINDOWS:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True
            )
            return str(pid) in result.stdout
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False


def _kill_pid(pid, force=False):
    """Kill a process by PID."""
    try:
        if IS_WINDOWS:
            flag = "/F" if force else "/T"
            subprocess.run(
                ["taskkill", flag, "/PID", str(pid)],
                capture_output=True, timeout=10
            )
        else:
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.kill(pid, sig)
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        pass


def stop_service(service_name, force=False):
    """Stop a service by its PID file."""
    pid = _read_pid(service_name)
    if pid and _is_alive(pid):
        print(f"Stopping {service_name} (PID {pid})...")
        _kill_pid(pid, force=force)
        # Wait up to 5 seconds for process to die
        for _ in range(10):
            if not _is_alive(pid):
                break
            time.sleep(0.5)
        if _is_alive(pid):
            if not force:
                print(f"Process still alive, force killing...")
                _kill_pid(pid, force=True)
                time.sleep(1)
            if _is_alive(pid):
                print(f"WARNING: Could not kill PID {pid}")
                return False
        pidfile = _get_pid_file(service_name)
        if pidfile.exists():
            pidfile.unlink()
        print(f"Stopped {service_name}")
        return True
    else:
        print(f"{service_name} is not running")
        pidfile = _get_pid_file(service_name)
        if pidfile.exists():
            pidfile.unlink()
        return True


def start_service(service_name):
    """Start a service in the background."""
    root = _find_project_root()

    # Map service names to commands
    cmd_map = {
        "csc-service": [sys.executable, "-m", "csc_service.main", "--daemon", "--local"],
        "queue-worker": [sys.executable, str(root / "bin" / "queue-worker")],
        "test-runner": [sys.executable, str(root / "bin" / "test-runner")],
    }

    cmd = cmd_map.get(service_name)
    if not cmd:
        print(f"Don't know how to start {service_name}")
        return False

    try:
        log_file = root / f"{service_name}.daemon.log"
        log_fh = open(log_file, "a", encoding="utf-8")
        kwargs = {"cwd": str(root), "stdout": log_fh, "stderr": subprocess.STDOUT}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True

        proc = subprocess.Popen(cmd, **kwargs)
        pidfile = _get_pid_file(service_name)
        pidfile.write_text(str(proc.pid))
        print(f"Started {service_name} with PID {proc.pid}")
        print(f"Log: {log_file}")
        return True
    except Exception as e:
        print(f"Failed to start {service_name}: {e}")
        return False


def restart(args, config_manager):
    """Restart a service."""
    service = args.service
    force = getattr(args, 'force', False)

    if service == "all":
        for svc in ("queue-worker", "test-runner", "csc-service"):
            stop_service(svc, force=force)
        time.sleep(2)
        start_service("csc-service")
    else:
        stop_service(service, force=force)
        time.sleep(2)
        start_service(service)


def install(args, config_manager):
    """Install background services (scheduled tasks / cron)."""
    if getattr(args, 'list_only', False):
        print("Services that would be installed:")
        print("  server        (runs continuously)")
        print("  queue-worker  (polls every 2 minutes)")
        print("  test-runner   (polls every 5 minutes)")
        return

    root = _find_project_root()
    service = args.service

    if IS_WINDOWS:
        _install_windows(root, service)
    else:
        _install_unix(root, service)


def _install_windows(root, service):
    """Install Windows scheduled tasks."""
    python = sys.executable
    tasks = []

    if service in ("all", "server"):
        tasks.append({
            "name": "CSC-Server",
            "cmd": f'"{python}" "{root / "bin" / "server"}"',
            "interval": None,  # Startup trigger
        })
    if service in ("all", "queue-worker"):
        tasks.append({
            "name": "CSC-QueueWorker",
            "cmd": f'"{python}" "{root / "bin" / "queue-worker"}"',
            "interval": 2,
        })
    if service in ("all", "test-runner"):
        tasks.append({
            "name": "CSC-TestRunner",
            "cmd": f'"{python}" "{root / "bin" / "test-runner"}"',
            "interval": 5,
        })

    for task in tasks:
        try:
            if task["interval"] is None:
                # Startup trigger (for server)
                subprocess.run([
                    "schtasks", "/Create", "/F",
                    "/SC", "ONSTART",
                    "/TN", task["name"],
                    "/TR", task["cmd"],
                ], check=True, capture_output=True)
                print(f"Installed scheduled task: {task['name']} (runs at startup)")
            else:
                # Periodic trigger
                subprocess.run([
                    "schtasks", "/Create", "/F",
                    "/SC", "MINUTE", "/MO", str(task["interval"]),
                    "/TN", task["name"],
                    "/TR", task["cmd"],
                ], check=True, capture_output=True)
                print(f"Installed scheduled task: {task['name']} (every {task['interval']}min)")
        except subprocess.CalledProcessError as e:
            print(f"Failed to install {task['name']}: {e.stderr.decode()[:200] if e.stderr else e}")
            print("Try running as Administrator")


def _install_unix(root, service):
    """Install cron jobs and startup scripts."""
    python = sys.executable
    lines = []

    if service in ("all", "server"):
        lines.append(f"@reboot cd {root} && {python} bin/server >> logs/server.log 2>&1 &")
    if service in ("all", "queue-worker"):
        lines.append(f"*/2 * * * * cd {root} && {python} bin/queue-worker >> logs/queue-worker.log 2>&1")
    if service in ("all", "test-runner"):
        lines.append(f"*/5 * * * * cd {root} && {python} bin/test-runner >> logs/test-runner.log 2>&1")

    print("Add these to your crontab (crontab -e):")
    for line in lines:
        print(f"  {line}")
    print("\nOr run: (crontab -l 2>/dev/null; echo '<line>') | crontab -")
    print("\nNote: Server runs at startup (@reboot). Other services run on schedule.")


def remove(args, config_manager):
    """Remove background services."""
    if getattr(args, 'list_only', False):
        print("Services that would be removed:")
        print("  server")
        print("  queue-worker")
        print("  test-runner")
        return

    service = args.service

    if IS_WINDOWS:
        tasks = []
        if service in ("all", "server"):
            tasks.append("CSC-Server")
        if service in ("all", "queue-worker"):
            tasks.append("CSC-QueueWorker")
        if service in ("all", "test-runner"):
            tasks.append("CSC-TestRunner")

        for task_name in tasks:
            try:
                subprocess.run(
                    ["schtasks", "/Delete", "/F", "/TN", task_name],
                    check=True, capture_output=True
                )
                print(f"Removed scheduled task: {task_name}")
            except subprocess.CalledProcessError:
                print(f"Task {task_name} not found or already removed")
    else:
        print("Remove cron entries manually: crontab -e")
        print("Look for lines containing 'queue-worker' or 'test-runner'")


def cycle(args, config_manager):
    """Run one processing cycle for a subsystem."""
    service = args.service
    root = _find_project_root()

    if service == "queue-worker":
        try:
            from csc_service.infra.queue_worker import run_cycle
            run_cycle()
            print("Queue worker cycle complete")
        except Exception as e:
            print(f"Queue worker cycle failed: {e}")

    elif service == "test-runner":
        # Run test-runner script directly
        try:
            result = subprocess.run(
                [sys.executable, str(root / "bin" / "test-runner")],
                cwd=str(root), capture_output=True, text=True, timeout=300
            )
            print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
        except subprocess.TimeoutExpired:
            print("Test runner timed out")
        except Exception as e:
            print(f"Test runner failed: {e}")

    elif service == "pm":
        try:
            from csc_service.infra.pm import setup, run_cycle
            setup(root)
            assigned = run_cycle()
            if assigned:
                for fname, agent in assigned:
                    print(f"Assigned {fname} -> {agent}")
            else:
                print("No workorders to assign")
        except Exception as e:
            print(f"PM cycle failed: {e}")

    else:
        print(f"Unknown service: {service}")
        print("Known: queue-worker, test-runner, pm")
        sys.exit(1)
