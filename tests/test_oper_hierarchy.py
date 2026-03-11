"""Tests for the IRC oper hierarchy implementation.

Covers:
  - storage.py v2 opers schema migration from v1
  - olines.conf parsing (valid, missing, malformed)
  - add_active_oper / remove_active_oper with flags
  - get_oper_flags / get_active_opers_info
  - server.oper_has_flag / server.active_opers_info properties
  - _handle_oper: successful auth, wrong password, stores flags
  - _handle_kill: requires kill flag
  - _handle_trust: requires trust flag, ADD/REMOVE/LIST
  - _handle_setmotd: requires setmotd flag
  - _handle_stats: requires stats flag, letters o/u/m/c
  - _handle_rehash: requires rehash flag, reloads olines
  - _handle_shutdown: requires shutdown flag
  - _handle_localconfig: requires localconfig flag, get/set/list
"""

import os
import sys
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, call

# Ensure csc_service is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "csc-service"))

from csc_service.server.storage import PersistentStorageManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_storage(tmp_dir):
    """Return a PersistentStorageManager pointing at a temp directory."""
    logs = []
    return PersistentStorageManager(
        base_path=tmp_dir,
        log_func=logs.append,
    ), logs


def write_olines_conf(tmp_dir, content):
    """Write a custom olines.conf into tmp_dir."""
    path = os.path.join(tmp_dir, "olines.conf")
    with open(path, "w") as f:
        f.write(content)
    return path


# ---------------------------------------------------------------------------
# Storage v2 schema tests
# ---------------------------------------------------------------------------

class TestStorageV2Schema(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.storage, self.logs = make_storage(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults_are_v2(self):
        data = self.storage.load_opers()
        self.assertEqual(data.get("version"), 2)
        self.assertIn("olines", data)
        self.assertNotIn("credentials", data)

    def test_default_olines_has_admin_and_localop(self):
        olines = self.storage.get_olines()
        self.assertIn("admin", olines)
        self.assertIn("localop", olines)
        self.assertEqual(olines["admin"]["class"], "admin")
        self.assertEqual(olines["localop"]["class"], "local")

    def test_admin_flags_include_kill(self):
        olines = self.storage.get_olines()
        self.assertIn("kill", olines["admin"]["flags"])

    def test_localop_flags_limited(self):
        olines = self.storage.get_olines()
        localop_flags = olines["localop"]["flags"]
        # localop should NOT have shutdown
        self.assertNotIn("shutdown", localop_flags)
        self.assertIn("kill", localop_flags)


class TestStorageV1Migration(unittest.TestCase):
    """Verify that v1 opers.json is transparently migrated to v2."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_v1(self, active_opers, credentials):
        path = os.path.join(self.tmp, "opers.json")
        with open(path, "w") as f:
            json.dump({
                "version": 1,
                "active_opers": active_opers,
                "credentials": credentials,
            }, f)

    def test_v1_migrated_on_load(self):
        self._write_v1(["alice"], {"admin": "secret"})
        storage, _ = make_storage(self.tmp)
        data = storage.load_opers()
        self.assertEqual(data["version"], 2)
        self.assertIn("olines", data)
        self.assertIn("admin", data["olines"])
        self.assertEqual(data["olines"]["admin"]["password"], "secret")

    def test_v1_active_opers_converted_to_dicts(self):
        self._write_v1(["alice"], {"admin": "secret"})
        storage, _ = make_storage(self.tmp)
        data = storage.load_opers()
        active = data["active_opers"]
        # Each item should be a dict with nick key
        for item in active:
            self.assertIsInstance(item, dict)
            self.assertIn("nick", item)

    def test_v1_credentials_removed_after_migration(self):
        self._write_v1([], {"admin": "pw"})
        storage, _ = make_storage(self.tmp)
        data = storage.load_opers()
        self.assertNotIn("credentials", data)


# ---------------------------------------------------------------------------
# add_active_oper / remove_active_oper
# ---------------------------------------------------------------------------

class TestActiveOperCRUD(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.storage, _ = make_storage(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_oper_stores_flags(self):
        self.storage.add_active_oper("alice", oper_name="admin",
                                     flags=["kill", "rehash"], oper_class="admin")
        info = self.storage.get_active_opers_info()
        self.assertIn("alice", info)
        self.assertEqual(info["alice"]["oper_name"], "admin")
        self.assertIn("kill", info["alice"]["flags"])
        self.assertIn("rehash", info["alice"]["flags"])
        self.assertEqual(info["alice"]["class"], "admin")

    def test_add_oper_infers_flags_from_olines(self):
        """If flags/class not given, they should be inferred from the named O-line."""
        self.storage.add_active_oper("bob", oper_name="admin")
        info = self.storage.get_active_opers_info()
        self.assertIn("bob", info)
        olines = self.storage.get_olines()
        expected_flags = set(olines["admin"]["flags"])
        self.assertEqual(set(info["bob"]["flags"]), expected_flags)

    def test_add_oper_is_case_insensitive_on_lookup(self):
        self.storage.add_active_oper("Alice", oper_name="admin",
                                     flags=["kill"], oper_class="admin")
        info = self.storage.get_active_opers_info()
        self.assertIn("alice", info)  # stored lowercase

    def test_remove_oper(self):
        self.storage.add_active_oper("alice", oper_name="admin",
                                     flags=["kill"], oper_class="admin")
        self.storage.remove_active_oper("alice")
        info = self.storage.get_active_opers_info()
        self.assertNotIn("alice", info)

    def test_remove_nonexistent_oper_is_noop(self):
        self.storage.remove_active_oper("nobody")  # should not raise

    def test_duplicate_add_updates_entry(self):
        self.storage.add_active_oper("alice", oper_name="localop",
                                     flags=["stats"], oper_class="local")
        self.storage.add_active_oper("alice", oper_name="admin",
                                     flags=["kill", "rehash"], oper_class="admin")
        info = self.storage.get_active_opers_info()
        # Should only appear once
        active = self.storage.get_active_opers()
        alice_entries = [a for a in active if a.get("nick") == "alice"]
        self.assertEqual(len(alice_entries), 1)
        self.assertEqual(alice_entries[0]["oper_name"], "admin")

    def test_get_oper_flags_returns_empty_for_non_oper(self):
        flags = self.storage.get_oper_flags("nobody")
        self.assertEqual(flags, [])

    def test_get_oper_flags_returns_flags_for_oper(self):
        self.storage.add_active_oper("carol", oper_name="admin",
                                     flags=["kill", "stats"], oper_class="admin")
        flags = self.storage.get_oper_flags("carol")
        self.assertIn("kill", flags)
        self.assertIn("stats", flags)


# ---------------------------------------------------------------------------
# olines.conf parsing
# ---------------------------------------------------------------------------

class TestOlinesConfParsing(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.storage, self.logs = make_storage(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parse_valid_conf(self):
        write_olines_conf(self.tmp, """
[oper:netadmin]
password = supersecret
host = *
class = netadmin
flags = kill,shutdown,rehash,global
""")
        olines = self.storage.parse_olines_conf(
            os.path.join(self.tmp, "olines.conf")
        )
        self.assertIn("netadmin", olines)
        self.assertEqual(olines["netadmin"]["password"], "supersecret")
        self.assertEqual(olines["netadmin"]["class"], "netadmin")
        self.assertIn("shutdown", olines["netadmin"]["flags"])
        self.assertIn("global", olines["netadmin"]["flags"])

    def test_parse_unknown_flags_dropped(self):
        write_olines_conf(self.tmp, """
[oper:test]
password = x
flags = kill,nonexistent_flag,stats
""")
        olines = self.storage.parse_olines_conf(
            os.path.join(self.tmp, "olines.conf")
        )
        flags = olines["test"]["flags"]
        self.assertIn("kill", flags)
        self.assertIn("stats", flags)
        self.assertNotIn("nonexistent_flag", flags)

    def test_parse_missing_conf_returns_empty(self):
        olines = self.storage.parse_olines_conf("/nonexistent/path/olines.conf")
        self.assertEqual(olines, {})

    def test_parse_conf_without_flags_uses_class_defaults(self):
        write_olines_conf(self.tmp, """
[oper:adminonly]
password = pw
class = admin
""")
        olines = self.storage.parse_olines_conf(
            os.path.join(self.tmp, "olines.conf")
        )
        flags = olines["adminonly"]["flags"]
        # admin class defaults include kill
        self.assertIn("kill", flags)

    def test_parse_multiple_oper_blocks(self):
        write_olines_conf(self.tmp, """
[oper:op1]
password = pw1
flags = kill

[oper:op2]
password = pw2
flags = stats
""")
        olines = self.storage.parse_olines_conf(
            os.path.join(self.tmp, "olines.conf")
        )
        self.assertIn("op1", olines)
        self.assertIn("op2", olines)

    def test_reload_olines_updates_stored_olines(self):
        write_olines_conf(self.tmp, """
[oper:newop]
password = fresh
flags = kill,rehash
""")
        new_olines = self.storage.reload_olines(
            os.path.join(self.tmp, "olines.conf")
        )
        self.assertIn("newop", new_olines)
        # Verify persisted
        stored = self.storage.get_olines()
        self.assertIn("newop", stored)


# ---------------------------------------------------------------------------
# Server property tests (using a minimal mock server)
# ---------------------------------------------------------------------------

def _make_mock_server(tmp_dir):
    """Build a minimal mock Server with storage attached."""
    storage, _ = make_storage(tmp_dir)

    class FakeServer:
        def __init__(self):
            self.storage = storage
            self.clients = {}

        @property
        def opers(self):
            return set(self.storage.get_active_opers_info().keys())

        @property
        def active_opers_info(self):
            return self.storage.get_active_opers_info()

        @property
        def oper_credentials(self):
            return {n: i["password"] for n, i in self.storage.get_olines().items()}

        def oper_has_flag(self, nick, flag):
            return flag in self.storage.get_oper_flags(nick)

        def get_olines(self):
            return self.storage.get_olines()

    return FakeServer()


class TestServerOperProperties(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.server = _make_mock_server(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_opers_property_empty_by_default(self):
        self.assertEqual(self.server.opers, set())

    def test_opers_property_reflects_active_opers(self):
        self.server.storage.add_active_oper("alice", oper_name="admin",
                                            flags=["kill"], oper_class="admin")
        self.assertIn("alice", self.server.opers)

    def test_oper_has_flag_true(self):
        self.server.storage.add_active_oper("bob", oper_name="admin",
                                            flags=["kill", "rehash"], oper_class="admin")
        self.assertTrue(self.server.oper_has_flag("bob", "kill"))
        self.assertTrue(self.server.oper_has_flag("bob", "rehash"))

    def test_oper_has_flag_false_for_missing_flag(self):
        self.server.storage.add_active_oper("carol", oper_name="localop",
                                            flags=["kill"], oper_class="local")
        self.assertFalse(self.server.oper_has_flag("carol", "shutdown"))

    def test_oper_has_flag_false_for_non_oper(self):
        self.assertFalse(self.server.oper_has_flag("nobody", "kill"))

    def test_oper_credentials_from_olines(self):
        creds = self.server.oper_credentials
        self.assertIn("admin", creds)
        self.assertEqual(creds["admin"], "changeme")

    def test_active_opers_info_structure(self):
        self.server.storage.add_active_oper("dave", oper_name="admin",
                                            flags=["kill", "global"], oper_class="global")
        info = self.server.active_opers_info
        self.assertIn("dave", info)
        entry = info["dave"]
        self.assertEqual(entry["oper_name"], "admin")
        self.assertEqual(entry["class"], "global")
        self.assertIn("kill", entry["flags"])


# ---------------------------------------------------------------------------
# Message handler tests (using mocks)
# ---------------------------------------------------------------------------

def _make_handler_mocks(tmp_dir):
    """Create a mock server + storage + MessageHandler for testing oper commands."""
    storage, logs = make_storage(tmp_dir)

    # Build a minimal fake server
    server = MagicMock()
    server.storage = storage
    server.log = MagicMock()
    server.send_wallops = MagicMock()
    server.put_data = MagicMock()
    server.sock_send = MagicMock()
    server.channel_manager = MagicMock()
    server.channel_manager.list_channels.return_value = []
    server.clients = {}
    server._running = True

    # Wire up property-like attributes
    def _opers():
        return set(storage.get_active_opers_info().keys())
    type(server).opers = property(lambda s: _opers())

    def _active_opers_info():
        return storage.get_active_opers_info()
    type(server).active_opers_info = property(lambda s: _active_opers_info())

    def _oper_credentials():
        return {n: i["password"] for n, i in storage.get_olines().items()}
    type(server).oper_credentials = property(lambda s: _oper_credentials())

    server.oper_has_flag = lambda nick, flag: flag in storage.get_oper_flags(nick)
    server.get_olines = lambda: storage.get_olines()
    server.startup_time = time.time()

    # Minimal MessageHandler construction: skip the full __init__
    from csc_service.server.server_message_handler import MessageHandler
    handler = object.__new__(MessageHandler)
    handler.server = server
    handler.file_handler = MagicMock()
    handler.client_registry = {}
    handler.registration_state = {}
    handler.reg_lock = __import__("threading").Lock()
    handler._pm_buffer_replayed = set()

    return handler, server, storage


def _irc_msg(command, params):
    """Build a minimal IRC message mock."""
    msg = MagicMock()
    msg.command = command
    msg.params = params
    return msg


class TestHandleOper(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.handler, self.server, self.storage = _make_handler_mocks(self.tmp)
        self.addr = ("127.0.0.1", 12345)
        # Register "alice" as a connected client
        self.server.clients[self.addr] = {"name": "alice", "last_seen": time.time(), "user_modes": set()}
        self.handler.registration_state[self.addr] = {
            "state": "registered", "nick": "alice", "user": "alice",
            "realname": "Alice", "password": ""
        }
        self.server._persist_session_data = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_oper_success_grants_oper_status(self):
        msg = _irc_msg("OPER", ["admin", "changeme"])
        self.handler._handle_oper(msg, self.addr)
        # alice should now be in active_opers
        info = self.storage.get_active_opers_info()
        self.assertIn("alice", info)

    def test_oper_success_stores_flags(self):
        msg = _irc_msg("OPER", ["admin", "changeme"])
        self.handler._handle_oper(msg, self.addr)
        olines = self.storage.get_olines()
        expected_flags = set(olines["admin"]["flags"])
        stored_flags = set(self.storage.get_oper_flags("alice"))
        self.assertEqual(stored_flags, expected_flags)

    def test_oper_wrong_password_rejected(self):
        msg = _irc_msg("OPER", ["admin", "wrongpassword"])
        self.handler._handle_oper(msg, self.addr)
        info = self.storage.get_active_opers_info()
        self.assertNotIn("alice", info)

    def test_oper_wrong_name_rejected(self):
        msg = _irc_msg("OPER", ["nobody", "changeme"])
        self.handler._handle_oper(msg, self.addr)
        info = self.storage.get_active_opers_info()
        self.assertNotIn("alice", info)

    def test_oper_too_few_params(self):
        msg = _irc_msg("OPER", ["admin"])
        self.handler._handle_oper(msg, self.addr)
        info = self.storage.get_active_opers_info()
        self.assertNotIn("alice", info)


class TestHandleKill(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.handler, self.server, self.storage = _make_handler_mocks(self.tmp)
        self.oper_addr = ("127.0.0.1", 11111)
        self.target_addr = ("127.0.0.1", 22222)
        # Register oper "op1"
        self.server.clients[self.oper_addr] = {"name": "op1", "last_seen": time.time(), "user_modes": set()}
        self.handler.registration_state[self.oper_addr] = {
            "state": "registered", "nick": "op1", "user": "op1", "realname": "Op1", "password": ""
        }
        # Register target "vic"
        self.server.clients[self.target_addr] = {"name": "vic", "last_seen": time.time(), "user_modes": set()}
        self.handler.registration_state[self.target_addr] = {
            "state": "registered", "nick": "vic", "user": "vic", "realname": "Victim", "password": ""
        }
        self.handler._server_kill = MagicMock(return_value="vic")
        self.handler._send_numeric = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_kill_denied_without_kill_flag(self):
        # op1 is NOT an oper — kill should be denied
        msg = _irc_msg("KILL", ["vic", "test"])
        self.handler._handle_kill(msg, self.oper_addr)
        self.handler._server_kill.assert_not_called()

    def test_kill_allowed_with_kill_flag(self):
        # Grant op1 the kill flag
        self.storage.add_active_oper("op1", oper_name="admin",
                                     flags=["kill"], oper_class="admin")
        msg = _irc_msg("KILL", ["vic", "test kill"])
        self.handler._handle_kill(msg, self.oper_addr)
        self.handler._server_kill.assert_called_once()

    def test_kill_denied_with_stats_flag_only(self):
        # stats flag does NOT confer kill privilege
        self.storage.add_active_oper("op1", oper_name="localop",
                                     flags=["stats"], oper_class="local")
        msg = _irc_msg("KILL", ["vic", "reason"])
        self.handler._handle_kill(msg, self.oper_addr)
        self.handler._server_kill.assert_not_called()


class TestHandleTrust(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.handler, self.server, self.storage = _make_handler_mocks(self.tmp)
        self.addr = ("127.0.0.1", 9999)
        self.server.clients[self.addr] = {"name": "trustop", "last_seen": time.time(), "user_modes": set()}
        self.handler.registration_state[self.addr] = {
            "state": "registered", "nick": "trustop", "user": "trustop",
            "realname": "TrustOp", "password": ""
        }
        self.handler._send_notice = MagicMock()
        self.handler._send_numeric = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_trust_denied_without_flag(self):
        msg = _irc_msg("TRUST", ["ADD", "nick1"])
        self.handler._handle_trust(msg, self.addr)
        self.handler._send_numeric.assert_called()

    def test_trust_add_with_flag(self):
        self.storage.add_active_oper("trustop", oper_name="admin",
                                     flags=["trust"], oper_class="admin")
        msg = _irc_msg("TRUST", ["ADD", "nick1"])
        self.handler._handle_trust(msg, self.addr)
        settings = self.storage.load_settings()
        self.assertIn("nick1", settings.get("trusted_nicks", []))

    def test_trust_remove_with_flag(self):
        self.storage.add_active_oper("trustop", oper_name="admin",
                                     flags=["trust"], oper_class="admin")
        # Add first
        settings = self.storage.load_settings()
        settings["trusted_nicks"] = ["nick1"]
        self.storage.save_settings(settings)
        # Now remove
        msg = _irc_msg("TRUST", ["REMOVE", "nick1"])
        self.handler._handle_trust(msg, self.addr)
        settings = self.storage.load_settings()
        self.assertNotIn("nick1", settings.get("trusted_nicks", []))

    def test_trust_list_with_flag(self):
        self.storage.add_active_oper("trustop", oper_name="admin",
                                     flags=["trust"], oper_class="admin")
        msg = _irc_msg("TRUST", ["LIST"])
        self.handler._handle_trust(msg, self.addr)
        # Should have sent notice with end-of-list
        calls = [str(c) for c in self.handler._send_notice.call_args_list]
        self.assertTrue(any("End of TRUST" in c for c in calls))


class TestHandleStats(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.handler, self.server, self.storage = _make_handler_mocks(self.tmp)
        self.addr = ("127.0.0.1", 8888)
        self.server.clients[self.addr] = {"name": "statsop", "last_seen": time.time(), "user_modes": set()}
        self.handler.registration_state[self.addr] = {
            "state": "registered", "nick": "statsop", "user": "statsop",
            "realname": "StatsOp", "password": ""
        }
        self.handler._send_notice = MagicMock()
        self.handler._send_numeric = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stats_denied_without_flag(self):
        msg = _irc_msg("STATS", ["o"])
        self.handler._handle_stats(msg, self.addr)
        self.handler._send_numeric.assert_called()

    def test_stats_o_shows_olines(self):
        self.storage.add_active_oper("statsop", oper_name="admin",
                                     flags=["stats"], oper_class="admin")
        msg = _irc_msg("STATS", ["o"])
        self.handler._handle_stats(msg, self.addr)
        calls = [str(c) for c in self.handler._send_notice.call_args_list]
        self.assertTrue(any("O-line" in c for c in calls))

    def test_stats_u_shows_uptime(self):
        self.storage.add_active_oper("statsop", oper_name="admin",
                                     flags=["stats"], oper_class="admin")
        msg = _irc_msg("STATS", ["u"])
        self.handler._handle_stats(msg, self.addr)
        calls = [str(c) for c in self.handler._send_notice.call_args_list]
        self.assertTrue(any("uptime" in c.lower() or "STATS u" in c for c in calls))

    def test_stats_m_shows_active_opers(self):
        self.storage.add_active_oper("statsop", oper_name="admin",
                                     flags=["stats"], oper_class="admin")
        msg = _irc_msg("STATS", ["m"])
        self.handler._handle_stats(msg, self.addr)
        calls = [str(c) for c in self.handler._send_notice.call_args_list]
        self.assertTrue(any("STATS m" in c for c in calls))

    def test_stats_c_shows_client_count(self):
        self.storage.add_active_oper("statsop", oper_name="admin",
                                     flags=["stats"], oper_class="admin")
        msg = _irc_msg("STATS", ["c"])
        self.handler._handle_stats(msg, self.addr)
        calls = [str(c) for c in self.handler._send_notice.call_args_list]
        self.assertTrue(any("STATS c" in c for c in calls))


class TestHandleRehash(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.handler, self.server, self.storage = _make_handler_mocks(self.tmp)
        self.addr = ("127.0.0.1", 7777)
        self.server.clients[self.addr] = {"name": "rehashop", "last_seen": time.time(), "user_modes": set()}
        self.handler.registration_state[self.addr] = {
            "state": "registered", "nick": "rehashop", "user": "rehashop",
            "realname": "RehashOp", "password": ""
        }
        self.handler._send_notice = MagicMock()
        self.handler._send_numeric = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rehash_denied_without_flag(self):
        msg = _irc_msg("REHASH", [])
        self.handler._handle_rehash(msg, self.addr)
        self.handler._send_numeric.assert_called()

    def test_rehash_reloads_olines(self):
        self.storage.add_active_oper("rehashop", oper_name="admin",
                                     flags=["rehash"], oper_class="admin")
        # Write a new olines.conf with an extra oper
        write_olines_conf(self.tmp, """
[oper:newop]
password = newpass
flags = kill
""")
        msg = _irc_msg("REHASH", [])
        self.handler._handle_rehash(msg, self.addr)
        # olines should now contain newop
        olines = self.storage.get_olines()
        self.assertIn("newop", olines)


class TestHandleShutdown(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.handler, self.server, self.storage = _make_handler_mocks(self.tmp)
        self.addr = ("127.0.0.1", 6666)
        self.server.clients[self.addr] = {"name": "shutop", "last_seen": time.time(), "user_modes": set()}
        self.handler.registration_state[self.addr] = {
            "state": "registered", "nick": "shutop", "user": "shutop",
            "realname": "ShutOp", "password": ""
        }
        self.handler._send_numeric = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_shutdown_denied_without_flag(self):
        msg = _irc_msg("SHUTDOWN", ["test"])
        self.handler._handle_shutdown(msg, self.addr)
        self.handler._send_numeric.assert_called()
        self.assertTrue(self.server._running)  # still running

    def test_shutdown_stops_server_with_flag(self):
        self.storage.add_active_oper("shutop", oper_name="admin",
                                     flags=["shutdown"], oper_class="netadmin")
        msg = _irc_msg("SHUTDOWN", ["Test shutdown"])
        self.handler._handle_shutdown(msg, self.addr)
        self.assertFalse(self.server._running)


class TestHandleLocalconfig(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.handler, self.server, self.storage = _make_handler_mocks(self.tmp)
        self.addr = ("127.0.0.1", 5555)
        self.server.clients[self.addr] = {"name": "cfgop", "last_seen": time.time(), "user_modes": set()}
        self.handler.registration_state[self.addr] = {
            "state": "registered", "nick": "cfgop", "user": "cfgop",
            "realname": "CfgOp", "password": ""
        }
        self.handler._send_notice = MagicMock()
        self.handler._send_numeric = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_localconfig_denied_without_flag(self):
        msg = _irc_msg("LOCALCONFIG", ["max_clients", "100"])
        self.handler._handle_localconfig(msg, self.addr)
        self.handler._send_numeric.assert_called()

    def test_localconfig_set_value(self):
        self.storage.add_active_oper("cfgop", oper_name="admin",
                                     flags=["localconfig"], oper_class="admin")
        msg = _irc_msg("LOCALCONFIG", ["max_clients", "200"])
        self.handler._handle_localconfig(msg, self.addr)
        settings = self.storage.load_settings()
        self.assertEqual(settings["local_config"]["max_clients"], "200")

    def test_localconfig_get_value(self):
        self.storage.add_active_oper("cfgop", oper_name="admin",
                                     flags=["localconfig"], oper_class="admin")
        # Pre-set a value
        settings = self.storage.load_settings()
        settings.setdefault("local_config", {})["max_clients"] = "150"
        self.storage.save_settings(settings)
        # Query
        msg = _irc_msg("LOCALCONFIG", ["max_clients"])
        self.handler._handle_localconfig(msg, self.addr)
        calls = [str(c) for c in self.handler._send_notice.call_args_list]
        self.assertTrue(any("150" in c for c in calls))

    def test_localconfig_list(self):
        self.storage.add_active_oper("cfgop", oper_name="admin",
                                     flags=["localconfig"], oper_class="admin")
        settings = self.storage.load_settings()
        settings.setdefault("local_config", {})["key1"] = "val1"
        self.storage.save_settings(settings)
        msg = _irc_msg("LOCALCONFIG", ["LIST"])
        self.handler._handle_localconfig(msg, self.addr)
        calls = [str(c) for c in self.handler._send_notice.call_args_list]
        self.assertTrue(any("key1" in c for c in calls))


class TestHandleSetMotd(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.handler, self.server, self.storage = _make_handler_mocks(self.tmp)
        self.addr = ("127.0.0.1", 4444)
        self.server.clients[self.addr] = {"name": "motdop", "last_seen": time.time(), "user_modes": set()}
        self.handler.registration_state[self.addr] = {
            "state": "registered", "nick": "motdop", "user": "motdop",
            "realname": "MotdOp", "password": ""
        }
        self.handler._send_notice = MagicMock()
        self.handler._send_numeric = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_setmotd_denied_without_flag(self):
        msg = _irc_msg("SETMOTD", ["New MOTD"])
        self.handler._handle_setmotd(msg, self.addr)
        self.handler._send_numeric.assert_called()
        self.server.put_data.assert_not_called()

    def test_setmotd_with_flag(self):
        self.storage.add_active_oper("motdop", oper_name="admin",
                                     flags=["setmotd"], oper_class="admin")
        msg = _irc_msg("SETMOTD", ["Welcome to CSC IRC!"])
        self.handler._handle_setmotd(msg, self.addr)
        self.server.put_data.assert_called_once_with("motd", "Welcome to CSC IRC!")


if __name__ == "__main__":
    unittest.main()
