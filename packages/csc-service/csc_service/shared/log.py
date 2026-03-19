"""Shim: re-exports Log from the installed csc-log layer package.

All code that does ``from csc_service.shared.log import Log`` continues
to work unchanged while now using the canonical layered-package class.

_get_logs_dir is re-exported for backward compatibility (used by
csc_data.old_data._write_ftp_announce via internal import).
"""

from csc_log import Log
from csc_log.log import _get_logs_dir

__all__ = ["Log", "_get_logs_dir"]
