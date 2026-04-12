from collections import deque
from typing import Dict, List, Optional

class ContextManager:
    """
    Manages per-channel backscroll buffers and direct mention detection.
    """
    def __init__(self, backscroll: int = 20):
        self._backscroll = backscroll
        self._buffers: Dict[str, deque] = {}

    def buffer(self, channel: str, nick: str, text: str):
        """
        Adds a message to the channel's backscroll buffer.
        """
        if channel not in self._buffers:
            self._buffers[channel] = deque(maxlen=self._backscroll)
        
        self._buffers[channel].append(f"{nick}: {text}")

    def get(self, channel: str, n: Optional[int] = None) -> List[str]:
        """
        Returns the last n lines of context for a specific channel.
        """
        if channel not in self._buffers:
            return []
        
        buffer = list(self._buffers[channel])
        n = n or self._backscroll
        return buffer[-n:]

    def is_direct_mention(self, text: str, wakewords: List[str]) -> bool:
        """
        Checks if the text contains any of the provided wake words.
        """
        text_lower = text.lower()
        for word in wakewords:
            if word.lower() in text_lower:
                return True
        return False

    def set_backscroll(self, n: int):
        """
        Updates the default backscroll limit for new buffers.
        """
        self._backscroll = n
