"""Global subprocess wrapper - auto-hides windows on Windows.

Import this module early (in __init__.py or main) to auto-patch subprocess.run and Popen.
"""
import subprocess
import sys

# Save originals
_original_run = subprocess.run
_original_popen = subprocess.Popen


def run(*args, **kwargs):
    """subprocess.run wrapper - auto-add CREATE_NO_WINDOW on Windows."""
    if sys.platform == "win32" and "creationflags" not in kwargs:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return _original_run(*args, **kwargs)


class Popen(subprocess.Popen):
    """subprocess.Popen wrapper - auto-add CREATE_NO_WINDOW on Windows."""
    def __init__(self, *args, **kwargs):
        if sys.platform == "win32" and "creationflags" not in kwargs:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        super().__init__(*args, **kwargs)


def patch_subprocess():
    """Monkey-patch subprocess module to auto-hide windows."""
    subprocess.run = run
    subprocess.Popen = Popen
