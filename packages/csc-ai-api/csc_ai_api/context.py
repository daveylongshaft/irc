from collections import deque


class ContextManager:
    """Per-channel circular backscroll buffer with wakeword detection.

    Every channel message is buffered regardless of whether the agent
    responds. When the agent does respond, get() provides the conversation
    history to send to the AI API.
    """

    def __init__(self, backscroll=20):
        self._backscroll = backscroll
        self._buffers = {}  # channel -> deque(maxlen=backscroll)

    def buffer(self, channel, nick, text):
        if channel not in self._buffers:
            self._buffers[channel] = deque(maxlen=self._backscroll)
        self._buffers[channel].append(f"{nick}: {text}")

    def get(self, channel, n=None):
        buf = self._buffers.get(channel)
        if not buf:
            return []
        lines = list(buf)
        if n is not None:
            lines = lines[-n:]
        return lines

    def is_direct_mention(self, text, wakewords):
        text_lower = text.lower()
        return any(w.lower() in text_lower for w in wakewords)

    def set_backscroll(self, n):
        self._backscroll = n
