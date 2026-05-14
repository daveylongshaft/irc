"""Load csc-service.json for mTLS cert paths and memory store root."""

import json
import os
from pathlib import Path


def _find_csc_service_json():
    candidates = []
    csc_root = os.environ.get("CSC_ROOT", "")
    if csc_root:
        candidates.append(Path(csc_root) / "etc" / "csc-service.json")
        candidates.append(Path(csc_root) / "csc-service.json")
    csc_etc = os.environ.get("CSC_ETC", "")
    if csc_etc:
        candidates.append(Path(csc_etc) / "csc-service.json")
    # Walk up from package directory
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / "etc" / "csc-service.json")
        candidates.append(parent / "csc-service.json")
        if (parent / ".irc_root").exists():
            break
    for path in candidates:
        if path.exists():
            return path
    return None


class memory_config:
    def __init__(self):
        path = _find_csc_service_json()
        data = {}
        if path:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass

        mem = data.get("memory", {})
        self.s2s_cert = data.get("s2s_cert", "")
        self.s2s_key = data.get("s2s_key", "")
        self.s2s_ca = data.get("s2s_ca", "")
        self.host = mem.get("host", "127.0.0.1")
        self.port = int(mem.get("port", 9532))
        self.store_root = Path(
            mem.get("store_root", "") or
            os.environ.get("CSC_MEMORY_ROOT", "") or
            self._default_store_root()
        )

    @staticmethod
    def _default_store_root():
        here = Path(__file__).resolve()
        for parent in here.parents:
            candidate = parent / "docs" / "memory"
            if candidate.exists():
                return str(candidate)
            if (parent / ".irc_root").exists():
                return str(parent / "docs" / "memory")
        return str(Path.home() / "docs" / "memory")

    @property
    def has_tls(self):
        return bool(self.s2s_cert and self.s2s_key and self.s2s_ca)
