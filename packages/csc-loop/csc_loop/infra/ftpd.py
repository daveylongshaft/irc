"""FTP daemon lifecycle for csc-loop.

Starts the FTP master (or slave) in daemon threads on first cycle,
monitors health on subsequent cycles. Restarts if threads die.
"""
import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

_master = None
_started_at = None


def _load_ftpd_config(work_dir):
    """Load ftpd config section from csc-service.json."""
    config_path = Path(work_dir) / "etc" / "csc-service.json"
    if not config_path.exists():
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            full = json.load(f)
        return full.get("ftpd")
    except (json.JSONDecodeError, OSError) as e:
        log.error("[ftpd] failed to load config: %s", e)
        return None


def run_cycle(work_dir=None):
    """Start or monitor the FTP daemon.

    Returns True if work was done (daemon started/restarted).
    """
    global _master, _started_at
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    # Already running and healthy
    if _master is not None and not _master._shutdown.is_set():
        return False

    if _master is not None:
        log.warning("[%s] [ftpd] master shutdown detected, restarting", ts)
        print(f"[{ts}] [ftpd] master shutdown detected, restarting")
        try:
            _master.stop()
        except Exception:
            pass

    from csc_ftpd.ftp_config import FtpConfig
    from csc_ftpd.ftp_master import FtpMaster

    ftpd_dict = _load_ftpd_config(work_dir) if work_dir else None
    config = FtpConfig(config_dict=ftpd_dict, csc_root=work_dir)

    if not config.enabled:
        return False

    if config.role != "master":
        # Slave support can be added later
        log.info("[%s] [ftpd] role=%s, skipping (only master supported in loop)", ts, config.role)
        return False

    _master = FtpMaster(config)
    _master.start()
    _started_at = time.time()

    print(f"[{ts}] [ftpd] master started (ftp={config.ftp_control_port}, slaves={config.master_control_port})")
    return True
