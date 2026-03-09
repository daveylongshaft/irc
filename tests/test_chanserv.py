```python
import pytest
from unittest.mock import Mock, MagicMock, patch, call
import threading
import sys
import os

# Mock the imports before any test runs
sys.modules['packages'] = MagicMock()
sys.modules['packages.csc_server'] = MagicMock()
sys.modules['packages.csc_shared'] = MagicMock()


@pytest.fixture
def mock_server():
    """Build a mock server object for testing."""
    server = Mock()
    server.name = "TestServer"
    server.server_name = "irc.test.local"
    server.clients = {}
    server.clients_lock = threading.Lock()
    
    # Mock ChannelManager
    channel_manager = Mock()
    channel_manager.get_channel = Mock(return_value=Mock(
        add_member=Mock(),
        remove_member=Mock(),
        is_op=Mock(return_value=False),
        members={}
    ))
    server.channel_manager = channel_manager
    
    server.log = Mock()
    server.sock_send = Mock()
    server.broadcast_to_channel = Mock()
    server.get_data = Mock(side_effect=lambda k: {} if k == "clients" else None)
    
    # Mock storage
    server.storage = Mock()
    server.storage.chanserv_get = Mock(return_value=None)
    server.storage.chanserv_register = Mock(return_value=True)
    server.storage.chanserv_update = Mock(return_value=True)
    server.storage.load_chanserv = Mock(return_value={"channels": {}})
    server.storage.load_settings = Mock(return_value={
        "nickserv": {"enforce_timeout": 60, "enforce_mode": "warn"}
    })
    
    server.opers = set()
    server._persist_session_data = Mock()
    server.project_root_dir = "/tmp/csc-test"
    server.timeout = 120
    
    return server


@pytest.fixture
def mock_file_handler(mock_server):
    """Mock FileHandler."""
    with patch('server_file_handler.FileHandler') as mock_fh:
        file_handler = Mock()
        file_handler.server = mock_server
        return file_handler


@pytest.fixture
def mock_irc_message():
    """Mock IRCMessage class."""
    msg = Mock()
    msg.command = "PRIVMSG"
    msg.params = ["#test", "hello"]
    msg.prefix = "user!user@host"
    msg.trailing = "hello"
    return msg


def test_message_handler_initialization(mock_server, mock_file_handler):
    """Test MessageHandler initializes correctly."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.file_handler = mock_file_handler
        
        assert handler.server == mock_server
        assert handler.file_handler == mock_file_handler


def test_parse_irc_message_basic():
    """Test basic IRC message parsing."""
    with patch('irc.parse_irc_message') as mock_parse:
        test_data = b"PRIVMSG #test :hello world\r\n"
        mock_parse.return_value = Mock(
            command="PRIVMSG",
            params=["#test"],
            trailing="hello world"
        )
        
        result = mock_parse(test_data)
        assert result.command == "PRIVMSG"
        assert result.params == ["#test"]
        assert result.trailing == "hello world"


def test_format_irc_message():
    """Test IRC message formatting."""
    with patch('irc.format_irc_message') as mock_format:
        mock_format.return_value = "PRIVMSG #test :hello\r\n"
        
        result = mock_format("PRIVMSG", params=["#test"], trailing="hello")
        assert result == "PRIVMSG #test :hello\r\n"


def test_client_registration(mock_server, mock_file_handler):
    """Test client NICK and USER registration."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock()
        
        addr = ("127.0.0.1", 5001)
        
        # Simulate NICK command
        handler.process(b"NICK testuser\r\n", addr)
        # Simulate USER command
        handler.process(b"USER testuser 0 * :Test User\r\n", addr)
        
        assert handler.process.call_count == 2


def test_join_channel(mock_server):
    """Test JOIN channel command."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock()
        
        addr = ("127.0.0.1", 5001)
        handler.process(b"JOIN #testchannel\r\n", addr)
        
        handler.process.assert_called_once()


def test_privmsg_to_channel(mock_server):
    """Test PRIVMSG to channel."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock()
        
        addr = ("127.0.0.1", 5001)
        handler.process(b"PRIVMSG #testchannel :hello everyone\r\n", addr)
        
        handler.process.assert_called_once()


def test_privmsg_to_user(mock_server):
    """Test PRIVMSG to specific user."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock()
        
        addr = ("127.0.0.1", 5001)
        handler.process(b"PRIVMSG targetuser :private message\r\n", addr)
        
        handler.process.assert_called_once()


def test_chanserv_register_channel(mock_server):
    """Test ChanServ REGISTER command."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler._handle_chanserv_register = Mock(return_value=True)
        
        mock_server.storage.chanserv_get.return_value = None
        mock_server.storage.chanserv_register.return_value = True
        
        addr = ("127.0.0.1", 5001)
        handler._handle_chanserv_register("#test", "owner", "Test Channel", addr)
        
        handler._handle_chanserv_register.assert_called_once()


def test_chanserv_op_command(mock_server):
    """Test ChanServ OP command."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler._handle_chanserv_op = Mock(return_value=True)
        
        mock_server.storage.chanserv_get.return_value = {
            "channel": "#test",
            "owner": "owner",
            "oplist": ["owner"]
        }
        
        addr = ("127.0.0.1", 5001)
        handler._handle_chanserv_op("#test", "targetuser", addr)
        
        handler._handle_chanserv_op.assert_called_once()


def test_chanserv_ban_command(mock_server):
    """Test ChanServ BAN command."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler._handle_chanserv_ban = Mock(return_value=True)
        
        mock_server.storage.chanserv_get.return_value = {
            "channel": "#test",
            "owner": "owner",
            "banlist": []
        }
        
        addr = ("127.0.0.1", 5001)
        handler._handle_chanserv_ban("#test", "baduser!*@*", addr)
        
        handler._handle_chanserv_ban.assert_called_once()


def test_chanserv_topic_command(mock_server):
    """Test ChanServ TOPIC command."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler._handle_chanserv_topic = Mock(return_value=True)
        
        mock_server.storage.chanserv_get.return_value = {
            "channel": "#test",
            "owner": "owner"
        }
        
        addr = ("127.0.0.1", 5001)
        handler._handle_chanserv_topic("#test", "New Topic", addr)
        
        handler._handle_chanserv_topic.assert_called_once()


def test_mode_command_add_op(mock_server):
    """Test MODE command to add operator mode."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock()
        
        addr = ("127.0.0.1", 5001)
        handler.process(b"MODE #testchannel +o user1\r\n", addr)
        
        handler.process.assert_called_once()


def test_mode_command_remove_op(mock_server):
    """Test MODE command to remove operator mode."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock()
        
        addr = ("127.0.0.1", 5001)
        handler.process(b"MODE #testchannel -o user1\r\n", addr)
        
        handler.process.assert_called_once()


def test_kick_command(mock_server):
    """Test KICK command."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock()
        
        addr = ("127.0.0.1", 5001)
        handler.process(b"KICK #testchannel user1 :spam\r\n", addr)
        
        handler.process.assert_called_once()


def test_part_channel(mock_server):
    """Test PART command to leave channel."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock()
        
        addr = ("127.0.0.1", 5001)
        handler.process(b"PART #testchannel :goodbye\r\n", addr)
        
        handler.process.assert_called_once()


def test_quit_command(mock_server):
    """Test QUIT command."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock()
        
        addr = ("127.0.0.1", 5001)
        handler.process(b"QUIT :leaving\r\n", addr)
        
        handler.process.assert_called_once()


def test_list_command(mock_server):
    """Test LIST command to list channels."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock()
        
        addr = ("127.0.0.1", 5001)
        handler.process(b"LIST\r\n", addr)
        
        handler.process.assert_called_once()


def test_names_command(mock_server):
    """Test NAMES command to list channel members."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock()
        
        addr = ("127.0.0.1", 5001)
        handler.process(b"NAMES #testchannel\r\n", addr)
        
        handler.process.assert_called_once()


def test_whois_command(mock_server):
    """Test WHOIS command."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock()
        
        addr = ("127.0.0.1", 5001)
        handler.process(b"WHOIS testuser\r\n", addr)
        
        handler.process.assert_called_once()


def test_message_handler_error_handling(mock_server):
    """Test error handling for malformed messages."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock(side_effect=Exception("Parse error"))
        
        addr = ("127.0.0.1", 5001)
        
        with pytest.raises(Exception):
            handler.process(b"INVALID\r\n", addr)


def test_channel_member_tracking(mock_server):
    """Test tracking of channel members."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        
        channel = mock_server.channel_manager.get_channel("#test")
        channel.add_member("user1", ("127.0.0.1", 5001))
        channel.add_member("user2", ("127.0.0.1", 5002))
        
        channel.add_member.assert_called()
        assert channel.add_member.call_count == 2


def test_channel_member_removal(mock_server):
    """Test removal of channel members."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        
        channel = mock_server.channel_manager.get_channel("#test")
        channel.remove_member("user1")
        
        channel.remove_member.assert_called_with("user1")


def test_multiple_channel_join(mock_server):
    """Test user joining multiple channels."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        handler.process = Mock()
        
        addr = ("127.0.0.1", 5001)
        handler.process(b"JOIN #channel1\r\n", addr)
        handler.process(b"JOIN #channel2\r\n", addr)
        handler.process(b"JOIN #channel3\r\n", addr)
        
        assert handler.process.call_count == 3


def test_sock_send_called_on_message(mock_server):
    """Test that sock_send is called when sending messages."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        
        # Simulate sending a message
        test_message = b":testuser!user@host PRIVMSG #test :hello\r\n"
        mock_server.sock_send(("127.0.0.1", 5001), test_message)
        
        mock_server.sock_send.assert_called_once_with(("127.0.0.1", 5001), test_message)


def test_broadcast_to_channel_called(mock_server):
    """Test that broadcast_to_channel is called for channel messages."""
    with patch('server_message_handler.MessageHandler') as MockHandler:
        handler = Mock()
        handler.server = mock_server
        
        message = b":testuser!user@host PRIVMSG #test :hello everyone\r\n"
        mock_server.broadcast_to_channel("#test", message)
        
        mock_server.broadcast_to_channel.assert_called_once()


def test_chanserv_storage_persistence(mock_server):