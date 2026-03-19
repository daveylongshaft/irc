"""Shim: re-exports Network from the installed csc-network layer package.

All code that does ``from csc_service.shared.network import Network`` continues
to work unchanged while now using the canonical layered-package class.
"""

from csc_network import Network

__all__ = ["Network"]
