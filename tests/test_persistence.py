```python
"""Pytest tests for CSC IRC persistence system.

Tests cover complete lifecycle, handler triggers, and power failure resilience.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import json
import tempfile
import shutil
import os

from csc_server.storage import PersistentStorageManager
from csc_shared.channel import ChannelManager, Channel
from csc_server.server_message_handler import MessageHandler
from csc_shared.irc import SERVER_NAME


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmpdir_persist(tmp_path):
    """Temporary directory for persistence tests."""
    return str(tmp_path)


@pytest.fixture
def mock_server(tmpdir_persist):
    """Mock server with real PersistentStorageManager."""
    server = Mock()
    server.storage = PersistentStorageManager(tmpdir_persist, log_func=lambda msg: None)
    server.clients = {}
    server.channel_manager = ChannelManager()
    server.name = "TestServer"
    server.server_name = SERVER_NAME
    server.disconnected_clients = {}
    server.max_disconnected_history = 100
    server.timeout = 300
    server.encryption_keys = {}
    server.nickserv_identified = {}
    server.clients_lock = MagicMock()
    
    # Setup initial credentials
    creds_data = server.storage.load_opers()
    creds_data["credentials"] = {"admin": "secret123", "mod": "modpass"}
    server.storage.save_opers(creds_data)
    
    # Mock methods
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
    server._persist_session_data = Mock()
    
    @property
    def client_registry(self):
        return self.storage.load_users().get("users", {})
    
    @property
    def oper_credentials(self):
        return self.storage.load_opers().get("credentials", {})
    
    @property
    def opers(self):
        return {nick.lower() for nick in self.storage.load_opers().get("active_opers", [])}
    
    server.client_registry = client_registry.fget(server)
    type(server).client_registry = client_registry
    type(server).oper_credentials = oper_credentials.fget(server)
    type(server).opers = opers.fget(server)
    
    return server


@pytest.fixture
def mock_server_mock_storage():
    """Mock server with fully mocked storage."""
    server = Mock()
    server.name = "TestServer"
    server.server_name = SERVER_NAME
    server.clients = {}
    server.channel_manager = ChannelManager()
    server.client_registry = {}
    server.oper_credentials = {"admin": "secret123"}
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
    server.disconnected_clients = {}
    server.max_disconnected_history = 100
    server.storage = Mock()
    server.storage.add_disconnection = Mock(return_value=True)
    server.storage.persist_all = Mock(return_value=True)
    server.storage.nickserv_get = Mock(return_value=None)
    server._persist_session_data = Mock()
    return server


@pytest.fixture
def message_handler(mock_server):
    """Message handler with mock server."""
    handler = MessageHandler(mock_server, MagicMock())
    return handler


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def register_client(handler, addr, nick, server):
    """Register a client with NICK and USER commands."""
    handler.process(f"NICK {nick}\r\n".encode(), addr)
    handler.process(f"USER {nick} 0 * :{nick}\r\n".encode(), addr)
    server.sock_send.reset_mock()


def register_client_full_reset(handler, addr, nick, server):
    """Register a client and reset all mocks."""
    handler.process(f"NICK {nick}\r\n".encode(), addr)
    handler.process(f"USER {nick} 0 * :{nick}\r\n".encode(), addr)
    server.sock_send.reset_mock()
    server._persist_session_data.reset_mock()
    server.storage.reset_mock()


def restart_server(tmpdir_persist):
    """Simulate server restart."""
    server = Mock()
    server.storage = PersistentStorageManager(tmpdir_persist, log_func=lambda msg: None)
    server.clients = {}
    server.channel_manager = ChannelManager()
    server.name = "TestServer"
    server.server_name = SERVER_NAME
    server.disconnected_clients = {}
    server.max_disconnected_history = 100
    server.timeout = 300
    server.encryption_keys = {}
    server.nickserv_identified = {}
    
    # Mocks
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
    
    handler = MessageHandler(server, MagicMock())
    server.storage.restore_all(server)
    return server, handler


# ---------------------------------------------------------------------------
# Complete persistence lifecycle tests
# ---------------------------------------------------------------------------

class TestCompletePersistence:
    """Full IRC session save/restore integration tests."""

    def test_full_session_multi_client(self, tmpdir_persist):
        """Full IRC session with multiple clients, restart, verify all state."""
        server = Mock()
        server.storage = PersistentStorageManager(tmpdir_persist, log_func=lambda msg: None)
        server.clients = {}
        server.channel_manager = ChannelManager()
        server.name = "TestServer"
        server.server_name = SERVER_NAME
        server.disconnected_clients = {}
        server.max_disconnected_history = 100
        server.timeout = 300
        server.log = Mock()
        server.sock_send = Mock()
        
        creds_data = server.storage.load_opers()
        creds_data["credentials"] = {"admin": "secret123", "mod": "modpass"}
        server.storage.save_opers(creds_data)
        
        addr_a = ("10.0.0.1", 6001)
        addr_b = ("10.0.0.2", 6002)
        addr_c = ("10.0.0.3", 6003)
        
        handler = MessageHandler(server, MagicMock())
        
        register_client(handler, addr_a, "Alice", server)
        register_client(handler, addr_b, "Bob", server)
        register_client(handler, addr_c, "Charlie", server)
        
        handler.process(b"JOIN #general\r\n", addr_a)
        handler.process(b"JOIN #general\r\n", addr_b)
        
        handler.process(b"PRIVMSG #general :Hello from Alice\r\n", addr_a)
        handler.process(b"PRIVMSG Bob :Private to Bob\r\n", addr_a)
        
        server.storage.persist_all(server)
        
        server_r, handler_r = restart_server(tmpdir_persist)
        
        assert len(server_r.clients) == 3
        assert "alice" in server_r.clients
        assert "bob" in server_r.clients
        assert "charlie" in server_r.clients
        
        assert "general" in server_r.channel_manager.channels
        channel = server_r.channel_manager.channels["general"]
        assert "alice" in channel.members
        assert "bob" in channel.members
        assert "charlie" not in channel.members

    def test_client_disconnect_reconnect(self, tmpdir_persist):
        """Client disconnect, persist, restart, reconnect."""
        server = Mock()
        server.storage = PersistentStorageManager(tmpdir_persist, log_func=lambda msg: None)
        server.clients = {}
        server.channel_manager = ChannelManager()
        server.name = "TestServer"
        server.server_name = SERVER_NAME
        server.disconnected_clients = {}
        server.max_disconnected_history = 100
        server.timeout = 300
        server.log = Mock()
        server.sock_send = Mock()
        
        creds_data = server.storage.load_opers()
        creds_data["credentials"] = {"admin": "secret123"}
        server.storage.save_opers(creds_data)
        
        addr_alice = ("10.0.0.1", 6001)
        
        handler = MessageHandler(server, MagicMock())
        register_client(handler, addr_alice, "Alice", server)
        handler.process(b"JOIN #general\r\n", addr_alice)
        
        server.storage.persist_all(server)
        
        handler.process(b"QUIT\r\n", addr_alice)
        server.storage.persist_all(server)
        
        server_r, handler_r = restart_server(tmpdir_persist)
        
        assert "alice" not in server_r.clients
        assert "general" in server_r.channel_manager.channels
        
        register_client(handler_r, addr_alice, "Alice", server_r)
        handler_r.process(b"JOIN #general\r\n", addr_alice)
        
        assert "alice" in server_r.clients
        assert "alice" in server_r.channel_manager.channels["general"].members

    def test_channel_modes_persist(self, tmpdir_persist):
        """Channel modes persist across restart."""
        server = Mock()
        server.storage = PersistentStorageManager(tmpdir_persist, log_func=lambda msg: None)
        server.clients = {}
        server.channel_manager = ChannelManager()
        server.name = "TestServer"
        server.server_name = SERVER_NAME
        server.disconnected_clients = {}
        server.max_disconnected_history = 100
        server.timeout = 300
        server.log = Mock()
        server.sock_send = Mock()
        
        creds_data = server.storage.load_opers()
        creds_data["credentials"] = {"admin": "secret123"}
        server.storage.save_opers(creds_data)
        
        addr = ("10.0.0.1", 6001)
        handler = MessageHandler(server, MagicMock())
        register_client(handler, addr, "Alice", server)
        handler.process(b"JOIN #general\r\n", addr)
        
        channel = server.channel_manager.channels["general"]
        channel.modes = {"m"}
        channel.topic = "Test Topic"
        
        server.storage.persist_all(server)
        
        server_r, handler_r = restart_server(tmpdir_persist)
        
        assert "general" in server_r.channel_manager.channels
        channel_r = server_r.channel_manager.channels["general"]
        assert "m" in channel_r.modes
        assert channel_r.topic == "Test Topic"

    def test_user_data_persist(self, tmpdir_persist):
        """User registration and credentials persist."""
        server = Mock()
        server.storage = PersistentStorageManager(tmpdir_persist, log_func=lambda msg: None)
        server.clients = {}
        server.channel_manager = ChannelManager()
        server.name = "TestServer"
        server.server_name = SERVER_NAME
        server.disconnected_clients = {}
        server.max_disconnected_history = 100
        server.timeout = 300
        server.log = Mock()
        server.sock_send = Mock()
        
        creds_data = server.storage.load_opers()
        creds_data["credentials"] = {"admin": "secret123"}
        server.storage.save_opers(creds_data)
        
        addr = ("10.0.0.1", 6001)
        handler = MessageHandler(server, MagicMock())
        register_client(handler, addr, "Alice", server)
        
        users = server.storage.load_users()
        users["users"]["alice"] = {"realname": "Alice User", "registered": True}
        server.storage.save_users(users)
        
        server.storage.persist_all(server)
        
        server_r, _ = restart_server(tmpdir_persist)
        
        users_r = server_r.storage.load_users()
        assert "alice" in users_r.get("users", {})
        assert users_r["users"]["alice"]["realname"] == "Alice User"

    def test_oper_status_persist(self, tmpdir_persist):
        """Oper status persists across restart."""
        server = Mock()
        server.storage = PersistentStorageManager(tmpdir_persist, log_func=lambda msg: None)
        server.clients = {}
        server.channel_manager = ChannelManager()
        server.name = "TestServer"
        server.server_name = SERVER_NAME
        server.disconnected_clients = {}
        server.max_disconnected_history = 100
        server.timeout = 300
        server.log = Mock()
        server.sock_send = Mock()
        
        creds_data = server.storage.load_opers()
        creds_data["credentials"] = {"admin": "secret123"}
        creds_data["active_opers"] = ["admin"]
        server.storage.save_opers(creds_data)
        
        server.storage.persist_all(server)
        
        server_r, _ = restart_server(tmpdir_persist)
        
        opers_r = server_r.storage.load_opers()
        assert "admin" in opers_r.get("active_opers", [])


# ---------------------------------------------------------------------------
# Handler persistence trigger tests
# ---------------------------------------------------------------------------

class TestHandlerPersistenceTriggers:
    """Tests that verify persistence is triggered at correct points."""

    def test_nick_change_triggers_persist(self, mock_server_mock_storage):
        """NICK change triggers _persist_session_data."""
        handler = MessageHandler(mock_server_mock_storage, MagicMock())
        addr = ("10.0.0.1", 6001)
        
        register_client_full_reset(handler, addr, "OldNick", mock_server_mock_storage)
        
        handler.process(b"NICK NewNick\r\n", addr)
        
        assert mock_server_mock_storage._persist_session_data.called

    def test_join_triggers_persist(self, mock_server_mock_storage):
        """JOIN triggers _persist_session_data."""
        handler = MessageHandler(mock_server_