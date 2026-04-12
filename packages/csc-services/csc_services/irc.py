"""Shared IRC protocol helpers exposed from the services layer."""

from dataclasses import dataclass, field
from typing import List, Optional


def _load_server_name() -> str:
    try:
        from csc_platform import Platform

        return Platform.get_server_shortname()
    except Exception:
        return "csc-server"


SERVER_NAME = _load_server_name()


@dataclass
class IRCMessage:
    prefix: Optional[str] = None
    command: str = ""
    params: List[str] = field(default_factory=list)
    trailing: Optional[str] = None
    raw: str = ""


class IRCProtocolMixin:
    """Mixin that exposes IRC helpers to Service subclasses."""

    SERVER_NAME = SERVER_NAME

    @staticmethod
    def parse_irc_message(line: str) -> IRCMessage:
        return parse_irc_message(line)

    @staticmethod
    def format_irc_message(prefix: Optional[str], command: str, params: Optional[List[str]] = None, trailing: Optional[str] = None) -> str:
        return format_irc_message(prefix, command, params=params, trailing=trailing)

    @staticmethod
    def numeric_reply(server_name: str, numeric: str, target_nick: str, *text_parts: str) -> str:
        return numeric_reply(server_name, numeric, target_nick, *text_parts)


def parse_irc_message(line: str) -> IRCMessage:
    raw = line.rstrip("\r\n")
    if not raw:
        return IRCMessage(raw=raw)

    rest = raw
    prefix = None
    trailing = None

    if rest.startswith(":"):
        space_idx = rest.find(" ")
        if space_idx == -1:
            return IRCMessage(prefix=rest[1:], raw=raw)
        prefix = rest[1:space_idx]
        rest = rest[space_idx + 1 :].lstrip()

    trailing_idx = rest.find(" :")
    if trailing_idx != -1:
        trailing = rest[trailing_idx + 2 :]
        rest = rest[:trailing_idx]

    parts = rest.split()
    if not parts:
        return IRCMessage(prefix=prefix, trailing=trailing, raw=raw)

    command = parts[0].upper()
    params = parts[1:]
    if trailing is not None:
        params.append(trailing)

    return IRCMessage(prefix=prefix, command=command, params=params, trailing=trailing, raw=raw)


def format_irc_message(
    prefix: Optional[str],
    command: str,
    params: Optional[List[str]] = None,
    trailing: Optional[str] = None,
) -> str:
    parts = []
    if prefix:
        parts.append(f":{prefix}")
    parts.append(command)

    if params is None:
        params = []

    if trailing is not None:
        parts.extend(params)
        parts.append(f":{trailing}")
    else:
        for i, p in enumerate(params):
            if i == len(params) - 1 and (" " in p or p.startswith(":")):
                parts.append(f":{p}")
            else:
                parts.append(p)

    return " ".join(parts)


def numeric_reply(server_name: str, numeric: str, target_nick: str, *text_parts: str) -> str:
    return f":{server_name} {numeric} {target_nick} :{' '.join(text_parts)}"
