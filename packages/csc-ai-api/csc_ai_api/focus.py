import time
from typing import Dict

class FocusManager:
    """
    Manages the engagement window for the AI agent.
    """
    def __init__(self, window_secs: int = 300):
        self._window = window_secs
        self._focused: Dict[str, float] = {}

    def mark_responded(self, channel: str, window_secs: int = None):
        """
        Enters or resets the focus window for a specific channel.
        """
        self._focused[channel] = time.time() + (window_secs or self._window)

    def is_focused(self, channel: str) -> bool:
        """
        Returns True if the agent is currently within the focus window for the channel.
        """
        return time.time() < self._focused.get(channel, 0.0)

    def reset(self, channel: str):
        """
        Clears focus for a channel immediately.
        """
        if channel in self._focused:
            del self._focused[channel]

    def set_window(self, secs: int):
        """
        Updates the default focus window duration.
        """
        self._window = secs
