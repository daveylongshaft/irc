"""
ServerData — pure mixin for all IRC-specific domain persistence.

This is a mixin class with NO parent.  It relies on the host class (Data)
to provide:
    self._read_json_file(path)
    self._write_json_file(path, data)
    self._get_etc_dir()  -> Path
    self.log(message)
    self.base_path       -> str   (set by Data.__init__)
    self._mtimes         -> dict  (set by Data.__init__)

Inheritance after assembly:
    Root -> Log -> Data(Log, ServerData) -> Version -> Platform -> ...

opers.json is the sole authority for operator credentials.
olines.conf is written as an export only (write_olines_conf).
It is NEVER read back.  No reload_olines, no parse_olines_conf,
no REHASH merge.
"""

import fnmatch
import os
import time

from csc_data.config_loader import load_config


class ServerData:
    """All IRC-specific file-backed persistence.  Pure mixin, no parent."""

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
            "protect_local_opers": True,
            "active_opers": [],
            "olines": {
                "admin": [
                    {
                        "user": "admin",
                        "password": "changeme",
                        "servers": ["*"],
                        "host_masks": ["*!*@*"],
                        "flags": "aol",
                        "comment": "default admin account",
                    }
                ]
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
                "enforce_mode": "disconnect",
            },
        },
    }

    MAX_HISTORY = 100

    # ------------------------------------------------------------------
    # Path / mtime helpers
    # ------------------------------------------------------------------

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

    def _ensure_all_files(self):
        """Create any missing storage files with defaults."""
        for key in self.FILES:
            filepath = self._file_path(key)
            if not os.path.exists(filepath):
                self.log(f"[STORAGE] Creating {self.FILES[key]} with defaults")
                self._atomic_write(filepath, self.DEFAULTS[key])

    def _quarantine(self, filepath):
        """Rename corrupt file to .corrupt.<timestamp> for investigation."""
        try:
            ts = int(time.time())
            corrupt_name = f"{filepath}.corrupt.{ts}"
            os.rename(filepath, corrupt_name)
            self.log(f"[STORAGE] Quarantined corrupt file: {corrupt_name}")
        except Exception as e:
            self.log(f"[STORAGE ERROR] Could not quarantine {filepath}: {e}")

    # ------------------------------------------------------------------
    # Atomic I/O wrappers (delegate to Data._read/write_json_file)
    # ------------------------------------------------------------------

    def _atomic_write(self, filepath, data):
        """Write data to file atomically via Data._write_json_file."""
        ok = self._write_json_file(filepath, data)
        if ok:
            key = next((k for k, v in self.FILES.items()
                        if str(filepath).endswith(v)), None)
            if key:
                try:
                    self._mtimes[key] = os.path.getmtime(filepath)
                except OSError:
                    pass
        return ok

    def _atomic_read(self, filepath, schema_name):
        """Read a JSON file safely."""
        from pathlib import Path as _Path
        p = _Path(filepath)
        if not p.exists():
            return None
        # The host class (Data) has the log method.
        data = load_config(p, schema_name, self)
        if data is None and p.exists() and p.stat().st_size > 10:
            self._quarantine(filepath)
            return None
        return data

    # ==================================================================
    # Oper / O-line persistence
    # opers.json is the SOLE authority.  olines.conf is export-only.
    # ==================================================================

    def _opers_path(self):
        return self._get_etc_dir() / "opers.json"

    def _olines_conf_path(self):
        return self._get_etc_dir() / "olines.conf"

    @staticmethod
    def _migrate_opers_v1_to_v2(data):
        """Upgrade v1 {credentials: {name: pass}} to v2 olines format."""
        creds = data.get("credentials", {})
        olines = {}
        for name, password in creds.items():
            olines[name] = [{
                "user": name, "password": password,
                "servers": ["*"], "host_masks": ["*!*@*"],
                "flags": "aol", "comment": "migrated from v1",
            }]
        old_active = data.get("active_opers", [])
        new_active = []
        for e in old_active:
            if isinstance(e, str):
                new_active.append({"nick": e, "account": e, "flags": "aol"})
            else:
                new_active.append(e)
        return {
            "version": 2,
            "protect_local_opers": True,
            "active_opers": new_active,
            "olines": olines,
        }

    @staticmethod
    def _match_hostmask(mask, client_mask):
        """Return True if client_mask matches the wildcard mask pattern."""
        try:
            m_nick, rest = mask.split("!", 1)
            m_user, m_host = rest.split("@", 1)
            c_nick, c_rest = client_mask.split("!", 1)
            c_user, c_host = c_rest.split("@", 1)
            return (fnmatch.fnmatch(c_nick.lower(), m_nick.lower()) and
                    fnmatch.fnmatch(c_user.lower(), m_user.lower()) and
                    fnmatch.fnmatch(c_host.lower(), m_host.lower()))
        except ValueError:
            return fnmatch.fnmatch(client_mask.lower(), mask.lower())

    def _load_opers(self):
        """Load opers.json, migrating v1->v2 if needed."""
        data = self._atomic_read(self._opers_path(), "opers")
        if not data:
            return dict(self.DEFAULTS["opers"])
        if data.get("version", 1) < 2:
            data = self._migrate_opers_v1_to_v2(data)
            self._write_json_file(self._opers_path(), data)
        return data

    def _save_opers(self, data):
        """Atomically save opers.json."""
        return self._write_json_file(self._opers_path(), data)

    def load_opers(self):
        """Public alias for backward compat."""
        return self._load_opers()

    def save_opers(self, data):
        """Public alias for backward compat."""
        return self._save_opers(data)

    def get_olines(self):
        """Return olines dict: {account: [entry, ...]}."""
        return self._load_opers().get("olines", {})

    def get_active_opers(self):
        """Return list of active oper dicts: [{nick, account, flags}]."""
        return list(self._load_opers().get("active_opers", []))

    def get_active_opers_info(self):
        """Return {nick_lower: entry_dict} for quick lookup."""
        return {
            e["nick"].lower(): e
            for e in self.get_active_opers()
            if isinstance(e, dict) and e.get("nick")
        }

    def get_oper_flags(self, nick):
        """Return flags string for an active oper nick, '' if not active."""
        nick_lower = nick.lower()
        for e in self._load_opers().get("active_opers", []):
            if isinstance(e, dict) and e.get("nick", "").lower() == nick_lower:
                return e.get("flags", "o")
        return ""

    @property
    def protect_local_opers(self):
        """Whether remote opers without O flag can KILL local opers."""
        return self._load_opers().get("protect_local_opers", True)

    def add_active_oper(self, nick, account="", flags="o"):
        """Add or update an active oper entry."""
        data = self._load_opers()
        active = data.setdefault("active_opers", [])
        nick_lower = nick.lower()
        active[:] = [e for e in active
                     if not (isinstance(e, dict) and e.get("nick", "").lower() == nick_lower)]
        active.append({"nick": nick_lower, "account": account or nick_lower, "flags": flags})
        return self._save_opers(data)

    def remove_active_oper(self, nick):
        """Remove an active oper entry by nick."""
        data = self._load_opers()
        nick_lower = nick.lower()
        data["active_opers"] = [
            e for e in data.get("active_opers", [])
            if not (isinstance(e, dict) and e.get("nick", "").lower() == nick_lower)
        ]
        return self._save_opers(data)

    def check_oper_auth(self, account, password, server_name, client_mask):
        """Verify OPER credentials against o-lines.

        Returns flags string on success, None on failure.
        """
        data = self._load_opers()
        entries = (data.get("olines", {}).get(account, []) +
                   data.get("remote_olines", {}).get(account, []))
        for entry in entries:
            if entry.get("password") != password:
                continue
            servers = entry.get("servers", ["*"])
            if not any(s == "*" or fnmatch.fnmatch(server_name.lower(), s.lower())
                       for s in servers):
                continue
            masks = entry.get("host_masks", ["*!*@*"])
            if any(self._match_hostmask(m, client_mask) for m in masks):
                return entry.get("flags", "o")
        return None

    def write_olines_conf(self, olines, path=None, server_name="csc-server"):
        """Write olines dict to olines.conf text format (EXPORT ONLY).

        This file is never read back.  opers.json is the sole authority.
        """
        if path is None:
            path = self._olines_conf_path()
        from pathlib import Path as _Path
        path = _Path(path)
        lines = [
            "# olines.conf -- CSC IRC Server operator configuration (EXPORT ONLY)",
            "# This file is auto-generated from opers.json.  Do NOT edit.",
            "# Format: name:flags:user:pass:servers:hostmasks:# comment",
            f"# Server: {server_name}",
            "",
        ]
        for name, entries in sorted(olines.items()):
            for entry in entries:
                servers = ",".join(entry.get("servers", ["*"]))
                masks = ",".join(entry.get("host_masks", ["*!*@*"]))
                flags = entry.get("flags", "o")
                user = entry.get("user", name)
                password = entry.get("password", "")
                comment = entry.get("comment", "")
                comment_str = f":# {comment}" if comment else ""
                lines.append(
                    f"{name}:{flags}:{user}:{password}:{servers}:{masks}{comment_str}"
                )
        lines.append("")
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return True
        except Exception as e:
            self.log(f"Error writing olines.conf: {e}")
            return False

    def save_opers_from_server(self, server):
        """Sync active_opers from server memory to opers.json."""
        data = self._load_opers()
        if hasattr(server, "_active_opers_full"):
            data["active_opers"] = list(server._active_opers_full)
        else:
            connected = {
                info.get("name", "").lower()
                for info in server.clients.values()
                if info.get("name")
            }
            data["active_opers"] = [
                e for e in data.get("active_opers", [])
                if isinstance(e, dict) and e.get("nick", "").lower() in connected
            ]
        return self._save_opers(data)

    # ==================================================================
    # Channel Operations
    # ==================================================================

    def _load_channels_from_disk(self):
        data = self._atomic_read(self._file_path("channels"), "channels")
        if data is None:
            return dict(self.DEFAULTS["channels"])
        return data

    def load_channels(self):
        return self._load_channels_from_disk()

    def save_channels(self, data):
        return self._atomic_write(self._file_path("channels"), data)

    def save_channels_from_manager(self, channel_manager):
        """Build and save channel data from a ChannelManager instance."""
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
                        "addr": list(info.get("addr") or ()),
                        "modes": list(info.get("modes", set())),
                    }
                    for nick, info in ch.members.items()
                    if info.get("addr")  # skip remote S2S users (addr=None)
                },
            }
        data = {"version": 1, "channels": channels}
        return self.save_channels(data)

    # ==================================================================
    # User Operations
    # ==================================================================

    def load_users(self):
        data = self._atomic_read(self._file_path("users"), "users")
        if data is None:
            return dict(self.DEFAULTS["users"])
        return data

    def save_users(self, data):
        return self._atomic_write(self._file_path("users"), data)

    def set_user(self, nick, user_data):
        data = self.load_users()
        users = data.setdefault("users", {})
        users[nick] = user_data
        return self.save_users(data)

    def remove_user(self, nick):
        data = self.load_users()
        users = data.get("users", {})
        if nick in users:
            del users[nick]
            return self.save_users(data)
        return True

    def save_users_from_server(self, server):
        """Build and save user data from server state."""
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
    # Ban Operations
    # ==================================================================

    def load_bans(self):
        data = self._atomic_read(self._file_path("bans"), "bans")
        if data is None:
            return dict(self.DEFAULTS["bans"])
        return data

    def save_bans(self, data):
        return self._atomic_write(self._file_path("bans"), data)

    def save_bans_from_manager(self, channel_manager):
        """Build and save ban data from ChannelManager."""
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
        data = self._atomic_read(self._file_path("history"), "history")
        if data is None:
            return dict(self.DEFAULTS["history"])
        return data

    def save_history(self, data):
        return self._atomic_write(self._file_path("history"), data)

    def add_disconnection(self, nick, user, realname, host, quit_reason=""):
        """Record a user disconnection for WHOWAS."""
        data = self.load_history()
        record = {
            "nick": nick, "user": user, "realname": realname,
            "host": host, "quit_time": time.time(), "quit_reason": quit_reason,
        }
        disconnections = data.get("disconnections", [])
        disconnections.append(record)
        if len(disconnections) > self.MAX_HISTORY:
            disconnections = disconnections[-self.MAX_HISTORY:]
        data["disconnections"] = disconnections
        return self.save_history(data)

    def save_history_from_server(self, server):
        """Save disconnection history from server's disconnected_clients dict."""
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
        if len(disconnections) > self.MAX_HISTORY:
            disconnections = disconnections[-self.MAX_HISTORY:]
        data = {"version": 1, "disconnections": disconnections}
        return self.save_history(data)

    # ==================================================================
    # NickServ Operations
    # ==================================================================

    def load_nickserv(self):
        data = self._atomic_read(self._file_path("nickserv"), "nickserv")
        if data is None:
            return dict(self.DEFAULTS["nickserv"])
        return data

    def save_nickserv(self, data):
        return self._atomic_write(self._file_path("nickserv"), data)

    def nickserv_register(self, nick, password, registered_by=""):
        data = self.load_nickserv()
        nicks = data.setdefault("nicks", {})
        key = nick.lower()
        if key in nicks:
            return False
        nicks[key] = {
            "nick": nick, "password": password,
            "registered_by": registered_by, "registered_at": time.time(),
        }
        return self.save_nickserv(data)

    def nickserv_drop(self, nick):
        data = self.load_nickserv()
        nicks = data.get("nicks", {})
        key = nick.lower()
        if key not in nicks:
            return False
        del nicks[key]
        return self.save_nickserv(data)

    def nickserv_get(self, nick):
        data = self.load_nickserv()
        return data.get("nicks", {}).get(nick.lower())

    def nickserv_check_password(self, nick, password):
        info = self.nickserv_get(nick)
        if not info:
            return False
        return info.get("password") == password

    # ==================================================================
    # ChanServ Operations
    # ==================================================================

    def load_chanserv(self):
        data = self._atomic_read(self._file_path("chanserv"), "chanserv")
        if data is None:
            return dict(self.DEFAULTS["chanserv"])
        return data

    def save_chanserv(self, data):
        return self._atomic_write(self._file_path("chanserv"), data)

    def chanserv_register(self, channel, owner, topic=""):
        data = self.load_chanserv()
        channels = data.setdefault("channels", {})
        key = channel.lower()
        if key in channels:
            return False
        channels[key] = {
            "channel": channel, "owner": owner, "topic": topic,
            "modes": ["t", "n"],
            "oplist": [owner.lower()], "voicelist": [], "banlist": [],
            "enforce_mode": False, "enforce_topic": False,
            "strict_ops": False, "strict_voice": False,
            "created_at": time.time(),
        }
        return self.save_chanserv(data)

    def chanserv_get(self, channel):
        data = self.load_chanserv()
        return data.get("channels", {}).get(channel.lower())

    def chanserv_update(self, channel, info):
        data = self.load_chanserv()
        channels = data.setdefault("channels", {})
        channels[channel.lower()] = info
        return self.save_chanserv(data)

    def chanserv_drop(self, channel):
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
        data = self._atomic_read(self._file_path("botserv"), "botserv")
        if data is None:
            return dict(self.DEFAULTS["botserv"])
        return data

    def save_botserv(self, data):
        return self._atomic_write(self._file_path("botserv"), data)

    def botserv_register(self, channel, botnick, owner, password):
        data = self.load_botserv()
        bots = data.setdefault("bots", {})
        key = f"{channel.lower()}:{botnick.lower()}"
        if key in bots:
            return False
        bots[key] = {
            "channel": channel, "botnick": botnick,
            "owner": owner, "password": password,
            "registered_at": time.time(),
            "logs": [], "logs_enabled": False,
        }
        return self.save_botserv(data)

    def botserv_get_for_channel(self, channel):
        data = self.load_botserv()
        bots = data.get("bots", {})
        chan_lower = channel.lower()
        return [b for k, b in bots.items() if k.startswith(f"{chan_lower}:")]

    def botserv_get(self, channel, botnick):
        data = self.load_botserv()
        key = f"{channel.lower()}:{botnick.lower()}"
        return data.get("bots", {}).get(key)

    def botserv_drop(self, channel, botnick):
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
        data = self._atomic_read(self._file_path("settings"), "settings")
        if data is None:
            return dict(self.DEFAULTS["settings"])
        return data

    def save_settings(self, data):
        return self._atomic_write(self._file_path("settings"), data)

    # ==================================================================
    # Bulk Persist / Restore
    # ==================================================================

    def persist_all(self, server):
        """Persist all server state to disk atomically."""
        ok = True
        if not self.save_channels_from_manager(server.channel_manager):
            ok = False
        if not self.save_users_from_server(server):
            ok = False
        if not self.save_opers_from_server(server):
            ok = False
        if not self.save_bans_from_manager(server.channel_manager):
            ok = False
        return ok

    def restore_channels(self, channel_manager):
        """Restore channel state from disk into a ChannelManager."""
        data = self._load_channels_from_disk()
        channels = data.get("channels", {})

        on_disk_keys = {name.lower() for name in channels.keys()}
        for name in list(channel_manager.channels.keys()):
            if name not in on_disk_keys and name != channel_manager.DEFAULT_CHANNEL.lower():
                self.log(f"[STORAGE] Removing channel not on disk: {name}")
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
            channel.members.clear()
            for nick, member_data in ch_data.get("members", {}).items():
                addr = tuple(member_data.get("addr", ()))
                modes = set(member_data.get("modes", []))
                if addr:
                    channel.add_member(nick, addr, modes)
            count += 1

        chanserv_data = self.load_chanserv()
        chanserv_channels = chanserv_data.get("channels", {})
        for name, info in chanserv_channels.items():
            key = name.lower()
            if key in channel_manager.channels:
                channel = channel_manager.channels[key]
                if info.get("topic"):
                    channel.topic = info["topic"]
                for mask in info.get("banlist", []):
                    channel.ban_list.add(mask)
                oplist = [n.lower() for n in info.get("oplist", [])]
                voicelist = [n.lower() for n in info.get("voicelist", [])]
                for m_nick, m_info in channel.members.items():
                    if m_nick.lower() in oplist:
                        m_info["modes"].add("o")
                    elif m_nick.lower() in voicelist:
                        m_info["modes"].add("v")
        return count

    def restore_users(self, server):
        """Restore user sessions from disk into server state."""
        data = self.load_users()
        users = data.get("users", {})
        now = time.time()

        live_nicks = {
            info.get("name", "").lower(): (addr, info.get("last_seen", 0))
            for addr, info in server.clients.items()
            if info.get("name")
        }

        count = 0
        for nick, user_data in users.items():
            last_seen = user_data.get("last_seen", 0)
            if isinstance(last_seen, dict):
                last_seen = max(last_seen.values()) if last_seen else 0
            if now - last_seen > server.timeout:
                self.log(f"[STORAGE] Skipping expired session: {nick} "
                         f"(last seen {now - last_seen:.0f}s ago)")
                server.channel_manager.remove_nick_from_all(nick)
                self.remove_user(nick)
                continue

            addr = tuple(user_data.get("last_addr", ()))
            if not addr or len(addr) != 2:
                continue

            existing = live_nicks.get(nick.lower())
            if existing:
                existing_addr, existing_last_seen = existing
                if now - existing_last_seen <= server.timeout:
                    count += 1
                    continue

            client_data = {
                "name": nick,
                "last_seen": last_seen,
                "user_modes": set(user_data.get("user_modes", [])),
            }
            if user_data.get("away_message"):
                client_data["away_message"] = user_data["away_message"]
            server.clients[addr] = client_data

            server.message_handler._ensure_reg_state(addr)
            reg = server.message_handler.registration_state[addr]
            reg["state"] = "registered"
            reg["nick"] = nick
            reg["user"] = user_data.get("user", nick)
            reg["realname"] = user_data.get("realname", nick)
            reg["password"] = user_data.get("password", "")

            for chan_name, chan_info in user_data.get("channels", {}).items():
                channel = server.channel_manager.ensure_channel(chan_name)
                member_modes = set(chan_info.get("modes", []))
                channel.add_member(nick, addr, member_modes)

            count += 1
            self.log(f"[STORAGE] Restored user: {nick} @ {addr}")
        return count

    def restore_opers(self, server):
        """Restore operator state from disk (v2 format).

        Only restores active opers that still have a live connection.
        opers.json is the sole authority -- no olines.conf merge.
        """
        data = self._load_opers()

        active = data.get("active_opers", [])
        connected_nicks = {info.get("name", "").lower()
                           for info in server.clients.values() if info.get("name")}
        count = 0
        server._active_opers_full = []
        for entry in active:
            if isinstance(entry, dict):
                nick = entry.get("nick", "").lower()
                flags = entry.get("flags", "o")
            else:
                nick = str(entry).lower()
                flags = "o"
            if not nick:
                continue
            if nick in connected_nicks:
                server._active_opers_full.append(
                    {"nick": nick,
                     "account": entry.get("account", nick) if isinstance(entry, dict) else nick,
                     "flags": flags}
                )
                for addr, info in server.clients.items():
                    if info.get("name", "").lower() == nick:
                        modes = info.setdefault("user_modes", set())
                        for flag in flags:
                            if flag in "oOaA":
                                modes.add(flag)
                        break
                count += 1
        return count

    def restore_bans(self, server):
        """Restore per-channel bans from disk."""
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
        """Restore disconnection history from disk."""
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
        """Restore complete server state from disk."""
        ch_count = self.restore_channels(server.channel_manager)
        user_count = self.restore_users(server)
        oper_count = self.restore_opers(server)
        ban_count = self.restore_bans(server)
        hist_count = self.restore_history(server)

        self.log(f"[STORAGE] Restore complete: {ch_count} channels, "
                 f"{user_count} users, {oper_count} opers, "
                 f"{ban_count} channels with bans, {hist_count} history records")

        return {
            "channels": ch_count,
            "users": user_count,
            "opers": oper_count,
            "bans": ban_count,
            "history": hist_count,
        }
