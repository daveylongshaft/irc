import threading
from collections import defaultdict
from typing import Dict, List, Tuple, Callable

class StandoffManager:
    """
    Handles coalescing delays for AI responses.
    Prevents response bursts by resetting a timer on each new message.
    """
    def __init__(self):
        self._timers: Dict[str, threading.Timer] = {}
        self._buffers: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        self._lock = threading.Lock()

    def add(self, channel: str, nick: str, text: str):
        """
        Appends a message to the buffer for a specific channel.
        """
        with self._lock:
            self._buffers[channel].append((nick, text))

    def start_or_reset(self, channel: str, delay_ms: int, callback: Callable[[str, List[Tuple[str, str]]], None]):
        """
        Starts or resets the standoff timer for a channel.
        """
        with self._lock:
            if channel in self._timers:
                self._timers[channel].cancel()
            
            timer = threading.Timer(delay_ms / 1000.0, self._fire, [channel, callback])
            timer.daemon = True
            self._timers[channel] = timer
            timer.start()

    def cancel(self, channel: str):
        """
        Cancels the standoff timer for a channel without clearing the buffer.
        """
        with self._lock:
            if channel in self._timers:
                self._timers[channel].cancel()
                del self._timers[channel]

    def flush(self, channel: str) -> List[Tuple[str, str]]:
        """
        Returns and clears the buffered messages for a channel.
        """
        with self._lock:
            messages = list(self._buffers.get(channel, []))
            self._buffers[channel] = []
            return messages

    def _fire(self, channel: str, callback: Callable[[str, List[Tuple[str, str]]], None]):
        """
        Timer callback: flushes buffer and triggers the response handler.
        """
        with self._lock:
            if channel in self._timers:
                del self._timers[channel]
            messages = list(self._buffers.get(channel, []))
            self._buffers[channel] = []
        
        if messages:
            callback(channel, messages)
