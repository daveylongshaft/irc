import threading
from collections import defaultdict


class StandoffManager:
    """Coalescing delay for AI responses.

    Buffers incoming messages per channel. When start_or_reset() is called,
    a timer is started; if another message arrives before it fires, the timer
    resets. When the timer finally expires, the callback receives all buffered
    messages at once.

    Direct @mentions bypass standoff: caller calls cancel() then processes
    the buffer immediately via flush().
    """

    def __init__(self):
        self._timers = {}   # channel -> threading.Timer
        self._buffers = defaultdict(list)  # channel -> [(nick, text)]
        self._lock = threading.Lock()

    def add(self, channel, nick, text):
        with self._lock:
            self._buffers[channel].append((nick, text))

    def start_or_reset(self, channel, delay_ms, callback):
        with self._lock:
            old = self._timers.pop(channel, None)
            if old is not None:
                old.cancel()
            t = threading.Timer(delay_ms / 1000.0, self._fire, args=[channel, callback])
            t.daemon = True
            self._timers[channel] = t
            t.start()

    def cancel(self, channel):
        with self._lock:
            t = self._timers.pop(channel, None)
            if t is not None:
                t.cancel()

    def flush(self, channel):
        with self._lock:
            msgs = list(self._buffers.get(channel, []))
            self._buffers[channel] = []
            return msgs

    def _fire(self, channel, callback):
        with self._lock:
            self._timers.pop(channel, None)
            msgs = list(self._buffers.get(channel, []))
            self._buffers[channel] = []
        if msgs:
            callback(channel, msgs)
