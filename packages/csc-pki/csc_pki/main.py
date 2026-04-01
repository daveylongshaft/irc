"""PKI subsystem entry point.

Runs as an in-proc daemon thread inside csc-service when
``enable_pki: true`` is set in csc-service.json.

Starts the enrollment HTTP server on 127.0.0.1:9530 and handles
periodic CRL refresh.
"""

import threading
import time

from csc_pki.csc_pki.enrollment_server import run_server, BIND_HOST, BIND_PORT


_thread = None


def start():
    """Start the PKI enrollment server in a daemon thread."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return  # Already running

    _thread = threading.Thread(
        target=run_server,
        args=(BIND_HOST, BIND_PORT),
        daemon=True,
        name="pki-enrollment",
    )
    _thread.start()


def is_alive():
    """Check if the PKI thread is running."""
    return _thread is not None and _thread.is_alive()
