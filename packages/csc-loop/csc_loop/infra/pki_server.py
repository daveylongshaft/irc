"""PKI enrollment server lifecycle for csc-loop.

Starts the enrollment HTTP server in a daemon thread on first cycle,
monitors health on subsequent cycles. Restarts if the thread dies.
"""
import logging
import threading
import time

log = logging.getLogger(__name__)

_thread = None
_started_at = None


def _run_enrollment():
    """Run the PKI enrollment server (blocks forever)."""
    from csc_pki.enrollment_server import run_server, BIND_HOST, BIND_PORT
    run_server(BIND_HOST, BIND_PORT)


def run_cycle(work_dir=None):
    """Start or monitor the PKI enrollment server.

    Returns True if work was done (server started/restarted).
    """
    global _thread, _started_at
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    if _thread is not None and _thread.is_alive():
        return False  # healthy, nothing to do

    if _thread is not None:
        log.warning("[%s] [pki] enrollment server thread died, restarting", ts)
        print(f"[{ts}] [pki] enrollment server thread died, restarting")

    _thread = threading.Thread(
        target=_run_enrollment,
        daemon=True,
        name="pki-enrollment",
    )
    _thread.start()
    _started_at = time.time()

    msg = "started" if _started_at == time.time() else "restarted"
    print(f"[{ts}] [pki] enrollment server {msg}")
    return True
