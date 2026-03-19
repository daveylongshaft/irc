"""Shim: re-exports Root from the installed csc-root layer package.

All code that does ``from csc_service.shared.root import Root`` continues
to work unchanged while now using the canonical layered-package class.
"""

from csc_root import Root

__all__ = ["Root"]
