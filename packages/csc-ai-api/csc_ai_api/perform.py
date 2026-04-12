import logging
import configparser
from pathlib import Path
from typing import List, Optional, Callable

logger = logging.getLogger("csc.ai_api.perform")

class PerformManager:
    """
    Manages IRC perform scripts and agent-specific configurations.
    """

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._vars = {}
        self._scripts = {}
        self._ai = {}

    def load(self):
        """
        Loads the configuration from the INI file.
        """
        if not self.config_path.exists():
            logger.warning(f"Config path {self.config_path} does not exist.")
            return

        config = configparser.ConfigParser(interpolation=None)
        config.read(self.config_path)

        if "identity" in config:
            self._vars = dict(config["identity"])
        
        if "perform" in config:
            for event, script in config["perform"].items():
                lines = []
                for line in script.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    # Strip ; comments
                    if " ;" in line:
                        line = line.split(" ;")[0].strip()
                    elif line.startswith(";"):
                        continue
                    if line:
                        lines.append(line)
                self._scripts[event] = lines

        if "ai" in config:
            self._ai = dict(config["ai"])

    def fire(self, event: str, extra_vars: dict = None, send_fn: Optional[Callable[[str], None]] = None):
        """
        Fires a lifecycle event, substituting variables and calling send_fn.
        """
        if event not in self._scripts:
            return

        variables = self._vars.copy()
        if extra_vars:
            variables.update(extra_vars)

        for line in self._scripts[event]:
            # Substitute variables
            for key, value in variables.items():
                placeholder = f"${key}"
                if placeholder in line:
                    line = line.replace(placeholder, str(value))
            
            if send_fn:
                send_fn(line)

    def get(self, section: str, key: str, fallback=None):
        """
        Returns a configuration value.
        """
        if section == "ai":
            return self._ai.get(key, fallback)
        if section == "identity":
            return self._vars.get(key, fallback)
        return fallback

    @property
    def wakewords(self) -> List[str]:
        """
        Returns a list of wake words.
        """
        raw_wakewords = self.get("ai", "wakewords", "")
        if not raw_wakewords:
            return []
        
        nick = self.nick
        words = raw_wakewords.replace("$nick", nick).split()
        return words

    @property
    def channels(self) -> List[str]:
        """
        Returns a list of channels to join.
        """
        raw_channels = self.get("identity", "channels", "")
        return raw_channels.split()

    @property
    def nick(self) -> str:
        return self.get("identity", "nick", "agent")

    @property
    def server(self) -> str:
        return self.get("identity", "server", "127.0.0.1")

    @property
    def port(self) -> int:
        import os
        try:
            return int(self.get("identity", "port", os.environ.get("CSC_SERVER_PORT", "9525")))
        except (ValueError, TypeError):
            return 9525
