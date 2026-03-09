```python
# --- Imports MUST come first ---
import pytest
from unittest.mock import Mock, MagicMock, patch, call
import time
import io
import sys
import os

# --- Add Parent Directories to Path ---
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
server_dir = os.path.join(parent_dir, "server")
shared_dir = os.path.join(parent_dir, "shared")
for d in [parent_dir, server_dir, shared_dir]:
    if d not in sys.path:
        sys.path.insert(0, d)
# --- End Path Modification ---

try:
    from server_console import ServerConsole
    from channel import ChannelManager, Channel
    from irc import SERVER_NAME, format_irc_message
    _IMPORTS_OK = True
except ImportError as e:
    print(f"ImportError: {e}")
    _IMPORTS_OK = False
    ServerConsole = None


def _build_mock_server():
    """Create a mock server with all attributes needed by ServerConsole."""
    server = Mock()
    server.name = "TestServer"
    server.server_name = SERVER_NAME
    server._running = True
    server.clients = {}
    server.channel_manager = ChannelManager()
    server.oper_credentials = {"admin": "changeme"}
    server.opers = set()
    server.motd = "Default MOTD"
    server.log = Mock()
    server.sock_send = Mock()
    server.get_data = Mock(return_value=None)
    server.put_data = Mock()
    server.broadcast = Mock()
    server.broadcast_to_channel = Mock()
    server.message_handler = Mock()
    server.message_handler.registration_state = {}
    return server


@pytest.mark.skipif(not _IMPORTS_OK, reason="Imports failed")
class TestServerConsoleChannels:
    """Tests for /channels command in ServerConsole."""

    def setup_method(self):
        """Sets up the test fixture."""
        self.server = _build_mock_server()
        self.console = ServerConsole(self.server)

    def test_list_channels_shows_channels_with_member_counts(self, capsys):
        """/channels lists all channels with their member counts."""
        # Add members to #general
        general = self.server.channel_manager.get_channel("#general")
        general.add_member("Alice", ("127.0.0.1", 50000))
        general.add_member("Bob", ("127.0.0.2", 50001))

        # Create another channel with a topic
        test_ch = self.server.channel_manager.ensure_channel("#test")
        test_ch.topic = "Testing channel"
        test_ch.add_member("Charlie", ("127.0.0.3", 50002))

        self.console.list_channels()
        captured = capsys.readouterr()
        output = captured.out

        assert "#general" in output
        assert "2 members" in output
        assert "#test" in output
        assert "1 members" in output
        assert "Testing channel" in output

    def test_list_channels_empty(self, capsys):
        """/channels with no channels shows appropriate message."""
        # Remove all channels (including default)
        self.server.channel_manager.channels.clear()
        self.console.list_channels()
        captured = capsys.readouterr()
        output = captured.out
        assert "No channels." in output

    def test_list_channels_shows_op_prefix(self, capsys):
        """/channels shows @ prefix for channel operators."""
        general = self.server.channel_manager.get_channel("#general")
        general.add_member("Alice", ("127.0.0.1", 50000), modes={"o"})
        general.add_member("Bob", ("127.0.0.2", 50001))

        self.console.list_channels()
        captured = capsys.readouterr()
        output = captured.out
        assert "@Alice" in output
        assert " Bob" in output


@pytest.mark.skipif(not _IMPORTS_OK, reason="Imports failed")
class TestServerConsoleKick:
    """Tests for /kick command in ServerConsole."""

    def setup_method(self):
        """Sets up the test fixture."""
        self.server = _build_mock_server()
        self.console = ServerConsole(self.server)
        self.addr1 = ("127.0.0.1", 50000)
        self.addr2 = ("127.0.0.2", 50001)
        # Set up active clients
        self.server.clients = {
            self.addr1: {"name": "Alice", "last_seen": time.time()},
            self.addr2: {"name": "Bob", "last_seen": time.time()},
        }
        # Add to channels
        general = self.server.channel_manager.get_channel("#general")
        general.add_member("Alice", self.addr1)
        general.add_member("Bob", self.addr2)

    def test_kick_removes_from_channels_and_sends_kill(self, capsys):
        """/kick removes the user from all channels and sends KILL + ERROR."""
        self.console.kick_client("/kick Alice")

        # Alice should be removed from active clients
        assert self.addr1 not in self.server.clients
        # Alice should be removed from #general
        general = self.server.channel_manager.get_channel("#general")
        assert not general.has_member("Alice")
        # Bob should still be there
        assert general.has_member("Bob")

        # KILL and ERROR should have been sent to Alice
        sent_calls = self.server.sock_send.call_args_list
        sent_to_alice = [c for c in sent_calls if c[0][1] == self.addr1]
        sent_data = b"".join(c[0][0] for c in sent_to_alice).decode("utf-8")
        assert "KILL" in sent_data
        assert "ERROR" in sent_data

        captured = capsys.readouterr()
        output = captured.out
        assert "Kicked Alice" in output

    def test_kick_nonexistent_user(self, capsys):
        """/kick for a non-existent user shows appropriate message."""
        self.console.kick_client("/kick GhostUser")
        captured = capsys.readouterr()
        output = captured.out
        assert "not found" in output.lower() or "unknown" in output.lower()

    def test_kick_no_argument(self, capsys):
        """/kick with no argument shows usage message."""
        self.console.kick_client("/kick")
        captured = capsys.readouterr()
        output = captured.out
        assert "usage" in output.lower() or "kick" in output.lower()


@pytest.mark.skipif(not _IMPORTS_OK, reason="Imports failed")
class TestServerConsoleOper:
    """Tests for /oper command in ServerConsole."""

    def setup_method(self):
        """Sets up the test fixture."""
        self.server = _build_mock_server()
        self.console = ServerConsole(self.server)

    def test_oper_login_success(self, capsys):
        """Successful /oper login adds to opers set."""
        self.console.oper_login("/oper admin changeme")
        assert "admin" in self.server.opers
        captured = capsys.readouterr()
        output = captured.out
        assert "granted" in output.lower() or "oper" in output.lower()

    def test_oper_login_wrong_password(self, capsys):
        """Wrong password in /oper shows error."""
        self.console.oper_login("/oper admin wrongpass")
        assert "admin" not in self.server.opers
        captured = capsys.readouterr()
        output = captured.out
        assert "denied" in output.lower() or "incorrect" in output.lower()

    def test_oper_login_unknown_user(self, capsys):
        """Unknown user in /oper shows error."""
        self.console.oper_login("/oper unknown pass")
        captured = capsys.readouterr()
        output = captured.out
        assert "not found" in output.lower() or "unknown" in output.lower()

    def test_oper_login_no_args(self, capsys):
        """/oper with no args shows usage."""
        self.console.oper_login("/oper")
        captured = capsys.readouterr()
        output = captured.out
        assert "usage" in output.lower() or "oper" in output.lower()


@pytest.mark.skipif(not _IMPORTS_OK, reason="Imports failed")
class TestServerConsoleMOTD:
    """Tests for /motd command in ServerConsole."""

    def setup_method(self):
        """Sets up the test fixture."""
        self.server = _build_mock_server()
        self.console = ServerConsole(self.server)

    def test_view_motd(self, capsys):
        """View current MOTD with /motd (no args)."""
        self.server.motd = "Welcome to Test Server"
        self.console.set_motd("/motd")
        captured = capsys.readouterr()
        output = captured.out
        assert "Welcome to Test Server" in output

    def test_set_motd(self, capsys):
        """Set new MOTD with /motd <message>."""
        self.console.set_motd("/motd New MOTD Text")
        assert self.server.motd == "New MOTD Text"
        captured = capsys.readouterr()
        output = captured.out
        assert "updated" in output.lower() or "set" in output.lower()

    def test_set_motd_multiword(self, capsys):
        """Set MOTD with multiple words."""
        msg = "Welcome to the test IRC server!"
        self.console.set_motd(f"/motd {msg}")
        assert self.server.motd == msg


@pytest.mark.skipif(not _IMPORTS_OK, reason="Imports failed")
class TestServerConsoleClients:
    """Tests for /clients command in ServerConsole."""

    def setup_method(self):
        """Sets up the test fixture."""
        self.server = _build_mock_server()
        self.console = ServerConsole(self.server)
        self.addr1 = ("127.0.0.1", 50000)
        self.addr2 = ("127.0.0.2", 50001)
        self.server.clients = {
            self.addr1: {"name": "Alice", "last_seen": time.time()},
            self.addr2: {"name": "Bob", "last_seen": time.time()},
        }

    def test_list_clients_shows_all_clients(self, capsys):
        """List clients shows all connected clients."""
        self.console.list_clients()
        captured = capsys.readouterr()
        output = captured.out
        assert "Alice" in output
        assert "Bob" in output
        assert "127.0.0.1" in output
        assert "127.0.0.2" in output

    def test_list_clients_empty(self, capsys):
        """List clients with no clients shows appropriate message."""
        self.server.clients.clear()
        self.console.list_clients()
        captured = capsys.readouterr()
        output = captured.out
        assert "no clients" in output.lower() or "empty" in output.lower()


@pytest.mark.skipif(not _IMPORTS_OK, reason="Imports failed")
class TestServerConsoleHelp:
    """Tests for /help command in ServerConsole."""

    def setup_method(self):
        """Sets up the test fixture."""
        self.server = _build_mock_server()
        self.console = ServerConsole(self.server)

    def test_help_shows_commands(self, capsys):
        """Help displays available commands."""
        self.console.show_help("/help")
        captured = capsys.readouterr()
        output = captured.out
        # Check for some expected commands
        assert output.strip()  # Should have some output


@pytest.mark.skipif(not _IMPORTS_OK, reason="Imports failed")
class TestServerConsoleQuit:
    """Tests for /quit and /shutdown commands in ServerConsole."""

    def setup_method(self):
        """Sets up the test fixture."""
        self.server = _build_mock_server()
        self.console = ServerConsole(self.server)

    def test_quit_stops_server(self, capsys):
        """Quit command stops the server."""
        self.server._running = True
        self.console.quit_server("/quit")
        assert not self.server._running

    def test_shutdown_stops_server(self, capsys):
        """Shutdown command stops the server."""
        self.server._running = True
        self.console.quit_server("/shutdown")
        assert not self.server._running


@pytest.mark.skipif(not _IMPORTS_OK, reason="Imports failed")
class TestServerConsoleWho:
    """Tests for /who command in ServerConsole."""

    def setup_method(self):
        """Sets up the test fixture."""
        self.server = _build_mock_server()
        self.console = ServerConsole(self.server)
        self.addr1 = ("127.0.0.1", 50000)
        self.addr2 = ("127.0.0.2", 50001)
        # Add clients
        self.server.clients = {
            self.addr1: {"name": "Alice", "last_seen": time.time()},
            self.addr2: {"name": "Bob", "last_seen": time.time()},
        }
        # Add to channels
        general = self.server.channel_manager.get_channel("#general")
        general.add_member("Alice", self.addr1)
        general.add_member("Bob", self.addr2)

    def test_who_channel_lists_members(self, capsys):
        """Who command lists members of specified channel."""
        self.console.who_command("/who #general")
        captured = capsys.readouterr()
        output = captured.out
        assert "Alice" in output
        assert "Bob" in output

    def test_who_all_lists_all_clients(self, capsys):
        """Who command without channel lists all clients."""
        self.console.who_command("/who")
        captured = capsys.readouterr()
        output = captured.out
        assert "Alice" in output or "Bob" in output


@pytest.mark.skipif(not _IMPORTS_OK, reason="Imports failed")
class TestServerConsoleBroadcast:
    """Tests for /broadcast command in ServerConsole."""

    def setup_method(self):
        """Sets up the test fixture."""
        self.server = _build_mock_server()
        self.console = ServerConsole(self.server)

    def test_broadcast_sends_to_all_clients(self, capsys):
        """Broadcast sends message to all clients."""
        self.console.broadcast_message("/broadcast Hello everyone")
        self.server.broadcast.assert_called()

    def test_broadcast_no_message(self, capsys):
        """Broadcast with no message shows error."""
        self.console.broadcast_message("/broadcast")
        captured = capsys.readouterr()
        output = captured.out
        assert output.strip()  # Should have some output (error/usage)


@pytest.mark.skipif(not _IMPORTS_OK, reason="Imports failed")
class TestServerConsoleIntegration:
    """Integration tests for ServerConsole command parsing."""

    def setup_method(self):
        """Sets up the test fixture."""
        self.server = _build_mock_server()
        self.console = ServerConsole(self.server)

    def test_console_init(self):
        """ServerConsole initializes with server."""
        assert self.console.server is self.server

    def test_command_parsing_with_leading_slash(self, capsys):
        """Commands are recognized with leading slash."""
        #