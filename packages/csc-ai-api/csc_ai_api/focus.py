import time


class FocusManager:
    """Tracks per-channel engagement windows after the agent responds.

    During the focus window all channel messages go through standoff coalescing
    (not just direct @mentions). Window resets each time the agent responds.
    """

    def __init__(self, window_secs=300):
        self._window = window_secs
        self._focused = {}  # channel -> expire_timestamp

    def mark_responded(self, channel, window_secs=None):
        self._focused[channel] = time.time() + (window_secs or self._window)

    def is_focused(self, channel):
        return time.time() < self._focused.get(channel, 0)

    def reset(self, channel):
        self._focused.pop(channel, None)

    def set_window(self, secs):
        self._window = secs
