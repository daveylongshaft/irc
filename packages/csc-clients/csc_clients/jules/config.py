"""Jules configuration - reads from csc-service.json."""

import json
from pathlib import Path


class JulesConfig:
    """Jules configuration loaded from csc-service.json."""

    def __init__(self, config_path=None):
        if config_path:
            self._data = json.loads(Path(config_path).read_text(encoding="utf-8"))
        else:
            # Walk up to find csc-service.json
            p = Path(__file__).resolve().parent
            for _ in range(10):
                for name in ("csc-service.json", "etc/csc-service.json"):
                    candidate = p / name
                    if candidate.exists():
                        self._data = json.loads(candidate.read_text(encoding="utf-8"))
                        self.jules_config = self._data.get("jules", {})
                        return
                if p == p.parent:
                    break
                p = p.parent
            self._data = {}
        self.jules_config = self._data.get("jules", {})

    @property
    def enabled(self):
        return self.jules_config.get("enabled", False)

    @property
    def api_key_path(self):
        return self.jules_config.get("api_key_path")

    @property
    def max_concurrent_sessions(self):
        return self.jules_config.get("max_concurrent_sessions", 1)

    @property
    def auto_approve_plans(self):
        return self.jules_config.get("auto_approve_plans", False)

    @property
    def github_repo(self):
        return self.jules_config.get("github_repo")

    @property
    def github_branch(self):
        return self.jules_config.get("github_branch", "main")
