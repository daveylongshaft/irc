"""FTP daemon configuration loader.

Loads and validates the 'ftpd' section from csc-service.json.
"""

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


class FtpConfig:
    """Load/validate ftpd config from csc-service.json.

    Tries CSC_HOME env var first, then cwd, then walks up to find
    csc-service.json (same pattern as _load_cert_config in server_s2s.py).
    """

    DEFAULTS = {
        "enabled": False,
        "role": "slave",
        "master_host": "10.10.10.1",
        "master_control_port": 9527,
        "ftp_control_port": 9521,
        "ftp_passive_range": [9540, 9560],
        "serve_root": "",
        "index_path": "etc/ftpd_index.json",
        "users_path": "etc/ftpd_users.json",
        "heartbeat_interval": 30,
        "inventory_refresh_interval": 300,
        "fxp_enabled": True,
        "tls_required": True,
    }

    def __init__(self, config_dict=None, csc_root=None):
        """Initialize from a dict or by loading from disk.

        Args:
            config_dict: Pre-loaded ftpd config dict (skips file I/O).
            csc_root: Project root path. If None, auto-detected.
        """
        if csc_root is not None:
            self.csc_root = Path(csc_root)
        else:
            self.csc_root = self._find_csc_root()

        if config_dict is not None:
            raw = config_dict
        else:
            raw = self._load_from_disk()

        # Merge defaults with loaded config
        for key, default in self.DEFAULTS.items():
            setattr(self, key, raw.get(key, default))

        # Resolve serve_root to absolute path (default: project root itself)
        if self.serve_root:
            self.serve_root = str(Path(self.serve_root).resolve())
        else:
            self.serve_root = str(self.csc_root)

        # Resolve index_path and users_path relative to csc_root
        self.index_path = str(self.csc_root / self.index_path)
        self.users_path = str(self.csc_root / self.users_path)

        # Load S2S TLS cert paths (reuse existing S2S certs)
        self.s2s_cert = ""
        self.s2s_key = ""
        self.s2s_ca = ""
        self._load_tls_paths()

    def _find_csc_root(self):
        """Find project root: CSC_HOME env, then cwd, then walk up."""
        csc_home = os.environ.get("CSC_HOME", "")
        if csc_home:
            p = Path(csc_home)
            if (p / "csc-service.json").exists() or (p / "etc" / "csc-service.json").exists():
                return p

        cwd = Path.cwd()
        candidate = cwd
        for _ in range(10):
            if (candidate / "csc-service.json").exists():
                return candidate
            if (candidate / "etc" / "csc-service.json").exists():
                return candidate
            if candidate == candidate.parent:
                break
            candidate = candidate.parent
        return cwd

    def _load_from_disk(self):
        """Load the ftpd section from csc-service.json."""
        candidates = [
            self.csc_root / "etc" / "csc-service.json",
            self.csc_root / "csc-service.json",
        ]
        for path in candidates:
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return data.get("ftpd", {})
                except Exception as e:
                    log.warning("FtpConfig: failed to load %s: %s", path, e)
        log.info("FtpConfig: no csc-service.json found, using defaults")
        return {}

    def _load_tls_paths(self):
        """Load S2S TLS cert paths from csc-service.json (top-level keys)."""
        candidates = [
            self.csc_root / "etc" / "csc-service.json",
            self.csc_root / "csc-service.json",
        ]
        for path in candidates:
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    self.s2s_cert = data.get("s2s_cert", "")
                    self.s2s_key = data.get("s2s_key", "")
                    self.s2s_ca = data.get("s2s_ca", "")
                    return
                except Exception:
                    pass

    @property
    def is_master(self):
        return self.role == "master"

    @property
    def is_slave(self):
        return self.role == "slave"

    @property
    def passive_range(self):
        """Return (low, high) tuple for passive port range."""
        r = self.ftp_passive_range
        if isinstance(r, list) and len(r) == 2:
            return (int(r[0]), int(r[1]))
        return (9540, 9560)

    @property
    def has_tls(self):
        """Check if TLS certs are configured."""
        return bool(self.s2s_cert and self.s2s_key and self.s2s_ca)

    def validate(self):
        """Validate config. Returns (ok, reason)."""
        if self.role not in ("master", "slave"):
            return False, f"Invalid role: {self.role!r} (must be 'master' or 'slave')"

        if self.is_master and self.tls_required and not self.has_tls:
            return False, "Master requires TLS but no S2S certs configured"

        low, high = self.passive_range
        if low >= high:
            return False, f"Invalid passive range: {low}-{high}"

        if self.is_slave and not self.master_host:
            return False, "Slave requires master_host"

        return True, "ok"

    def __repr__(self):
        return (
            f"FtpConfig(role={self.role!r}, enabled={self.enabled}, "
            f"master_host={self.master_host!r}, serve_root={self.serve_root!r})"
        )
