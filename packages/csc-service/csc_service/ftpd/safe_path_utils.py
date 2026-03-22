"""Safe path utilities for FTP handlers - prevents path traversal attacks."""

from pathlib import Path


def safe_vpath_to_local(vpath: str, serve_root: Path) -> Path:
    """
    Convert a virtual path to a local filesystem path with security checks.

    Prevents path traversal attacks by:
    1. Resolving the path to its canonical form
    2. Ensuring the resolved path stays within serve_root
    3. Rejecting symlinks that point outside serve_root

    Args:
        vpath: Virtual path (e.g., '/file.txt', '/../../../etc/passwd')
        serve_root: Root directory that all paths must stay within

    Returns:
        Resolved Path object if safe

    Raises:
        ValueError: If path traversal or symlink escape attempted
    """
    # Convert serve_root to absolute Path
    serve_root = Path(serve_root).resolve()

    # Remove leading '/' and convert '/' to OS separators
    rel = vpath.lstrip('/').replace('/', '\\')

    # Build the candidate path
    candidate = serve_root / rel

    # Resolve to canonical form (follows symlinks, removes .. and .)
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as e:
        raise ValueError(f"Path resolution failed: {e}")

    # Check 1: Resolved path must be within or equal to serve_root
    try:
        resolved.relative_to(serve_root)
    except ValueError:
        raise ValueError(f"Path traversal attack detected: {vpath} resolves outside serve_root")

    # Check 2: If the candidate had symlinks, verify they don't escape serve_root
    # Walk up the path and check each symlink target
    current = candidate
    while current != current.parent:
        if current.is_symlink():
            target = current.resolve()
            try:
                target.relative_to(serve_root)
            except ValueError:
                raise ValueError(f"Symlink escape detected: {current} -> {target} escapes serve_root")
        current = current.parent

    return resolved
