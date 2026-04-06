import configparser
import re
from pathlib import Path


class PerformManager:
    """Reads client.conf and fires IRC perform scripts at lifecycle events.

    client.conf format (INI):
      [identity]  nick, user, operid, pass, server, port, channels
      [perform]   one command per line per event; $var substituted from [identity]
      [ai]        wakewords, standoff_min/max, backscroll, focus_window, ignore_timeout

    Lifecycle events: post_start, post_connect, pre_disconnect, pre_quit, join, part
    Extra vars (e.g. $channel for join/part) passed via fire(extra_vars=...).
    """

    def __init__(self, config_path):
        self._path = Path(config_path)
        self._vars = {}
        self._scripts = {}
        self._ai = {}
        self._raw = configparser.ConfigParser(
            allow_no_value=True,
            comment_prefixes=(";", "#"),
            inline_comment_prefixes=(";",),
        )

    def load(self):
        if not self._path.exists():
            try:
                from csc_platform import Platform
                Platform.log(f"[PerformManager] WARNING: config not found: {self._path}")
            except Exception:
                pass
            return

        self._raw.read(str(self._path), encoding="utf-8")

        self._vars = dict(self._raw.items("identity")) if self._raw.has_section("identity") else {}

        if self._raw.has_section("perform"):
            for event, raw in self._raw.items("perform"):
                if raw is None:
                    self._scripts[event] = []
                    continue
                lines = []
                for line in raw.splitlines():
                    line = line.strip()
                    if line and not line.startswith(";"):
                        lines.append(line)
                self._scripts[event] = lines

        self._ai = dict(self._raw.items("ai")) if self._raw.has_section("ai") else {}

    def fire(self, event, extra_vars=None, send_fn=None):
        """Substitute variables and call send_fn(line) for each script line."""
        lines = self._scripts.get(event, [])
        if not lines or send_fn is None:
            return
        vars_combined = dict(self._vars)
        if extra_vars:
            vars_combined.update(extra_vars)
        for line in lines:
            rendered = self._substitute(line, vars_combined)
            if rendered.strip():
                send_fn(rendered)

    def get(self, section, key, fallback=None):
        if section == "ai":
            return self._ai.get(key, fallback)
        if section == "identity":
            return self._vars.get(key, fallback)
        if self._raw.has_section(section):
            return self._raw.get(section, key, fallback=fallback)
        return fallback

    @property
    def wakewords(self):
        raw = self._ai.get("wakewords", "")
        nick = self._vars.get("nick", "")
        words = []
        for w in raw.split():
            words.append(w.replace("$nick", nick))
        return words

    @property
    def channels(self):
        raw = self._vars.get("channels", "")
        return [c for c in raw.split() if c]

    @property
    def nick(self):
        return self._vars.get("nick", "ai")

    @property
    def server(self):
        return self._vars.get("server", "127.0.0.1")

    @property
    def port(self):
        try:
            return int(self._vars.get("port", "9525"))
        except ValueError:
            return 9525

    @staticmethod
    def _substitute(line, vars_dict):
        def replace(m):
            key = m.group(1).lower()
            return vars_dict.get(key, m.group(0))
        return re.sub(r'\$([A-Za-z_][A-Za-z0-9_]*)', replace, line)
