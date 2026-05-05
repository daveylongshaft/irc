"""Portable CSC core package.

This package is designed to run directly from a directory on ``sys.path``.
No pip installation is required for basic path discovery and service control.
"""

from .platform import Platform, find_csc_dir, find_runtime_root, platform

__all__ = [
    "Platform",
    "find_csc_dir",
    "find_runtime_root",
    "platform",
]
