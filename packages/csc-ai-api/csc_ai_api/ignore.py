import time


class IgnoreManager:
    """Tracks whether this agent has been silenced via !ignore.

    !ignore               -> silence self
    !ignore nick1 nick2   -> silence self only if my nick is in the list
    Timeout configurable (default 300s). @mention breaks silence immediately.
    """

    def __init__(self, timeout_secs=300):
        self._timeout = timeout_secs
        self._ignored_until = 0.0

    def parse(self, text, my_nick):
        parts = text.strip().split()
        if not parts or parts[0].lower() != "!ignore":
            return
        targets = parts[1:]
        if not targets or my_nick.lower() in [t.lower() for t in targets]:
            self._ignored_until = time.time() + self._timeout

    def is_ignored(self):
        return time.time() < self._ignored_until

    def clear(self):
        self._ignored_until = 0.0

    def set_timeout(self, secs):
        self._timeout = secs
