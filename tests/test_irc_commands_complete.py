```python
#!/usr/bin/env python3
"""Pytest test file for IRC commands - WHOIS, WHO, NAMES, WHOWAS."""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import socket
import time


class TestIRCCommands:
    """Test IRC user query commands."""

    @pytest.fixture
    def mock_socket(self):
        """Create a mock socket for testing."""
        with patch('socket.socket') as mock_sock_class:
            mock_sock = MagicMock()
            mock_sock_class.return_value = mock_sock
            yield mock_sock

    @pytest.fixture
    def irc_client(self, mock_socket):
        """Create a simple IRC client for testing."""
        class IRCClient:
            def __init__(self):
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.settimeout(2)
                self.server_addr = ('127.0.0.1', 9525)
                self.nickname = None
                self.joined_channels = []
                self.user_cache = {}
                self.whowas_cache = []

            def send_command(self, command):
                """Send a raw IRC command."""
                self.sock.sendto((command + "\r\n").encode(), self.server_addr)

            def recv_response(self):
                """Receive a response from server."""
                try:
                    data, _ = self.sock.recvfrom(4096)
                    return data.decode('utf-8', errors='ignore')
                except socket.timeout:
                    return None

            def register(self, nickname, username, realname):
                """Register with server."""
                self.nickname = nickname
                self.send_command(f"NICK {nickname}")
                self.send_command(f"USER {username} 0 * :{realname}")

            def join_channel(self, channel):
                """Join a channel."""
                self.send_command(f"JOIN {channel}")
                if channel not in self.joined_channels:
                    self.joined_channels.append(channel)

            def names(self, channel):
                """Query NAMES for a channel."""
                self.send_command(f"NAMES {channel}")

            def who(self, target):
                """Query WHO for target."""
                self.send_command(f"WHO {target}")

            def whois(self, target):
                """Query WHOIS for target."""
                self.send_command(f"WHOIS {target}")

            def whowas(self, target):
                """Query WHOWAS for target."""
                self.send_command(f"WHOWAS {target}")

            def quit(self, message=""):
                """Disconnect from server."""
                self.send_command(f"QUIT :{message}")

        return IRCClient()

    def test_register_user(self, irc_client, mock_socket):
        """Test user registration with NICK and USER."""
        mock_socket.recvfrom.return_value = (
            b":server 001 TestUser :Welcome to IRC\r\n",
            ('127.0.0.1', 9525)
        )

        irc_client.register("TestUser", "testuser", "Test User Real Name")

        assert irc_client.nickname == "TestUser"
        mock_socket.sendto.assert_any_call(
            b"NICK TestUser\r\n",
            ('127.0.0.1', 9525)
        )
        mock_socket.sendto.assert_any_call(
            b"USER testuser 0 * :Test User Real Name\r\n",
            ('127.0.0.1', 9525)
        )

    def test_join_channel(self, irc_client, mock_socket):
        """Test joining a channel."""
        irc_client.nickname = "TestUser"
        irc_client.join_channel("#general")

        assert "#general" in irc_client.joined_channels
        mock_socket.sendto.assert_called_with(
            b"JOIN #general\r\n",
            ('127.0.0.1', 9525)
        )

    def test_names_command(self, irc_client, mock_socket):
        """Test NAMES command for channel."""
        mock_socket.recvfrom.return_value = (
            b":server 353 TestUser = #general :TestUser @Claude Gemini\r\n",
            ('127.0.0.1', 9525)
        )
        irc_client.nickname = "TestUser"

        irc_client.names("#general")
        response = irc_client.recv_response()

        assert response is not None
        assert "353" in response
        assert "#general" in response
        mock_socket.sendto.assert_called_with(
            b"NAMES #general\r\n",
            ('127.0.0.1', 9525)
        )

    def test_who_command(self, irc_client, mock_socket):
        """Test WHO command for channel."""
        mock_socket.recvfrom.return_value = (
            b":server 352 TestUser #general testuser 127.0.0.1 server TestUser H :0 Test User Real Name\r\n",
            ('127.0.0.1', 9525)
        )
        irc_client.nickname = "TestUser"

        irc_client.who("#general")
        response = irc_client.recv_response()

        assert response is not None
        assert "352" in response
        assert "TestUser" in response
        mock_socket.sendto.assert_called_with(
            b"WHO #general\r\n",
            ('127.0.0.1', 9525)
        )

    def test_whois_online_user(self, irc_client, mock_socket):
        """Test WHOIS command for online user."""
        responses = [
            b":server 311 TestUser Claude claude 127.0.0.1 * :Claude Bot\r\n",
            b":server 312 TestUser Claude server.example.com :Test Server\r\n",
            b":server 318 TestUser Claude :End of WHOIS\r\n",
        ]
        mock_socket.recvfrom.side_effect = [(resp, ('127.0.0.1', 9525)) for resp in responses]
        irc_client.nickname = "TestUser"

        irc_client.whois("Claude")
        response1 = irc_client.recv_response()
        response2 = irc_client.recv_response()
        response3 = irc_client.recv_response()

        assert response1 is not None
        assert "311" in response1
        assert "Claude" in response1
        assert response3 is not None
        assert "318" in response3
        mock_socket.sendto.assert_called_with(
            b"WHOIS Claude\r\n",
            ('127.0.0.1', 9525)
        )

    def test_whois_nonexistent_user(self, irc_client, mock_socket):
        """Test WHOIS command for non-existent user."""
        mock_socket.recvfrom.return_value = (
            b":server 401 TestUser NonExistent :No such nick/channel\r\n",
            ('127.0.0.1', 9525)
        )
        irc_client.nickname = "TestUser"

        irc_client.whois("NonExistent")
        response = irc_client.recv_response()

        assert response is not None
        assert "401" in response
        assert "ERR_NOSUCHNICK" in response or "No such nick" in response

    def test_whowas_disconnected_user(self, irc_client, mock_socket):
        """Test WHOWAS command for previously connected user."""
        responses = [
            b":server 314 TestUser2 TestUser testuser 127.0.0.1 * :Test User Real Name\r\n",
            b":server 369 TestUser2 TestUser :End of WHOWAS\r\n",
        ]
        mock_socket.recvfrom.side_effect = [(resp, ('127.0.0.1', 9525)) for resp in responses]
        irc_client.nickname = "TestUser2"

        irc_client.whowas("TestUser")
        response1 = irc_client.recv_response()
        response2 = irc_client.recv_response()

        assert response1 is not None
        assert "314" in response1
        assert "TestUser" in response1
        assert response2 is not None
        assert "369" in response2
        mock_socket.sendto.assert_called_with(
            b"WHOWAS TestUser\r\n",
            ('127.0.0.1', 9525)
        )

    def test_whowas_never_existed_user(self, irc_client, mock_socket):
        """Test WHOWAS command for never-existed user."""
        mock_socket.recvfrom.return_value = (
            b":server 406 TestUser NeverExisted :There was no such nickname\r\n",
            ('127.0.0.1', 9525)
        )
        irc_client.nickname = "TestUser"

        irc_client.whowas("NeverExisted")
        response = irc_client.recv_response()

        assert response is not None
        assert "406" in response
        assert "ERR_WASNOSUCHNICK" in response or "no such nickname" in response

    def test_quit_command(self, irc_client, mock_socket):
        """Test QUIT command."""
        irc_client.nickname = "TestUser"
        irc_client.quit("Testing complete")

        mock_socket.sendto.assert_called_with(
            b"QUIT :Testing complete\r\n",
            ('127.0.0.1', 9525)
        )

    def test_socket_timeout_handling(self, irc_client, mock_socket):
        """Test handling of socket timeout."""
        mock_socket.recvfrom.side_effect = socket.timeout()
        irc_client.nickname = "TestUser"

        response = irc_client.recv_response()

        assert response is None

    def test_multiple_responses_parsing(self, irc_client, mock_socket):
        """Test parsing multiple IRC responses."""
        responses = [
            b":server 353 TestUser = #general :TestUser @Claude Gemini\r\n",
            b":server 366 TestUser #general :End of NAMES\r\n",
        ]
        mock_socket.recvfrom.side_effect = [(resp, ('127.0.0.1', 9525)) for resp in responses]
        irc_client.nickname = "TestUser"

        response_list = []
        for _ in range(2):
            resp = irc_client.recv_response()
            if resp:
                response_list.append(resp)

        assert len(response_list) == 2
        assert "353" in response_list[0]
        assert "366" in response_list[1]

    def test_channel_list_tracking(self, irc_client):
        """Test tracking of joined channels."""
        irc_client.nickname = "TestUser"

        irc_client.join_channel("#general")
        irc_client.join_channel("#test")
        irc_client.join_channel("#general")  # Join again

        assert "#general" in irc_client.joined_channels
        assert "#test" in irc_client.joined_channels
        assert len(irc_client.joined_channels) == 2

    def test_whois_multiple_users(self, mock_socket):
        """Test WHOIS queries for multiple users."""
        with patch('socket.socket') as mock_sock_class:
            mock_sock = MagicMock()
            mock_sock_class.return_value = mock_sock

            class SimpleClient:
                def __init__(self):
                    self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    self.server_addr = ('127.0.0.1', 9525)

                def whois(self, target):
                    self.sock.sendto(f"WHOIS {target}\r\n".encode(), self.server_addr)

            client = SimpleClient()
            targets = ["Claude", "Gemini", "TestBot"]

            for target in targets:
                client.whois(target)

            assert mock_sock.sendto.call_count >= 3

    def test_names_response_parsing(self, irc_client, mock_socket):
        """Test parsing NAMES response with multiple users."""
        names_data = b":server 353 TestUser = #general :TestUser @Claude +Gemini GPT4\r\n"
        mock_socket.recvfrom.return_value = (names_data, ('127.0.0.1', 9525))
        irc_client.nickname = "TestUser"

        irc_client.names("#general")
        response = irc_client.recv_response()

        assert "TestUser" in response
        assert "Claude" in response
        assert "Gemini" in response
        assert "GPT4" in response
        assert "@" in response  # Channel operator marker
        assert "+" in response  # Voice marker

    def test_who_response_parsing(self, irc_client, mock_socket):
        """Test parsing WHO response with user details."""
        who_data = b":server 352 TestUser #general testuser 127.0.0.1 server TestUser H@+ :0 Test User\r\n"
        mock_socket.recvfrom.return_value = (who_data, ('127.0.0.1', 9525))
        irc_client.nickname = "TestUser"

        irc_client.who("#general")
        response = irc_client.recv_response()

        assert "352" in response
        assert "testuser" in response
        assert "127.0.0.1" in response
        assert "H@+" in response  # Mode flags

    def test_unicode_handling_in_responses(self, irc_client, mock_socket):
        """Test handling of unicode in IRC responses."""
        unicode_data = ":server 311 TestUser User user 127.0.0.1 * :User with émojis 🎉\r\n".encode('utf-8')
        mock_socket.recvfrom.return_value = (unicode_data, ('127.0.0.1', 9525))
        irc_client.nickname = "TestUser"

        irc_client.whois("User")
        response = irc_client.recv_response()

        assert response is not None
        assert "User" in response or "311" in response

    def test_sequential_commands(self, irc_client, mock_socket):
        """Test sending multiple commands in sequence."""
        responses = [
            b":server 001 TestUser :Welcome\r\n",
            b":server 366 TestUser #general :End of NAMES\r\n",
            b":server 315 TestUser #general :End of WHO\r\n",
        ]
        mock_socket.recvfrom.side_effect = [(resp, ('127.0.0.1', 9525)) for resp in responses]
        irc_client.nickname = "TestUser"

        irc_client.names("#general")
        resp1 = irc_client.recv_response()

        irc_client.who("#general")
        resp2 = irc_client.recv_response()

        irc_client.quit()
        resp3 = irc_client.recv_response()

        assert resp1 is not None
        assert resp2 is not None
        assert resp3 is not None

    def test_empty_response_handling(self, irc_client, mock_socket):
        """Test handling of empty responses."""
        mock_socket.recvfrom.return_value = (b"", ('127.0.0.1', 9525))
        irc_client.nickname = "TestUser"

        response = irc_client.recv_response()

        assert response == ""

    def test_server_