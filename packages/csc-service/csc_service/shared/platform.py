"""Shim: re-exports Platform from the installed csc-platform layer package.

All code that does ``from csc_service.shared.platform import Platform`` continues
to work unchanged while now using the canonical layered-package class.

_parse_size is re-exported for backward compatibility (used by agent_service.py).
"""

from csc_platform import Platform
from csc_platform.platform import _parse_size

__all__ = ["Platform", "_parse_size"]
