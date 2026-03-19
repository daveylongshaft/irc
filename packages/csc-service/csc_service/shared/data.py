"""Shim: re-exports Data from the installed csc-data layer package.

All code that does ``from csc_service.shared.data import Data`` continues
to work unchanged while now using the canonical layered-package class.

csc_data.Data inherits from csc_data.old_data.Data (which contains the
full key-value store + IRC persistence implementation) and overrides
log() and _write_runtime() to write to the encrypted VFS instead of
plain disk files. This is the key change: server logs now go to VFS.
"""

from csc_data import Data

__all__ = ["Data"]
