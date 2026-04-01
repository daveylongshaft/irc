"""Shared utilities for batch API."""

import os
import sys
import json
import re
from pathlib import Path


def ensure_env(var: str) -> str:
    """Get environment variable or read from .env file."""
    # Check environment first
    val = os.environ.get(var)
    if val:
        return val

    # Try to load from .env files
    env_files = [
        Path.home() / ".config" / "csc" / ".env",
        Path.cwd() / ".env",
        Path("/c/csc/.env"),
    ]

    for env_file in env_files:
        if env_file.exists():
            try:
                for line in env_file.read_text(encoding='utf-8').split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        if key.strip() == var:
                            val = value.strip()
                            # Remove quotes if present
                            if val.startswith('"') and val.endswith('"'):
                                val = val[1:-1]
                            elif val.startswith("'") and val.endswith("'"):
                                val = val[1:-1]
                            if val:
                                # Set in environment for subprocess calls
                                os.environ[var] = val
                                return val
            except Exception as e:
                pass  # Continue to next file

    # Not found
    print(f"ERROR: {var} not set in environment or .env files", file=sys.stderr)
    print(f"Set it in:", file=sys.stderr)
    print(f"  - Environment: export {var}=\"...\"", file=sys.stderr)
    print(f"  - ~/.config/csc/.env", file=sys.stderr)
    print(f"  - .env in current directory", file=sys.stderr)
    sys.exit(1)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown.

    Returns: (metadata_dict, remaining_content)
    """
    if not content.startswith("---"):
        return {}, content

    lines = content.split("\n")
    if len(lines) < 2:
        return {}, content

    # Find closing ---
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, content

    # Parse YAML-like frontmatter (simple, not full YAML parser)
    fm_text = "\n".join(lines[1:end_idx])
    metadata = {}

    for line in fm_text.split("\n"):
        if not line.strip() or line.startswith("#"):
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Remove quotes
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            metadata[key] = val

    # Remaining content
    remaining = "\n".join(lines[end_idx + 1:]).strip()
    return metadata, remaining


def read_text(path: Path) -> str:
    """Read text file."""
    try:
        return path.read_text(encoding='utf-8')
    except Exception as e:
        print(f"ERROR reading {path}: {e}", file=sys.stderr)
        sys.exit(1)


def load_system_context(context_dir: Path = None, defaults: list[str] = None) -> str:
    """Load system context from files.

    Args:
        context_dir: Optional directory to read context files from
        defaults: List of default file paths to try (relative to csc root)

    Returns:
        System context string for prompt
    """
    parts = []

    if context_dir and context_dir.exists():
        # Load all .txt and .md files from context_dir
        for fpath in sorted(context_dir.glob("*")):
            if fpath.is_file() and fpath.suffix in (".txt", ".md"):
                try:
                    content = fpath.read_text(encoding='utf-8')
                    parts.append(f"=== {fpath.name} ===\n{content}")
                except:
                    pass

    if not parts and defaults:
        # Try default paths
        csc_root = Path(__file__).resolve().parent.parent.parent
        for rel_path in defaults:
            fpath = (csc_root / rel_path).resolve()
            if fpath.exists():
                try:
                    content = fpath.read_text(encoding='utf-8')
                    parts.append(f"=== {rel_path} ===\n{content}")
                except:
                    pass

    return "\n\n".join(parts) if parts else ""


def abs_path(user_path: str) -> Path:
    """Convert user path to absolute, relative to cwd."""
    p = Path(user_path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def is_workorder_file(path: Path) -> bool:
    """Check if file looks like a workorder (.md file)."""
    return path.is_file() and path.suffix == ".md"


def collect_workorders(source: str) -> list[Path]:
    """Collect workorder files from path or directory.

    Args:
        source: Path to single .md file or directory with .md files

    Returns:
        List of Path objects pointing to workorder files
    """
    source_path = abs_path(source)

    if source_path.is_file() and source_path.suffix == ".md":
        return [source_path]

    if source_path.is_dir():
        # Collect all .md files in directory (not recursive)
        files = [f for f in sorted(source_path.iterdir()) if is_workorder_file(f)]
        return files

    print(f"ERROR: {source} is not a workorder file or directory", file=sys.stderr)
    sys.exit(1)
