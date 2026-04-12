from __future__ import annotations

from collections import deque
from typing import Callable

from csc_server.queue.command import CommandEnvelope
from csc_server.queue.store import CommandStore


class LocalCommandQueue:
    """In-memory queue scaffold for server command execution."""

    def __init__(self, logger: Callable[[str], None], store: CommandStore | None = None):
        self._logger = logger
        self._store = store
        self._items = deque()

    def append(self, envelope: CommandEnvelope, persist: bool = True) -> None:
        self._items.append(envelope)
        if persist and self._store is not None:
            self._store.record_enqueued(envelope)
        self._logger(
            f"[QUEUE] queued {envelope.kind} id={envelope.command_id} "
            f"source={envelope.source_session} replicate={envelope.replicate}"
        )

    def pop_next(self) -> CommandEnvelope | None:
        if not self._items:
            return None
        return self._items.popleft()

    def __len__(self) -> int:
        return len(self._items)
