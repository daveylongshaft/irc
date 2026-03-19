"""Cross-platform install planning for the layered CSC core packages.

This module is intentionally planner-first so it can be integrated into a
future `csc-ctl` workflow without taking direct dependencies on the current
service lifecycle implementation. It focuses on:

- ordered package install/uninstall plans
- path resolution for this repo checkout
- import migration examples from legacy `csc_service.shared` / `server` paths
- rendering shell-friendly plans for Windows and Linux integrators
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import os
import shlex
from typing import Sequence


@dataclass(frozen=True)
class LayerPackageSpec:
    """Metadata for one independently installable layer package."""

    distribution: str
    import_name: str
    class_name: str
    relative_dir: str
    dependencies: tuple[str, ...]
    legacy_imports: tuple[str, ...]
    replacement_import: str
    notes: str = ""

    def package_dir(self, repo_root: Path) -> Path:
        return repo_root / self.relative_dir


LAYER_PACKAGE_ORDER: tuple[LayerPackageSpec, ...] = (
    LayerPackageSpec(
        distribution="csc-root",
        import_name="csc_root",
        class_name="Root",
        relative_dir="packages/csc-root",
        dependencies=(),
        legacy_imports=("from csc_service.shared.root import Root",),
        replacement_import="from csc_root import Root",
    ),
    LayerPackageSpec(
        distribution="csc-log",
        import_name="csc_log",
        class_name="Log",
        relative_dir="packages/csc-log",
        dependencies=("csc-root",),
        legacy_imports=("from csc_service.shared.log import Log",),
        replacement_import="from csc_log import Log",
    ),
    LayerPackageSpec(
        distribution="csc-data",
        import_name="csc_data",
        class_name="Data",
        relative_dir="packages/csc-data",
        dependencies=("csc-log",),
        legacy_imports=("from csc_service.shared.data import Data",),
        replacement_import="from csc_data import Data",
        notes="Uses enc-ext-vfs for encrypted relative data/log storage under CSC_ROOT/vfs while keeping ServerData/ops/etc helpers in csc_service.",
    ),
    LayerPackageSpec(
        distribution="csc-version",
        import_name="csc_version",
        class_name="Version",
        relative_dir="packages/csc-version",
        dependencies=("csc-data",),
        legacy_imports=("from csc_service.shared.version import Version",),
        replacement_import="from csc_version import Version",
    ),
    LayerPackageSpec(
        distribution="csc-platform",
        import_name="csc_platform",
        class_name="Platform",
        relative_dir="packages/csc-platform",
        dependencies=("csc-version",),
        legacy_imports=("from csc_service.shared.platform import Platform",),
        replacement_import="from csc_platform import Platform",
    ),
    LayerPackageSpec(
        distribution="csc-network",
        import_name="csc_network",
        class_name="Network",
        relative_dir="packages/csc-network",
        dependencies=("csc-platform",),
        legacy_imports=("from csc_service.shared.network import Network",),
        replacement_import="from csc_network import Network",
    ),
    LayerPackageSpec(
        distribution="csc-service-base",
        import_name="csc_service_base",
        class_name="Service",
        relative_dir="packages/csc-service-base",
        dependencies=("csc-network",),
        legacy_imports=(
            "from csc_service.server.service import Service",
            "from csc_service.shared.service import Service",
        ),
        replacement_import="from csc_service_base import Service",
        notes="Still uses csc_service shared service modules for dynamic service loading.",
    ),
    LayerPackageSpec(
        distribution="csc-server-core",
        import_name="csc_server_core",
        class_name="Server",
        relative_dir="packages/csc-server-core",
        dependencies=("csc-service-base",),
        legacy_imports=("from csc_service.server.server import Server",),
        replacement_import="from csc_server_core import Server",
        notes="Still uses csc_service server handlers and shared IRC helpers for non-core server composition.",
    ),
)

LEGACY_IMPORT_MAP = {
    legacy: spec.replacement_import
    for spec in LAYER_PACKAGE_ORDER
    for legacy in spec.legacy_imports
}


def _walk_for_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "packages" / "csc-root").exists() and (candidate / "packages" / "csc-service").exists():
            return candidate
    return start


def resolve_repo_root() -> Path:
    """Resolve this checkout's repo root.

    Preference order:
    1. `CSC_ROOT` if it looks like this repo checkout.
    2. `Platform.PROJECT_ROOT` when available.
    3. Walk up from this file until `packages/csc-root` and `packages/csc-service` exist.
    """
    env_root = os.environ.get("CSC_ROOT")
    if env_root:
        env_path = Path(env_root).expanduser().resolve()
        if (env_path / "packages" / "csc-root").exists():
            return env_path

    try:
        from csc_service.shared.platform import Platform

        platform_root = Path(Platform.PROJECT_ROOT).resolve()
        if (platform_root / "packages" / "csc-root").exists():
            return platform_root
    except Exception:
        pass

    return _walk_for_repo_root(Path(__file__).resolve())


def build_install_plan(repo_root: Path | None = None) -> list[dict]:
    """Return structured install metadata in dependency order."""
    resolved_root = Path(repo_root).resolve() if repo_root else resolve_repo_root()
    plan = []
    for spec in LAYER_PACKAGE_ORDER:
        plan.append(
            {
                **asdict(spec),
                "package_dir": str(spec.package_dir(resolved_root)),
            }
        )
    return plan


def _quote_for_shell(path: Path, shell: str) -> str:
    text = str(path)
    if shell == "powershell":
        return f"'{text}'"
    return shlex.quote(text)


def build_install_commands(
    repo_root: Path | None = None,
    python_executable: str = "python",
    editable: bool = True,
    shell: str = "bash",
) -> list[str]:
    """Build ordered pip install commands for all layered packages."""
    resolved_root = Path(repo_root).resolve() if repo_root else resolve_repo_root()
    flag = "-e " if editable else ""
    commands = []
    for spec in LAYER_PACKAGE_ORDER:
        package_dir = _quote_for_shell(spec.package_dir(resolved_root), shell)
        commands.append(f"{python_executable} -m pip install {flag}{package_dir}".strip())
    return commands


def build_uninstall_commands(python_executable: str = "python") -> list[str]:
    """Build reverse-order uninstall commands for all layered packages."""
    commands = []
    for spec in reversed(LAYER_PACKAGE_ORDER):
        commands.append(f"{python_executable} -m pip uninstall -y {spec.distribution}")
    return commands


def render_install_plan(
    repo_root: Path | None = None,
    python_executable: str = "python",
    shell: str = "bash",
) -> str:
    """Render a human-readable integration plan for control-app usage."""
    resolved_root = Path(repo_root).resolve() if repo_root else resolve_repo_root()
    install_commands = build_install_commands(resolved_root, python_executable=python_executable, shell=shell)
    uninstall_commands = build_uninstall_commands(python_executable=python_executable)

    lines = [
        "CSC Layer Package Reinstall Plan",
        f"repo_root: {resolved_root}",
        "",
        "Phase 1: stop and remove existing services with the old control app",
        "  - csc-ctl remove all",
        "  - csc-ctl disable all",
        "  - preserve config/state files before pulling updates",
        "",
        "Phase 2: uninstall old layer packages in reverse order",
    ]
    lines.extend(f"  - {command}" for command in uninstall_commands)
    lines.append("")
    lines.append("Phase 3: pull repo changes and install new layer packages in dependency order")
    lines.extend(f"  - {command}" for command in install_commands)
    lines.append("")
    lines.append("Phase 4: reinstall / enable / start services with the new control app integration")
    lines.append("  - csc-ctl install all")
    lines.append("  - csc-ctl enable all")
    lines.append("  - csc-ctl restart all")
    lines.append("")
    lines.append("Import migration examples:")
    for legacy, replacement in LEGACY_IMPORT_MAP.items():
        lines.append(f"  - {legacy}  ->  {replacement}")
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None = None):
    import argparse

    parser = argparse.ArgumentParser(description="Render install plans for the layered CSC packages.")
    parser.add_argument("--repo-root", help="Override repo root used to build package paths.")
    parser.add_argument("--python", default="python", help="Python executable to use in generated commands.")
    parser.add_argument("--shell", choices=("bash", "powershell"), default="bash")
    parser.add_argument("--json", action="store_true", help="Print the structured install plan as JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None
    if args.json:
        print(json.dumps(build_install_plan(repo_root), indent=2))
    else:
        print(render_install_plan(repo_root, python_executable=args.python, shell=args.shell))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
