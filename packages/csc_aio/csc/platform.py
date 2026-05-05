"""Portable path and platform helpers for CSC AIO."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Iterable


MARKER_FILE = ".csc_root"


def _candidate_paths(start: Path | None = None) -> Iterable[Path]:
    """Yield likely places to begin root discovery."""

    csc_dir = os.environ.get("CSC_DIR")
    if csc_dir:
        yield Path(csc_dir)
    if start is not None:
        yield Path(start)
    yield Path(__file__).resolve()
    yield Path.cwd()
    csc_root = os.environ.get("CSC_ROOT")
    if csc_root:
        yield Path(csc_root)


def find_csc_dir(start: str | Path | None = None) -> Path:
    """Find the directory containing the ``.csc_root`` marker."""

    for candidate in _candidate_paths(Path(start) if start is not None else None):
        try:
            current = candidate.resolve()
        except OSError:
            continue
        if current.is_file():
            current = current.parent
        for path in (current, *current.parents):
            if (path / MARKER_FILE).exists():
                return path
            nested = path / "csc" / MARKER_FILE
            if nested.exists():
                return path / "csc"
    raise FileNotFoundError(f"Unable to locate {MARKER_FILE}")


def find_runtime_root(start: str | Path | None = None) -> Path:
    """Find the userland runtime root that contains ``csc/``, ``ops/``, and ``tmp/``."""

    csc_dir = find_csc_dir(start)
    env_root = os.environ.get("CSC_ROOT")
    if env_root:
        root = Path(env_root).resolve()
        if (root / "csc").resolve() == csc_dir:
            return root
        if root == csc_dir:
            return root.parent
    return csc_dir.parent


class Platform:
    """Resolve portable CSC paths from a dropped-in ``csc`` directory."""

    CSC_DIR = find_csc_dir()
    PROJECT_ROOT = find_runtime_root(CSC_DIR)

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root).resolve() if root else self.PROJECT_ROOT
        self.csc_dir = self.root / "csc"
        if not (self.csc_dir / MARKER_FILE).exists() and (self.root / MARKER_FILE).exists():
            self.csc_dir = self.root

    @classmethod
    def from_here(cls, start: str | Path | None = None) -> "Platform":
        """Build a Platform using marker discovery from ``start``."""

        return cls(find_runtime_root(start))

    def ensure_dirs(self) -> None:
        """Create the standard userland runtime directories."""

        for path in self.path_map().values():
            if path.suffix:
                continue
            path.mkdir(parents=True, exist_ok=True)

    def path_map(self) -> dict[str, Path]:
        """Return canonical CSC directories as Path objects."""

        return {
            "CSC_ROOT": self.root,
            "CSC_DIR": self.csc_dir,
            "CSC_ETC": self.root / "etc",
            "CSC_LOGS": self.root / "ops" / "logs",
            "CSC_TMP": self.root / "tmp",
            "CSC_OPS": self.root / "ops",
            "CSC_OPS_WO": self.root / "ops" / "wo",
            "CSC_OPS_AGENTS": self.root / "ops" / "agents",
            "CSC_SERVICES": self.csc_dir / "services",
            "CSC_STAGING": self.csc_dir / "staging_uploads",
            "CSC_BIN": self.root / "bin",
        }

    def export_env_paths(self) -> dict[str, str]:
        """Export CSC path variables into ``os.environ`` and return them."""

        pairs = {key: str(value) for key, value in self.path_map().items()}
        pairs["CSC_SERVER_NAME"] = self.get_server_shortname()
        os.environ.update(pairs)
        return pairs

    def get_server_shortname(self) -> str:
        """Return this node's stable shortname, creating it if needed."""

        path = self.root / "server_name"
        if path.exists():
            value = path.read_text(encoding="utf-8", errors="replace").strip()
            if value:
                return value
        host = socket.gethostname().split(".")[0].lower() or "csc-node"
        path.write_text(host + "\n", encoding="utf-8")
        return host

    def format_exports(self, shell: str = "auto") -> str:
        """Render path exports for the requested shell."""

        pairs = self.export_env_paths()
        if shell == "auto":
            shell = "powershell" if os.name == "nt" else "posix"
        if shell == "json":
            return json.dumps(pairs, indent=2)
        if shell == "powershell":
            return "\n".join(f'$env:{key} = "{value}"' for key, value in pairs.items())
        if shell == "cmd":
            return "\n".join(f'set "{key}={value}"' for key, value in pairs.items())
        return "\n".join(f'export {key}="{value}"' for key, value in pairs.items())


def platform(root: str | Path | None = None) -> Platform:
    """Return a Platform instance."""

    return Platform(root)
