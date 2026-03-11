"""
Tests for the bridge module (bridge.py, session.py, irc_utils.py, data_bridge.py,
irc_normalizer.py, control_handler.py).

Written as part of PR #1 review -- the PR claimed tests were included but they
were absent. This file provides basic coverage of the ported bridge module.
"""

import pytest
import threading
import time
from unittest.mock import MagicMock, patch
import sys
import os

# Adjust path for test runner
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'packages', 'csc-service')))


# ---------------------------------------------------------------------------
# irc_utils / irc.py — parsing and formatting
# ---------------------------------------------------------------------------

class TestParseIrcMessage:
    def _parse(self, line):
        from csc_service.bridge.irc_utils import parse_irc_message
        return parse_irc_message(line)

    def test_empty_line(self):
        msg = self._parse("")
        assert msg.command == ""
        assert msg.params == []
        assert msg.prefix is None

    def test_simple_command(self):
        msg = self._parse("PING :server")
        assert msg.command == "PING"
        assert msg.trailing == "server"
        assert msg.params == ["server"]

    def test_command_with_prefix(self):
        msg = self._parse(":nick!user@host PRIVMSG #chan :hello world")
        assert msg.prefix == "nick!user@host"
        assert msg.command == "PRIVMSG"
        assert msg.params == ["#chan", "hello world"]
        assert msg.trailing == "hello world"

    def test_command_uppercase_normalisation(self):
        msg = self._parse("privmsg #chan :test")
        assert msg.command == "PRIVMSG"

    def test_crlf_stripped(self):
        msg = self._parse("NICK alice\r\n")
        assert msg.command == "NICK"
        assert msg.params == ["alice"]

    def test_raw_preserved(self):
        msg = self._parse("JOIN #test")
        assert msg.raw == "JOIN #test"

    def test_no_trailing(self):
        msg = self._parse("MODE alice +i")
        assert msg.command == "MODE"
        assert msg.params == ["alice", "+i"]
        assert msg.trailing is None

    def test_prefix_only(self):
        msg = self._parse(":server")
        assert msg.prefix == "server"
        assert msg.command == ""

    def test_numeric_reply(self):
        msg = self._parse(":csc-server 001 alice :Welcome to IRC")
        assert msg.command == "001"
        assert msg.prefix == "csc-server"
        assert msg.trailing == "Welcome to IRC"


class TestFormatIrcMessage:
    def _format(self, prefix, command, params=None, trailing=None):
        from csc_service.bridge.irc_utils import format_irc_message
        return format_irc_message(prefix, command, params, trailing)

    def test_simple_command(self):
        result = self._format(None, "PING", trailing="server")
        assert result == "PING :server"

    def test_with_prefix(self):
        result = self._format("alice!a@h", "PRIVMSG", ["#chan"], "hi there")
        assert result == ":alice!a@h PRIVMSG #chan :hi there"

    def test_no_params_no_trailing(self):
        result = self._format(None, "VERSION")
        assert result == "VERSION"

    def test_auto_colon_for_space_in_last_param(self):
        result = self._format(None, "PRIVMSG", ["hello world"])
        assert result == "PRIVMSG :hello world"

    def test_numeric_reply_format(self):
        result = self._format("csc-server", "001", ["alice"], "Welcome")
        assert result == ":csc-server 001 alice :Welcome"


class TestNumericReply:
    def test_basic(self):
        from csc_service.bridge.irc_utils import numeric_reply
        result = numeric_reply("csc-server", "001", "alice", "Welcome to IRC")
        assert result == ":csc-server 001 alice :Welcome to IRC"

    def test_empty_text(self):
        from csc_service.bridge.irc_utils import numeric_reply
        result = numeric_reply("srv", "401", "bob")
        assert result == ":srv 401 bob :"

    def test_multiple_parts_joined(self):
        from csc_service.bridge.irc_utils import numeric_reply
        result = numeric_reply("srv", "001", "nick", "a", "b", "c")
        assert result == ":srv 001 nick :a b c"


# ---------------------------------------------------------------------------
# ClientSession
# ---------------------------------------------------------------------------

class TestClientSession:
    def test_defaults(self):
        from csc_service.bridge.session import ClientSession
        s = ClientSession()
        assert s.session_id  # non-empty UUID
        assert s.nick is None
        assert s.state == "CONNECTED"
        assert s.encrypted is False

    def test_touch_updates_last_activity(self):
        from csc_service.bridge.session import ClientSession
        s = ClientSession()
        before = s.last_activity
        time.sleep(0.01)
        s.touch()
        assert s.last_activity > before

    def test_age_increases_over_time(self):
        from csc_service.bridge.session import ClientSession
        s = ClientSession()
        time.sleep(0.01)
        assert s.age() > 0

    def test_session_id_unique(self):
        from csc_service.bridge.session import ClientSession
        ids = {ClientSession().session_id for _ in range(50)}
        assert len(ids) == 50


# ---------------------------------------------------------------------------
# BridgeData (data_bridge.py) — using temp files
# ---------------------------------------------------------------------------

class TestBridgeData:
    @pytest.fixture(autouse=True)
    def patch_data_dir(self, tmp_path, monkeypatch):
        """Redirect BridgeData storage to a tmp directory."""
        from csc_service.shared import data as data_mod
        monkeypatch.setattr(data_mod.Data, '_get_data_dir', lambda self: tmp_path)

    def _make_bd(self):
        from csc_service.bridge.data_bridge import BridgeData
        return BridgeData()

    def test_create_user_success(self):
        bd = self._make_bd()
        result = bd.create_user("alice", "secret")
        assert result is True

    def test_create_user_duplicate(self):
        bd = self._make_bd()
        bd.create_user("alice", "secret")
        result = bd.create_user("alice", "other")
        assert result is False

    def test_validate_user_correct(self):
        bd = self._make_bd()
        bd.create_user("alice", "mypassword")
        assert bd.validate_user("alice", "mypassword") is True

    def test_validate_user_wrong_password(self):
        bd = self._make_bd()
        bd.create_user("alice", "mypassword")
        assert bd.validate_user("alice", "wrongpass") is False

    def test_validate_user_unknown(self):
        bd = self._make_bd()
        assert bd.validate_user("nobody", "anything") is False

    def test_add_history_and_get(self):
        bd = self._make_bd()
        bd.create_user("alice", "pw")
        bd.add_history("alice", "tcp:none:rfc:irc.example.com:6667")
        hist = bd.get_history("alice")
        assert hist[0] == "tcp:none:rfc:irc.example.com:6667"

    def test_add_history_deduplication(self):
        bd = self._make_bd()
        bd.create_user("alice", "pw")
        bd.add_history("alice", "tcp:none:rfc:a.com:6667")
        bd.add_history("alice", "tcp:none:rfc:b.com:6667")
        bd.add_history("alice", "tcp:none:rfc:a.com:6667")  # duplicate
        hist = bd.get_history("alice")
        assert hist[0] == "tcp:none:rfc:a.com:6667"
        assert hist.count("tcp:none:rfc:a.com:6667") == 1

    def test_history_capped_at_25(self):
        bd = self._make_bd()
        bd.create_user("alice", "pw")
        for i in range(30):
            bd.add_history("alice", f"tcp:none:rfc:host{i}.com:6667")
        hist = bd.get_history("alice")
        assert len(hist) <= 25

    def test_set_and_get_favorite(self):
        bd = self._make_bd()
        bd.create_user("alice", "pw")
        bd.set_favorite("alice", "home", "udp:rsa:csc:127.0.0.1:9525")
        result = bd.get_favorite("alice", "home")
        assert result == "udp:rsa:csc:127.0.0.1:9525"

    def test_get_favorite_missing(self):
        bd = self._make_bd()
        bd.create_user("alice", "pw")
        assert bd.get_favorite("alice", "notexist") is None

    def test_get_favorites_empty(self):
        bd = self._make_bd()
        bd.create_user("alice", "pw")
        assert bd.get_favorites("alice") == {}

    def test_history_nonexistent_user(self):
        bd = self._make_bd()
        assert bd.get_history("nobody") == []


# ---------------------------------------------------------------------------
# ControlHandler — unit tests with mocks
# ---------------------------------------------------------------------------

class TestControlHandlerAuth:
    def _make_handler(self, tmp_path, monkeypatch):
        from csc_service.shared import data as data_mod
        monkeypatch.setattr(data_mod.Data, '_get_data_dir', lambda self: tmp_path)
        from csc_service.bridge.data_bridge import BridgeData
        from csc_service.bridge.control_handler import ControlHandler
        from csc_service.bridge.session import ClientSession

        bd = BridgeData()
        bridge = MagicMock()
        bridge.data = bd

        session = ClientSession()
        session.inbound = MagicMock()
        session.inbound.send_to_client = MagicMock()

        handler = ControlHandler(session, bridge)
        return handler, bd

    def test_auth_requires_nick_and_user(self, tmp_path, monkeypatch):
        handler, bd = self._make_handler(tmp_path, monkeypatch)
        bd.create_user("alice", "pw")
        # Only set nick, no username yet
        handler.nick = "alice"
        handler._try_auth()
        assert handler.authenticated is False

    def test_auth_succeeds_with_correct_credentials(self, tmp_path, monkeypatch):
        handler, bd = self._make_handler(tmp_path, monkeypatch)
        bd.create_user("alice", "mypassword")
        handler.nick = "alice"
        handler.username = "alice"
        handler.password = "mypassword"
        handler._try_auth()
        assert handler.authenticated is True

    def test_auth_fails_with_wrong_password(self, tmp_path, monkeypatch):
        handler, bd = self._make_handler(tmp_path, monkeypatch)
        bd.create_user("alice", "mypassword")
        handler.nick = "alice"
        handler.username = "alice"
        handler.password = "wrongpassword"
        handler._try_auth()
        assert handler.authenticated is False

    def test_admin_bootstrap_when_empty_db(self, tmp_path, monkeypatch):
        handler, bd = self._make_handler(tmp_path, monkeypatch)
        # Empty DB + username=admin triggers bootstrap
        handler.nick = "admin"
        handler.username = "admin"
        handler.password = "bootstrappass"
        handler._try_auth()
        assert handler.authenticated is True
        # Verify admin user was created
        assert bd.validate_user("admin", "bootstrappass") is True

    def test_nick_command_sets_nick(self, tmp_path, monkeypatch):
        handler, bd = self._make_handler(tmp_path, monkeypatch)
        handler.handle_line(b"NICK testuser\r\n")
        assert handler.nick == "testuser"

    def test_pass_command_sets_password(self, tmp_path, monkeypatch):
        handler, bd = self._make_handler(tmp_path, monkeypatch)
        handler.handle_line(b"PASS secretpass\r\n")
        assert handler.password == "secretpass"

    def test_ping_sends_pong(self, tmp_path, monkeypatch):
        handler, bd = self._make_handler(tmp_path, monkeypatch)
        handler.handle_line(b"PING :12345\r\n")
        # Should have sent a PONG
        calls = handler.session.inbound.send_to_client.call_args_list
        assert any(b"PONG" in str(c).encode() or b"PONG" in (c[0][1] if c[0] else b"") for c in calls)


# ---------------------------------------------------------------------------
# ConfigManager (config.py)
# ---------------------------------------------------------------------------

class TestConfigManager:
    def test_load_missing_file_returns_defaults(self, tmp_path):
        from csc_service.config import ConfigManager
        cfg = ConfigManager(config_file=str(tmp_path / "nonexistent.json"))
        assert isinstance(cfg.config, dict)

    def test_save_and_reload(self, tmp_path):
        from csc_service.config import ConfigManager
        config_path = str(tmp_path / "test.json")
        cfg = ConfigManager(config_file=config_path)
        cfg.set_value("key1", "value1")
        cfg2 = ConfigManager(config_file=config_path)
        assert cfg2.get_value("key1") == "value1"

    def test_set_nested_value(self, tmp_path):
        from csc_service.config import ConfigManager
        config_path = str(tmp_path / "test.json")
        cfg = ConfigManager(config_file=config_path)
        cfg.set_value("services.myservice.port", 9999)
        assert cfg.get_value("services.myservice.port") == 9999

    def test_atomic_write_uses_temp_file(self, tmp_path):
        """save_config should write via .tmp then rename -- verify final file exists."""
        from csc_service.config import ConfigManager
        config_path = str(tmp_path / "cfg.json")
        cfg = ConfigManager(config_file=config_path)
        cfg.config = {"test": True}
        cfg.save_config()
        import json
        with open(config_path) as f:
            data = json.load(f)
        assert data == {"test": True}

    def test_get_service_config(self, tmp_path):
        from csc_service.config import ConfigManager
        config_path = str(tmp_path / "test.json")
        cfg = ConfigManager(config_file=config_path)
        cfg.config = {"services": {"mybot": {"enabled": True}}}
        result = cfg.get_service_config("mybot")
        assert result == {"enabled": True}

    def test_get_missing_key_returns_none(self, tmp_path):
        from csc_service.config import ConfigManager
        cfg = ConfigManager(config_file=str(tmp_path / "x.json"))
        assert cfg.get_value("does.not.exist") is None


# ---------------------------------------------------------------------------
# IrcNormalizer — basic mode smoke tests
# ---------------------------------------------------------------------------

class TestIrcNormalizer:
    def test_init_rfc_to_csc(self):
        from csc_service.bridge.irc_normalizer import IrcNormalizer
        norm = IrcNormalizer("rfc_to_csc")
        assert norm.mode == "rfc_to_csc"
        assert norm.seen_welcome is False

    def test_init_csc_to_rfc(self):
        from csc_service.bridge.irc_normalizer import IrcNormalizer
        norm = IrcNormalizer("csc_to_rfc")
        assert norm.mode == "csc_to_rfc"

    def test_normalize_empty_block(self):
        from csc_service.bridge.irc_normalizer import IrcNormalizer
        norm = IrcNormalizer("rfc_to_csc")
        session = MagicMock()
        result = norm.normalize_client_to_server("", session)
        assert result is None or result == ""
