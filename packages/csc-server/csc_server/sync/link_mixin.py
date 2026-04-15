"""LinkMixin: attaches link-handling capability to any class (typically Server).

Design:
    - Links are registered into two O(1) indices at the same time:
        _links_by_id[link.id]          -> Link     (always populated)
        _links_by_origin[origin_server] -> Link    (populated once bound)
    - All routing lookups hit one of these indices. Address-based
      lookup exists only for bootstrap first-packet binding of a
      pre-configured Link that has no origin_server yet.
    - Nothing outside the mixin reaches into `_links_by_id` or
      `_links_by_origin` directly. Always go through the methods.
    - No __init__. Classes that use LinkMixin must call `_init_links()`
      explicitly from their own __init__.
"""
from __future__ import annotations

from typing import Iterable, Iterator

from csc_server.sync.link import Link, aggregate_channel_lists, aggregate_user_lists


class LinkMixin:
    """Mixin that adds link management to a host class."""

    def _init_links(self) -> None:
        """Initialise the link tables. Call once from the host __init__."""
        self._links_by_id: dict[str, Link] = {}
        self._links_by_origin: dict[str, Link] = {}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_link(self, link: Link) -> Link:
        """Register a new link in all indices.

        Raises ValueError on id collision (effectively impossible with
        uuid4) or on origin_server collision with an existing bound link.
        """
        if link.id in self._links_by_id:
            raise ValueError(f"Link id collision: {link.id}")
        if link.origin_server is not None:
            existing = self._links_by_origin.get(link.origin_server)
            if existing is not None:
                raise ValueError(
                    f"Link origin_server={link.origin_server!r} already bound "
                    f"to link id={existing.id}"
                )
        self._links_by_id[link.id] = link
        if link.origin_server is not None:
            self._links_by_origin[link.origin_server] = link
        return link

    def add_link_from_peer_tuple(
        self,
        peer: tuple,
        *,
        name: str | None = None,
    ) -> Link:
        """Build a Link from a peer config tuple and register it.

        Accepts (host, port) or (origin_server, host, port). See
        Link.from_peer_tuple for semantics.
        """
        link = Link.from_peer_tuple(self, peer, name=name)
        return self.add_link(link)

    def bind_link_origin(self, link: Link, origin_server: str) -> None:
        """Bind a previously-unbound Link to an origin_server identity.

        Updates both the Link and the _links_by_origin index atomically.
        This is called from SyncMesh on the first SYNCLINE we receive
        that matches an unbound, pre-configured Link's address.
        """
        if link.id not in self._links_by_id:
            raise ValueError(f"Link id={link.id} not registered, cannot bind")
        existing = self._links_by_origin.get(origin_server)
        if existing is not None and existing.id != link.id:
            raise ValueError(
                f"origin_server={origin_server!r} already bound to link "
                f"id={existing.id}, refusing to rebind to id={link.id}"
            )
        link.bind_origin(origin_server)
        self._links_by_origin[origin_server] = link

    def remove_link(self, link_id: str) -> Link | None:
        """Unregister a link by id. Returns the removed Link or None."""
        link = self._links_by_id.pop(link_id, None)
        if link is None:
            return None
        if link.origin_server is not None:
            self._links_by_origin.pop(link.origin_server, None)
        return link

    def replace_links(self, new_links: Iterable[Link]) -> None:
        """Replace the entire link set atomically (used by config reload)."""
        by_id: dict[str, Link] = {}
        by_origin: dict[str, Link] = {}
        for link in new_links:
            if link.id in by_id:
                raise ValueError(f"Duplicate link id in replacement set: {link.id}")
            by_id[link.id] = link
            if link.origin_server is not None:
                if link.origin_server in by_origin:
                    raise ValueError(
                        f"Duplicate origin_server in replacement set: {link.origin_server!r}"
                    )
                by_origin[link.origin_server] = link
        self._links_by_id = by_id
        self._links_by_origin = by_origin

    # ------------------------------------------------------------------
    # Queries (routing-critical: O(1))
    # ------------------------------------------------------------------

    def get_link_by_id(self, link_id: str) -> Link | None:
        return self._links_by_id.get(link_id)

    def get_link_by_origin(self, origin_server: str) -> Link | None:
        return self._links_by_origin.get(origin_server)

    def has_link_id(self, link_id: str) -> bool:
        return link_id in self._links_by_id

    def has_origin(self, origin_server: str) -> bool:
        return origin_server in self._links_by_origin

    def iter_links(self) -> Iterator[Link]:
        return iter(self._links_by_id.values())

    def link_ids(self) -> list[str]:
        return list(self._links_by_id.keys())

    def link_names(self) -> list[str]:
        return [link.name for link in self._links_by_id.values()]

    def link_count(self) -> int:
        return len(self._links_by_id)

    def link_stats(self) -> list[dict]:
        """Snapshot of all links' stats, for STATS L formatting."""
        return [link.stats_dict() for link in self._links_by_id.values()]

    # ------------------------------------------------------------------
    # Soft / bootstrap helpers (NOT routing primitives)
    # ------------------------------------------------------------------

    def find_unbound_link_for_addr(self, addr: tuple[str, int] | None) -> Link | None:
        """Find a pre-configured, not-yet-bound Link whose configured
        address matches `addr`. Used ONCE per link at bootstrap to bind
        origin_server the first time we receive from a configured peer.
        Never used for routing after the link is bound.
        """
        if addr is None:
            return None
        for link in self._links_by_id.values():
            if link.origin_server is None and link.connection.addr_matches(addr):
                return link
        return None

    # ------------------------------------------------------------------
    # Aggregation across links (full network views)
    # ------------------------------------------------------------------

    def all_known_users(self, local_users: Iterable[str] = ()) -> set[str]:
        return aggregate_user_lists(local_users, self._links_by_id.values())

    def all_known_channels(self, local_channels: Iterable[str] = ()) -> set[str]:
        return aggregate_channel_lists(local_channels, self._links_by_id.values())

    def all_known_opers(self, local_opers: Iterable[str] = ()) -> set[str]:
        full = set(local_opers)
        for link in self._links_by_id.values():
            full.update(link.opers)
        return full

    def links_where_user_known(self, nick: str) -> list[Link]:
        """Return every link that currently believes `nick` lives on its side.

        For netsplit handling: when a link dies, ask each surviving link
        'do you see this user?' and synthesize QUITs for the ones
        nobody sees anymore.
        """
        return [link for link in self._links_by_id.values() if link.has_user(nick)]

    def links_where_channel_known(self, channel: str) -> list[Link]:
        return [link for link in self._links_by_id.values() if link.has_channel(channel)]
