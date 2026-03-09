"""
Tests for CSC S2S federation protocol and nick collision resolution.
"""

import socket
import threading
import time
import json
import pytest
import os
import sys
from pathlib import Path

# Add packages to path
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "csc-server"))
sys.path.insert(1, str(Path(__file__).parent.parent / "packages" / "csc-shared"))

from server_s2s import ServerNetwork, ServerLink
from collision_resolver import detect_collision, resolve_collision


class MockServer:
    def __init__(self, server_id, port=9525, s2s_port=9526):
        self.server_id = server_id
        self.port = port
        self.s2s_port = s2s_port
        self.startup_time = time.time()
        self.clients = {}
        self.opers = set()
        self.logs = []
        
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
            def add(self, target, source, text): pass
        self.chat_buffer = MockChatBuffer()

    def log(self, message):
        self.logs.append(message)
        # print(f"[{self.server_id}] {message}")

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
    def __init__(self, name):
        self.name = name
        self.modes = set()
        self.members = {}
        self.topic = ""
    def has_member(self, nick):
        return nick.lower() in self.members


@pytest.fixture
def s2s_env(monkeypatch):
    # Set environment variables for testing
    monkeypatch.setenv("CSC_SERVER_LINK_PASSWORD", "testpass")
    yield


def test_collision_resolver():
    """Test nick collision resolution logic."""
    # server_001 wins (older)
    winner, loser_nick = resolve_collision(
        "alice", "server_001", "server_002",
        local_connect_time=1000, remote_connect_time=2000
    )
    assert winner == "server_001"
    assert loser_nick.startswith("alice_")

    # server_002 wins (older)
    winner, loser_nick = resolve_collision(
        "bob", "server_001", "server_002",
        local_connect_time=2000, remote_connect_time=1000
    )
    assert winner == "server_002"
    assert loser_nick.startswith("bob_")

    # Same timestamp, server ID tiebreaker (lexicographical)
    winner, loser_nick = resolve_collision(
        "charlie", "server_001", "server_002",
        local_connect_time=1000, remote_connect_time=1000
    )
    assert winner == "server_001"


def test_s2s_handshake(s2s_env, monkeypatch):
    """Test S2S SLINK/SLINKACK handshake."""
    server1 = MockServer("server_001", s2s_port=19526)
    server2 = MockServer("server_002", s2s_port=19527)
    
    monkeypatch.setenv("CSC_SERVER_ID", "server_001")
    monkeypatch.setenv("CSC_S2S_PORT", "19526")
    net1 = ServerNetwork(server1)
    
    monkeypatch.setenv("CSC_SERVER_ID", "server_002")
    monkeypatch.setenv("CSC_S2S_PORT", "19527")
    net2 = ServerNetwork(server2)
    
    # Start net1 listener
    assert net1.start_listener() is True
    time.sleep(0.1)
    
    # net2 links to net1
    assert net2.link_to("127.0.0.1", 19526, "testpass") is True
    time.sleep(0.5)
    
    # Verify links
    assert "server_002" in net1.get_peer_servers()
    assert "server_001" in net2.get_peer_servers()
    
    net1.shutdown()
    net2.shutdown()


def test_s2s_sync_user(s2s_env, monkeypatch):
    """Test user synchronization across servers."""
    server1 = MockServer("server_001", s2s_port=19528)
    server2 = MockServer("server_002", s2s_port=19529)
    
    monkeypatch.setenv("CSC_SERVER_ID", "server_001")
    monkeypatch.setenv("CSC_S2S_PORT", "19528")
    net1 = ServerNetwork(server1)
    server1.s2s_network = net1
    
    monkeypatch.setenv("CSC_SERVER_ID", "server_002")
    monkeypatch.setenv("CSC_S2S_PORT", "19529")
    net2 = ServerNetwork(server2)
    server2.s2s_network = net2
    
    assert net1.start_listener() is True
    time.sleep(0.5)
    assert net2.link_to("127.0.0.1", 19528, "testpass") is True
    time.sleep(0.5)
    
    # Sync a user from server1 to server2
    net1.sync_user_join("alice", "1.2.3.4", "+i")
    time.sleep(1.0)

    # Verify server2 knows about alice
    remote_user = net2.get_user_from_network("alice")
    if remote_user is None:
        print(f"\nServer1 Logs: {server1.logs}")
        print(f"\nServer2 Logs: {server2.logs}")
    assert remote_user is not None
    
    assert remote_user["nick"] == "alice"
    assert remote_user["server_id"] == "server_001"
    
    net1.shutdown()
    net2.shutdown()


def test_s2s_sync_msg(s2s_env, monkeypatch):
    """Test message routing across servers."""
    server1 = MockServer("server_001", s2s_port=19530)
    server2 = MockServer("server_002", s2s_port=19531)
    
    monkeypatch.setenv("CSC_SERVER_ID", "server_001")
    monkeypatch.setenv("CSC_S2S_PORT", "19530")
    net1 = ServerNetwork(server1)
    server1.s2s_network = net1
    
    monkeypatch.setenv("CSC_SERVER_ID", "server_002")
    monkeypatch.setenv("CSC_S2S_PORT", "19531")
    net2 = ServerNetwork(server2)
    server2.s2s_network = net2
    
    assert net1.start_listener() is True
    time.sleep(0.5)
    assert net2.link_to("127.0.0.1", 19530, "testpass") is True
    time.sleep(0.5)
    
    # Mock a local channel on server2
    chan = MockChannel("#test")
    server2.channel_manager.channels["#test"] = chan
    
    # Send a message from server1 to #test on server2
    net1.route_message("alice", "#test", "Hello World")
    time.sleep(0.5)
    
    # Verify server2 received and broadcasted the message
    assert any("BROADCAST to #test: :alice!alice@server_001 PRIVMSG #test :Hello World" in log for log in server2.logs)
    
    net1.shutdown()
    net2.shutdown()


def test_s2s_sync_nick(s2s_env, monkeypatch):
    """Test nick change synchronization."""
    server1 = MockServer("server_001", s2s_port=19532)
    server2 = MockServer("server_002", s2s_port=19533)
    
    monkeypatch.setenv("CSC_SERVER_ID", "server_001")
    monkeypatch.setenv("CSC_S2S_PORT", "19532")
    net1 = ServerNetwork(server1)
    server1.s2s_network = net1
    
    monkeypatch.setenv("CSC_SERVER_ID", "server_002")
    monkeypatch.setenv("CSC_S2S_PORT", "19533")
    net2 = ServerNetwork(server2)
    server2.s2s_network = net2
    
    assert net1.start_listener() is True
    time.sleep(0.5)
    assert net2.link_to("127.0.0.1", 19532, "testpass") is True
    time.sleep(0.5)
    
    # Alice is on server1
    net1.sync_user_join("alice", "1.2.3.4", "+i")
    time.sleep(0.5)
    
    # Alice changes nick to alison
    net1.sync_nick_change("alice", "alison")
    time.sleep(1.0)
    
    # Verify server2 updated its tracking
    if net2.get_user_from_network("alison") is None:
        print(f"\nServer1 Logs: {server1.logs}")
        print(f"\nServer2 Logs: {server2.logs}")
    assert net2.get_user_from_network("alice") is None
    assert net2.get_user_from_network("alison") is not None
    assert any("BROADCAST: :alice!alice@server_001 NICK alison" in log for log in server2.logs)
    
    net1.shutdown()
    net2.shutdown()


def test_s2s_sync_topic(s2s_env, monkeypatch):
    """Test topic synchronization."""
    server1 = MockServer("server_001", s2s_port=19534)
    server2 = MockServer("server_002", s2s_port=19535)
    
    monkeypatch.setenv("CSC_SERVER_ID", "server_001")
    monkeypatch.setenv("CSC_S2S_PORT", "19534")
    net1 = ServerNetwork(server1)
    server1.s2s_network = net1
    
    monkeypatch.setenv("CSC_SERVER_ID", "server_002")
    monkeypatch.setenv("CSC_S2S_PORT", "19535")
    net2 = ServerNetwork(server2)
    server2.s2s_network = net2
    
    assert net1.start_listener() is True
    time.sleep(0.5)
    assert net2.link_to("127.0.0.1", 19534, "testpass") is True
    time.sleep(0.5)
    
    # Mock a local channel on server2
    chan = MockChannel("#test")
    server2.channel_manager.channels["#test"] = chan
    
    # Server1 syncs a topic change
    net1.sync_topic("#test", "New Topic")
    time.sleep(1.0)
    
    # Verify server2 updated topic
    assert chan.topic == "New Topic"
    assert any("BROADCAST to #test: :server_001!server_001@server_001 TOPIC #test :New Topic" in log for log in server2.logs)
    
    net1.shutdown()
    net2.shutdown()
