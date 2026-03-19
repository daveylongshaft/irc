"""Package installation orchestrator.

Currently installs the unified csc-service package.

Future: Will support 8 layered packages in dependency order:
1. csc-root
2. csc-log
3. csc-data
4. csc-version
5. csc-platform
6. csc-network
7. csc-service-base
8. csc-server-core
"""

import subprocess
import sys
from pathlib import Path


# Dependency order (csc_root must be first, each depends on previous)
LAYER_PACKAGE_ORDER = (
    "csc_root",
    "csc_log",
    "csc_data",
    "csc_version",
    "csc_platform",
    "csc_network",
    "csc_service_base",
    "csc_server_core",
)

# Directory names for each package (relative to repo root)
PACKAGE_DIRS = {
    "csc_root": "irc/packages/csc_root",
    "csc_log": "irc/packages/csc_log",
    "csc_data": "irc/packages/csc_data",
    "csc_version": "irc/packages/csc_version",
    "csc_platform": "irc/packages/csc_platform",
    "csc_network": "irc/packages/csc_network",
    "csc_service_base": "irc/packages/csc_service_base",
    "csc_server_core": "irc/packages/csc_server_core",
}


def resolve_repo_root():
    """Resolve the repository root directory.

    Looks for /c/csc first (main project root), then searches upward from cwd.
    """
    # Try /c/csc first (main project root)
    main_root = Path("/c/csc")
    if main_root.exists() and (main_root / ".git").exists():
        return main_root

    # Otherwise search upward from cwd
    current = Path.cwd()
    while current != current.parent:
        if (current / ".csc_root").exists() or (current / ".git").exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find repository root")


def build_install_commands(repo_root, python_executable=None, editable=True):
    """Build pip install commands for layered packages.

    Args:
        repo_root: Path to repository root
        python_executable: Python executable to use (default: sys.executable)
        editable: Install in editable mode (default: True)

    Returns:
        List of pip install command strings
    """
    if python_executable is None:
        python_executable = sys.executable

    repo_root = Path(repo_root)
    commands = []

    for package_name in LAYER_PACKAGE_ORDER:
        package_dir = repo_root / PACKAGE_DIRS[package_name]

        # Skip if directory doesn't exist
        if not package_dir.exists():
            print(f"Warning: {package_name} directory not found at {package_dir}, skipping")
            continue

        if editable:
            cmd = f"{python_executable} -m pip install -e {package_dir}"
        else:
            cmd = f"{python_executable} -m pip install {package_dir}"

        commands.append(cmd)

    return commands


def build_uninstall_commands():
    """Build pip uninstall commands for layered packages (reverse order).

    Returns:
        List of pip uninstall command strings
    """
    commands = []

    # Uninstall in reverse order (8 -> 1)
    for package_name in reversed(LAYER_PACKAGE_ORDER):
        cmd = f"{sys.executable} -m pip uninstall -y {package_name}"
        commands.append(cmd)

    return commands


def install_packages(repo_root, python_executable=None, editable=True):
    """Install all layered packages in order.

    Args:
        repo_root: Path to repository root
        python_executable: Python executable to use
        editable: Install in editable mode

    Returns:
        (success: bool, errors: list)
    """
    commands = build_install_commands(repo_root, python_executable, editable)
    errors = []

    for i, cmd in enumerate(commands, 1):
        print(f"[{i}/{len(commands)}] {cmd}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            errors.append((cmd, result.stderr))

    return len(errors) == 0, errors


def uninstall_packages():
    """Uninstall all layered packages in reverse order.

    Returns:
        (success: bool, errors: list)
    """
    commands = build_uninstall_commands()
    errors = []

    for i, cmd in enumerate(commands, 1):
        print(f"[{i}/{len(commands)}] {cmd}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            errors.append((cmd, result.stderr))

    return len(errors) == 0, errors
