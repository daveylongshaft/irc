#!/usr/bin/env python3
"""
Cross-platform installer for CSC external files.

Detects the platform and installs:
- Service files (systemd, launchd, Task Scheduler, termux-boot)
- Launcher scripts (shell scripts or .bat wrappers)
- Crontab / scheduled task for the test runner

Usage:
    python3 deploy/install.py                  # auto-detect everything
    python3 deploy/install.py --dry-run        # show what would happen
    python3 deploy/install.py --user davey     # override user
    python3 deploy/install.py --python /usr/bin/python3.10
    python3 deploy/install.py --uninstall      # remove installed files

stdlib only — no pip dependencies.
"""

import argparse
import grp
import os
import platform as _platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVICES = [
    "csc-server",
    "csc-bridge",
    "csc-gemini",
    "csc-claude",
    "csc-chatgpt",
    "csc-client",
]

# Start order matters for systemd enable, but templates handle After= deps
DEPLOY_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DEPLOY_DIR.parent
SERVICES_DIR = DEPLOY_DIR / "services"
LAUNCHERS_DIR = DEPLOY_DIR / "launchers"
CRONTAB_FILE = DEPLOY_DIR / "crontab.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg, dry_run=False):
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"  {prefix}{msg}")


def detect_platform():
    """Return one of: linux, macos, windows, android."""
    if "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux"):
        return "android"
    system = _platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    return "linux"


def detect_python():
    """Return the path to the current python interpreter."""
    return sys.executable


def detect_user():
    """Return the current username."""
    return os.getenv("USER") or os.getenv("USERNAME") or "nobody"


def detect_group(user):
    """Return the primary group of the given user."""
    if sys.platform == "win32":
        return user
    try:
        import pwd
        pw = pwd.getpwnam(user)
        return grp.getgrgid(pw.pw_gid).gr_name
    except (KeyError, ImportError):
        return user


def process_template(template_path, replacements):
    """Read a template file and substitute {PLACEHOLDER} values."""
    text = template_path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(f"{{{key}}}", value)
    return text


def write_file(path, content, mode=None, dry_run=False):
    """Write content to a file, creating parent dirs as needed."""
    if dry_run:
        log(f"write {path} ({len(content)} bytes)", dry_run=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)
    log(f"wrote {path}")


def copy_file(src, dst, mode=None, dry_run=False):
    """Copy a file, creating parent dirs as needed."""
    if dry_run:
        log(f"copy {src} -> {dst}", dry_run=True)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if mode is not None:
        dst.chmod(mode)
    log(f"copied {src} -> {dst}")


def remove_file(path, dry_run=False):
    """Remove a file if it exists."""
    if not path.exists():
        return
    if dry_run:
        log(f"remove {path}", dry_run=True)
        return
    path.unlink()
    log(f"removed {path}")


def run_cmd(cmd, dry_run=False, check=True):
    """Run a shell command."""
    cmd_str = " ".join(str(c) for c in cmd)
    if dry_run:
        log(f"run: {cmd_str}", dry_run=True)
        return
    log(f"run: {cmd_str}")
    subprocess.run(cmd, check=check)


# ---------------------------------------------------------------------------
# Linux installer (systemd)
# ---------------------------------------------------------------------------

def install_linux(replacements, dry_run=False):
    print("\n[Linux] Installing systemd services...")
    systemd_dir = Path("/etc/systemd/system")

    for svc in SERVICES:
        template = SERVICES_DIR / f"{svc}.service.template"
        if not template.exists():
            log(f"SKIP {svc} — template not found: {template}")
            continue
        content = process_template(template, replacements)
        dest = systemd_dir / f"{svc}.service"
        write_file(dest, content, dry_run=dry_run)

    print("\n[Linux] Installing launcher scripts...")
    bin_dir = Path.home() / ".local" / "bin"
    for svc in SERVICES:
        src = LAUNCHERS_DIR / svc
        if not src.exists():
            log(f"SKIP {svc} — launcher not found: {src}")
            continue
        content = process_template(src, replacements)
        dest = bin_dir / svc
        write_file(dest, content, mode=0o755, dry_run=dry_run)

    print("\n[Linux] Installing crontab entry...")
    install_crontab_linux(replacements, dry_run=dry_run)

    print("\n[Linux] Reloading systemd...")
    run_cmd(["systemctl", "daemon-reload"], dry_run=dry_run, check=False)

    print("\nDone. Enable services with:")
    print("  sudo systemctl enable --now csc-server csc-bridge")
    print("  sudo systemctl enable --now csc-gemini csc-claude csc-chatgpt")


def uninstall_linux(dry_run=False):
    print("\n[Linux] Removing systemd services...")
    systemd_dir = Path("/etc/systemd/system")
    for svc in SERVICES:
        run_cmd(["systemctl", "stop", svc], dry_run=dry_run, check=False)
        run_cmd(["systemctl", "disable", svc], dry_run=dry_run, check=False)
        remove_file(systemd_dir / f"{svc}.service", dry_run=dry_run)
    run_cmd(["systemctl", "daemon-reload"], dry_run=dry_run, check=False)

    print("\n[Linux] Removing launcher scripts...")
    bin_dir = Path.home() / ".local" / "bin"
    for svc in SERVICES:
        remove_file(bin_dir / svc, dry_run=dry_run)

    print("\n[Linux] Removing crontab entry...")
    uninstall_crontab_linux(dry_run=dry_run)


def install_crontab_linux(replacements, dry_run=False):
    """Add the CSC test runner entry to the user's crontab."""
    if not CRONTAB_FILE.exists():
        log(f"SKIP crontab — {CRONTAB_FILE} not found")
        return

    new_entry = process_template(CRONTAB_FILE, replacements).strip()

    # Read existing crontab
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, check=False
        )
        existing = result.stdout if result.returncode == 0 else ""
    except FileNotFoundError:
        existing = ""

    # Check if already installed
    if "run_tests.sh" in existing:
        log("crontab entry already exists, skipping")
        return

    updated = existing.rstrip("\n") + "\n" + new_entry + "\n"
    if dry_run:
        log(f"install crontab entry: {new_entry}", dry_run=True)
        return

    proc = subprocess.run(
        ["crontab", "-"], input=updated, text=True, check=False
    )
    if proc.returncode == 0:
        log(f"installed crontab entry: {new_entry}")
    else:
        log("WARNING: failed to install crontab entry")


def uninstall_crontab_linux(dry_run=False):
    """Remove the CSC test runner entry from the user's crontab."""
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            return
        existing = result.stdout
    except FileNotFoundError:
        return

    lines = [l for l in existing.splitlines() if "run_tests.sh" not in l]
    updated = "\n".join(lines) + "\n"

    if dry_run:
        log("remove crontab entry containing run_tests.sh", dry_run=True)
        return

    subprocess.run(["crontab", "-"], input=updated, text=True, check=False)
    log("removed crontab entry")


# ---------------------------------------------------------------------------
# macOS installer (launchd)
# ---------------------------------------------------------------------------

LAUNCHD_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.csc.{svc_name}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{working_dir}/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{working_dir}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{install_dir}/logs/{svc_name}.log</string>
    <key>StandardErrorPath</key>
    <string>{install_dir}/logs/{svc_name}.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
"""

LAUNCHD_CRON_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.csc.test-runner</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>{install_dir}/tests/run_tests.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{install_dir}</string>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{install_dir}/logs/test-runner.log</string>
    <key>StandardErrorPath</key>
    <string>{install_dir}/logs/test-runner.error.log</string>
</dict>
</plist>
"""


def install_macos(replacements, dry_run=False):
    print("\n[macOS] Installing launchd services...")
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    logs_dir = PROJECT_ROOT / "logs"

    if not dry_run:
        agents_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

    # Map service names to their working directories
    svc_to_pkg = {
        "csc-server": "csc-server",
        "csc-bridge": "csc-bridge",
        "csc-gemini": "csc-gemini",
        "csc-claude": "csc-claude",
        "csc-chatgpt": "csc-chatgpt",
        "csc-client": "csc-client",
    }

    for svc in SERVICES:
        pkg = svc_to_pkg.get(svc, svc)
        working_dir = PROJECT_ROOT / "packages" / pkg
        content = LAUNCHD_PLIST_TEMPLATE.format(
            svc_name=svc,
            python=replacements["PYTHON"],
            working_dir=working_dir,
            install_dir=replacements["INSTALL_DIR"],
        )
        dest = agents_dir / f"com.csc.{svc}.plist"
        write_file(dest, content, dry_run=dry_run)

    # Test runner plist
    content = LAUNCHD_CRON_PLIST.format(install_dir=replacements["INSTALL_DIR"])
    dest = agents_dir / "com.csc.test-runner.plist"
    write_file(dest, content, dry_run=dry_run)

    print("\n[macOS] Installing launcher scripts...")
    bin_dir = Path("/usr/local/bin")
    if not os.access(str(bin_dir), os.W_OK):
        bin_dir = Path.home() / ".local" / "bin"
    for svc in SERVICES:
        src = LAUNCHERS_DIR / svc
        if not src.exists():
            continue
        content = process_template(src, replacements)
        dest = bin_dir / svc
        write_file(dest, content, mode=0o755, dry_run=dry_run)

    print("\nDone. Load services with:")
    for svc in SERVICES:
        print(f"  launchctl load ~/Library/LaunchAgents/com.csc.{svc}.plist")
    print("  launchctl load ~/Library/LaunchAgents/com.csc.test-runner.plist")


def uninstall_macos(dry_run=False):
    print("\n[macOS] Removing launchd services...")
    agents_dir = Path.home() / "Library" / "LaunchAgents"

    for svc in SERVICES:
        plist = agents_dir / f"com.csc.{svc}.plist"
        if plist.exists():
            run_cmd(["launchctl", "unload", str(plist)], dry_run=dry_run, check=False)
            remove_file(plist, dry_run=dry_run)

    runner_plist = agents_dir / "com.csc.test-runner.plist"
    if runner_plist.exists():
        run_cmd(["launchctl", "unload", str(runner_plist)], dry_run=dry_run, check=False)
        remove_file(runner_plist, dry_run=dry_run)

    print("\n[macOS] Removing launcher scripts...")
    for bin_dir in [Path("/usr/local/bin"), Path.home() / ".local" / "bin"]:
        for svc in SERVICES:
            remove_file(bin_dir / svc, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Windows installer (Task Scheduler + .bat wrappers)
# ---------------------------------------------------------------------------

BAT_TEMPLATE = """\
@echo off
"{python}" -m {module}.main %*
"""


def install_windows(replacements, dry_run=False):
    print("\n[Windows] Installing .bat launcher scripts...")
    # Put launchers next to the existing bin/ .bat files
    bin_dir = PROJECT_ROOT / "bin"

    module_map = {
        "csc-server": "csc_server",
        "csc-bridge": "csc_bridge",
        "csc-gemini": "csc_gemini",
        "csc-claude": "csc_claude",
        "csc-chatgpt": "csc_chatgpt",
        "csc-client": "csc_client",
    }

    for svc in SERVICES:
        module = module_map.get(svc, svc.replace("-", "_"))
        content = BAT_TEMPLATE.format(
            python=replacements["PYTHON"],
            module=module,
        )
        dest = bin_dir / f"{svc}.bat"
        write_file(dest, content, dry_run=dry_run)

    print("\n[Windows] Registering test runner in Task Scheduler...")
    ps_script = DEPLOY_DIR / "install_task_scheduler.ps1"
    if ps_script.exists():
        run_cmd([
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(ps_script), "-InstallDir", str(PROJECT_ROOT),
        ], dry_run=dry_run, check=False)
    else:
        # Inline fallback — register directly
        run_tests_ps1 = PROJECT_ROOT / "tests" / "run_tests.ps1"
        if not run_tests_ps1.exists():
            log("SKIP Task Scheduler — tests/run_tests.ps1 not found")
            log("Create it from the PROMPT_windows_test_runner_task_scheduler prompt first")
        else:
            run_cmd([
                "schtasks", "/create", "/tn", "CSC-TestRunner",
                "/tr", f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{run_tests_ps1}"',
                "/sc", "MINUTE", "/mo", "1", "/f",
            ], dry_run=dry_run, check=False)

    print("\nDone. Launchers installed in:")
    print(f"  {bin_dir}")
    print("Add this directory to your PATH if not already there.")


def uninstall_windows(dry_run=False):
    print("\n[Windows] Removing .bat launcher scripts...")
    bin_dir = PROJECT_ROOT / "bin"
    for svc in SERVICES:
        remove_file(bin_dir / f"{svc}.bat", dry_run=dry_run)

    print("\n[Windows] Removing scheduled task...")
    run_cmd(
        ["schtasks", "/delete", "/tn", "CSC-TestRunner", "/f"],
        dry_run=dry_run, check=False,
    )


# ---------------------------------------------------------------------------
# Android / Termux installer (termux-boot scripts)
# ---------------------------------------------------------------------------

TERMUX_BOOT_TEMPLATE = """\
#!/data/data/com.termux/files/usr/bin/bash
# CSC service: {svc_name}
cd "{working_dir}"
nohup {python} main.py > "{install_dir}/logs/{svc_name}.log" 2>&1 &
"""

TERMUX_CRON_BOOT = """\
#!/data/data/com.termux/files/usr/bin/bash
# CSC test runner — runs every minute via crond
# Ensure crond is running (termux-services or manual)
if command -v crond >/dev/null 2>&1; then
    crond
fi
"""


def install_android(replacements, dry_run=False):
    print("\n[Android/Termux] Installing boot scripts...")
    boot_dir = Path.home() / ".termux" / "boot"
    prefix_bin = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr")) / "bin"
    logs_dir = PROJECT_ROOT / "logs"

    if not dry_run:
        boot_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

    svc_to_pkg = {
        "csc-server": "csc-server",
        "csc-bridge": "csc-bridge",
        "csc-gemini": "csc-gemini",
        "csc-claude": "csc-claude",
        "csc-chatgpt": "csc-chatgpt",
        "csc-client": "csc-client",
    }

    for svc in SERVICES:
        pkg = svc_to_pkg.get(svc, svc)
        working_dir = PROJECT_ROOT / "packages" / pkg
        content = TERMUX_BOOT_TEMPLATE.format(
            svc_name=svc,
            python=replacements["PYTHON"],
            working_dir=working_dir,
            install_dir=replacements["INSTALL_DIR"],
        )
        dest = boot_dir / f"csc-start-{svc}.sh"
        write_file(dest, content, mode=0o755, dry_run=dry_run)

    # Cron boot script
    content = TERMUX_CRON_BOOT
    write_file(boot_dir / "csc-start-crond.sh", content, mode=0o755, dry_run=dry_run)

    print("\n[Android/Termux] Installing launcher scripts...")
    for svc in SERVICES:
        src = LAUNCHERS_DIR / svc
        if not src.exists():
            continue
        content = process_template(src, replacements)
        dest = prefix_bin / svc
        write_file(dest, content, mode=0o755, dry_run=dry_run)

    print("\n[Android/Termux] Installing crontab entry...")
    install_crontab_linux(replacements, dry_run=dry_run)

    print("\nDone. Install termux-boot from F-Droid to auto-start on device boot.")
    print("Services will start on next reboot, or run the boot scripts manually:")
    print(f"  bash {boot_dir}/csc-start-csc-server.sh")


def uninstall_android(dry_run=False):
    print("\n[Android/Termux] Removing boot scripts...")
    boot_dir = Path.home() / ".termux" / "boot"
    for svc in SERVICES:
        remove_file(boot_dir / f"csc-start-{svc}.sh", dry_run=dry_run)
    remove_file(boot_dir / "csc-start-crond.sh", dry_run=dry_run)

    print("\n[Android/Termux] Removing launcher scripts...")
    prefix_bin = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr")) / "bin"
    for svc in SERVICES:
        remove_file(prefix_bin / svc, dry_run=dry_run)

    print("\n[Android/Termux] Removing crontab entry...")
    uninstall_crontab_linux(dry_run=dry_run)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CSC cross-platform installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Detects platform automatically. Installs services, launchers, and cron.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without doing it")
    parser.add_argument("--uninstall", action="store_true",
                        help="Remove installed files")
    parser.add_argument("--user", default=None,
                        help="Override service user (default: current user)")
    parser.add_argument("--group", default=None,
                        help="Override service group (default: user's primary group)")
    parser.add_argument("--python", default=None,
                        help="Override python binary path (default: sys.executable)")
    parser.add_argument("--platform", default=None,
                        choices=["linux", "macos", "windows", "android"],
                        help="Override platform detection")

    args = parser.parse_args()

    plat = args.platform or detect_platform()
    python = args.python or detect_python()
    user = args.user or detect_user()
    group = args.group or detect_group(user)

    print(f"CSC Installer")
    print(f"  Platform:    {plat}")
    print(f"  Project:     {PROJECT_ROOT}")
    print(f"  Python:      {python}")
    print(f"  User:        {user}")
    print(f"  Group:       {group}")

    if args.uninstall:
        print(f"\nUninstalling...{' (dry run)' if args.dry_run else ''}")
        dispatch_uninstall = {
            "linux": uninstall_linux,
            "macos": uninstall_macos,
            "windows": uninstall_windows,
            "android": uninstall_android,
        }
        fn = dispatch_uninstall.get(plat)
        if fn:
            fn(dry_run=args.dry_run)
        else:
            print(f"ERROR: unsupported platform: {plat}")
            sys.exit(1)
        return

    replacements = {
        "INSTALL_DIR": str(PROJECT_ROOT),
        "USER": user,
        "GROUP": group,
        "PYTHON": python,
    }

    print(f"\nInstalling...{' (dry run)' if args.dry_run else ''}")

    dispatch_install = {
        "linux": install_linux,
        "macos": install_macos,
        "windows": install_windows,
        "android": install_android,
    }

    fn = dispatch_install.get(plat)
    if fn:
        fn(replacements, dry_run=args.dry_run)
    else:
        print(f"ERROR: unsupported platform: {plat}")
        sys.exit(1)


if __name__ == "__main__":
    main()
