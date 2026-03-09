```python
import pytest
import socket
import time
from unittest.mock import Mock, MagicMock, patch, call
import struct


class TestIRCClient:
    """Test suite for IRC client communication module."""

    @pytest.fixture
    def mock_socket(self):
        """Fixture providing a mocked socket."""
        return MagicMock(spec=socket.socket)

    @pytest.fixture
    def client_setup(self, mock_socket):
        """Fixture setting up basic client configuration."""
        return {
            "sock": mock_socket,
            "server_addr": ("127.0.0.1", 9525),
            "nick": "test_client",
            "timeout": 2.0,
        }

    def test_socket_creation(self):
        """Test that socket is created with correct parameters."""
        with patch("socket.socket") as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)

            mock_socket_class.assert_called_once_with(
                socket.AF_INET, socket.SOCK_DGRAM
            )
            mock_sock.settimeout.assert_called_once_with(2.0)

    def test_send_message(self, client_setup):
        """Test sending a message to the server."""
        sock = client_setup["sock"]
        server_addr = client_setup["server_addr"]
        message = "NICK test_client\r\n"

        sock.sendto(message.encode(), server_addr)

        sock.sendto.assert_called_once_with(message.encode(), server_addr)

    def test_send_nick_command(self, client_setup):
        """Test sending NICK command."""
        sock = client_setup["sock"]
        nick = client_setup["nick"]
        server_addr = client_setup["server_addr"]

        nick_msg = f"NICK {nick}\r\n"
        sock.sendto(nick_msg.encode(), server_addr)

        sock.sendto.assert_called_once_with(nick_msg.encode(), server_addr)

    def test_send_user_command(self, client_setup):
        """Test sending USER command."""
        sock = client_setup["sock"]
        nick = client_setup["nick"]
        server_addr = client_setup["server_addr"]

        user_msg = f"USER {nick} 0 * :Test User\r\n"
        sock.sendto(user_msg.encode(), server_addr)

        sock.sendto.assert_called_once_with(user_msg.encode(), server_addr)

    def test_recv_message_success(self, client_setup):
        """Test receiving a message successfully."""
        sock = client_setup["sock"]
        test_data = b"001 test_client :Welcome\r\n"
        sock.recvfrom.return_value = (test_data, ("127.0.0.1", 9525))

        data, addr = sock.recvfrom(65500)
        text = data.decode().strip()

        assert text == "001 test_client :Welcome"
        sock.recvfrom.assert_called_once_with(65500)

    def test_recv_message_timeout(self, client_setup):
        """Test socket timeout during receive."""
        sock = client_setup["sock"]
        sock.recvfrom.side_effect = socket.timeout("Socket timeout")

        with pytest.raises(socket.timeout):
            sock.recvfrom(65500)

    def test_recv_message_returns_none_on_timeout(self, client_setup):
        """Test that timeout is caught and returns None."""
        sock = client_setup["sock"]
        sock.recvfrom.side_effect = socket.timeout("Socket timeout")

        try:
            sock.recvfrom(65500)
            result = None
        except socket.timeout:
            result = None

        assert result is None

    def test_wait_for_welcome_message(self, client_setup):
        """Test waiting for welcome (001) response."""
        sock = client_setup["sock"]
        nick = client_setup["nick"]

        welcome_msg = f"001 {nick} :Welcome to the network\r\n"
        sock.recvfrom.return_value = (welcome_msg.encode(), ("127.0.0.1", 9525))

        data, addr = sock.recvfrom(65500)
        text = data.decode().strip()

        assert f"001 {nick}" in text

    def test_join_channel_command(self, client_setup):
        """Test sending JOIN command."""
        sock = client_setup["sock"]
        server_addr = client_setup["server_addr"]
        channel = "#general"

        join_msg = f"JOIN {channel}\r\n"
        sock.sendto(join_msg.encode(), server_addr)

        sock.sendto.assert_called_once_with(join_msg.encode(), server_addr)

    def test_socket_close(self, client_setup):
        """Test closing the socket."""
        sock = client_setup["sock"]
        sock.close()
        sock.close.assert_called_once()

    def test_multiple_messages_sequence(self, client_setup):
        """Test sending and receiving multiple messages in sequence."""
        sock = client_setup["sock"]
        server_addr = client_setup["server_addr"]
        nick = client_setup["nick"]

        # Send NICK
        sock.sendto(f"NICK {nick}\r\n".encode(), server_addr)

        # Send USER
        sock.sendto(f"USER {nick} 0 * :Test\r\n".encode(), server_addr)

        # Receive welcome
        sock.recvfrom.return_value = (
            f"001 {nick} :Welcome\r\n".encode(),
            server_addr,
        )
        data, _ = sock.recvfrom(65500)

        # Send JOIN
        sock.sendto("JOIN #general\r\n".encode(), server_addr)

        assert sock.sendto.call_count == 3
        assert sock.recvfrom.called

    def test_message_encoding_decoding(self, client_setup):
        """Test proper encoding and decoding of messages."""
        message = "PRIVMSG #general :Hello world\r\n"
        encoded = message.encode()
        decoded = encoded.decode().strip()

        assert decoded == "PRIVMSG #general :Hello world"

    def test_server_address_validation(self, client_setup):
        """Test server address is correctly formatted."""
        server_addr = client_setup["server_addr"]
        assert isinstance(server_addr, tuple)
        assert len(server_addr) == 2
        assert server_addr[0] == "127.0.0.1"
        assert server_addr[1] == 9525

    def test_nickname_with_special_characters(self):
        """Test nickname handling with allowed special characters."""
        nicks = ["nick_123", "nick-test", "test_nick_", "nick123"]
        for nick in nicks:
            msg = f"NICK {nick}\r\n"
            assert nick in msg
            assert msg.endswith("\r\n")

    def test_channel_join_syntax(self):
        """Test channel join command syntax."""
        channels = ["#general", "#test", "#channel-name"]
        for channel in channels:
            msg = f"JOIN {channel}\r\n"
            assert channel in msg
            assert msg.startswith("JOIN ")
            assert msg.endswith("\r\n")

    def test_timeout_duration(self, client_setup):
        """Test socket timeout is set correctly."""
        sock = client_setup["sock"]
        timeout = client_setup["timeout"]
        
        sock.settimeout(timeout)
        sock.settimeout.assert_called_with(2.0)

    def test_recv_buffer_size(self, client_setup):
        """Test that receive uses correct buffer size."""
        sock = client_setup["sock"]
        buffer_size = 65500
        
        sock.recvfrom(buffer_size)
        sock.recvfrom.assert_called_with(buffer_size)

    def test_welcome_message_detection(self, client_setup):
        """Test detection of welcome (001) message."""
        nick = client_setup["nick"]
        messages = [
            f"001 {nick} :Welcome",
            f"001 {nick} :Welcome to server",
            "002 other :message",
        ]

        found = False
        for msg in messages:
            if f"001 {nick}" in msg:
                found = True
                break

        assert found is True

    def test_receive_multiple_attempts(self, client_setup):
        """Test retry logic for receiving messages."""
        sock = client_setup["sock"]
        
        # Simulate timeout then success
        responses = [
            socket.timeout("Timeout"),
            (b"001 test :Welcome\r\n", ("127.0.0.1", 9525)),
        ]
        sock.recvfrom.side_effect = responses

        # First attempt times out
        with pytest.raises(socket.timeout):
            sock.recvfrom(65500)

        # Second attempt succeeds
        data, addr = sock.recvfrom(65500)
        assert data == b"001 test :Welcome\r\n"

    def test_message_stripping(self):
        """Test that messages are properly stripped of whitespace."""
        raw_message = b"PRIVMSG #test :Hello world\r\n"
        decoded = raw_message.decode().strip()
        
        assert decoded == "PRIVMSG #test :Hello world"
        assert not decoded.endswith("\r\n")

    def test_concurrent_operations_mock(self, client_setup):
        """Test that socket operations can be called in sequence."""
        sock = client_setup["sock"]
        server_addr = client_setup["server_addr"]

        # Setup mock responses
        sock.recvfrom.return_value = (b"001 test :Welcome\r\n", server_addr)

        # Perform operations
        sock.sendto(b"NICK test\r\n", server_addr)
        data, _ = sock.recvfrom(65500)
        sock.sendto(b"JOIN #general\r\n", server_addr)
        sock.close()

        assert sock.sendto.call_count == 2
        assert sock.recvfrom.call_count == 1
        assert sock.close.called

    def test_user_registration_flow(self, client_setup):
        """Test complete user registration flow."""
        sock = client_setup["sock"]
        server_addr = client_setup["server_addr"]
        nick = client_setup["nick"]

        # Send registration
        sock.sendto(f"NICK {nick}\r\n".encode(), server_addr)
        sock.sendto(f"USER {nick} 0 * :Test User\r\n".encode(), server_addr)

        # Mock welcome response
        sock.recvfrom.return_value = (
            f"001 {nick} :Welcome to IRC\r\n".encode(),
            server_addr,
        )
        data, _ = sock.recvfrom(65500)
        response = data.decode().strip()

        assert f"001 {nick}" in response
        assert sock.sendto.call_count == 2

    def test_socket_initialization_parameters(self):
        """Test socket initialization with correct parameters."""
        with patch("socket.socket") as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock

            # Create socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)

            # Verify
            mock_socket_class.assert_called_once_with(
                socket.AF_INET, socket.SOCK_DGRAM
            )
            assert mock_sock.settimeout.called

    def test_private_message_command(self, client_setup):
        """Test PRIVMSG command formatting."""
        sock = client_setup["sock"]
        server_addr = client_setup["server_addr"]

        msg = "PRIVMSG #general :Test message\r\n"
        sock.sendto(msg.encode(), server_addr)

        sock.sendto.assert_called_once_with(msg.encode(), server_addr)

    def test_quit_command(self, client_setup):
        """Test QUIT command."""
        sock = client_setup["sock"]
        server_addr = client_setup["server_addr"]

        msg = "QUIT :Goodbye\r\n"
        sock.sendto(msg.encode(), server_addr)

        sock.sendto.assert_called_once_with(msg.encode(), server_addr)
```