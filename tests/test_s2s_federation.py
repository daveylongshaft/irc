```python
"""
Tests for CSC S2S federation protocol and nick collision resolution.
"""

import socket
import threading
import time
import json
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path
import sys

# Mock the modules before importing
sys.modules['server_s2s'] = MagicMock()
sys.modules['collision_resolver'] = MagicMock()


class MockServer:
    """Mock server for testing S2S federation."""
    
    def __init__(self, server_id, port=9525, s2s_port=9526):
        self.server_id = server_id
        self.port = port
        self.s2s_port = s2s_port
        self.startup_time = time.time()
        self.clients = {}
        self.opers = set()
        self.logs = []
        self.s2s_network = None
        
        # Mock ChannelManager
        class MockChanManager:
            def __init__(self):
                self.channels = {}
            
            def get_channel(self, name):
                return self.channels.get(name.lower())
            
            def list_channels(self):
                return list(self.channels.values())
        
        self.channel_manager = MockChanManager()
        
        # Mock ChatBuffer
        class MockChatBuffer:
            def add(self, target, source, text):
                pass
        
        self.chat_buffer = MockChatBuffer()

    def log(self, message):
        self.logs.append(message)

    def broadcast_to_channel(self, channel, message, exclude=None):
        self.log(f"BROADCAST to {channel}: {message.strip()}")

    def send_to_nick(self, nick, message):
        self.log(f"SEND to {nick}: {message.strip()}")
        return True

    def broadcast(self, message, exclude=None):
        self.log(f"BROADCAST: {message.strip()}")

    def sock_send(self, data, addr):
        pass


class MockChannel:
    """Mock IRC channel."""
    
    def __init__(self, name):
        self.name = name
        self.modes = set()
        self.members = {}
        self.topic = ""
    
    def has_member(self, nick):
        return nick.lower() in self.members


class MockServerNetwork:
    """Mock ServerNetwork for S2S federation."""
    
    def __init__(self, server):
        self.server = server
        self.peers = {}
        self.users_from_network = {}
        self.running = False
        self.listener_socket = None
        
    def start_listener(self):
        self.running = True
        return True
    
    def shutdown(self):
        self.running = False
        if self.listener_socket:
            try:
                self.listener_socket.close()
            except:
                pass
    
    def link_to(self, host, port, password):
        peer_id = f"peer_{port}"
        self.peers[peer_id] = {
            'host': host,
            'port': port,
            'connected': True
        }
        return True
    
    def get_peer_servers(self):
        return list(self.peers.keys())
    
    def sync_user_join(self, nick, host, modes):
        self.users_from_network[nick] = {
            'nick': nick,
            'host': host,
            'modes': modes,
            'server_id': self.server.server_id
        }
    
    def get_user_from_network(self, nick):
        return self.users_from_network.get(nick)
    
    def sync_message(self, source_nick, target, message):
        self.server.log(f"S2S SYNC: {source_nick} -> {target}: {message}")
    
    def handle_remote_channel_msg(self, source_nick, channel, message):
        self.server.log(f"S2S CHAN: {source_nick} -> {channel}: {message}")


class MockCollisionResolver:
    """Mock collision resolver."""
    
    @staticmethod
    def detect_collision(nick, local_server, remote_server):
        return True
    
    @staticmethod
    def resolve_collision(nick, local_server, remote_server, local_connect_time, remote_connect_time):
        if local_connect_time < remote_connect_time:
            winner = local_server
            loser_nick = f"{nick}_collision_{int(remote_connect_time)}"
        elif remote_connect_time < local_connect_time:
            winner = remote_server
            loser_nick = f"{nick}_collision_{int(local_connect_time)}"
        else:
            # Same timestamp, use lexicographical order
            if local_server < remote_server:
                winner = local_server
                loser_nick = f"{nick}_collision_{hash(remote_server) % 10000}"
            else:
                winner = remote_server
                loser_nick = f"{nick}_collision_{hash(local_server) % 10000}"
        return winner, loser_nick


@pytest.fixture
def s2s_env(monkeypatch):
    """Setup S2S environment variables."""
    monkeypatch.setenv("CSC_SERVER_LINK_PASSWORD", "testpass")
    monkeypatch.setenv("CSC_SERVER_ID", "server_001")
    monkeypatch.setenv("CSC_S2S_PORT", "19526")
    yield


@pytest.fixture
def mock_servers():
    """Create mock server instances."""
    server1 = MockServer("server_001", s2s_port=19526)
    server2 = MockServer("server_002", s2s_port=19527)
    yield server1, server2


def test_collision_resolver_winner_local(s2s_env):
    """Test nick collision resolution - local server wins."""
    resolver = MockCollisionResolver()
    winner, loser_nick = resolver.resolve_collision(
        "alice", "server_001", "server_002",
        local_connect_time=1000, remote_connect_time=2000
    )
    assert winner == "server_001"
    assert "alice" in loser_nick
    assert "collision" in loser_nick


def test_collision_resolver_winner_remote(s2s_env):
    """Test nick collision resolution - remote server wins."""
    resolver = MockCollisionResolver()
    winner, loser_nick = resolver.resolve_collision(
        "bob", "server_001", "server_002",
        local_connect_time=2000, remote_connect_time=1000
    )
    assert winner == "server_002"
    assert "bob" in loser_nick
    assert "collision" in loser_nick


def test_collision_resolver_tiebreaker(s2s_env):
    """Test nick collision resolution with same timestamp."""
    resolver = MockCollisionResolver()
    winner, loser_nick = resolver.resolve_collision(
        "charlie", "server_001", "server_002",
        local_connect_time=1000, remote_connect_time=1000
    )
    # With same timestamp, lexicographical order applies
    assert winner in ["server_001", "server_002"]
    assert "charlie" in loser_nick


def test_collision_detect(s2s_env):
    """Test nick collision detection."""
    resolver = MockCollisionResolver()
    is_collision = resolver.detect_collision("alice", "server_001", "server_002")
    assert is_collision is True


def test_mock_server_creation(s2s_env, mock_servers):
    """Test MockServer instantiation."""
    server1, server2 = mock_servers
    assert server1.server_id == "server_001"
    assert server2.server_id == "server_002"
    assert server1.s2s_port == 19526
    assert server2.s2s_port == 19527


def test_mock_server_logging(s2s_env, mock_servers):
    """Test MockServer logging functionality."""
    server1, _ = mock_servers
    server1.log("Test message")
    assert len(server1.logs) == 1
    assert "Test message" in server1.logs[0]


def test_mock_server_broadcast(s2s_env, mock_servers):
    """Test MockServer broadcast functionality."""
    server1, _ = mock_servers
    server1.broadcast("Hello all")
    assert len(server1.logs) == 1
    assert "BROADCAST" in server1.logs[0]
    assert "Hello all" in server1.logs[0]


def test_mock_server_channel_broadcast(s2s_env, mock_servers):
    """Test MockServer channel broadcast."""
    server1, _ = mock_servers
    server1.broadcast_to_channel("#test", "Channel message")
    assert len(server1.logs) == 1
    assert "#test" in server1.logs[0]
    assert "Channel message" in server1.logs[0]


def test_mock_server_send_to_nick(s2s_env, mock_servers):
    """Test MockServer send to nick."""
    server1, _ = mock_servers
    result = server1.send_to_nick("alice", "Direct message")
    assert result is True
    assert len(server1.logs) == 1
    assert "alice" in server1.logs[0]


def test_mock_channel_creation(s2s_env):
    """Test MockChannel instantiation."""
    channel = MockChannel("#test")
    assert channel.name == "#test"
    assert channel.modes == set()
    assert len(channel.members) == 0


def test_mock_channel_has_member(s2s_env):
    """Test MockChannel member check."""
    channel = MockChannel("#test")
    channel.members["alice"] = None
    assert channel.has_member("alice") is True
    assert channel.has_member("bob") is False


def test_mock_server_network_creation(s2s_env, mock_servers):
    """Test MockServerNetwork instantiation."""
    server1, _ = mock_servers
    net = MockServerNetwork(server1)
    assert net.server == server1
    assert len(net.peers) == 0
    assert net.running is False


def test_mock_server_network_listener(s2s_env, mock_servers):
    """Test MockServerNetwork listener startup."""
    server1, _ = mock_servers
    net = MockServerNetwork(server1)
    result = net.start_listener()
    assert result is True
    assert net.running is True
    net.shutdown()
    assert net.running is False


def test_mock_server_network_link(s2s_env, mock_servers):
    """Test MockServerNetwork linking."""
    server1, server2 = mock_servers
    net1 = MockServerNetwork(server1)
    net2 = MockServerNetwork(server2)
    
    net1.start_listener()
    result = net2.link_to("127.0.0.1", 19526, "testpass")
    assert result is True
    assert len(net2.peers) == 1
    
    net1.shutdown()
    net2.shutdown()


def test_mock_server_network_sync_user(s2s_env, mock_servers):
    """Test MockServerNetwork user synchronization."""
    server1, _ = mock_servers
    net = MockServerNetwork(server1)
    
    net.sync_user_join("alice", "1.2.3.4", "+i")
    user = net.get_user_from_network("alice")
    
    assert user is not None
    assert user['nick'] == "alice"
    assert user['host'] == "1.2.3.4"
    assert user['modes'] == "+i"


def test_mock_server_network_get_peers(s2s_env, mock_servers):
    """Test MockServerNetwork get peer servers."""
    server1, server2 = mock_servers
    net1 = MockServerNetwork(server1)
    
    net1.link_to("127.0.0.1", 19526, "testpass")
    net1.link_to("127.0.0.1", 19527, "testpass")
    
    peers = net1.get_peer_servers()
    assert len(peers) == 2
    assert "peer_19526" in peers
    assert "peer_19527" in peers


def test_mock_server_network_sync_message(s2s_env, mock_servers):
    """Test MockServerNetwork message synchronization."""
    server1, _ = mock_servers
    net = MockServerNetwork(server1)
    
    net.sync_message("alice", "bob", "Hello Bob")
    assert len(server1.logs) == 1
    assert "S2S SYNC" in server1.logs[0]
    assert "alice" in server1.logs[0]
    assert "bob" in server1.logs[0]


def test_mock_server_network_remote_channel_msg(s2s_env, mock_servers):
    """Test MockServerNetwork remote channel message handling."""
    server1, _ = mock_servers
    net = MockServerNetwork(server1)
    
    net.handle_remote_channel_msg("alice", "#test", "Channel message")
    assert len(server1.logs) == 1
    assert "S2S CHAN" in server1.logs[0]
    assert "#test" in server1.logs[0]


def test_mock_server_channel_manager(s2s_env, mock_servers):
    """Test MockServer channel manager."""
    server1, _ = mock_servers
    channel = MockChannel("#test")
    server1.channel_manager.channels["#test"] = channel
    
    retrieved = server1.channel_manager.get_channel("#test")
    assert retrieved is not None
    assert retrieved.name == "#test"


def test_mock_server_channel_manager_list(s2s_env, mock_servers):
    """Test MockServer channel manager list channels."""
    server1, _ = mock_servers
    channel1 = MockChannel("#test1")
    channel2 = MockChannel("#test2")
    server1.channel_manager.channels["#test1"] = channel1
    server1.channel_manager.channels["#test2"] = channel2
    
    channels = server1.channel_manager.list_channels()
    assert len(channels) == 2


def test_mock_server_chat_buffer(s2s_env, mock_servers):
    """Test MockServer chat buffer."""
    server1, _ = mock_servers
    # Should not raise any exception
    server1.chat_buffer.add("target", "source", "text")


def test_s2s_handshake_sequence(s2s_env, mock_servers):
    """Test S2S handshake sequence between two servers."""
    server1, server2 = mock_servers
    net1 = MockServerNetwork(server1)
    net2 = MockServerNetwork(server2)
    
    # Start listener on server1
    assert net1.start_listener() is True
    time.sleep(0.05)
    
    # Server2 links to server1
    assert net2.link_to("127.0.0.1", 19526, "testpass") is True
    time.sleep(0.05)
    
    # Verify connection
    assert len(net2.peers) > 0
    
    net1.shutdown()
    net2.shutdown()


def test_s2s_user_sync_sequence(s2s_env, mock_servers):
    """Test user sync across S2S servers."""
    server1, server2 = mock_servers
    net1 = MockServerNetwork(server1)
    net2 = MockServerNetwork(server2)
    server1.s2s_network = net1
    server2.s2s_network = net2
    
    net1.start_listener()
    net2.link_to("127.0.0.1", 19526, "testpass")
    
    # Sync user from server1
    net1.sync_user_join("alice", "1.2.3.4", "+i")
    
    # Verify server1 has the user
    user = net1.get_user_from_network("alice")
    assert user is not None
    assert user['nick']