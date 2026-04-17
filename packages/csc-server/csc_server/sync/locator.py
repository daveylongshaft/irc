"""WRU/HIA - Nick/Server locator protocol for mesh discovery."""

from csc_server.queue.command import CommandEnvelope


class Locator:
    """Handles WRU (Where are you?) and HIA (Here I am) for nick/server discovery."""

    def __init__(self, server, logger):
        self.server = server
        self._logger = logger

    def handle_wru(self, envelope: CommandEnvelope) -> None:
        """Receive WRU. If target is behind us, reply with HIA."""
        target_type = envelope.payload.get("target_type")
        target = envelope.payload.get("target")
        request_id = envelope.payload.get("id")
        origin_link_id = envelope.arrival_link_id

        found_link = None

        if target_type == "nick":
            for link in self.server.iter_links():
                if link.id != origin_link_id and link.has_nick_behind(target):
                    found_link = link
                    break
        elif target_type == "server":
            for link in self.server.iter_links():
                if link.id != origin_link_id and target in link.servers_behind:
                    found_link = link
                    break

        if found_link:
            hia = CommandEnvelope(
                kind="HIA",
                payload={
                    "target_type": target_type,
                    "target": target,
                    "id": request_id,
                },
                origin_server=self.server.name,
                source_session="s2s-locator",
                replicate=False,
            )
            arriving_link = self.server.get_link_by_id(origin_link_id)
            if arriving_link:
                wire = (self._encode_syncline(hia) + "\r\n").encode("utf-8")
                arriving_link.connection.sendto(wire)
                self._logger(
                    f"[WRU] Sent HIA for {target_type}:{target} via {arriving_link.name}"
                )

    def broadcast_wru(self, target_type: str, target: str) -> str:
        """Flood WRU to all links: 'Where are you <nick/server>?'"""
        import time
        request_id = f"wru-{target_type}-{target}-{int(time.time())}"

        wru = CommandEnvelope(
            kind="WRU",
            payload={
                "target_type": target_type,
                "target": target,
                "id": request_id,
            },
            origin_server=self.server.name,
            source_session="s2s-locator",
            replicate=False,
        )

        wire = (self._encode_syncline(wru) + "\r\n").encode("utf-8")
        for link in self.server.iter_links():
            link.connection.sendto(wire)

        self._logger(
            f"[WRU] Broadcast query for {target_type}:{target} "
            f"id={request_id} to {self.server.link_count()} link(s)"
        )
        return request_id

    def handle_hia(self, envelope: CommandEnvelope) -> None:
        """Receive HIA: 'Here I am - target is behind me.'"""
        target_type = envelope.payload.get("target_type")
        target = envelope.payload.get("target")
        from_link = self.server.get_link_by_id(envelope.arrival_link_id)

        if from_link:
            if target_type == "nick":
                from_link.add_nick_behind(target)
                self._logger(f"[HIA] Learned {target} is behind {from_link.name}")
            elif target_type == "server":
                if target not in from_link.servers_behind:
                    from_link.servers_behind.append(target)
                self._logger(f"[HIA] Learned {target} is behind {from_link.name}")

    def _encode_syncline(self, envelope: CommandEnvelope) -> str:
        """Encode envelope as SYNCLINE."""
        import json
        payload_json = json.dumps(envelope.to_dict())
        return f"SYNCLINE :{payload_json}"
