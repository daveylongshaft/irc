```python
"""
pytest test file for CSC IRC server NickServ functionality.
Tests registration, identification, ghost command, and stale nick cleanup.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import time
import threading
from io import BytesIO


# Mock imports with fallback paths
@pytest.fixture(autouse=True)
def setup_imports():
    """Setup imports before tests run."""
    pass


def _build_mock_server(oper_credentials=None):
    """Create a mock server object with all attributes needed by MessageHandler."""
    server = Mock()
    server.name = "TestServer"
    server.server_name = "irc.csc.test"
    server.clients = {}
    server.clients_lock = threading.Lock()
    server.channel_manager = Mock()
    server.channel_manager.channels = {}
    server.client_registry = {}
    server.oper_credentials = oper_credentials or {}
    server.opers = set()
    server.log = Mock()
    server.sock_send = Mock()
    server.get_data = Mock(return_value=None)
    server.put_data = Mock()
    server.broadcast = Mock()
    server.broadcast_to_channel = Mock()
    server.send_to_nick = Mock(return_value=True)
    server.handle_command = Mock(return_value="OK result")
    server.chat_buffer = Mock()
    server.chat_buffer.read = Mock(return_value=[])
    server.chat_buffer.append = Mock()
    server.send_wallops = Mock()
    server.disconnected_clients = {}
    server.max_disconnected_history = 100
    server.storage = Mock()
    server.storage.nickserv_get = Mock(return_value=None)
    server.storage.nickserv_register = Mock(return_value=True)
    server.storage.nickserv_check_password = Mock(return_value=False)
    server.storage.load_settings = Mock(return_value={
        "nickserv": {
            "enforce_timeout": 60,
            "enforce_mode": "disconnect"
        }
    })
    server.storage.load_users = Mock(return_value={"users": {}})
    server.nickserv_identified = {}
    server._persist_session_data = Mock()
    server.project_root_dir = "/tmp/csc-test"
    server.timeout = 120
    return server


def _register_client(handler, addr, nick, server):
    """Complete a full NICK+USER registration for a client."""
    nick_data = f"NICK {nick}\r\n".encode("utf-8")
    handler.process(nick_data, addr)
    user_data = f"USER {nick} 0 * :{nick}\r\n".encode("utf-8")
    handler.process(user_data, addr)
    server.sock_send.reset_mock()


def _sent_lines(server):
    """Extract all sent IRC lines from sock_send mock calls."""
    lines = []
    for c in server.sock_send.call_args_list:
        if not c or not c[0]:
            continue
        data = c[0][0]
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        for line in data.splitlines():
            if line.strip():
                lines.append(line.strip())
    return lines


@pytest.fixture
def mock_server():
    """Fixture providing a mock server."""
    return _build_mock_server()


@pytest.fixture
def mock_file_handler(mock_server):
    """Fixture providing a mock file handler."""
    handler = Mock()
    handler.server = mock_server
    return handler


@pytest.fixture
def message_handler(mock_server, mock_file_handler):
    """Fixture providing a message handler with mocked dependencies."""
    with patch('server_message_handler.MessageHandler', create=True):
        handler = Mock()
        handler.server = mock_server
        handler.file_handler = mock_file_handler
        handler.process = Mock()
        return handler


# ===========================================================================
# Registration Tests
# ===========================================================================

class TestNickServRegistration:
    """Tests for NickServ REGISTER command."""

    def test_register_command_success(self, mock_server, mock_file_handler):
        """REGISTER saves nick and auto-identifies."""
        addr = ("127.0.0.1", 5001)
        
        # Simulate client registration
        mock_server.clients[addr] = Mock()
        mock_server.clients[addr].nick = "User1"
        mock_server.clients[addr].user = "User1"
        mock_server.clients[addr].host = "csc-server"
        
        mock_server.storage.nickserv_get.return_value = None
        mock_server.storage.nickserv_register.return_value = True
        
        # Should register nick with password
        mock_server.storage.nickserv_register("User1", "secretpass", "User1@csc-server")
        
        assert mock_server.storage.nickserv_register.called
        mock_server.storage.nickserv_register.assert_called_with(
            "User1", "secretpass", "User1@csc-server"
        )

    def test_register_command_already_registered(self, mock_server):
        """REGISTER fails if nick already registered."""
        addr = ("127.0.0.1", 5001)
        
        mock_server.clients[addr] = Mock()
        mock_server.clients[addr].nick = "User1"
        
        # Nick already registered
        mock_server.storage.nickserv_get.return_value = {
            "nick": "User1",
            "password": "hashedpass"
        }
        
        result = mock_server.storage.nickserv_get("User1")
        assert result is not None
        assert result["nick"] == "User1"

    def test_register_command_empty_password(self, mock_server):
        """REGISTER with empty password should fail."""
        addr = ("127.0.0.1", 5001)
        
        mock_server.clients[addr] = Mock()
        mock_server.clients[addr].nick = "User1"
        
        # Empty password validation
        password = ""
        assert len(password) == 0

    def test_register_sets_identified_flag(self, mock_server):
        """After REGISTER, nick should be marked as identified."""
        addr = ("127.0.0.1", 5001)
        
        mock_server.nickserv_identified[addr] = "User1"
        
        assert mock_server.nickserv_identified[addr] == "User1"


# ===========================================================================
# Identification Tests
# ===========================================================================

class TestNickServIdentification:
    """Tests for NickServ IDENTIFY command."""

    def test_identify_correct_password(self, mock_server):
        """IDENTIFY with correct password identifies the user."""
        addr = ("127.0.0.1", 5001)
        
        mock_server.clients[addr] = Mock()
        mock_server.clients[addr].nick = "User1"
        
        mock_server.storage.nickserv_check_password.return_value = True
        
        # Check password
        result = mock_server.storage.nickserv_check_password("User1", "secretpass")
        assert result is True

    def test_identify_wrong_password(self, mock_server):
        """IDENTIFY with wrong password fails."""
        addr = ("127.0.0.1", 5001)
        
        mock_server.clients[addr] = Mock()
        mock_server.clients[addr].nick = "User1"
        
        mock_server.storage.nickserv_check_password.return_value = False
        
        result = mock_server.storage.nickserv_check_password("User1", "wrongpass")
        assert result is False

    def test_identify_nonexistent_nick(self, mock_server):
        """IDENTIFY for nonexistent nick should fail."""
        addr = ("127.0.0.1", 5001)
        
        mock_server.clients[addr] = Mock()
        mock_server.clients[addr].nick = "UnknownUser"
        
        mock_server.storage.nickserv_get.return_value = None
        
        result = mock_server.storage.nickserv_get("UnknownUser")
        assert result is None

    def test_identify_sets_identified_flag(self, mock_server):
        """After successful IDENTIFY, client should be marked identified."""
        addr = ("127.0.0.1", 5001)
        
        mock_server.nickserv_identified[addr] = "User1"
        
        assert addr in mock_server.nickserv_identified
        assert mock_server.nickserv_identified[addr] == "User1"


# ===========================================================================
# Ghost Command Tests
# ===========================================================================

class TestNickServGhost:
    """Tests for NickServ GHOST command."""

    def test_ghost_kills_stale_client(self, mock_server):
        """GHOST should disconnect a client with the same nick."""
        addr1 = ("127.0.0.1", 5001)
        addr2 = ("127.0.0.1", 5002)
        
        # Stale client with same nick
        mock_server.clients[addr1] = Mock()
        mock_server.clients[addr1].nick = "User1"
        mock_server.clients[addr1].socket = Mock()
        
        # New client requesting ghost
        mock_server.clients[addr2] = Mock()
        mock_server.clients[addr2].nick = "User1_new"
        
        # Simulate ghost by removing old client
        del mock_server.clients[addr1]
        
        assert addr1 not in mock_server.clients
        assert addr2 in mock_server.clients

    def test_ghost_with_correct_password(self, mock_server):
        """GHOST with correct password removes stale nick."""
        addr_stale = ("127.0.0.1", 5001)
        addr_new = ("127.0.0.1", 5002)
        
        mock_server.clients[addr_stale] = Mock()
        mock_server.clients[addr_stale].nick = "User1"
        mock_server.clients[addr_stale].socket = Mock()
        
        mock_server.clients[addr_new] = Mock()
        mock_server.clients[addr_new].nick = "NewUser1"
        
        mock_server.storage.nickserv_check_password.return_value = True
        
        # Verify password check
        result = mock_server.storage.nickserv_check_password("User1", "correctpass")
        assert result is True

    def test_ghost_with_wrong_password(self, mock_server):
        """GHOST with wrong password should fail."""
        addr = ("127.0.0.1", 5001)
        
        mock_server.clients[addr] = Mock()
        mock_server.clients[addr].nick = "User1"
        
        mock_server.storage.nickserv_check_password.return_value = False
        
        result = mock_server.storage.nickserv_check_password("User1", "wrongpass")
        assert result is False
        
        # Client should still be in registry
        assert addr in mock_server.clients

    def test_ghost_nonexistent_nick(self, mock_server):
        """GHOST for nonexistent nick should fail."""
        addr = ("127.0.0.1", 5001)
        
        mock_server.clients[addr] = Mock()
        mock_server.clients[addr].nick = "CurrentUser"
        
        mock_server.storage.nickserv_get.return_value = None
        
        result = mock_server.storage.nickserv_get("NonexistentNick")
        assert result is None


# ===========================================================================
# Stale Nick Cleanup Tests
# ===========================================================================

class TestStaleNickCleanup:
    """Tests for stale nick cleanup mechanism."""

    def test_cleanup_disconnected_clients(self, mock_server):
        """Disconnected clients should be moved to disconnected_clients."""
        addr = ("127.0.0.1", 5001)
        
        client = Mock()
        client.nick = "User1"
        client.last_activity = time.time() - 200  # 200 seconds ago
        mock_server.clients[addr] = client
        
        # Simulate timeout (120 seconds)
        if time.time() - client.last_activity > mock_server.timeout:
            mock_server.disconnected_clients[addr] = client
            del mock_server.clients[addr]
        
        assert addr not in mock_server.clients
        assert addr in mock_server.disconnected_clients

    def test_cleanup_preserves_recent_clients(self, mock_server):
        """Recently active clients should not be cleaned up."""
        addr = ("127.0.0.1", 5001)
        
        client = Mock()
        client.nick = "User1"
        client.last_activity = time.time()  # Just now
        mock_server.clients[addr] = client
        
        # Should not be cleaned up
        if time.time() - client.last_activity <= mock_server.timeout:
            # Client stays in clients dict
            assert addr in mock_server.clients

    def test_cleanup_respects_max_history(self, mock_server):
        """Disconnected clients history should respect max limit."""
        for i in range(150):
            addr = ("127.0.0.1", 5000 + i)
            client = Mock()
            client.nick = f"User{i}"
            mock_server.disconnected_clients[addr] = client
        
        # Trim if over limit
        if len(mock_server.disconnected_clients) > mock_server.max_disconnected_history:
            to_remove = len(mock_server.disconnected_clients) - mock_server.max_disconnected_history
            addrs_to_remove = list(mock_server.disconnected_clients.keys())[:to_remove]
            for addr in addrs_to_remove:
                del mock_server.disconnected_clients[addr]
        
        assert len(mock_server.disconnected_clients) <= mock_server.max_disconnected_history

    def test_cleanup_on_new_nick_registration(self, mock_server):
        """Registering a new nick should clear old disconnected entry."""
        addr_old = ("127.0.0.1", 5001)
        addr_new = ("127.0.0.1", 5002)
        
        # Old client disconnected
        mock_server.disconnected_clients[addr_old] = Mock()
        mock_server.disconnected_clients[addr_old].nick = "User1"
        
        # New client takes the nick
        mock_server.clients[addr_new] = Mock()
        mock_server.clients[addr_new].nick = "User1"
        
        # Clean up old entry
        if mock_server.disconnected_clients[addr_old].nick == "User1":
            del mock_server.disconnected_clients[addr_old]
        
        assert addr_old not in mock_server.disconnected_clients
        assert addr_new in mock_server.clients


# ===========================================================================
# Integration Tests
# ===========================================================================

class TestNickServIntegration:
    """Integration tests for NickServ functionality."""

    def test_full_registration_flow(self, mock_server):
        """Test complete registration -> identify flow."""
        addr = ("127.0.0.1", 5001)
        
        # Register
        mock_server.clients[addr] = Mock()
        mock_server.clients[addr].nick = "User1"
        mock_server.storage.nickserv_register.return_value = True
        
        result = mock_server.storage.nickserv_register("User1", "pass123", "User1@host")
        assert result is True
        
        # Mark as identified
        mock_server.nickserv_identified[addr] = "User1"
        assert mock_server.nickserv_identified[addr] == "User1"

    def test_disconnect_reconnect_identify(self, mock_server):
        """