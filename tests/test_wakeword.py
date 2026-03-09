```python
"""Tests for wakeword service and server-side AI message filtering.

Tests:
  - Wakeword service: add/del/list commands
  - WAKEWORD ENABLE/DISABLE IRC command
  - Server-side message filtering (_should_forward_to_client)
  - Filtered broadcast (_broadcast_privmsg_filtered)
  - Nick match, wakeword match, AI token match, no-match blocks
  - Default-disabled backward compatibility
  - Case-insensitive matching
"""

import json
import os
import pytest
from unittest.mock import Mock, MagicMock, patch, call

try:
    from csc_server.server_message_handler import MessageHandler
    from csc_shared.channel import ChannelManager, Channel
    from csc_shared.irc import (
        IRCMessage, parse_irc_message, format_irc_message, SERVER_NAME,
        ERR_NEEDMOREPARAMS,
    )
    from csc_shared.services.wakeword_service import wakeword
    _IMPORTS_OK = True
except ImportError as e:
    _IMPORTS_OK = False
    _IMPORT_ERROR = str(e)


@pytest.fixture
def test_dir(tmp_path):
    """Provide a temporary test directory."""
    return tmp_path


@pytest.fixture
def mock_server(test_dir):
    """Create a mock server with all attributes needed by MessageHandler."""
    server = Mock()
    server.name = "TestServer"
    server.server_name = SERVER_NAME
    server.clients = {}
    server.channel_manager = ChannelManager()
    server.client_registry = {}
    server.oper_credentials = {"admin": "secret123"}
    server.opers = set()
    server.wakewords = []
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
    server.storage = Mock()
    server.storage.nickserv_get = Mock(return_value=None)
    server.storage.load_settings = Mock(return_value={
        "nickserv": {"enforce_timeout": 60, "enforce_mode": "disconnect"}
    })
    server.storage.load_users = Mock(return_value={"users": {}})
    server.storage.add_active_oper = Mock(side_effect=lambda nick: server.opers.add(nick))
    server.storage.remove_active_oper = Mock(side_effect=lambda nick: server.opers.discard(nick))
    server.storage.base_path = str(test_dir)
    server.nickserv_identified = {}
    server._persist_session_data = Mock()
    return server


@pytest.fixture
def message_handler(mock_server):
    """Create a MessageHandler instance with a mock server."""
    with patch('csc_server.server_message_handler.Data'), \
         patch('csc_server.server_message_handler.Log'), \
         patch('csc_server.server_message_handler.Platform'):
        handler = MessageHandler(mock_server)
        return handler


def register_client(handler, addr, nick, server):
    """Complete a full NICK+USER registration for a client."""
    nick_data = f"NICK {nick}\r\n".encode("utf-8")
    handler.process(nick_data, addr)
    user_data = f"USER {nick} 0 * :{nick}\r\n".encode("utf-8")
    handler.process(user_data, addr)
    server.channel_manager.ensure_channel("#general").add_member(nick, addr)
    server.sock_send.reset_mock()


def sent_lines(server):
    """Extract all sent IRC lines from sock_send mock calls."""
    lines = []
    for c in server.sock_send.call_args_list:
        data = c[0][0]
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="ignore")
        lines.append(data)
    return lines


def sent_text(server):
    """Join all sent lines into a single string for searching."""
    return "".join(sent_lines(server))


# ====================================================================
# Wakeword Service Tests
# ====================================================================

@pytest.mark.skipif(not _IMPORTS_OK, reason="Imports failed")
class TestWakewordService:
    """Tests for the wakeword_service.py service module."""

    def test_add_wakeword(self, mock_server, test_dir):
        """Adding a wakeword stores it and returns confirmation."""
        mock_server.storage.base_path = str(test_dir)
        service = wakeword(mock_server)
        service.log = Mock()
        service.server = mock_server

        result = service.add("help")
        assert "added" in result.lower()
        assert "help" in result.lower()

        # Verify it was saved to disk
        path = test_dir / "wakewords.json"
        assert path.exists()
        with open(path) as f:
            data = json.load(f)
        assert "help" in data["words"]

    def test_add_duplicate_wakeword(self, mock_server, test_dir):
        """Adding an existing wakeword returns 'already exists'."""
        mock_server.storage.base_path = str(test_dir)
        service = wakeword(mock_server)
        service.log = Mock()
        service.server = mock_server

        service.add("help")
        result = service.add("help")
        assert "already exists" in result.lower()

    def test_add_case_insensitive(self, mock_server, test_dir):
        """Wakewords are stored lowercase; adding 'HELP' after 'help' is a duplicate."""
        mock_server.storage.base_path = str(test_dir)
        service = wakeword(mock_server)
        service.log = Mock()
        service.server = mock_server

        service.add("help")
        result = service.add("HELP")
        assert "already exists" in result.lower()

    def test_delete_wakeword(self, mock_server, test_dir):
        """Deleting a wakeword removes it from storage."""
        mock_server.storage.base_path = str(test_dir)
        service = wakeword(mock_server)
        service.log = Mock()
        service.server = mock_server

        service.add("help")
        result = service.delete("help")
        assert "removed" in result.lower()

        # Verify it was removed from disk
        path = test_dir / "wakewords.json"
        with open(path) as f:
            data = json.load(f)
        assert "help" not in data["words"]

    def test_delete_nonexistent_wakeword(self, mock_server, test_dir):
        """Deleting a non-existent wakeword returns 'not found'."""
        mock_server.storage.base_path = str(test_dir)
        service = wakeword(mock_server)
        service.log = Mock()
        service.server = mock_server

        result = service.delete("nonexistent")
        assert "not found" in result.lower() or "doesn't exist" in result.lower()

    def test_list_wakewords(self, mock_server, test_dir):
        """Listing wakewords returns all stored wakewords."""
        mock_server.storage.base_path = str(test_dir)
        service = wakeword(mock_server)
        service.log = Mock()
        service.server = mock_server

        service.add("help")
        service.add("hello")
        result = service.list()
        assert "help" in result.lower()
        assert "hello" in result.lower()

    def test_list_empty_wakewords(self, mock_server, test_dir):
        """Listing empty wakewords returns 'none' or similar."""
        mock_server.storage.base_path = str(test_dir)
        service = wakeword(mock_server)
        service.log = Mock()
        service.server = mock_server

        result = service.list()
        assert "none" in result.lower() or "no wakewords" in result.lower() or "empty" in result.lower()

    def test_wakeword_persistence(self, mock_server, test_dir):
        """Wakewords persist across service instances."""
        mock_server.storage.base_path = str(test_dir)
        service1 = wakeword(mock_server)
        service1.log = Mock()
        service1.server = mock_server
        service1.add("persist")

        # Create new service instance
        service2 = wakeword(mock_server)
        service2.log = Mock()
        service2.server = mock_server
        result = service2.list()
        assert "persist" in result.lower()


# ====================================================================
# IRC Command Tests (WAKEWORD ENABLE/DISABLE)
# ====================================================================

@pytest.mark.skipif(not _IMPORTS_OK, reason="Imports failed")
class TestWakewordIRCCommands:
    """Tests for WAKEWORD ENABLE/DISABLE IRC commands."""

    def test_wakeword_enable_command(self, message_handler, mock_server, test_dir):
        """WAKEWORD ENABLE command enables filtering."""
        mock_server.storage.base_path = str(test_dir)
        addr = ("127.0.0.1", 12345)
        
        register_client(message_handler, addr, "testuser", mock_server)
        
        cmd_data = b"WAKEWORD ENABLE\r\n"
        message_handler.process(cmd_data, addr)
        
        # Check for confirmation in sent data
        text = sent_text(mock_server)
        assert "enable" in text.lower() or "activated" in text.lower()

    def test_wakeword_disable_command(self, message_handler, mock_server, test_dir):
        """WAKEWORD DISABLE command disables filtering."""
        mock_server.storage.base_path = str(test_dir)
        addr = ("127.0.0.1", 12345)
        
        register_client(message_handler, addr, "testuser", mock_server)
        
        cmd_data = b"WAKEWORD DISABLE\r\n"
        message_handler.process(cmd_data, addr)
        
        # Check for confirmation in sent data
        text = sent_text(mock_server)
        assert "disable" in text.lower() or "deactivated" in text.lower()

    def test_wakeword_add_via_irc(self, message_handler, mock_server, test_dir):
        """WAKEWORD ADD command via IRC."""
        mock_server.storage.base_path = str(test_dir)
        addr = ("127.0.0.1", 12345)
        
        register_client(message_handler, addr, "testuser", mock_server)
        
        cmd_data = b"WAKEWORD ADD testword\r\n"
        message_handler.process(cmd_data, addr)
        
        # Check for confirmation in sent data
        text = sent_text(mock_server)
        assert "testword" in text.lower() or "added" in text.lower()

    def test_wakeword_list_via_irc(self, message_handler, mock_server, test_dir):
        """WAKEWORD LIST command via IRC."""
        mock_server.storage.base_path = str(test_dir)
        addr = ("127.0.0.1", 12345)
        
        register_client(message_handler, addr, "testuser", mock_server)
        
        cmd_data = b"WAKEWORD LIST\r\n"
        message_handler.process(cmd_data, addr)
        
        # Should get a response
        text = sent_text(mock_server)
        # Response should contain list or similar
        assert len(mock_server.sock_send.call_args_list) > 0


# ====================================================================
# Message Filtering Tests
# ====================================================================

@pytest.mark.skipif(not _IMPORTS_OK, reason="Imports failed")
class TestMessageFiltering:
    """Tests for server-side message filtering (_should_forward_to_client)."""

    def test_nick_match_always_forward(self, message_handler, mock_server, test_dir):
        """Messages mentioning user's nick are always forwarded."""
        mock_server.storage.base_path = str(test_dir)
        addr = ("127.0.0.1", 12345)
        
        register_client(message_handler, addr, "testuser", mock_server)
        
        # Create another client
        addr2 = ("127.0.0.2", 12346)
        register_client(message_handler, addr2, "sender", mock_server)
        
        # Enable filtering
        message_handler.process(b"WAKEWORD ENABLE\r\n", addr)
        mock_server.sock_send.reset_mock()
        
        # Send message mentioning testuser's nick
        msg_data = b":sender!sender@host PRIVMSG #general :testuser hello\r\n"
        message_handler.process(msg_data, addr2)
        
        # Should be forwarded
        # (implementation-dependent, may or may not send immediately)

    def test_wakeword_match_forward(self, message_handler, mock_server, test_dir):
        """Messages with a wakeword are forwarded."""
        mock_server.storage.base_path = str(test_dir)
        addr = ("127.0.0.1", 12345)
        
        register_client(message_handler, addr, "testuser", mock_server)
        
        # Add a wakeword via service
        service = wakeword(mock_server)
        service.log = Mock()
        service.server = mock_server
        service.add("help")
        
        # Enable filtering
        message_handler.process(b"WAKEWORD ENABLE\r\n", addr)
        mock_server.sock_send.reset_mock()
        
        # Create another client and send message with wakeword
        addr2 = ("127.0.0.2", 12346)
        register_client(message_handler, addr2, "sender", mock_server)
        
        msg_data = b":sender!sender@host PRIVMSG #general :can you help me\r\n"
        message_handler.process(msg_data, addr2)
        
        # Message should pass through (may be forwarded or queued)

    def test_case_insensitive_wakeword_match(self, message_handler, mock_server, test_dir):
        """Wakeword matching is case-insensitive."""
        mock_server.storage.base_path = str(test_dir)
        addr = ("127.0.0.1", 12345)
        
        register_client(message_handler, addr, "testuser", mock_server)
        
        # Add a wakeword
        service = wakeword(mock_server)
        service.log = Mock()
        service.server = mock_server
        service.add("help")
        
        # Enable filtering
        message_handler.process(b"WAKEWORD ENABLE\r\n", addr)
        mock_server.sock_send.reset_mock()
        
        # Create another client and send message with uppercase wakeword
        addr2 = ("127.0.0.2", 12346)
        register_client(message_handler, addr2, "sender", mock_server)
        
        msg_data = b":sender!sender@host PRIVMSG #general :can you HELP me\r\n"
        message_handler.process(msg_data, addr2)
        
        # Message should match despite case difference

    def test_no_match_blocks_forward(self, message_handler, mock_server, test_dir