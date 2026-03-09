```python
import pytest
from unittest.mock import patch, Mock, MagicMock, mock_open
import json
import tempfile
import os
import sys
import threading


@pytest.fixture
def config_file(tmp_path):
    """Create a temporary config file with valid JSON."""
    config_path = tmp_path / "test_config.json"
    config_data = {
        "client_name": "testuser",
        "server_host": "127.0.0.1",
        "server_port": 9525,
        "log_file": "testuser.log",
    }
    config_path.write_text(json.dumps(config_data))
    return config_path, config_data


@pytest.fixture
def mock_socket():
    """Mock socket to prevent real UDP connections."""
    with patch("network.socket.socket") as mock_socket_cls:
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        yield mock_sock


@pytest.fixture
def mock_log():
    """Mock log to prevent file I/O."""
    with patch("log.Log.log"):
        yield


@pytest.fixture
def mock_version():
    """Mock Version to prevent directory creation."""
    with patch("version.Version.__init__", return_value=None):
        yield


@pytest.fixture
def client_instance(config_file, mock_socket, mock_log, mock_version):
    """Create a Client instance with all dependencies mocked."""
    config_path, config_data = config_file
    
    # Patch Network.__init__ to skip parent initialization
    with patch("network.Network.__init__", return_value=None):
        # Import Client after patching
        from client import Client
        
        # Create client instance without calling __init__
        client = Client.__new__(Client)
        
        # Set up Data/Log internals
        client._storage = config_data.copy()
        client._storage_lock = threading.Lock()
        client._connected_source = str(config_path)
        client.isDataConnected = True
        client.source_filename = str(config_path)
        client.log_file = "testuser.log"
        client.name = "testuser"
        client.log = MagicMock()
        
        # Load config
        client.config_file = str(config_path)
        client.server_host = "127.0.0.1"
        client.server_port = 9525
        client.server_addr = ("127.0.0.1", 9525)
        
        # Set up Network internals
        client.sock = mock_socket
        client._running = True
        client.buffsize = 65500
        client.message_queue = MagicMock()
        client._listener_thread = None
        client.clients = {}
        client.last_keepalive = 0
        client.keepalive_interval = 90
        
        # IRC channel tracking
        client.current_channel = "#general"
        client._last_message_sent = None
        
        # Set up aliases and macros with mocked dependencies
        with patch("aliases.Aliases.__init__", return_value=None):
            from aliases import Aliases
            client.aliases = Aliases.__new__(Aliases)
            client.aliases.client = client
            client.aliases.aliases = {}
        
        with patch("macros.Macros.__init__", return_value=None):
            from macros import Macros
            client.macros = Macros.__new__(Macros)
            client.macros.client = client
            client.macros.macros = {}
        
        yield client


@pytest.fixture
def sent_messages_capture(client_instance):
    """Capture messages sent by the client."""
    sent_messages = []
    
    def capture_send(msg):
        sent_messages.append(msg)
    
    with patch("network.Network.send", side_effect=capture_send):
        yield sent_messages


# ==================================================================
# Registration Tests
# ==================================================================

def test_identify_sends_nick_command(client_instance, sent_messages_capture):
    """identify() sends a NICK command containing the client name."""
    client_instance.identify()
    nick_msgs = [m for m in sent_messages_capture if m.startswith("NICK")]
    assert len(nick_msgs) == 1
    assert "testuser" in nick_msgs[0]


def test_identify_sends_user_command(client_instance, sent_messages_capture):
    """identify() sends a USER command containing the client name."""
    client_instance.identify()
    user_msgs = [m for m in sent_messages_capture if m.startswith("USER")]
    assert len(user_msgs) == 1
    assert "testuser" in user_msgs[0]


def test_identify_user_format(client_instance, sent_messages_capture):
    """USER command follows the format: USER name 0 * :name"""
    client_instance.identify()
    user_msgs = [m for m in sent_messages_capture if m.startswith("USER")]
    assert user_msgs[0] == "USER testuser 0 * :testuser\r\n"


def test_identify_nick_format(client_instance, sent_messages_capture):
    """NICK command follows the format: NICK name"""
    client_instance.identify()
    nick_msgs = [m for m in sent_messages_capture if m.startswith("NICK")]
    assert nick_msgs[0] == "NICK testuser\r\n"


# ==================================================================
# Parsing Tests
# ==================================================================

def test_parse_irc_message_basic():
    """parse_irc_message() parses a basic IRC message correctly."""
    from irc import parse_irc_message
    
    msg = "PING :irc.example.com"
    parsed = parse_irc_message(msg)
    assert parsed.command == "PING"
    assert parsed.params == ["irc.example.com"]


def test_parse_irc_message_with_prefix():
    """parse_irc_message() extracts prefix from message."""
    from irc import parse_irc_message
    
    msg = ":nick!user@host PRIVMSG #channel :Hello"
    parsed = parse_irc_message(msg)
    assert parsed.prefix == "nick!user@host"
    assert parsed.command == "PRIVMSG"


def test_parse_irc_message_with_trailing():
    """parse_irc_message() extracts trailing parameter correctly."""
    from irc import parse_irc_message
    
    msg = ":nick!user@host PRIVMSG #channel :This is a message"
    parsed = parse_irc_message(msg)
    assert parsed.params[-1] == "This is a message"


def test_irc_message_class_construction():
    """IRCMessage class constructs and stores message data."""
    from irc import IRCMessage
    
    msg = IRCMessage(
        prefix="nick!user@host",
        command="PRIVMSG",
        params=["#channel", "Hello"]
    )
    assert msg.prefix == "nick!user@host"
    assert msg.command == "PRIVMSG"
    assert msg.params == ["#channel", "Hello"]


def test_parse_irc_message_no_params():
    """parse_irc_message() handles messages with no parameters."""
    from irc import parse_irc_message
    
    msg = "PING"
    parsed = parse_irc_message(msg)
    assert parsed.command == "PING"
    assert parsed.params == []


def test_parse_irc_message_multiple_params():
    """parse_irc_message() handles multiple space-separated parameters."""
    from irc import parse_irc_message
    
    msg = "PRIVMSG #channel1 #channel2 param3"
    parsed = parse_irc_message(msg)
    assert parsed.command == "PRIVMSG"
    assert len(parsed.params) >= 3


# ==================================================================
# Channel Tests
# ==================================================================

def test_join_channel_sends_join_command(client_instance, sent_messages_capture):
    """join_channel() sends a JOIN command."""
    client_instance.join_channel("#newchannel")
    join_msgs = [m for m in sent_messages_capture if m.startswith("JOIN")]
    assert len(join_msgs) > 0
    assert "#newchannel" in join_msgs[0]


def test_join_channel_updates_current_channel(client_instance, sent_messages_capture):
    """join_channel() updates the current_channel attribute."""
    client_instance.join_channel("#newchannel")
    assert client_instance.current_channel == "#newchannel"


def test_leave_channel_sends_part_command(client_instance, sent_messages_capture):
    """leave_channel() sends a PART command."""
    client_instance.current_channel = "#general"
    client_instance.leave_channel()
    part_msgs = [m for m in sent_messages_capture if m.startswith("PART")]
    assert len(part_msgs) > 0
    assert "#general" in part_msgs[0]


def test_join_command_format(client_instance, sent_messages_capture):
    """JOIN command follows the IRC format: JOIN #channel"""
    client_instance.join_channel("#test")
    join_msgs = [m for m in sent_messages_capture if m.startswith("JOIN")]
    assert "JOIN #test" in join_msgs[0]


# ==================================================================
# Message Sending Tests
# ==================================================================

def test_send_message_to_channel(client_instance, sent_messages_capture):
    """send_message() sends a PRIVMSG to the current channel."""
    client_instance.send_message("Hello, channel!")
    privmsg_msgs = [m for m in sent_messages_capture if m.startswith("PRIVMSG")]
    assert len(privmsg_msgs) > 0
    assert "Hello, channel!" in privmsg_msgs[0]


def test_send_message_uses_current_channel(client_instance, sent_messages_capture):
    """send_message() uses current_channel for the target."""
    client_instance.current_channel = "#specific"
    client_instance.send_message("Test message")
    privmsg_msgs = [m for m in sent_messages_capture if m.startswith("PRIVMSG")]
    assert "#specific" in privmsg_msgs[0]


def test_send_message_format(client_instance, sent_messages_capture):
    """PRIVMSG follows the format: PRIVMSG #channel :message"""
    client_instance.current_channel = "#test"
    client_instance.send_message("Hello")
    privmsg_msgs = [m for m in sent_messages_capture if "Hello" in m]
    assert len(privmsg_msgs) > 0
    assert "PRIVMSG #test :Hello" in privmsg_msgs[0]


def test_send_message_with_special_chars(client_instance, sent_messages_capture):
    """send_message() handles messages with special characters."""
    special_msg = "Hello! @#$%^&*()"
    client_instance.send_message(special_msg)
    privmsg_msgs = [m for m in sent_messages_capture if special_msg in m]
    assert len(privmsg_msgs) > 0


# ==================================================================
# Response Handling Tests
# ==================================================================

def test_handle_ping_responds_with_pong(client_instance, sent_messages_capture):
    """handle_ping() sends a PONG response."""
    from irc import IRCMessage
    
    ping_msg = IRCMessage(prefix=None, command="PING", params=["irc.example.com"])
    client_instance.handle_ping(ping_msg)
    pong_msgs = [m for m in sent_messages_capture if m.startswith("PONG")]
    assert len(pong_msgs) > 0


def test_handle_ping_with_server_name(client_instance, sent_messages_capture):
    """handle_ping() includes server name in PONG."""
    from irc import IRCMessage
    
    ping_msg = IRCMessage(prefix=None, command="PING", params=["irc.example.com"])
    client_instance.handle_ping(ping_msg)
    pong_msgs = [m for m in sent_messages_capture if m.startswith("PONG")]
    assert "irc.example.com" in pong_msgs[0]


def test_server_name_constant_exists():
    """SERVER_NAME constant is defined in irc module."""
    from irc import SERVER_NAME
    assert SERVER_NAME is not None
    assert isinstance(SERVER_NAME, str)


# ==================================================================
# Parse Edge Cases
# ==================================================================

def test_parse_empty_string():
    """parse_irc_message() handles empty strings gracefully."""
    from irc import parse_irc_message
    
    # Should either return a default IRCMessage or handle gracefully
    result = parse_irc_message("")
    assert result is not None


def test_parse_whitespace_only():
    """parse_irc_message() handles whitespace-only strings."""
    from irc import parse_irc_message
    
    result = parse_irc_message("   ")
    assert result is not None


def test_parse_prefix_only():
    """parse_irc_message() handles prefix-only messages."""
    from irc import parse_irc_message
    
    msg = ":nick!user@host"
    parsed = parse_irc_message(msg)
    assert parsed.prefix == "nick!user@host"


def test_parse_message_with_crlf():
    """parse_irc_message() handles CRLF line endings."""
    from irc import parse_irc_message
    
    msg = "PRIVMSG #channel :Hello\r\n"
    parsed = parse_irc_message(msg)
    assert parsed.command == "PRIVMSG"


# ==================================================================
# IRC Message Class Tests
# ==================================================================

def test_ircmessage_equality():
    """IRCMessage instances with same data are comparable."""
    from irc import IRCMessage
    
    msg1 = IRCMessage(prefix="test", command="PRIVMSG", params=["#ch", "text"])
    msg2 = IRCMessage(prefix="test", command="PRIVMSG", params=["#ch", "text"])
    # Both should have same attributes
    assert msg1.prefix == msg2.prefix
    assert msg1.command == msg2.command
    assert msg1.params == msg2.params


def test_ircmessage_with_none_prefix():
    """IRCMessage handles None prefix."""
    from irc import IRCMessage
    
    msg = IRCMessage(prefix=None, command="PING", params=["server"])
    assert msg.prefix is None
    assert msg.command == "PING"


def test_ircmessage_empty_params():
    """IRCMessage handles empty params list."""
    from irc import IRCMessage
    
    msg = IRCMessage(prefix="test", command="QUIT", params=[])
    assert msg.params == []


# ==================================================================
# Integration Tests
# ==================================================================

def test_identify_then_join_flow(client_instance, sent_messages_capture):
    """Test identify() followed by join_channel()."""
    client_instance.identify()
    client_instance.join_channel("#test")
    
    messages_str = " ".join(sent_messages_capture)
    assert "NICK testuser" in messages_str
    assert "USER testuser" in messages_str
    assert "JOIN #test" in messages_str


def test_join_then_send_message_flow(client_instance, sent_messages_capture):
    """Test join_channel() followed by send_message()."""
    client_instance.join_channel("#channel")
    client_instance.send_message("Test message")
    
    messages_str = " ".join(sent_messages_capture)
    assert "JOIN #channel" in messages_str
    assert "PRIVMSG #channel :Test message" in messages_str


def test_multiple_channel_switches(client_instance, sent_messages_capture):
    """Test joining multiple channels in sequence."""
    client_instance.join_channel("#ch1")
    assert client_instance.current_channel == "#ch1"
    
    client_instance.join_channel("#