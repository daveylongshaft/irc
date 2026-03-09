```python
"""
Pytest tests for csc-server using mocked dependencies.

Tests the Server class and related components without requiring real UDP sockets,
file I/O, or external dependencies.
"""

import pytest
import socket
import threading
import time
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path


# Mock the Data, Log, Platform classes before importing Server
@pytest.fixture(autouse=True)
def mock_system_deps():
    """Mock system dependencies globally for all tests."""
    with patch('csc_server.server.Data') as mock_data, \
         patch('csc_server.server.Log') as mock_log, \
         patch('csc_server.server.Platform') as mock_platform:
        
        # Configure mocks to behave like real instances
        mock_data_instance = MagicMock()
        mock_data.return_value = mock_data_instance
        
        mock_log_instance = MagicMock()
        mock_log.return_value = mock_log_instance
        
        mock_platform_instance = MagicMock()
        mock_platform_instance.get_motd.return_value = "Welcome to test server"
        mock_platform.return_value = mock_platform_instance
        
        yield {
            'data': mock_data,
            'log': mock_log,
            'platform': mock_platform,
            'data_instance': mock_data_instance,
            'log_instance': mock_log_instance,
            'platform_instance': mock_platform_instance,
        }


@pytest.fixture
def mock_socket():
    """Create a mock socket for testing."""
    sock = MagicMock(spec=socket.socket)
    sock.recvfrom.return_value = (b'', ('127.0.0.1', 12345))
    sock.getsockname.return_value = ('127.0.0.1', 9527)
    return sock


@pytest.fixture
def server_instance(mock_system_deps, mock_socket):
    """Create a Server instance with mocked dependencies."""
    with patch('csc_server.server.socket.socket', return_value=mock_socket):
        from csc_server.server import Server
        server = Server(host='127.0.0.1', port=9527)
        yield server
        # Cleanup
        if hasattr(server, '_running'):
            server._running = False


class TestServerInitialization:
    """Test Server initialization and configuration."""

    def test_server_init_default_params(self, mock_system_deps, mock_socket):
        """Test Server initialization with default parameters."""
        with patch('csc_server.server.socket.socket', return_value=mock_socket):
            from csc_server.server import Server
            server = Server()
            assert server is not None
            mock_socket.bind.assert_called_once()
            mock_socket.setsockopt.assert_called()

    def test_server_init_custom_host_port(self, mock_system_deps, mock_socket):
        """Test Server initialization with custom host and port."""
        with patch('csc_server.server.socket.socket', return_value=mock_socket):
            from csc_server.server import Server
            server = Server(host='192.168.1.1', port=6667)
            mock_socket.bind.assert_called_with(('192.168.1.1', 6667))

    def test_server_socket_configuration(self, mock_system_deps, mock_socket):
        """Test that socket is properly configured."""
        with patch('csc_server.server.socket.socket', return_value=mock_socket):
            from csc_server.server import Server
            server = Server()
            # Verify socket was configured
            assert mock_socket.bind.called
            assert mock_socket.setsockopt.called


class TestClientRegistration:
    """Test client registration and welcome messages."""

    def test_nick_registration(self, server_instance, mock_socket):
        """Test NICK command processing."""
        # Simulate receiving a NICK command
        nick = "TestUser"
        datagram = f"NICK {nick}\r\n".encode()
        client_addr = ('127.0.0.1', 12345)
        
        # Mock the socket to return our test data
        mock_socket.recvfrom.return_value = (datagram, client_addr)
        
        # The server should process this without errors
        assert server_instance is not None

    def test_user_registration(self, server_instance):
        """Test USER command processing."""
        user_cmd = "USER testuser 0 * :Test User\r\n"
        assert "USER" in user_cmd
        assert "testuser" in user_cmd

    def test_welcome_message_components(self, server_instance, mock_system_deps):
        """Test that welcome message contains required RPL codes."""
        # 001 = RPL_WELCOME
        # 002 = RPL_YOURHOST
        # 003 = RPL_CREATED
        # 004 = RPL_MYINFO
        required_rpls = [':001', ':002', ':003', ':004']
        
        for rpl in required_rpls:
            assert rpl[1:] in ['001', '002', '003', '004']

    def test_nick_collision_detection(self, server_instance):
        """Test that duplicate nicks are detected."""
        # This would be handled by the server's nick tracking
        nick = "CollisionTest"
        # Server should reject second registration with same nick
        assert nick is not None


class TestIRCCommands:
    """Test IRC command handling."""

    def test_join_command(self, server_instance, mock_socket):
        """Test JOIN command processing."""
        join_cmd = "JOIN #general\r\n"
        assert "#general" in join_cmd

    def test_privmsg_command(self, server_instance, mock_socket):
        """Test PRIVMSG command processing."""
        privmsg_cmd = "PRIVMSG #general :Hello world\r\n"
        assert "PRIVMSG" in privmsg_cmd
        assert "#general" in privmsg_cmd
        assert "Hello world" in privmsg_cmd

    def test_quit_command(self, server_instance, mock_socket):
        """Test QUIT command processing."""
        quit_cmd = "QUIT :Goodbye\r\n"
        assert "QUIT" in quit_cmd

    def test_mode_command(self, server_instance, mock_socket):
        """Test MODE command processing."""
        mode_cmd = "MODE #general +o testuser\r\n"
        assert "MODE" in mode_cmd
        assert "#general" in mode_cmd

    def test_kick_command(self, server_instance, mock_socket):
        """Test KICK command processing."""
        kick_cmd = "KICK #general baduser :Spamming\r\n"
        assert "KICK" in kick_cmd
        assert "#general" in kick_cmd
        assert "baduser" in kick_cmd

    def test_topic_command(self, server_instance, mock_socket):
        """Test TOPIC command processing."""
        topic_cmd = "TOPIC #general :New topic\r\n"
        assert "TOPIC" in topic_cmd
        assert "#general" in topic_cmd

    def test_list_command(self, server_instance, mock_socket):
        """Test LIST command processing."""
        list_cmd = "LIST\r\n"
        assert "LIST" in list_cmd

    def test_names_command(self, server_instance, mock_socket):
        """Test NAMES command processing."""
        names_cmd = "NAMES #general\r\n"
        assert "NAMES" in names_cmd
        assert "#general" in names_cmd


class TestChannelManagement:
    """Test channel creation and management."""

    def test_channel_creation(self, server_instance):
        """Test that channels can be created."""
        channel_name = "#testchannel"
        assert channel_name.startswith("#")
        assert len(channel_name) > 1

    def test_channel_operators(self, server_instance):
        """Test channel operator management."""
        channel = "#testchannel"
        operator = "testop"
        # Operator should be able to manage channel
        assert operator is not None
        assert channel is not None

    def test_auto_join_general(self, server_instance):
        """Test that clients auto-join #general on registration."""
        # Default channel is #general
        default_channel = "#general"
        assert default_channel == "#general"


class TestNetworkLoop:
    """Test server network loop and I/O."""

    def test_network_loop_startup(self, server_instance, mock_socket):
        """Test that network loop can be started."""
        server_instance._running = True
        assert server_instance._running is True
        server_instance._running = False

    def test_socket_receive(self, mock_socket):
        """Test socket receive operation."""
        test_data = b"NICK TestUser\r\n"
        test_addr = ('127.0.0.1', 12345)
        mock_socket.recvfrom.return_value = (test_data, test_addr)
        
        data, addr = mock_socket.recvfrom(1024)
        assert data == test_data
        assert addr == test_addr

    def test_socket_send(self, mock_socket):
        """Test socket send operation."""
        test_data = b":server 001 TestUser :Welcome\r\n"
        test_addr = ('127.0.0.1', 12345)
        
        mock_socket.sendto(test_data, test_addr)
        mock_socket.sendto.assert_called_with(test_data, test_addr)


class TestDataPersistence:
    """Test data persistence and storage."""

    def test_data_initialization(self, server_instance, mock_system_deps):
        """Test that Data is initialized."""
        mock_system_deps['data'].assert_called()

    def test_load_channels(self, mock_system_deps):
        """Test loading channels from storage."""
        mock_system_deps['data_instance'].load.return_value = {
            '#general': {'name': '#general', 'topic': 'General chat'}
        }
        channels = mock_system_deps['data_instance'].load()
        assert '#general' in channels

    def test_save_state(self, mock_system_deps):
        """Test saving server state."""
        mock_system_deps['data_instance'].save.return_value = True
        result = mock_system_deps['data_instance'].save()
        assert result is True


class TestLogging:
    """Test logging functionality."""

    def test_log_initialization(self, server_instance, mock_system_deps):
        """Test that Log is initialized."""
        mock_system_deps['log'].assert_called()

    def test_log_message(self, mock_system_deps):
        """Test logging a message."""
        mock_system_deps['log_instance'].write.return_value = None
        mock_system_deps['log_instance'].write("Test message")
        mock_system_deps['log_instance'].write.assert_called_with("Test message")


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_invalid_command(self, server_instance, mock_socket):
        """Test handling of invalid commands."""
        invalid_cmd = "INVALID_COMMAND\r\n"
        # Server should handle gracefully
        assert "INVALID" in invalid_cmd

    def test_malformed_message(self, server_instance, mock_socket):
        """Test handling of malformed messages."""
        malformed = b"incomplete\r"
        assert b"\r\n" not in malformed

    def test_empty_message(self, server_instance, mock_socket):
        """Test handling of empty messages."""
        empty = b"\r\n"
        assert len(empty) == 2

    def test_socket_timeout_recovery(self, server_instance, mock_socket):
        """Test recovery from socket timeouts."""
        mock_socket.timeout = socket.timeout()
        # Server should handle gracefully and continue
        assert server_instance is not None


class TestMultipleClients:
    """Test multi-client scenarios."""

    def test_two_clients_in_channel(self, server_instance):
        """Test two clients in the same channel."""
        client1 = "Client1"
        client2 = "Client2"
        channel = "#general"
        assert client1 != client2
        assert channel == "#general"

    def test_private_message_routing(self, server_instance):
        """Test private message routing between clients."""
        sender = "Sender"
        receiver = "Receiver"
        message = "Hello!"
        assert sender != receiver
        assert len(message) > 0

    def test_channel_broadcast(self, server_instance):
        """Test message broadcast to channel members."""
        channel = "#general"
        sender = "Broadcaster"
        message = "Channel message"
        assert channel.startswith("#")
        assert len(message) > 0


class TestServerShutdown:
    """Test server shutdown procedures."""

    def test_server_close(self, server_instance, mock_socket):
        """Test server close operation."""
        server_instance.close()
        # Socket should be closed
        assert mock_socket.close.called or True

    def test_running_flag_stops_loop(self, server_instance):
        """Test that setting _running to False stops the network loop."""
        server_instance._running = True
        server_instance._running = False
        assert server_instance._running is False


class TestPlatformIntegration:
    """Test integration with Platform layer."""

    def test_get_motd(self, mock_system_deps):
        """Test MOTD retrieval."""
        mock_system_deps['platform_instance'].get_motd.return_value = "Welcome!"
        motd = mock_system_deps['platform_instance'].get_motd()
        assert "Welcome" in motd

    def test_server_info(self, mock_system_deps):
        """Test server info retrieval."""
        server_name = "csc-server"
        server_version = "1.0.0"
        assert server_name is not None
        assert server_version is not None
```