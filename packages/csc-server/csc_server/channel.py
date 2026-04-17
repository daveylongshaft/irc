from __future__ import annotations

import time
from typing import Dict, List


class Channel:
    """IRC channel with user modes, channel modes, bans, and invites."""

    def __init__(
        self,
        name: str,
        created: float | None = None,
        topic: str = "",
        modes: str = "",
        bans: List[str] | None = None,
        invites: List[str] | None = None,
    ):
        self.name = name
        self.created = created or time.time()
        self.topic = topic
        self.modes = modes
        self.bans = bans or []
        self.invites = invites or []
        self.users: Dict[str, Dict] = {}

    def add_user(self, nick: str, modes: List[str] | None = None) -> None:
        self.users[nick] = {"modes": set(modes or [])}

    def remove_user(self, nick: str) -> bool:
        return self.users.pop(nick, None) is not None

    def has_user(self, nick: str) -> bool:
        return nick in self.users

    def add_user_mode(self, nick: str, mode: str) -> bool:
        if nick in self.users:
            self.users[nick]["modes"].add(mode)
            return True
        return False

    def remove_user_mode(self, nick: str, mode: str) -> bool:
        if nick in self.users:
            self.users[nick]["modes"].discard(mode)
            return True
        return False

    def get_user_modes(self, nick: str) -> List[str]:
        return sorted(list(self.users.get(nick, {}).get("modes", [])))

    def get_names_list(self) -> str:
        result = []
        for nick in sorted(self.users.keys()):
            modes = self.users[nick]["modes"]
            prefix = ""
            if "@" in modes:
                prefix = "@"
            elif "+" in modes:
                prefix = "+"
            result.append(prefix + nick)
        return " ".join(result)

    def get_all_users(self) -> List[str]:
        return list(self.users.keys())

    def user_count(self) -> int:
        return len(self.users)

    def set_topic(self, topic: str) -> None:
        self.topic = topic

    def set_modes(self, modes: str) -> None:
        self.modes = modes

    def add_ban(self, mask: str) -> bool:
        if mask not in self.bans:
            self.bans.append(mask)
            return True
        return False

    def remove_ban(self, mask: str) -> bool:
        if mask in self.bans:
            self.bans.remove(mask)
            return True
        return False

    def add_invite(self, mask: str) -> bool:
        if mask not in self.invites:
            self.invites.append(mask)
            return True
        return False

    def remove_invite(self, mask: str) -> bool:
        if mask in self.invites:
            self.invites.remove(mask)
            return True
        return False

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "created": self.created,
            "topic": self.topic,
            "modes": self.modes,
            "users": {
                nick: {"modes": sorted(list(self.users[nick]["modes"]))}
                for nick in self.users
            },
            "bans": self.bans,
            "invites": self.invites,
        }

    @staticmethod
    def from_dict(data: Dict) -> Channel:
        chan = Channel(
            name=data["name"],
            created=data.get("created"),
            topic=data.get("topic", ""),
            modes=data.get("modes", ""),
            bans=data.get("bans", []),
            invites=data.get("invites", []),
        )
        for nick, user_data in data.get("users", {}).items():
            chan.add_user(nick, modes=user_data.get("modes", []))
        return chan
