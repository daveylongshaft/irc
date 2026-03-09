"""
Platform gate helper for cross-platform tests.

Tests that target a specific platform (e.g., Windows, macOS, Android/Termux)
should call `require_platform()` at module level or in setUp. If the current
machine doesn't match, the test prints a PLATFORM_SKIP line and raises
unittest.SkipTest. The cron runner (`run_tests.sh`) detects PLATFORM_SKIP
in the log and deletes it, so the test keeps cycling until it reaches the
right machine.

Usage in a test file:

    from platform_gate import require_platform
    require_platform(["windows"])  # Module-level gate

    class TestWindowsSpecific(unittest.TestCase):
        def test_something(self):
            ...

Or per-test:

    from platform_gate import skip_unless_platform

    class TestMixed(unittest.TestCase):
        @skip_unless_platform(["darwin"])
        def test_macos_only(self):
            ...

Supported platform names (case-insensitive):
    linux, windows, darwin, android, termux, wsl
"""

import os
import sys
import platform as _platform
import unittest
import functools


def _current_platforms():
    """Return set of platform tags for the current machine."""
    tags = set()
    system = _platform.system().lower()
    tags.add(system)
    tags.add(sys.platform)

    # Android/Termux
    if "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux"):
        tags.add("android")
        tags.add("termux")

    # WSL
    release = _platform.release().lower()
    if "microsoft" in release or "wsl" in release:
        tags.add("wsl")

    # Docker
    if os.path.exists("/.dockerenv"):
        tags.add("docker")

    return tags


def require_platform(required, reason=None):
    """Gate the entire test module to specific platform(s).

    Call at module level. If the current platform doesn't match any of the
    required platforms, prints PLATFORM_SKIP and raises SkipTest so the
    cron runner knows to delete the log and retry later.

    Args:
        required: List of platform names (e.g., ["windows", "darwin"])
        reason: Optional human-readable reason
    """
    current = _current_platforms()
    required_lower = {r.lower() for r in required}

    if not current.intersection(required_lower):
        msg = reason or f"Requires platform {required}, have {sorted(current)}"
        # This line is what run_tests.sh looks for
        print(f"PLATFORM_SKIP: {msg}")
        raise unittest.SkipTest(msg)


def skip_unless_platform(required, reason=None):
    """Decorator to skip individual tests on wrong platform.

    Usage:
        @skip_unless_platform(["windows"])
        def test_windows_registry(self):
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current = _current_platforms()
            required_lower = {r.lower() for r in required}
            if not current.intersection(required_lower):
                msg = reason or f"Requires platform {required}, have {sorted(current)}"
                print(f"PLATFORM_SKIP: {msg}")
                raise unittest.SkipTest(msg)
            return func(*args, **kwargs)
        return wrapper
    return decorator
