import time

class IgnoreManager:
    """
    Manages temporary silence state for the AI agent.
    """
    def __init__(self, timeout_secs: int = 300):
        self._timeout = timeout_secs
        self._ignored_until: float = 0.0

    def parse(self, text: str, my_nick: str):
        """
        Parses !ignore commands to determine if this agent should be silenced.
        """
        tokens = text.split()
        if not tokens or tokens[0].lower() != "!ignore":
            return

        # "!ignore" with no arguments affects all agents
        if len(tokens) == 1:
            self._ignored_until = time.time() + self._timeout
            return

        # "!ignore nick1 nick2" affects only listed agents
        target_nicks = [t.lower() for t in tokens[1:]]
        if my_nick.lower() in target_nicks:
            self._ignored_until = time.time() + self._timeout

    def is_ignored(self) -> bool:
        """
        Returns True if the agent is currently in a silence period.
        """
        return time.time() < self._ignored_until

    def clear(self):
        """
        Clears the ignore state immediately.
        """
        self._ignored_until = 0.0

    def set_timeout(self, secs: int):
        """
        Updates the default silence duration.
        """
        self._timeout = secs
