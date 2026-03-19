"""MessageQueue: thread-safe FIFO wrapper for the unified S2S event queue."""

import queue
from typing import Optional

from .queue_record import QueueRecord


class MessageQueue:
    """Thread-safe FIFO queue for QueueRecord events.

    Wraps queue.Queue to provide a simple put/get interface for the
    QueueProcessor consumer thread.
    """

    def __init__(self):
        self._q = queue.Queue()

    def enqueue(self, record: QueueRecord) -> None:
        """Add a record to the queue (non-blocking)."""
        self._q.put(record)

    def dequeue(self, timeout: float = 0.5) -> Optional[QueueRecord]:
        """Remove and return the next record, or None on timeout."""
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def qsize(self) -> int:
        """Approximate queue depth."""
        return self._q.qsize()
