```python
#!/usr/bin/env python3
"""
Pytest test suite for CSC IRC command orchestration system.

Tests IRC command handling with mocked network, file I/O, and subprocess.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, mock_open, call
from datetime import datetime
from pathlib import Path
import json
import socket


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_socket():
    """Mock socket for IRC connections."""
    with patch('socket.socket') as mock_sock:
        yield mock_sock


@pytest.fixture
def mock_log_file(tmp_path):
    """Mock logging to temporary file."""
    log_file = tmp_path / "irc-command-test-results.log"
    return log_file


@pytest.fixture
def mock_data_class():
    """Mock Data class."""
    with patch('csc.Data') as mock_data:
        yield mock_data


@pytest.fixture
def mock_log_class():
    """Mock Log class."""
    with patch('csc.Log') as mock_log:
        yield mock_log


@pytest.fixture
def mock_platform_class():
    """Mock Platform class."""
    with patch('csc.Platform') as mock_platform:
        yield mock_platform


@pytest.fixture
def irc_test_client():
    """Create IRC test client instance."""
    from irc_module import IRCTestClient
    return IRCTestClient(nick="testbot", user="testuser", realname="Test User")


@pytest.fixture
def irc_command_tester(mock_log_file):
    """Create IRC command tester instance."""
    from irc_module import IRCCommandTester
    return IRCCommandTester(str(mock_log_file))


# ============================================================================
# Tests for IRCTestClient
# ============================================================================

class TestIRCTestClient:
    """Test cases for IRCTestClient class."""

    def test_client_initialization(self):
        """Test IRCTestClient initialization with default and custom parameters."""
        from irc_module import IRCTestClient
        
        # Test with all parameters
        client = IRCTestClient(nick="testbot", user="testuser", realname="Test User")
        assert client.nick == "testbot"
        assert client.user == "testuser"
        assert client.realname == "Test User"
        assert client.sock is None
        assert client.connected is False
        assert client.received_data == []
        assert client.receive_thread is None

    def test_client_initialization_defaults(self):
        """Test IRCTestClient initialization with default values."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="botname")
        assert client.nick == "botname"
        assert client.user == "testuser"
        assert client.realname == "Test User"

    def test_client_connect_success(self, mock_socket):
        """Test successful connection to IRC server."""
        from irc_module import IRCTestClient
        
        mock_sock_instance = MagicMock()
        mock_socket.return_value = mock_sock_instance
        
        client = IRCTestClient(nick="testbot")
        result = client.connect()
        
        assert result is True
        assert client.connected is True
        mock_socket.assert_called_once_with(socket.AF_INET, socket.SOCK_DGRAM)
        mock_sock_instance.settimeout.assert_called_once()

    def test_client_connect_failure(self, mock_socket):
        """Test connection failure handling."""
        from irc_module import IRCTestClient
        
        mock_socket.side_effect = socket.error("Connection failed")
        
        client = IRCTestClient(nick="testbot")
        result = client.connect()
        
        assert result is False
        assert client.connected is False

    def test_client_disconnect(self):
        """Test client disconnection."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        client.connected = True
        
        client.disconnect()
        
        assert client.connected is False
        client.sock.close.assert_called_once()

    def test_client_disconnect_without_socket(self):
        """Test disconnect when socket is None."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = None
        client.connected = False
        
        # Should not raise exception
        client.disconnect()
        assert client.connected is False

    def test_send_raw_command(self):
        """Test sending raw IRC command."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        
        client._send_raw("PRIVMSG #channel :test message")
        
        client.sock.sendto.assert_called_once()
        call_args = client.sock.sendto.call_args
        assert b"PRIVMSG #channel :test message" in call_args[0][0]

    def test_send_raw_handles_error(self):
        """Test send_raw handles socket errors gracefully."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        client.sock.sendto.side_effect = socket.error("Send failed")
        
        # Should not raise exception
        client._send_raw("PRIVMSG #channel :test")

    def test_receive_data(self):
        """Test receiving data from server."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        mock_sock = MagicMock()
        client.sock = mock_sock
        
        # Simulate server response
        mock_sock.recvfrom.side_effect = [
            (b":server 001 testbot :Welcome\r\n", ("127.0.0.1", 6667)),
            socket.timeout()
        ]
        
        client._receive()
        
        assert len(client.received_data) > 0
        assert "Welcome" in client.received_data[0]

    def test_send_command(self):
        """Test sending command and receiving response."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        client.sock.recvfrom.side_effect = [
            (b":server RESPONSE data\r\n", ("127.0.0.1", 6667)),
            socket.timeout()
        ]
        
        response = client.send_command("PRIVMSG #channel :hello")
        
        assert "RESPONSE" in response
        client.sock.sendto.assert_called()


# ============================================================================
# Tests for IRC Commands
# ============================================================================

class TestIRCModeCommand:
    """Test /mode IRC command functionality."""

    def test_mode_command_channel_mode(self):
        """Test MODE command for setting channel modes."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        
        # Mock response for mode command
        client.sock.recvfrom.side_effect = [
            (b":server 324 testbot #channel +nt\r\n", ("127.0.0.1", 6667)),
            socket.timeout()
        ]
        
        response = client.send_command("MODE #channel +m")
        assert response  # Should have some response

    def test_mode_command_user_mode(self):
        """Test MODE command for setting user modes."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        
        client.sock.recvfrom.side_effect = [
            (b":server 221 testbot +i\r\n", ("127.0.0.1", 6667)),
            socket.timeout()
        ]
        
        response = client.send_command("MODE testbot +i")
        assert response

    def test_mode_command_invalid_parameters(self):
        """Test MODE command with invalid parameters."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        
        client.sock.recvfrom.side_effect = [
            (b":server 461 testbot MODE :Not enough parameters\r\n", ("127.0.0.1", 6667)),
            socket.timeout()
        ]
        
        response = client.send_command("MODE")
        assert "461" in response or "Not enough" in response


class TestIRCNamesCommand:
    """Test /names IRC command functionality."""

    def test_names_command_valid_channel(self):
        """Test NAMES command for valid channel."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        
        client.sock.recvfrom.side_effect = [
            (b":server 353 testbot = #channel :user1 user2 @user3\r\n", ("127.0.0.1", 6667)),
            (b":server 366 testbot #channel :End of NAMES list\r\n", ("127.0.0.1", 6667)),
            socket.timeout()
        ]
        
        response = client.send_command("NAMES #channel")
        assert "user1" in response or "353" in response

    def test_names_command_no_channel(self):
        """Test NAMES command without specifying channel."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        
        client.sock.recvfrom.side_effect = [
            (b":server 353 testbot = #channel1 :user1\r\n", ("127.0.0.1", 6667)),
            socket.timeout()
        ]
        
        response = client.send_command("NAMES")
        assert response


class TestIRCWhoCommand:
    """Test /who IRC command functionality."""

    def test_who_command_valid_channel(self):
        """Test WHO command for valid channel."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        
        client.sock.recvfrom.side_effect = [
            (b":server 352 testbot #channel user1 host.com server user1 H :0 Real Name\r\n", 
             ("127.0.0.1", 6667)),
            (b":server 315 testbot #channel :End of WHO list\r\n", ("127.0.0.1", 6667)),
            socket.timeout()
        ]
        
        response = client.send_command("WHO #channel")
        assert "352" in response or "user1" in response

    def test_who_command_user_pattern(self):
        """Test WHO command with user pattern."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        
        client.sock.recvfrom.side_effect = [
            (b":server 352 testbot * user1 host.com server user1 H :0 Real\r\n",
             ("127.0.0.1", 6667)),
            socket.timeout()
        ]
        
        response = client.send_command("WHO user*")
        assert response


class TestIRCWhoisCommand:
    """Test /whois IRC command functionality."""

    def test_whois_command_valid_user(self):
        """Test WHOIS command for valid user."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        
        client.sock.recvfrom.side_effect = [
            (b":server 311 testbot targetuser ident host.com * :Real Name\r\n",
             ("127.0.0.1", 6667)),
            (b":server 312 testbot targetuser server.com :Server Info\r\n",
             ("127.0.0.1", 6667)),
            (b":server 318 testbot targetuser :End of WHOIS\r\n", ("127.0.0.1", 6667)),
            socket.timeout()
        ]
        
        response = client.send_command("WHOIS targetuser")
        assert "311" in response or "targetuser" in response

    def test_whois_command_nonexistent_user(self):
        """Test WHOIS command for nonexistent user."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        
        client.sock.recvfrom.side_effect = [
            (b":server 401 testbot ghostuser :No such nick/channel\r\n",
             ("127.0.0.1", 6667)),
            socket.timeout()
        ]
        
        response = client.send_command("WHOIS ghostuser")
        assert "401" in response


class TestIRCNoticeCommand:
    """Test /notice IRC command functionality."""

    def test_notice_command_to_user(self):
        """Test NOTICE command to send message to user."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        client.sock.recvfrom.side_effect = [socket.timeout()]
        
        response = client.send_command("NOTICE targetuser :test notice message")
        
        client.sock.sendto.assert_called()

    def test_notice_command_to_channel(self):
        """Test NOTICE command to send message to channel."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        client.sock.recvfrom.side_effect = [socket.timeout()]
        
        response = client.send_command("NOTICE #channel :channel notice")
        
        client.sock.sendto.assert_called()

    def test_notice_command_missing_parameters(self):
        """Test NOTICE command with missing parameters."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        client.sock.recvfrom.side_effect = socket.timeout()
        
        # Command without message should be handled
        client.send_command("NOTICE targetuser")


class TestIRCPrivmsgCommand:
    """Test /msg (PRIVMSG) IRC command functionality."""

    def test_privmsg_to_user(self):
        """Test PRIVMSG command to send message to user."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        client.sock.recvfrom.side_effect = [socket.timeout()]
        
        response = client.send_command("PRIVMSG targetuser :hello there")
        
        client.sock.sendto.assert_called()

    def test_privmsg_to_channel(self):
        """Test PRIVMSG command to send message to channel."""
        from irc_module import IRCTestClient
        
        client = IRCTestClient(nick="testbot")
        client.sock = MagicMock()
        client.sock.recvfrom.side_effect = [socket.timeout()]
        
        response = client.send_command("PRIVMSG #channel :hello channel")
        
        client.sock.sendto.assert_called()

    def test_privmsg_multiline_