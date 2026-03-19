"""Shim: re-exports Version from the installed csc-version layer package.

All code that does ``from csc_service.shared.version import Version`` continues
to work unchanged while now using the canonical layered-package class.
"""

from csc_version import Version

__all__ = ["Version"]
