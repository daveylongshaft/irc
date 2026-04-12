from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from csc_platform import Platform

from csc_server.queue.command import CommandEnvelope


class CommandStore:
    """Append-only command log used to rebuild pending queue state on restart."""

    LOG_FILENAME = "command-log.jsonl"

    def __init__(self, logger: Callable[[str], None], base_dir: Path | None = None):
        self._logger = logger
        self._base_dir = base_dir or self._resolve_base_dir()
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._base_dir / self.LOG_FILENAME

    @property
    def log_path(self) -> Path:
        return self._log_path

    def record_enqueued(self, envelope: CommandEnvelope) -> None:
        self._append_event("queued", envelope)

    def record_executed(self, envelope: CommandEnvelope) -> None:
        self._append_event("executed", envelope)

    def load_pending(self) -> list[CommandEnvelope]:
        pending: dict[str, CommandEnvelope] = {}
        order: list[str] = []

        if not self._log_path.exists():
            return []

        with self._log_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                event = json.loads(raw_line)
                event_type = event.get("event")
                payload = event.get("envelope")
                if not payload:
                    continue

                command_id = payload["command_id"]
                if event_type == "queued":
                    if command_id not in pending:
                        order.append(command_id)
                    pending[command_id] = CommandEnvelope.from_dict(payload)
                elif event_type == "executed":
                    pending.pop(command_id, None)

        return [pending[command_id] for command_id in order if command_id in pending]

    def _append_event(self, event_type: str, envelope: CommandEnvelope) -> None:
        record = {
            "event": event_type,
            "command_id": envelope.command_id,
            "envelope": envelope.to_dict(),
        }
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        self._logger(f"[QUEUE] persisted {event_type} id={envelope.command_id}")

    @classmethod
    def _resolve_base_dir(cls) -> Path:
        runtime_dir = Platform.PROJECT_ROOT / "tmp" / "run"
        platform_data = Platform.load_platform_json()
        temp_root = (platform_data or {}).get("runtime", {}).get("temp_root")
        if temp_root:
            runtime_dir = Path(temp_root) / "run"
        return runtime_dir / "csc-server"
