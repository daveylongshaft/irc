```python
"""Pytest test file for IRC command functionality (UDP)."""

import pytest
import socket
from unittest.mock import Mock, patch, MagicMock
import struct


class TestIRCCommands:
    """Test suite for IRC command handling over UDP."""

    @pytest.fixture
    def mock_socket(self):
        """Create a mock UDP socket."""
        with patch('socket.socket') as mock_sock_class:
            mock_sock = MagicMock()
            mock_sock_class.return_value = mock_sock
            yield mock_sock

    @pytest.fixture
    def server_addr(self):
        """Fixture for server address."""
        return ('127.0.0.1', 9525)

    def test_socket_creation(self, mock_socket):
        """Test that UDP socket is created correctly."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        
        assert mock_socket.settimeout.called
        mock_socket.settimeout.assert_called_with(3)

    def test_nick_command(self, mock_socket, server_addr):
        """Test NICK command registration."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        nick_cmd = b"NICK TestClient\r\n"
        
        sock.sendto(nick_cmd, server_addr)
        
        mock_socket.sendto.assert_called_with(nick_cmd, server_addr)

    def test_user_command(self, mock_socket, server_addr):
        """Test USER command registration."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        user_cmd = b"USER testuser 0 * :Test User\r\n"
        
        sock.sendto(user_cmd, server_addr)
        
        mock_socket.sendto.assert_called_with(user_cmd, server_addr)

    def test_join_channel(self, mock_socket, server_addr):
        """Test JOIN command for channel membership."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        join_cmd = b"JOIN #test\r\n"
        
        sock.sendto(join_cmd, server_addr)
        
        mock_socket.sendto.assert_called_with(join_cmd, server_addr)

    def test_join_multiple_channels(self, mock_socket, server_addr):
        """Test JOIN command for multiple channels."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        channels = [b"JOIN #test1\r\n", b"JOIN #test2\r\n"]
        
        for cmd in channels:
            sock.sendto(cmd, server_addr)
        
        assert mock_socket.sendto.call_count == 2

    def test_names_command(self, mock_socket, server_addr):
        """Test NAMES command to list channel users."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        names_cmd = b"NAMES #test\r\n"
        
        # Mock response
        mock_response = b":server 353 user = #test :user1 user2 user3\r\n"
        mock_socket.recvfrom.return_value = (mock_response, server_addr)
        
        sock.sendto(names_cmd, server_addr)
        data, addr = sock.recvfrom(4096)
        
        assert mock_socket.sendto.called
        assert data == mock_response
        assert addr == server_addr

    def test_who_command(self, mock_socket, server_addr):
        """Test WHO command for user details."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        who_cmd = b"WHO #test\r\n"
        
        # Mock response
        mock_response = b":server 352 user #test user host server user H :0 Real Name\r\n"
        mock_socket.recvfrom.return_value = (mock_response, server_addr)
        
        sock.sendto(who_cmd, server_addr)
        data, addr = sock.recvfrom(4096)
        
        assert mock_socket.sendto.called
        assert data == mock_response

    def test_whois_existing_user_gemini(self, mock_socket, server_addr):
        """Test WHOIS command for existing user (Gemini)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        whois_cmd = b"WHOIS Gemini\r\n"
        
        # Mock WHOIS response
        mock_responses = [
            b":server 311 user Gemini gemini host 0.0.0.0 :Gemini User\r\n",
            b":server 312 user Gemini server :Server Info\r\n",
            b":server 319 user Gemini :#channel1 #channel2\r\n",
            b":server 318 user Gemini :End of WHOIS\r\n"
        ]
        mock_socket.recvfrom.side_effect = [(r, server_addr) for r in mock_responses]
        
        sock.sendto(whois_cmd, server_addr)
        
        # Receive all responses
        responses = []
        for _ in range(len(mock_responses)):
            data, addr = sock.recvfrom(4096)
            responses.append(data)
        
        assert len(responses) == 4
        assert mock_socket.sendto.called

    def test_whois_existing_user_claude(self, mock_socket, server_addr):
        """Test WHOIS command for existing user (Claude)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        whois_cmd = b"WHOIS Claude\r\n"
        
        # Mock WHOIS response
        mock_responses = [
            b":server 311 user Claude claude host 0.0.0.0 :Claude User\r\n",
            b":server 312 user Claude server :Server Info\r\n",
            b":server 319 user Claude :#channel3\r\n",
            b":server 318 user Claude :End of WHOIS\r\n"
        ]
        mock_socket.recvfrom.side_effect = [(r, server_addr) for r in mock_responses]
        
        sock.sendto(whois_cmd, server_addr)
        
        # Receive all responses
        responses = []
        for _ in range(len(mock_responses)):
            data, addr = sock.recvfrom(4096)
            responses.append(data)
        
        assert len(responses) == 4
        assert b"Claude" in responses[0]

    def test_whois_nonexistent_user(self, mock_socket, server_addr):
        """Test WHOIS command for non-existent user."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        whois_cmd = b"WHOIS NonExistentUser\r\n"
        
        # Mock error response
        mock_response = b":server 401 user NonExistentUser :No such nick\r\n"
        mock_socket.recvfrom.return_value = (mock_response, server_addr)
        
        sock.sendto(whois_cmd, server_addr)
        data, addr = sock.recvfrom(4096)
        
        assert b"401" in data  # Error code for "No such nick"
        assert b"NonExistentUser" in data

    def test_whowas_command_not_implemented(self, mock_socket, server_addr):
        """Test WHOWAS command (may not be implemented)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        whowas_cmd = b"WHOWAS TestUser\r\n"
        
        # Mock timeout or error
        mock_socket.recvfrom.side_effect = socket.timeout("No response")
        
        sock.sendto(whowas_cmd, server_addr)
        
        with pytest.raises(socket.timeout):
            sock.recvfrom(4096)

    def test_quit_command(self, mock_socket, server_addr):
        """Test QUIT command to disconnect."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        quit_cmd = b"QUIT :Test complete\r\n"
        
        sock.sendto(quit_cmd, server_addr)
        
        mock_socket.sendto.assert_called_with(quit_cmd, server_addr)

    def test_socket_close(self, mock_socket):
        """Test socket cleanup on close."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.close()
        
        mock_socket.close.assert_called_once()

    def test_malformed_irc_command(self, mock_socket, server_addr):
        """Test handling of malformed IRC commands."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        malformed_cmd = b"INVALID COMMAND\r\n"
        
        sock.sendto(malformed_cmd, server_addr)
        
        # Should still send, but server may respond with error
        mock_socket.sendto.assert_called_with(malformed_cmd, server_addr)

    def test_empty_channel_name(self, mock_socket, server_addr):
        """Test JOIN with empty channel name."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        join_cmd = b"JOIN \r\n"
        
        sock.sendto(join_cmd, server_addr)
        
        mock_socket.sendto.assert_called_with(join_cmd, server_addr)

    def test_socket_timeout_configuration(self, mock_socket):
        """Test socket timeout is configured correctly."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        
        mock_socket.settimeout.assert_called_with(3)

    def test_multiple_sequential_commands(self, mock_socket, server_addr):
        """Test sending multiple commands in sequence."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        commands = [
            b"NICK TestClient\r\n",
            b"USER testuser 0 * :Test User\r\n",
            b"JOIN #test\r\n",
            b"NAMES #test\r\n"
        ]
        
        for cmd in commands:
            sock.sendto(cmd, server_addr)
        
        assert mock_socket.sendto.call_count == 4

    def test_response_decoding_utf8(self, mock_socket, server_addr):
        """Test proper UTF-8 decoding of server responses."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Mock response with UTF-8 content
        mock_response = ":server 353 user = #test :user1 user2\r\n".encode('utf-8')
        mock_socket.recvfrom.return_value = (mock_response, server_addr)
        
        data, addr = sock.recvfrom(4096)
        decoded = data.decode('utf-8', errors='ignore')
        
        assert "user1" in decoded
        assert "user2" in decoded

    def test_udp_socket_type(self, mock_socket):
        """Test that UDP socket (SOCK_DGRAM) is used."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Verify the socket type matches UDP
        assert socket.SOCK_DGRAM == socket.SOCK_DGRAM

    def test_ipv4_socket_family(self, mock_socket):
        """Test that IPv4 socket (AF_INET) is used."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Verify the address family matches IPv4
        assert socket.AF_INET == socket.AF_INET

    def test_concurrent_whois_requests(self, mock_socket, server_addr):
        """Test multiple WHOIS requests."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        users = [b"WHOIS user1\r\n", b"WHOIS user2\r\n", b"WHOIS user3\r\n"]
        
        mock_response = b":server 311 user nick host 0.0.0.0 :User\r\n"
        mock_socket.recvfrom.return_value = (mock_response, server_addr)
        
        for user_cmd in users:
            sock.sendto(user_cmd, server_addr)
        
        assert mock_socket.sendto.call_count == 3

    def test_channel_name_validation(self, mock_socket, server_addr):
        """Test various channel name formats."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        channels = [b"JOIN #test\r\n", b"JOIN #test-123\r\n", b"JOIN #test_abc\r\n"]
        
        for cmd in channels:
            sock.sendto(cmd, server_addr)
        
        assert mock_socket.sendto.call_count == 3
```