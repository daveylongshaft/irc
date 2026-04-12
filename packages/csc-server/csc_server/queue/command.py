from __future__ import annotations

from dataclasses import dataclass, field
import time
import uuid


@dataclass(slots=True)
class CommandEnvelope:
    """Canonical queue item shared by ingress, sync, and execution.

    arrival_link_id is a LOCAL routing tag set by SyncMesh when a command
    is received from a peer link. It travels with the envelope through
    the queue and dispatcher so any downstream code can identify which
    link the command came in on in O(1) time (via server.get_link_by_id)
    without ever touching IP/port information. It is never serialized
    to the wire -- a peer's idea of our local link ids would be
    meaningless. Client-originated envelopes leave it as None.
    """

    kind: str
    payload: dict
    source_session: str
    origin_server: str
    replicate: bool = True
    command_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    arrival_link_id: str | None = None

    def to_dict(self) -> dict:
        # arrival_link_id is intentionally NOT serialized (local-only tag).
        return {
            "kind": self.kind,
            "payload": self.payload,
            "source_session": self.source_session,
            "origin_server": self.origin_server,
            "replicate": self.replicate,
            "command_id": self.command_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "CommandEnvelope":
        return cls(
            kind=payload["kind"],
            payload=payload["payload"],
            source_session=payload["source_session"],
            origin_server=payload["origin_server"],
            replicate=payload.get("replicate", True),
            command_id=payload["command_id"],
            created_at=payload.get("created_at", time.time()),
            arrival_link_id=None,
        )
