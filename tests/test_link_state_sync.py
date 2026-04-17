"""
Integration tests for link state sync: nick collision, SQUIT cleanup,
BURST exchange, WHO/WHOIS remote, nick change propagation, channel cleanup,
KILL command, oper sync, channel mode sync, INVITE relay.

Run with:  pytest tests/test_link_state_sync.py -v
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = REPO_ROOT / "packages"

for package_dir in PACKAGES_DIR.iterdir():
    if package_dir.is_dir():
        sys.path.insert(0, str(package_dir))


def _reload_server_module():
    server_module = importlib.import_module("csc_server.server")
    return importlib.reload(server_module)


def _make_server(tmp_path, monkeypatch, port=0):
    from csc_platform import Platform
    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()
    return server_module.Server(host="127.0.0.1", port=port)


def _register_user(server, nick, session_id=None):
    """Register a user with NICK + USER and run both commands."""
    sid = session_id or f"session-{nick}"
    server.enqueue_client_line(f"NICK {nick}", source_session=sid)
    server.enqueue_client_line(f"USER {nick} 0 * :{nick}", source_session=sid)
    server.run_once()
    server.run_once()
    return sid


def _run_all(server, max_steps=50):
    """Drain the command queue."""
    for _ in range(max_steps):
        if not server.run_once():
            break


# ---------------------------------------------------------------------------
# Link and Channel helpers
# ---------------------------------------------------------------------------

from csc_server.sync.link import Link
from csc_server.channel import Channel


def _make_dummy_link(server, name="peer1", origin="peer1.example"):
    """Create a Link with a mock connection (no real network)."""
    link = Link(server, "127.0.0.1", 19999, origin_server=origin, name=name, resolve=False)
    server.add_link(link)
    return link


# ===========================================================================
# Test: Nick collision detection in _nick_in_use
# ===========================================================================

class TestNickCollision:
    def test_nick_in_use_detects_remote_user(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            link = _make_dummy_link(server)
            link.add_user("alice")

            assert server.dispatcher._nick_in_use("alice", "some-session") is True
            assert server.dispatcher._nick_in_use("Alice", "some-session") is True
            assert server.dispatcher._nick_in_use("bob", "some-session") is False
        finally:
            server.sock.close()

    def test_nick_in_use_detects_nicks_behind(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            link = _make_dummy_link(server)
            link.add_nick_behind("charlie")

            assert server.dispatcher._nick_in_use("charlie", "some-session") is True
            assert server.dispatcher._nick_in_use("Charlie", "some-session") is True
        finally:
            server.sock.close()

    def test_nick_collision_rejected_on_register(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            link = _make_dummy_link(server)
            link.add_user("alice")

            server.enqueue_client_line("NICK alice", source_session="session-x")
            server.run_once()

            # Should get ERR_NICKNAMEINUSE (433)
            events = server.state.outbound_events
            assert any("433" in e["line"] for e in events), \
                f"Expected 433 NICKNAMEINUSE, got: {[e['line'] for e in events]}"
        finally:
            server.sock.close()


# ===========================================================================
# Test: BURST nick collision detection
# ===========================================================================

class TestBurstCollision:
    def test_burst_drops_colliding_nicks(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            _register_user(server, "alice")
            link = _make_dummy_link(server)

            burst_data = {
                "servers_behind": [],
                "nicks_behind": ["alice", "bob"],
                "channels": {},
            }
            server.sync_mesh.receive_burst(link, burst_data)

            # alice should be dropped (collision), bob should remain
            assert "alice" not in link.nicks_behind
            assert "bob" in link.nicks_behind
        finally:
            server.sock.close()


# ===========================================================================
# Test: Channel mode sync
# ===========================================================================

class TestChannelModeSync:
    def test_sync_link_channel_state_includes_modes(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            sid = _register_user(server, "alice")
            link = _make_dummy_link(server)

            server.enqueue_client_line("JOIN #test", source_session=sid)
            _run_all(server)

            # Set channel modes
            server.state.set_channel_mode("#test", "i")
            server.state.set_channel_mode("#test", "m")

            server.dispatcher._sync_link_channel_state("#test")

            link_chan = link.channels.get("#test")
            assert link_chan is not None
            assert "i" in link_chan.modes
            assert "m" in link_chan.modes
        finally:
            server.sock.close()


# ===========================================================================
# Test: Nick change propagation to link channels
# ===========================================================================

class TestNickChangePropagation:
    def test_nick_change_updates_link_channels(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            link = _make_dummy_link(server)
            # Pre-populate link with a channel that has alice
            chan = Channel(name="#test")
            chan.add_user("alice", modes=["@"])
            link.channels["#test"] = chan
            link.add_user("alice")
            link.add_nick_behind("alice")

            # Rename via Link.rename_nick
            link.rename_nick("alice", "alice2")

            assert not chan.has_user("alice")
            assert chan.has_user("alice2")
            assert "@" in chan.get_user_modes("alice2")
            assert "alice2" in link.nicks_behind
            assert "alice" not in link.nicks_behind
            assert "alice2" in link.users
            assert "alice" not in link.users
        finally:
            server.sock.close()


# ===========================================================================
# Test: WHO/WHOIS for remote users
# ===========================================================================

class TestRemoteWhoWhois:
    def test_whois_finds_remote_user(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            sid = _register_user(server, "bob")
            link = _make_dummy_link(server, origin="remote.server")
            link.add_user("alice")
            link.add_nick_behind("alice")

            server.enqueue_client_line("WHOIS alice", source_session=sid)
            _run_all(server)

            lines = [e["line"] for e in server.state.outbound_events if e["session_id"] == sid]
            # Should get RPL_WHOISUSER (311) for alice
            whois_lines = [l for l in lines if " 311 " in l]
            assert len(whois_lines) >= 1, f"No WHOIS reply found in: {lines}"
            assert "alice" in whois_lines[0]
            assert "remote.server" in whois_lines[0]
        finally:
            server.sock.close()

    def test_who_channel_includes_remote_members(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            sid = _register_user(server, "bob")
            server.enqueue_client_line("JOIN #test", source_session=sid)
            _run_all(server)

            link = _make_dummy_link(server, origin="remote.server")
            chan = Channel(name="#test")
            chan.add_user("alice", modes=["@"])
            link.channels["#test"] = chan

            before = len(server.state.outbound_events)
            server.enqueue_client_line("WHO #test", source_session=sid)
            _run_all(server)

            lines = [e["line"] for e in server.state.outbound_events[before:] if e["session_id"] == sid]
            who_lines = [l for l in lines if " 352 " in l]
            nicks_in_who = [l.split()[7] for l in who_lines]  # nick is 8th field
            assert "bob" in nicks_in_who
            assert "alice" in nicks_in_who
        finally:
            server.sock.close()


# ===========================================================================
# Test: SQUIT handler and link cleanup
# ===========================================================================

class TestSquitCleanup:
    def test_squit_clears_link_state(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            sid = _register_user(server, "admin")
            # Grant oper
            session = server.state.ensure_session(sid)
            session["oper_flags"] = "oO"
            session["oper_account"] = "admin"
            server.add_active_oper("admin", "admin", "oO")

            link = _make_dummy_link(server, origin="peer1.example")
            link.add_user("alice")
            link.add_nick_behind("alice")
            link.add_nick_behind("charlie")
            chan = Channel(name="#test")
            chan.add_user("alice")
            link.channels["#test"] = chan

            server.enqueue_client_line("SQUIT peer1.example :Testing", source_session=sid)
            _run_all(server)

            assert len(link.users) == 0
            assert len(link.nicks_behind) == 0
            assert len(link.channels) == 0
        finally:
            server.sock.close()


# ===========================================================================
# Test: Channel cleanup when empty
# ===========================================================================

class TestChannelCleanup:
    def test_link_channel_removed_when_empty(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            link = _make_dummy_link(server)
            chan = Channel(name="#test")
            link.channels["#test"] = chan
            # No users in local or link channel

            server.dispatcher._cleanup_empty_link_channels("#test")
            assert "#test" not in link.channels
        finally:
            server.sock.close()

    def test_link_channel_kept_if_has_users(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            link = _make_dummy_link(server)
            chan = Channel(name="#test")
            chan.add_user("alice")
            link.channels["#test"] = chan

            server.dispatcher._cleanup_empty_link_channels("#test")
            assert "#test" in link.channels
        finally:
            server.sock.close()


# ===========================================================================
# Test: KILL command
# ===========================================================================

class TestKillCommand:
    def test_kill_removes_remote_user(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            sid = _register_user(server, "admin")
            session = server.state.ensure_session(sid)
            session["oper_flags"] = "oO"
            server.add_active_oper("admin", "admin", "oO")

            link = _make_dummy_link(server, origin="remote.server")
            link.add_user("victim")
            link.add_nick_behind("victim")

            server.enqueue_client_line("KILL victim :bad behavior", source_session=sid)
            _run_all(server)

            assert not link.has_user("victim")
            assert "victim" not in link.nicks_behind
        finally:
            server.sock.close()


# ===========================================================================
# Test: INVITE relay to links
# ===========================================================================

class TestInviteRelay:
    def test_invite_syncs_to_link_channel(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            sid = _register_user(server, "alice")
            server.enqueue_client_line("JOIN #secret", source_session=sid)
            _run_all(server)

            # Set +i on channel
            server.state.set_channel_mode("#secret", "i")

            link = _make_dummy_link(server)
            link_chan = Channel(name="#secret")
            link.channels["#secret"] = link_chan

            # Register bob so invite target exists
            sid_bob = _register_user(server, "bob")

            server.enqueue_client_line("INVITE bob #secret", source_session=sid)
            _run_all(server)

            assert "bob" in link_chan.invites
        finally:
            server.sock.close()


# ===========================================================================
# Test: Oper privilege sync
# ===========================================================================

class TestOperSync:
    def test_burst_includes_opers(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            link = _make_dummy_link(server, origin="remote.server")
            burst_data = {
                "servers_behind": [],
                "nicks_behind": ["alice"],
                "opers": ["alice"],
                "channels": {},
            }
            server.sync_mesh.receive_burst(link, burst_data)

            assert "alice" in link.opers
        finally:
            server.sock.close()

    def test_require_oper_checks_link_opers_for_remote(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            from csc_server.queue.command import CommandEnvelope
            link = _make_dummy_link(server, origin="remote.server")
            link.add_oper("remoteop")

            # Create a remote-origin envelope
            envelope = CommandEnvelope(
                kind="IRC",
                payload={"line": "KILL someone :test"},
                source_session="remote-session",
                origin_server="remote.server",
            )
            server.state.ensure_session("remote-session")

            result = server.dispatcher._require_oper(envelope, "remoteop")
            assert result is True
        finally:
            server.sock.close()


# ===========================================================================
# Test: Link.clear_remote_state
# ===========================================================================

class TestLinkClearState:
    def test_clear_remote_state_empties_everything(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            link = _make_dummy_link(server)
            link.add_user("alice")
            link.add_user("bob")
            link.add_nick_behind("charlie")
            link.add_oper("alice")
            link.set_servers_behind(["server2"])
            chan = Channel(name="#test")
            chan.add_user("alice")
            link.channels["#test"] = chan

            removed_nicks, removed_channels = link.clear_remote_state()

            assert "alice" in removed_nicks
            assert "bob" in removed_nicks
            assert "charlie" in removed_nicks
            assert "#test" in removed_channels
            assert len(link.users) == 0
            assert len(link.channels) == 0
            assert len(link.opers) == 0
            assert len(link.nicks_behind) == 0
            assert len(link.servers_behind) == 0
        finally:
            server.sock.close()


# ===========================================================================
# Test: Netsplit QUIT emission
# ===========================================================================

class TestNetsplitQuits:
    def test_emit_netsplit_quits_sends_quit_to_all_sessions(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            sid = _register_user(server, "localuser")

            link = _make_dummy_link(server, origin="dead.server")
            link.add_user("remoteuser")
            link.add_nick_behind("remoteuser")

            before = len(server.state.outbound_events)
            server.sync_mesh.emit_netsplit_quits(link)

            new_events = server.state.outbound_events[before:]
            quit_lines = [e["line"] for e in new_events if "QUIT" in e["line"]]
            assert len(quit_lines) >= 1
            assert "remoteuser" in quit_lines[0]

            # Link state should be cleared
            assert len(link.users) == 0
            assert len(link.nicks_behind) == 0
        finally:
            server.sock.close()


# ===========================================================================
# Test: BURST retry tracking
# ===========================================================================

class TestBurstRetry:
    def test_burst_retry_counter_increments(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            link = _make_dummy_link(server, origin="remote.server")
            # Use set_crypto_key to enable encryption (sendto will fail
            # silently since there's no real peer, but the retry logic runs)
            link.connection.set_crypto_key(b"\x00" * 32)

            # First attempt
            server.sync_mesh.send_burst(link)
            assert server.sync_mesh._burst_retries.get(link.id) == 1

            # Second attempt
            server.sync_mesh.send_burst(link)
            assert server.sync_mesh._burst_retries.get(link.id) == 2
        finally:
            server.sock.close()

    def test_burst_receive_clears_retry_state(self, tmp_path, monkeypatch):
        server = _make_server(tmp_path, monkeypatch)
        try:
            link = _make_dummy_link(server, origin="remote.server")
            server.sync_mesh._burst_retries[link.id] = 2
            server.sync_mesh._burst_sent_at[link.id] = 12345.0

            burst_data = {
                "servers_behind": [],
                "nicks_behind": [],
                "channels": {},
            }
            server.sync_mesh.receive_burst(link, burst_data)

            assert link.id not in server.sync_mesh._burst_retries
            assert link.id not in server.sync_mesh._burst_sent_at
        finally:
            server.sock.close()
