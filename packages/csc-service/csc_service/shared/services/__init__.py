"""CSC shared services."""
import os
import json
from pathlib import Path


def find_project_root():
    """Find the CSC project root directory.

    Strategy:
    1. Check CSC_ROOT environment variable (most reliable override)
    2. Check platform.json in ancestor dirs for working_dir
    3. Walk up looking for marker files (CLAUDE.md, csc-service.json, README.1shot)
    4. Fallback: 6 levels up from this file
    """
    # 1. Environment variable override
    env_root = os.environ.get("CSC_ROOT")
    if env_root and Path(env_root).is_dir():
        return Path(env_root)

    # 2. Walk up from this file looking for markers
    p = Path(__file__).resolve().parent
    markers = ("CLAUDE.md", "csc-service.json", "README.1shot")
    for _ in range(10):
        # Check if platform.json has a working_dir we can use
        pj = p / "platform.json"
        if pj.exists():
            try:
                data = json.loads(pj.read_text(encoding="utf-8"))
                wd = data.get("working_dir")
                if wd and Path(wd).is_dir():
                    return Path(wd)
            except (json.JSONDecodeError, OSError):
                pass
        # Check for marker files (prefer csc-service.json as it's most specific)
        if (p / "csc-service.json").exists():
            return p
        # Fall back to CLAUDE.md if csc-service.json not found
        if (p / "CLAUDE.md").exists():
            # But make sure we're not in a subdirectory with CLAUDE.md (like irc/)
            # Only return if this looks like the true project root
            if (p / "ops").is_dir() or (p / "irc").is_dir():
                return p
        if p == p.parent:
            break
        p = p.parent
    # Last resort: walk up 7 levels (services → shared → csc_service → csc-service → packages → irc → CSC_ROOT)
    return Path(__file__).resolve().parent.parent.parent.parent.parent.parent.parent


PROJECT_ROOT = find_project_root()
