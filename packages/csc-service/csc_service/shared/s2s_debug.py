"""S2S debug logging with auto-truncation.

Toggle: create /opt/csc/S2S_DEBUG to enable, remove to disable.
Logs to /opt/csc/logs/s2s-debug.log, auto-truncates at 1000 lines.
"""

import os
import time
import threading
from pathlib import Path

_MAX_LINES = 1000
_TOGGLE_FILE = None  # resolved lazily
_LOG_FILE = None
_lock = threading.Lock()
_enabled_cache = False
_enabled_check_time = 0


def _resolve_paths():
    global _TOGGLE_FILE, _LOG_FILE
    if _TOGGLE_FILE is not None:
        return
    try:
        from csc_platform import Platform
        root = Path(Platform.PROJECT_ROOT)
    except Exception:
        root = Path("/opt/csc")
    _TOGGLE_FILE = root / "S2S_DEBUG"
    _LOG_FILE = root / "logs" / "s2s-debug.log"
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def enabled():
    """Check if S2S debug is enabled (cached for 5s)."""
    global _enabled_cache, _enabled_check_time
    now = time.time()
    if now - _enabled_check_time < 5:
        return _enabled_cache
    _resolve_paths()
    _enabled_cache = _TOGGLE_FILE.exists()
    _enabled_check_time = now
    return _enabled_cache


def dlog(tag, msg):
    """Write a debug log line if S2S_DEBUG is enabled.

    Args:
        tag: Short identifier like "LINK", "HANDSHAKE", "AUTH"
        msg: Debug message
    """
    if not enabled():
        return
    _resolve_paths()
    ts = time.strftime("%H:%M:%S", time.localtime())
    ms = int((time.time() % 1) * 1000)
    hostname = os.uname().nodename.split(".")[0] if hasattr(os, "uname") else "?"
    line = f"[{ts}.{ms:03d}] [{hostname}] [{tag}] {msg}\n"

    with _lock:
        try:
            with open(_LOG_FILE, "a") as f:
                f.write(line)
            # Truncate if over limit
            _maybe_truncate()
        except Exception:
            pass


def _maybe_truncate():
    """Keep only last _MAX_LINES lines."""
    try:
        with open(_LOG_FILE, "r") as f:
            lines = f.readlines()
        if len(lines) > _MAX_LINES:
            with open(_LOG_FILE, "w") as f:
                f.writelines(lines[-_MAX_LINES:])
    except Exception:
        pass
