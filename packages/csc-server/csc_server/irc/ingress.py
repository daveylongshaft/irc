from __future__ import annotations

from typing import Callable

from csc_services import parse_irc_message

from csc_server.queue.command import CommandEnvelope
from csc_server.queue.local_queue import LocalCommandQueue
from csc_server.sync.mesh import SyncMesh


class IRCIngress:
    """Normalizes incoming client lines into canonical queue items."""

    def __init__(self, server, queue: LocalCommandQueue, sync_mesh: SyncMesh, logger: Callable[[str], None]):
        self.server = server
        self.queue = queue
        self.sync_mesh = sync_mesh
        self._logger = logger

    def accept_client_line(
        self,
        line: str,
        source_session: str,
        metadata: dict | None = None,
    ) -> CommandEnvelope:
        line = line.rstrip("\r\n")
        kind = line.split(" ", 1)[0].upper() if line else "EMPTY"
        payload = self._build_payload(line=line, source_session=source_session, metadata=metadata)
        envelope = CommandEnvelope(
            kind=kind,
            payload=payload,
            source_session=source_session,
            origin_server=self.server.name.lower(),
            replicate=self._should_replicate(kind, line),
        )
        self._logger(f"[INGRESS] accepted {kind} from {source_session}")
        debug_fn = getattr(self.server, "debug", None)
        if callable(debug_fn):
            debug_fn(
                f"[DEBUG] ingress kind={kind} source={source_session} "
                f"metadata={metadata or {}} line={line!r}"
            )
        self.sync_mesh.sync_command(envelope)
        self.queue.append(envelope)
        return envelope

    def _build_payload(self, line: str, source_session: str, metadata: dict | None) -> dict:
        resolved_metadata = self._resolve_metadata(line=line, source_session=source_session, metadata=metadata)
        payload = {"line": line}
        if resolved_metadata:
            payload.update(resolved_metadata)
        return payload

    def _resolve_metadata(self, line: str, source_session: str, metadata: dict | None) -> dict:
        resolved = {}
        state = getattr(self.server, "state", None)
        context = {}
        if state is not None and hasattr(state, "get_session_context"):
            context = state.get_session_context(source_session)

        source_nick = None
        if metadata and metadata.get("source_nick") is not None:
            source_nick = str(metadata["source_nick"]).strip()
        elif context.get("source_nick"):
            source_nick = str(context["source_nick"]).strip()
        elif source_session:
            source_nick = str(source_session).strip()
        if source_nick:
            resolved["source_nick"] = source_nick

        if metadata and "source_is_oper" in metadata:
            resolved["source_is_oper"] = bool(metadata["source_is_oper"])
        elif context.get("source_is_oper"):
            resolved["source_is_oper"] = True

        channel = self._extract_channel(line)
        if metadata and "source_is_channel_op" in metadata:
            resolved["source_is_channel_op"] = bool(metadata["source_is_channel_op"])
        elif channel and channel.lower() in context.get("channel_ops", set()):
            resolved["source_is_channel_op"] = True

        return resolved

    @staticmethod
    def _extract_channel(line: str) -> str:
        if not line:
            return ""
        message = parse_irc_message(line)
        if message.command != "PRIVMSG" or not message.params:
            return ""
        target = str(message.params[0]).strip()
        if target.startswith("#"):
            return target
        return ""

    @staticmethod
    def _should_replicate(kind: str, line: str) -> bool:
        if not line:
            return False
        non_replicated = {
            "PASS", "PING", "PONG", "OPER", "CAP", "CRYPTOINIT",
            "WHO", "WHOIS", "MOTD", "STATS",
            # Info/query commands are local to the asking server.
            "LUSERS", "VERSION", "TIME", "ADMIN", "INFO", "LINKS",
            "USERHOST", "ISON",
            # Local oper actions for now (until real S2S propagation lands).
            "REHASH", "RESTART", "DIE", "CONNECT",
        }
        return kind not in non_replicated
