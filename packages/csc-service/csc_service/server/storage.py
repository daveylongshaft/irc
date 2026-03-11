"""
PersistentStorageManager - Atomic file-based persistence for the IRC server.

Manages five JSON files with atomic writes (temp + fsync + rename) to ensure
zero data loss on power failure or crash.

Files managed:
  - channels.json: channel state, members, modes, bans
  - users.json: user sessions, credentials, modes
  - opers.json: operator status and credentials (v2: olines + active list)
  - bans.json: per-channel ban masks
  - history.json: disconnection records for WHOWAS

opers.json v2 schema:
  {
    "version": 2,
    "active_opers": [
      {"nick": "alice", "oper_name": "admin", "flags": [...], "class": "admin"}
    ],
    "olines": {
      "admin": {"password": "...", "host": "*", "class": "admin", "flags": [...]}
    }
  }

olines.conf:
  INI-style file defining operator blocks.  Loaded at startup and on REHASH.
  See olines.conf for format documentation.
"""

import configparser
import json
import os
import time
import logging

logger = logging.getLogger(__name__)


class PersistentStorageManager:
    """Atomic file-based storage for IRC server state."""

    FILES = {
        "channels": "channels.json",
        "users": "users.json",
        "opers": "opers.json",
        "bans": "bans.json",
        "history": "history.json",
        "nickserv": "nickserv.json",
        "chanserv": "chanserv.json",
        "botserv": "botserv.json",
        "settings": "settings.json",
    }

    DEFAULTS = {
        "channels": {"version": 1, "channels": {}},
        "users": {"version": 1, "users": {}},
        "opers": {
            "version": 2,
            "active_opers": [],
            "olines": {
                "admin": {
                    "password": "changeme",
                    "host": "*",
                    "class": "admin",
                    "flags": ["kill", "ban", "rehash", "setmotd", "stats",
                              "localconfig", "trust", "global", "connect", "squit"],
                },
                "localop": {
                    "password": "localpass",
                    "host": "127.0.0.1",
                    "class": "local",
                    "flags": ["kill", "stats"],
                },
            },
        },
        "bans": {"version": 1, "channel_bans": {}},
        "history": {"version": 1, "disconnections": []},
        "nickserv": {"version": 1, "nicks": {}},
        "chanserv": {"version": 1, "channels": {}},
        "botserv": {"version": 1, "bots": {}},
        "settings": {
            "version": 1,
            "nickserv": {
                "enforce_timeout": 60,
                "enforce_mode": "disconnect"
            }
        },
    }

    MAX_HISTORY = 100

    def __init__(self, base_path, log_func=None):
        """Initialize storage manager.

        Args:
            base_path: Directory where JSON files are stored.
            log_func: Optional logging function (e.g. server.log).
                      Falls back to logger.info if not provided.
        """
        self.base_path = base_path
        self._log = log_func or logger.info
        self._mtimes = {}  # key -> last seen mtime
        self._ensure_all_files()

    def _file_path(self, key):
        """Get full path for a storage file."""
        return os.path.join(self.base_path, self.FILES[key])

    def _has_changed(self, key):
        """Check if a file has changed on disk since last read."""
        path = self._file_path(key)
        try:
            mtime = os.path.getmtime(path)
            if key not in self._mtimes or mtime > self._mtimes[key]:
                self._mtimes[key] = mtime
                return True
        except OSError:
            pass
        return False

    # ==================================================================
    # Atomic I/O
    # ==================================================================

    def _atomic_write(self, filepath, data):
        """Write data to file atomically using temp+fsync+rename.

        Returns True on success, False on error.
        """
        tmp_path = filepath + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, filepath)
            # Update mtime so we don't immediately reload our own write
            key = next((k for k, v in self.FILES.items() if filepath.endswith(v)), None)
            if key:
                self._mtimes[key] = os.path.getmtime(filepath)
            return True
        except Exception as e:
            self._log(f"[STORAGE ERROR] Atomic write failed for {filepath}: {e}")
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return False

    def _atomic_read(self, filepath):
        """Read and parse a JSON file safely.

        Returns parsed data on success, None on error.
        """
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            self._log(f"[STORAGE ERROR] Corrupt JSON in {filepath}: {e}")
            self._quarantine(filepath)
            return None
        except FileNotFoundError:
            return None
        except Exception as e:
            self._log(f"[STORAGE ERROR] Read failed for {filepath}: {e}")
            return None

    def _quarantine(self, filepath):
        """Rename corrupt file to .corrupt.<timestamp> for investigation."""
        try:
            ts = int(time.time())
            corrupt_name = f"{filepath}.corrupt.{ts}"
            os.rename(filepath, corrupt_name)
            self._log(f"[STORAGE] Quarantined corrupt file: {corrupt_name}")
        except Exception as e:
            self._log(f"[STORAGE ERROR] Could not quarantine {filepath}: {e}")

    def _ensure_all_files(self):
        """Create any missing storage files with defaults."""
        for key in self.FILES:
            filepath = self._file_path(key)
            if not os.path.exists(filepath):
                self._log(f"[STORAGE] Creating {self.FILES[key]} with defaults")
                self._atomic_write(filepath, self.DEFAULTS[key])

    # ==================================================================
    # Channel Operations
    # ==================================================================

    def _load_channels_from_disk(self):
        """Load all channel data from disk. Returns dict or defaults on error."""
        data = self._atomic_read(self._file_path("channels"))
        if data is None:
            return dict(self.DEFAULTS["channels"])
        return data

    def load_channels(self):
        """Load all channel data. Returns dict or defaults on error."""
        return self._load_channels_from_disk()

    def save_channels(self, data):
        """Save complete channel data. Returns True/False."""
        return self._atomic_write(self._file_path("channels"), data)

    def save_channels_from_manager(self, channel_manager):
        """Build and save channel data from a ChannelManager instance.

        Args:
            channel_manager: The server's ChannelManager object.
        Returns:
            True on success, False on error.
        """
        channels = {}
        for ch in channel_manager.list_channels():
            channels[ch.name] = {
                "name": ch.name,
                "topic": ch.topic,
                "modes": list(ch.modes),
                "mode_params": dict(ch.mode_params),
                "ban_list": list(ch.ban_list),
                "invite_list": list(ch.invite_list),
                "created": ch.created,
                "members": {
                    nick: {
                        "addr": list(info.get("addr", ())),
                        "modes": list(info.get("modes", set())),
                    }
                    for nick, info in ch.members.items()
                },
            }
        data = {"version": 1, "channels": channels}
        return self.save_channels(data)

    # ==================================================================
    # User Operations
    # ==================================================================

    def load_users(self):
        """Load all user data. Returns dict or defaults on error."""
        data = self._atomic_read(self._file_path("users"))
        if data is None:
            return dict(self.DEFAULTS["users"])
        return data

    def save_users(self, data):
        """Save complete user data. Returns True/False."""
        return self._atomic_write(self._file_path("users"), data)

    def set_user(self, nick, user_data):
        """Update or create a single user entry on disk."""
        data = self.load_users()
        users = data.setdefault("users", {})
        users[nick] = user_data
        return self.save_users(data)

    def remove_user(self, nick):
        """Remove a user entry from disk."""
        data = self.load_users()
        users = data.get("users", {})
        if nick in users:
            del users[nick]
            return self.save_users(data)
        return True

    def save_users_from_server(self, server):
        """Build and save user data from server state.

        Args:
            server: The Server instance.
        Returns:
            True on success, False on error.
        """
        users = {}
        for addr, info in list(server.clients.items()):
            nick = info.get("name")
            if not nick:
                continue
            reg = server.message_handler.registration_state.get(addr, {})
            channels_data = {}
            for ch in server.channel_manager.find_channels_for_nick(nick):
                member_info = ch.members.get(nick, {})
                channels_data[ch.name] = {
                    "modes": list(member_info.get("modes", set()))
                }
            users[nick] = {
                "nick": nick,
                "user": reg.get("user", nick),
                "realname": reg.get("realname", nick),
                "password": reg.get("password", ""),
                "user_modes": list(info.get("user_modes", set())),
                "away_message": info.get("away_message"),
                "last_addr": list(addr),
                "last_seen": info.get("last_seen", 0),
                "channels": channels_data,
            }
        data = {"version": 1, "users": users}
        return self.save_users(data)

    # ==================================================================
    # Oper Operations
    # ==================================================================

    # ==================================================================
    # olines.conf Parser
    # ==================================================================

    _ALL_FLAGS = frozenset([
        "kill", "ban", "rehash", "shutdown", "setmotd", "stats",
        "localconfig", "trust", "global", "connect", "squit",
    ])

    _CLASS_DEFAULT_FLAGS = {
        "local":    frozenset(["kill", "stats"]),
        "global":   frozenset(["kill", "stats", "global"]),
        "admin":    frozenset(["kill", "ban", "rehash", "setmotd", "stats",
                               "localconfig", "trust", "global", "connect", "squit"]),
        "netadmin": frozenset(["kill", "ban", "rehash", "shutdown", "setmotd", "stats",
                               "localconfig", "trust", "global", "connect", "squit"]),
    }

    def parse_olines_conf(self, conf_path=None):
        """Parse an olines.conf file and return an olines dict.

        Args:
            conf_path: Path to olines.conf.  Defaults to olines.conf in base_path.
        Returns:
            dict of {oper_name: {password, host, class, flags}} on success.
            Returns {} if file does not exist or cannot be parsed.
        """
        if conf_path is None:
            conf_path = os.path.join(self.base_path, "olines.conf")

        # Fall back to the directory of this source file if not in base_path
        if not os.path.exists(conf_path):
            src_dir = os.path.dirname(os.path.abspath(__file__))
            conf_path = os.path.join(src_dir, "olines.conf")

        if not os.path.exists(conf_path):
            self._log("[OLINES] olines.conf not found, using defaults from opers.json")
            return {}

        parser = configparser.RawConfigParser()
        try:
            parser.read(conf_path)
        except Exception as e:
            self._log(f"[OLINES] Failed to parse olines.conf: {e}")
            return {}

        olines = {}
        for section in parser.sections():
            if not section.lower().startswith("oper:"):
                continue
            oper_name = section[5:].strip()  # strip "oper:" prefix
            if not oper_name:
                continue

            password = parser.get(section, "password", fallback="").strip()
            host = parser.get(section, "host", fallback="*").strip()
            oper_class = parser.get(section, "class", fallback="local").strip().lower()

            # Parse flags list
            raw_flags = parser.get(section, "flags", fallback="").strip()
            if raw_flags:
                flags = [f.strip().lower() for f in raw_flags.split(",") if f.strip()]
                # Keep only known flags
                flags = [f for f in flags if f in self._ALL_FLAGS]
            else:
                # Default flags from class
                flags = list(self._CLASS_DEFAULT_FLAGS.get(oper_class, self._CLASS_DEFAULT_FLAGS["local"]))

            olines[oper_name] = {
                "password": password,
                "host": host,
                "class": oper_class,
                "flags": flags,
            }

        self._log(f"[OLINES] Loaded {len(olines)} oper block(s) from {conf_path}")
        return olines

    def reload_olines(self, conf_path=None):
        """Re-parse olines.conf and update the olines block in opers.json.

        Returns:
            dict of newly loaded olines (may be empty on error).
        """
        olines = self.parse_olines_conf(conf_path)
        if not olines:
            return olines

        data = self._load_opers_from_disk()
        self._migrate_opers_v1_to_v2(data)
        data["olines"] = olines
        self.save_opers(data)
        return olines

    # ==================================================================
    # Opers v2: schema migration helper
    # ==================================================================

    def _migrate_opers_v1_to_v2(self, data):
        """Migrate opers data dict from v1 to v2 schema in-place.

        v1 had: {"version":1, "credentials": {name:pass}, "active_opers": [nick,...]}
        v2 has: {"version":2, "olines": {...},             "active_opers": [{nick,...},...]}

        Mutates data in place. No-op if already v2.
        """
        if data.get("version", 1) >= 2:
            return

        # Build olines from v1 credentials
        old_creds = data.pop("credentials", {})
        olines = {}
        for name, password in old_creds.items():
            olines[name] = {
                "password": password,
                "host": "*",
                "class": "local",
                "flags": list(self._CLASS_DEFAULT_FLAGS["local"]),
            }

        # Convert active_opers: list[str] -> list[dict]
        old_active = data.get("active_opers", [])
        new_active = []
        for item in old_active:
            if isinstance(item, str):
                # Best-effort: pick first matching oline, else use nick as oper_name
                oline = olines.get(item, olines.get(list(olines.keys())[0]) if olines else {})
                new_active.append({
                    "nick": item,
                    "oper_name": item,
                    "flags": list(oline.get("flags", [])),
                    "class": oline.get("class", "local"),
                })
            else:
                new_active.append(item)  # already v2 dict

        data["version"] = 2
        data["olines"] = olines
        data["active_opers"] = new_active

    # ==================================================================
    # Oper Operations (v2)
    # ==================================================================

    def _load_opers_from_disk(self):
        """Load oper data from disk. Returns dict or defaults on error."""
        data = self._atomic_read(self._file_path("opers"))
        if data is None:
            return dict(self.DEFAULTS["opers"])
        # Migrate v1 in-memory if needed (won't auto-save; caller decides)
        if data.get("version", 1) < 2:
            self._migrate_opers_v1_to_v2(data)
        return data

    def load_opers(self):
        """Public alias for _load_opers_from_disk."""
        return self._load_opers_from_disk()

    def get_olines(self):
        """Return the olines dict: {oper_name: {password, host, class, flags}}."""
        data = self._load_opers_from_disk()
        return data.get("olines", {})

    def get_active_opers(self):
        """Return list of active oper dicts: [{nick, oper_name, flags, class}]."""
        data = self._load_opers_from_disk()
        return list(data.get("active_opers", []))

    def get_active_opers_info(self):
        """Return dict of {nick_lower: {nick, oper_name, flags, class}} for quick lookup."""
        result = {}
        for item in self.get_active_opers():
            if isinstance(item, dict) and item.get("nick"):
                result[item["nick"].lower()] = item
        return result

    def get_oper_flags(self, nick):
        """Return the flags list for an active oper nick, or [] if not an oper."""
        info = self.get_active_opers_info().get(nick.lower())
        if not info:
            return []
        return list(info.get("flags", []))

    def get_latest_opers_data(self):
        """Retrieve the latest operator credentials and active opers from disk.

        Returns a tuple: (credentials_dict, active_opers_set).
        credentials_dict is {oper_name: password} built from olines for v2.
        active_opers_set is a set of lowercase nick strings.
        """
        data = self._load_opers_from_disk()
        olines = data.get("olines", {})
        # Build credentials-compatible dict from olines for backward compat
        credentials = {name: info["password"] for name, info in olines.items()}
        # Also include v1 credentials if present
        credentials.update(data.get("credentials", {}))
        active_opers = set()
        for item in data.get("active_opers", []):
            if isinstance(item, dict):
                nick = item.get("nick")
                if nick:
                    active_opers.add(nick.lower())
            elif isinstance(item, str):
                active_opers.add(item.lower())
        return credentials, active_opers

    def save_opers(self, data):
        """Save complete oper data. Returns True/False."""
        return self._atomic_write(self._file_path("opers"), data)

    def save_opers_from_server(self, server):
        """Build and save oper data from server state.

        Args:
            server: The Server instance.
        Returns:
            True on success, False on error.
        """
        data = self._load_opers_from_disk()
        self._migrate_opers_v1_to_v2(data)
        # Preserve olines from disk; update active_opers from server
        data["active_opers"] = list(server.active_opers_info.values())
        return self.save_opers(data)

    def add_active_oper(self, nick, oper_name=None, flags=None, oper_class=None):
        """Add or update a nick in the active opers list on disk.

        Args:
            nick: Lowercase nick.
            oper_name: The O-line name used to authenticate.
            flags: List of oper flags.
            oper_class: Oper class string.
        """
        data = self._load_opers_from_disk()
        self._migrate_opers_v1_to_v2(data)
        active = data.get("active_opers", [])

        # Determine flags/class from olines if not provided
        if oper_name and (flags is None or oper_class is None):
            oline = data.get("olines", {}).get(oper_name, {})
            if flags is None:
                flags = list(oline.get("flags", []))
            if oper_class is None:
                oper_class = oline.get("class", "local")

        # Remove existing entry for this nick
        active = [a for a in active if not (isinstance(a, dict) and a.get("nick", "").lower() == nick.lower())]

        active.append({
            "nick": nick.lower(),
            "oper_name": oper_name or nick.lower(),
            "flags": list(flags or []),
            "class": oper_class or "local",
        })
        data["active_opers"] = active
        return self.save_opers(data)

    def remove_active_oper(self, nick):
        """Remove a nick from the active opers list on disk."""
        data = self._load_opers_from_disk()
        self._migrate_opers_v1_to_v2(data)
        active = data.get("active_opers", [])
        active = [
            a for a in active
            if not (isinstance(a, dict) and a.get("nick", "").lower() == nick.lower())
            and not (isinstance(a, str) and a.lower() == nick.lower())
        ]
        data["active_opers"] = active
        return self.save_opers(data)

    # ==================================================================
    # Ban Operations
    # ==================================================================

    def load_bans(self):
        """Load ban data. Returns dict or defaults on error."""
        data = self._atomic_read(self._file_path("bans"))
        if data is None:
            return dict(self.DEFAULTS["bans"])
        return data

    def save_bans(self, data):
        """Save complete ban data. Returns True/False."""
        return self._atomic_write(self._file_path("bans"), data)

    def save_bans_from_manager(self, channel_manager):
        """Build and save ban data from ChannelManager.

        Args:
            channel_manager: The server's ChannelManager object.
        Returns:
            True on success, False on error.
        """
        channel_bans = {}
        for ch in channel_manager.list_channels():
            if ch.ban_list:
                channel_bans[ch.name] = list(ch.ban_list)
        data = {"version": 1, "channel_bans": channel_bans}
        return self.save_bans(data)

    # ==================================================================
    # History Operations
    # ==================================================================

    def load_history(self):
        """Load disconnection history. Returns dict or defaults on error."""
        data = self._atomic_read(self._file_path("history"))
        if data is None:
            return dict(self.DEFAULTS["history"])
        return data

    def save_history(self, data):
        """Save complete history data. Returns True/False."""
        return self._atomic_write(self._file_path("history"), data)

    def add_disconnection(self, nick, user, realname, host, quit_reason=""):
        """Record a user disconnection for WHOWAS.

        Args:
            nick: The user's nick.
            user: The user's username.
            realname: The user's real name.
            host: The user's host/IP.
            quit_reason: Reason for disconnect.
        Returns:
            True on success, False on error.
        """
        data = self.load_history()
        record = {
            "nick": nick,
            "user": user,
            "realname": realname,
            "host": host,
            "quit_time": time.time(),
            "quit_reason": quit_reason,
        }
        disconnections = data.get("disconnections", [])
        disconnections.append(record)
        # Trim to max
        if len(disconnections) > self.MAX_HISTORY:
            disconnections = disconnections[-self.MAX_HISTORY:]
        data["disconnections"] = disconnections
        return self.save_history(data)

    def save_history_from_server(self, server):
        """Save disconnection history from server's disconnected_clients dict.

        Args:
            server: The Server instance.
        Returns:
            True on success, False on error.
        """
        disconnections = []
        for nick, info in server.disconnected_clients.items():
            disconnections.append({
                "nick": nick,
                "user": info.get("user", nick),
                "realname": info.get("realname", nick),
                "host": info.get("host", "unknown"),
                "quit_time": info.get("quit_time", 0),
                "quit_reason": info.get("quit_reason", ""),
            })
        # Keep only last MAX_HISTORY
        if len(disconnections) > self.MAX_HISTORY:
            disconnections = disconnections[-self.MAX_HISTORY:]
        data = {"version": 1, "disconnections": disconnections}
        return self.save_history(data)

    # ==================================================================
    # NickServ Operations
    # ==================================================================

    def load_nickserv(self):
        """Load NickServ nick registration database."""
        data = self._atomic_read(self._file_path("nickserv"))
        if data is None:
            return dict(self.DEFAULTS["nickserv"])
        return data

    def save_nickserv(self, data):
        """Save NickServ database. Returns True/False."""
        return self._atomic_write(self._file_path("nickserv"), data)

    def nickserv_register(self, nick, password, registered_by=""):
        """Register a nick with NickServ. Returns True/False."""
        data = self.load_nickserv()
        nicks = data.setdefault("nicks", {})
        key = nick.lower()
        if key in nicks:
            return False
        nicks[key] = {
            "nick": nick,
            "password": password,
            "registered_by": registered_by,
            "registered_at": time.time(),
        }
        return self.save_nickserv(data)

    def nickserv_drop(self, nick):
        """Unregister a nick. Returns True if dropped, False if not found."""
        data = self.load_nickserv()
        nicks = data.get("nicks", {})
        key = nick.lower()
        if key not in nicks:
            return False
        del nicks[key]
        return self.save_nickserv(data)

    def nickserv_get(self, nick):
        """Get registration info for a nick. Returns dict or None."""
        data = self.load_nickserv()
        return data.get("nicks", {}).get(nick.lower())

    def nickserv_check_password(self, nick, password):
        """Validate a NickServ password. Returns True/False."""
        info = self.nickserv_get(nick)
        if not info:
            return False
        return info.get("password") == password

    # ==================================================================
    # ChanServ Operations
    # ==================================================================

    def load_chanserv(self):
        """Load ChanServ channel registration database."""
        data = self._atomic_read(self._file_path("chanserv"))
        if data is None:
            return dict(self.DEFAULTS["chanserv"])
        return data

    def save_chanserv(self, data):
        """Save ChanServ database. Returns True/False."""
        return self._atomic_write(self._file_path("chanserv"), data)

    def chanserv_register(self, channel, owner, topic=""):
        """Register a channel with ChanServ. Returns True/False."""
        data = self.load_chanserv()
        channels = data.setdefault("channels", {})
        key = channel.lower()
        if key in channels:
            return False
        channels[key] = {
            "channel": channel,
            "owner": owner,
            "topic": topic,
            "modes": ["t", "n"],  # default registered modes
            "oplist": [owner.lower()],
            "voicelist": [],
            "banlist": [],
            "enforce_mode": False,   # +E: require NickServ identify
            "enforce_topic": False,  # +T: only owner/oper can change topic
            "strict_ops": False,     # +S: only oplist can be op
            "strict_voice": False,   # +V: only voicelist can be voice
            "created_at": time.time(),
        }
        return self.save_chanserv(data)

    def chanserv_get(self, channel):
        """Get registration info for a channel. Returns dict or None."""
        data = self.load_chanserv()
        return data.get("channels", {}).get(channel.lower())

    def chanserv_update(self, channel, info):
        """Update registration info for a channel."""
        data = self.load_chanserv()
        channels = data.setdefault("channels", {})
        channels[channel.lower()] = info
        return self.save_chanserv(data)

    def chanserv_drop(self, channel):
        """Unregister a channel. Returns True/False."""
        data = self.load_chanserv()
        channels = data.get("channels", {})
        key = channel.lower()
        if key not in channels:
            return False
        del channels[key]
        return self.save_chanserv(data)

    # ==================================================================
    # BotServ Operations
    # ==================================================================

    def load_botserv(self):
        """Load BotServ bot registration database."""
        data = self._atomic_read(self._file_path("botserv"))
        if data is None:
            return dict(self.DEFAULTS["botserv"])
        return data

    def save_botserv(self, data):
        """Save BotServ database. Returns True/False."""
        return self._atomic_write(self._file_path("botserv"), data)

    def botserv_register(self, channel, botnick, owner, password):
        """Register a bot for a channel. Returns True/False."""
        data = self.load_botserv()
        bots = data.setdefault("bots", {})
        # Key is channel:botnick
        key = f"{channel.lower()}:{botnick.lower()}"
        if key in bots:
            return False
        bots[key] = {
            "channel": channel,
            "botnick": botnick,
            "owner": owner,
            "password": password,
            "registered_at": time.time(),
            "logs": [], # For PROMPT 100
            "logs_enabled": False,
        }
        return self.save_botserv(data)

    def botserv_get_for_channel(self, channel):
        """Get all bots for a channel."""
        data = self.load_botserv()
        bots = data.get("bots", {})
        chan_lower = channel.lower()
        return [b for k, b in bots.items() if k.startswith(f"{chan_lower}:")]

    def botserv_get(self, channel, botnick):
        """Get specific bot info."""
        data = self.load_botserv()
        key = f"{channel.lower()}:{botnick.lower()}"
        return data.get("bots", {}).get(key)

    def botserv_drop(self, channel, botnick):
        """Unregister a bot."""
        data = self.load_botserv()
        key = f"{channel.lower()}:{botnick.lower()}"
        if key not in data.get("bots", {}):
            return False
        del data["bots"][key]
        return self.save_botserv(data)

    # ==================================================================
    # Settings Operations
    # ==================================================================

    def load_settings(self):
        """Load server settings."""
        data = self._atomic_read(self._file_path("settings"))
        if data is None:
            return dict(self.DEFAULTS["settings"])
        return data

    def save_settings(self, data):
        """Save server settings."""
        return self._atomic_write(self._file_path("settings"), data)

    # ==================================================================
    # Bulk Persist (called by server._persist_session_data)
    # ==================================================================

    def persist_all(self, server):
        """Persist all server state to disk atomically.

        This is the main entry point called after every state change.

        Args:
            server: The Server instance.
        Returns:
            True if all writes succeeded, False if any failed.
        """
        ok = True
        if not self.save_channels_from_manager(server.channel_manager):
            ok = False
        if not self.save_users_from_server(server):
            ok = False
        if not self.save_opers_from_server(server):
            ok = False
        if not self.save_bans_from_manager(server.channel_manager):
            ok = False
        # History is saved individually via add_disconnection, not in bulk
        return ok

    # ==================================================================
    # State Restoration (called on server startup)
    # ==================================================================

    def restore_channels(self, channel_manager):
        """Restore channel state from disk into a ChannelManager.

        Args:
            channel_manager: The server's ChannelManager instance.
        Returns:
            Number of channels restored.
        """
        data = self._load_channels_from_disk()
        channels = data.get("channels", {})
        
        # Clear existing channels that are not on disk (except default)
        on_disk_keys = {name.lower() for name in channels.keys()}
        for name in list(channel_manager.channels.keys()):
            if name not in on_disk_keys and name != channel_manager.DEFAULT_CHANNEL.lower():
                self._log(f"[STORAGE] Removing channel not on disk: {name}")
                del channel_manager.channels[name]

        count = 0
        for name, ch_data in channels.items():
            channel = channel_manager.ensure_channel(name)
            channel.topic = ch_data.get("topic", "")
            channel.modes = set(ch_data.get("modes", []))
            channel.mode_params = ch_data.get("mode_params", {})
            channel.ban_list = set(ch_data.get("ban_list", []))
            channel.invite_list = set(ch_data.get("invite_list", []))
            channel.created = ch_data.get("created", time.time())
            
            # Clear existing members and restore from disk
            channel.members.clear()
            for nick, member_data in ch_data.get("members", {}).items():
                addr = tuple(member_data.get("addr", ()))
                modes = set(member_data.get("modes", []))
                if addr:
                    channel.add_member(nick, addr, modes)
            count += 1

        # Apply ChanServ registration state
        chanserv_data = self.load_chanserv()
        chanserv_channels = chanserv_data.get("channels", {})
        for name, info in chanserv_channels.items():
            key = name.lower()
            if key in channel_manager.channels:
                channel = channel_manager.channels[key]
                # Override topic if ChanServ has one
                if info.get("topic"):
                    channel.topic = info["topic"]
                # Merge bans
                for mask in info.get("banlist", []):
                    channel.ban_list.add(mask)
                # Apply oplist/voicelist to restored members
                oplist = [n.lower() for n in info.get("oplist", [])]
                voicelist = [n.lower() for n in info.get("voicelist", [])]
                for m_nick, m_info in channel.members.items():
                    if m_nick.lower() in oplist:
                        m_info["modes"].add("o")
                    elif m_nick.lower() in voicelist:
                        m_info["modes"].add("v")

        return count

    def restore_users(self, server):
        """Restore user sessions from disk into server state.

        Args:
            server: The Server instance.
        Returns:
            Number of users restored.
        """
        data = self.load_users()
        users = data.get("users", {})
        now = time.time()
        
        # Clear existing active clients that are not on disk or expired
        on_disk_addresses = set()
        for nick, user_data in users.items():
            addr = tuple(user_data.get("last_addr", ()))
            if addr: on_disk_addresses.add(addr)
            
        for addr in list(server.clients.keys()):
            info = server.clients.get(addr, {})
            # Only drop if it's a registered client (has name) that's not on disk
            if info.get("name") and info.get("name") != "unknown" and addr not in on_disk_addresses:
                self._log(f"[STORAGE] Dropping active client not on disk: {info.get('name')} @ {addr}")
                server.clients.pop(addr, None)
                server.message_handler.registration_state.pop(addr, None)

        count = 0
        for nick, user_data in users.items():
            last_seen = user_data.get("last_seen", 0)
            # Handle old format where last_seen was a dict of {addr: timestamp}
            if isinstance(last_seen, dict):
                last_seen = max(last_seen.values()) if last_seen else 0
            if now - last_seen > server.timeout:
                self._log(f"[STORAGE] Skipping expired session: {nick} "
                          f"(last seen {now - last_seen:.0f}s ago)")
                # Clean stale nick from channels and persistent user store
                server.channel_manager.remove_nick_from_all(nick)
                self.remove_user(nick)
                continue

            addr = tuple(user_data.get("last_addr", ()))
            if not addr or len(addr) != 2:
                continue

            # Restore to server.clients
            client_data = {
                "name": nick,
                "last_seen": last_seen,
                "user_modes": set(user_data.get("user_modes", [])),
            }
            if user_data.get("away_message"):
                client_data["away_message"] = user_data["away_message"]
            server.clients[addr] = client_data

            # Restore registration state
            server.message_handler._ensure_reg_state(addr)
            reg = server.message_handler.registration_state[addr]
            reg["state"] = "registered"
            reg["nick"] = nick
            reg["user"] = user_data.get("user", nick)
            reg["realname"] = user_data.get("realname", nick)
            reg["password"] = user_data.get("password", "")

            # Restore channel memberships
            for chan_name, chan_info in user_data.get("channels", {}).items():
                channel = server.channel_manager.ensure_channel(chan_name)
                member_modes = set(chan_info.get("modes", []))
                channel.add_member(nick, addr, member_modes)

            count += 1
            self._log(f"[STORAGE] Restored user: {nick} @ {addr}")
        return count

    def restore_opers(self, server):
        """Restore operator state from disk.

        Args:
            server: The Server instance.
        Returns:
            Number of opers restored.
        """
        data = self.load_opers()

        # Load olines from olines.conf (authoritative) then merge with stored olines
        conf_olines = self.parse_olines_conf()
        stored_olines = data.get("olines", {})
        if conf_olines:
            # Conf file takes precedence; update stored olines
            merged_olines = dict(stored_olines)
            merged_olines.update(conf_olines)
            data["olines"] = merged_olines
            self.save_opers(data)

        # Restore active opers (only if they have an active session)
        active = data.get("active_opers", [])
        count = 0
        for item in active:
            if isinstance(item, dict):
                nick = item.get("nick", "")
            else:
                nick = item
            if not nick:
                continue
            # Verify nick is actually connected
            for addr, info in server.clients.items():
                if info.get("name", "").lower() == nick.lower():
                    count += 1
                    break
        return count

    def restore_bans(self, server):
        """Restore per-channel bans from disk.

        Args:
            server: The Server instance.
        Returns:
            Number of channels with bans restored.
        """
        data = self.load_bans()
        channel_bans = data.get("channel_bans", {})
        count = 0
        for chan_name, masks in channel_bans.items():
            channel = server.channel_manager.get_channel(chan_name)
            if channel:
                channel.ban_list = set(masks)
                count += 1
        return count

    def restore_history(self, server):
        """Restore disconnection history from disk.

        Args:
            server: The Server instance.
        Returns:
            Number of records restored.
        """
        data = self.load_history()
        disconnections = data.get("disconnections", [])
        for record in disconnections:
            nick = record.get("nick")
            if nick:
                server.disconnected_clients[nick] = {
                    "user": record.get("user", nick),
                    "realname": record.get("realname", nick),
                    "host": record.get("host", "unknown"),
                    "quit_time": record.get("quit_time", 0),
                    "quit_reason": record.get("quit_reason", ""),
                }
        return len(disconnections)

    def restore_all(self, server):
        """Restore complete server state from disk.

        Call order matters: channels first, then users (so they can join channels).

        Args:
            server: The Server instance.
        Returns:
            Dict with counts of restored items.
        """
        ch_count = self.restore_channels(server.channel_manager)
        user_count = self.restore_users(server)
        oper_count = self.restore_opers(server)
        ban_count = self.restore_bans(server)
        hist_count = self.restore_history(server)

        self._log(f"[STORAGE] Restore complete: {ch_count} channels, "
                  f"{user_count} users, {oper_count} opers, "
                  f"{ban_count} channels with bans, {hist_count} history records")

        return {
            "channels": ch_count,
            "users": user_count,
            "opers": oper_count,
            "bans": ban_count,
            "history": hist_count,
        }

    # ==================================================================
    # Migration from old snapshot system
    # ==================================================================

    def migrate_from_snapshot(self, server):
        """Migrate data from old Server_data.json session_snapshot format.

        Checks if old snapshot data exists and migrates it to new files.
        Only runs once - removes snapshot key after migration.

        Args:
            server: The Server instance (for get_data/put_data).
        Returns:
            True if migration happened, False if not needed.
        """
        snapshot = server.get_data("session_snapshot")
        if not snapshot:
            return False

        self._log("[STORAGE] Migrating from old snapshot format...")

        # Migrate channels
        channels_snapshot = snapshot.get("channels", {})
        if channels_snapshot:
            channels_data = {"version": 1, "channels": {}}
            for name, ch_info in channels_snapshot.items():
                channels_data["channels"][name] = {
                    "name": name,
                    "topic": ch_info.get("topic", ""),
                    "modes": ch_info.get("modes", []),
                    "mode_params": {},
                    "ban_list": ch_info.get("ban_list", []),
                    "invite_list": [],
                    "created": ch_info.get("created", time.time()),
                    "members": {},
                }
            self.save_channels(channels_data)

        # Migrate users
        sessions = snapshot.get("sessions", {})
        if sessions:
            users_data = {"version": 1, "users": {}}
            for nick, sess in sessions.items():
                users_data["users"][nick] = {
                    "nick": nick,
                    "user": sess.get("user", nick),
                    "realname": sess.get("realname", nick),
                    "password": sess.get("password", ""),
                    "user_modes": sess.get("user_modes", []),
                    "away_message": sess.get("away_message"),
                    "last_addr": sess.get("last_addr", []),
                    "last_seen": sess.get("last_seen", 0),
                    "channels": sess.get("channels", {}),
                }
            self.save_users(users_data)

        # Migrate opers
        active_opers = snapshot.get("active_opers", [])
        oper_creds = server.get_data("oper_credentials") or {}
        self.save_opers({
            "version": 1,
            "active_opers": active_opers,
            "credentials": oper_creds,
        })

        # Initialize empty bans and history
        self.save_bans(self.DEFAULTS["bans"])
        self.save_history(self.DEFAULTS["history"])

        self._log(f"[STORAGE] Migration complete: "
                  f"{len(channels_snapshot)} channels, "
                  f"{len(sessions)} users, "
                  f"{len(active_opers)} opers")

        return True
