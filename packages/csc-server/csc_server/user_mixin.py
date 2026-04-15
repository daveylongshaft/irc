"""UserMixin: attaches user-handling capability to any class (typically Server).

Design:
    - Users are registered into three O(1) indices:
        _users_by_id[user.id]           -> User  (always populated)
        _users_by_session[session_id]   -> User  (always populated)
        _users_by_nick[nick.lower()]    -> User  (populated once nick is set)
    - All lookups hit one of these indices.
    - Nothing outside the mixin reaches into the dicts directly.
    - No __init__. Classes that use UserMixin must call _init_users()
      from their own __init__.

Follows the same pattern as LinkMixin.
"""
from __future__ import annotations

from typing import Iterator

from csc_server.user import User


class UserMixin:
    """Mixin that adds user management to a host class."""

    def _init_users(self) -> None:
        """Initialise user tables. Call once from the host __init__."""
        self._users_by_id: dict[str, User] = {}
        self._users_by_session: dict[str, User] = {}
        self._users_by_nick: dict[str, User] = {}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_user(self, user: User) -> User:
        """Register a new user in all indices."""
        if user.id in self._users_by_id:
            raise ValueError(f"User id collision: {user.id}")
        sid = user.session_id
        if sid in self._users_by_session:
            raise ValueError(f"User session collision: {sid}")
        self._users_by_id[user.id] = user
        self._users_by_session[sid] = user
        if user.nick is not None:
            nick_key = user.nick.lower()
            if nick_key in self._users_by_nick:
                raise ValueError(f"User nick collision: {user.nick!r}")
            self._users_by_nick[nick_key] = user
        return user

    def remove_user(self, user_id: str) -> User | None:
        """Unregister a user by id. Returns removed User or None."""
        user = self._users_by_id.pop(user_id, None)
        if user is None:
            return None
        self._users_by_session.pop(user.session_id, None)
        if user.nick is not None:
            self._users_by_nick.pop(user.nick.lower(), None)
        return user

    def rename_user(self, user: User, old_nick: str, new_nick: str) -> None:
        """Update nick index when a user changes nick."""
        if old_nick is not None:
            self._users_by_nick.pop(old_nick.lower(), None)
        self._users_by_nick[new_nick.lower()] = user

    def reindex_user_session(self, user: User, old_session_id: str) -> None:
        """Update session index when a user's source address changes (NAT rebind)."""
        self._users_by_session.pop(old_session_id, None)
        self._users_by_session[user.session_id] = user

    # ------------------------------------------------------------------
    # Queries (O(1))
    # ------------------------------------------------------------------

    def get_user_by_id(self, user_id: str) -> User | None:
        return self._users_by_id.get(user_id)

    def get_user_by_session(self, session_id: str) -> User | None:
        return self._users_by_session.get(session_id)

    def get_user_by_nick(self, nick: str) -> User | None:
        return self._users_by_nick.get(nick.lower())

    def has_user_id(self, user_id: str) -> bool:
        return user_id in self._users_by_id

    def has_nick(self, nick: str) -> bool:
        return nick.lower() in self._users_by_nick

    def iter_users(self) -> Iterator[User]:
        return iter(self._users_by_id.values())

    def local_users(self) -> list[User]:
        return [u for u in self._users_by_id.values() if not u.is_remote]

    def remote_users(self) -> list[User]:
        return [u for u in self._users_by_id.values() if u.is_remote]

    def user_count(self) -> int:
        return len(self._users_by_id)

    def user_nicks(self) -> list[str]:
        return [u.nick for u in self._users_by_id.values() if u.nick]

    def user_stats(self) -> list[dict]:
        """Snapshot of all users' stats."""
        return [u.stats_dict() for u in self._users_by_id.values()]
