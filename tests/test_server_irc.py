```python
# --- Imports MUST come first ---
import pytest
from unittest.mock import Mock, MagicMock, patch, call
import time
import sys
import os

# --- Add Parent Directories to Path ---
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
server_dir = os.path.join(parent_dir, "server")
shared_dir = os.path.join(parent_dir, "shared")
for d in [parent_dir, server_dir, shared_dir]:
    if d not in sys.path:
        sys.path.insert(0, d)
# --- End Path Modification ---

try:
    from csc_service.server.server_message_handler import MessageHandler
    from csc_service.server.server_file_handler import FileHandler
    from csc_service.shared.channel import ChannelManager
    from csc_service.shared.irc import (
        IRCMessage, parse_irc_message, format_irc_message, SERVER_NAME,
        RPL_WELCOME, RPL_YOURHOST, RPL_CREATED, RPL_MYINFO,
        RPL_LIST, RPL_LISTEND, RPL_NOTOPIC, RPL_TOPIC,
        RPL_NAMREPLY, RPL_ENDOFNAMES,
        RPL_MOTDSTART, RPL_MOTD, RPL_ENDOFMOTD, RPL_YOUREOPER,
        ERR_NOSUCHNICK, ERR_NOSUCHCHANNEL, ERR_CANNOTSENDTOCHAN,
        ERR_NORECIPIENT, ERR_NOTEXTTOSEND, ERR_NONICKNAMEGIVEN,
        ERR_ERRONEUSNICKNAME, ERR_NICKNAMEINUSE,
        ERR_USERNOTINCHANNEL, ERR_NOTONCHANNEL, ERR_NOTREGISTERED,
        ERR_NEEDMOREPARAMS, ERR_ALREADYREGISTRED, ERR_PASSWDMISMATCH,
        ERR_CHANOPRIVSNEEDED,
    )
    _IMPORTS_OK = True
except ImportError as e:
    print(f"ImportError: {e}")
    _IMPORTS_OK = False


def _build_mock_server():
    """Create a mock server object with all attributes needed by MessageHandler."""
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
    server.storage = Mock()
    server.storage.nickserv_get = Mock(return_value=None)
    server.storage.chanserv_get = Mock(return_value={
        "banlist": [],
        "oplist": [],
        "voicelist": [],
        "modes": ["t", "n"],
        "topic": ""
    })
    server.storage.load_settings = Mock(return_value={"nickserv": {"enforce_timeout": 60, "enforce_mode": "disconnect"}})
    server.storage.load_users = Mock(return_value={"users": {}})
    server.storage.add_active_oper = Mock(side_effect=lambda nick: server.opers.add(nick))
    server.storage.remove_active_oper = Mock(side_effect=lambda nick: server.opers.discard(nick))
    server.nickserv_identified = {}
    server.s2s_network = Mock()
    server.s2s_network.get_user_from_network = Mock(return_value=None)
    server._persist_session_data = Mock()
    return server


def _register_client(handler, addr, nick, server):
    """Complete a full NICK+USER registration for a client."""
    nick_data = f"NICK {nick}\r\n".encode("utf-8")
    handler.process(nick_data, addr)
    user_data = f"USER {nick} 0 * :{nick}\r\n".encode("utf-8")
    handler.process(user_data, addr)
    server.channel_manager.ensure_channel("#general").add_member(nick, addr)
    server.sock_send.reset_mock()


def _sent_lines(server):
    """Extract all sent IRC lines from sock_send mock calls."""
    lines = []
    for c in server.sock_send.call_args_list:
        data = c[0][0]
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="ignore")
        lines.append(data)
    return lines


def _sent_text(server):
    """Join all sent lines into a single string for searching."""
    return "".join(_sent_lines(server))


@pytest.mark.skipif(not _IMPORTS_OK, reason="Skipping tests because imports failed.")
class TestRegistration:
    """Tests for NICK, USER, PASS registration flow."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup the test fixture."""
        self.server = _build_mock_server()
        self.file_handler = Mock()
        self.file_handler.sessions = {}
        self.handler = MessageHandler(self.server, self.file_handler)
        self.addr = ("127.0.0.1", 50000)

    def test_nick_and_user_completes_registration_with_welcome_burst(self):
        """NICK + USER completes registration and sends 001-004 welcome burst."""
        nick_data = b"NICK TestUser\r\n"
        self.handler.process(nick_data, self.addr)
        user_data = b"USER TestUser 0 * :Test User\r\n"
        self.handler.process(user_data, self.addr)

        text = _sent_text(self.server)
        assert RPL_WELCOME in text
        assert RPL_YOURHOST in text
        assert RPL_CREATED in text
        assert RPL_MYINFO in text
        assert "Welcome to" in text

    def test_nick_only_does_not_complete_registration(self):
        """NICK alone should not complete registration."""
        self.handler.process(b"NICK OnlyNick\r\n", self.addr)
        text = _sent_text(self.server)
        assert RPL_WELCOME not in text
        assert not self.handler._is_registered(self.addr)

    def test_user_only_does_not_complete_registration(self):
        """USER alone should not complete registration."""
        self.handler.process(b"USER someone 0 * :Some One\r\n", self.addr)
        text = _sent_text(self.server)
        assert RPL_WELCOME not in text
        assert not self.handler._is_registered(self.addr)

    def test_duplicate_nick_rejected(self):
        """Attempting to register with a nick already in use sends ERR_NICKNAMEINUSE."""
        _register_client(self.handler, self.addr, "ExistingNick", self.server)
        
        addr2 = ("127.0.0.1", 50001)
        self.handler.process(b"NICK ExistingNick\r\n", addr2)
        text = _sent_text(self.server)
        assert ERR_NICKNAMEINUSE in text

    def test_pass_with_wrong_password_rejected(self):
        """PASS with incorrect password sends ERR_PASSWDMISMATCH."""
        self.handler.process(b"PASS wrongpassword\r\n", self.addr)
        text = _sent_text(self.server)
        assert ERR_PASSWDMISMATCH in text

    def test_nick_change_after_registration(self):
        """Client can change nick after registration."""
        _register_client(self.handler, self.addr, "InitialNick", self.server)
        self.server.sock_send.reset_mock()
        
        self.handler.process(b"NICK NewNick\r\n", self.addr)
        assert self.handler._get_nick(self.addr) == "NewNick"

    def test_erroneous_nick_rejected(self):
        """Nick with invalid characters is rejected."""
        self.handler.process(b"NICK Invalid@Nick\r\n", self.addr)
        text = _sent_text(self.server)
        assert ERR_ERRONEUSNICKNAME in text or ERR_NONICKNAMEGIVEN in text

    def test_empty_nick_rejected(self):
        """Empty NICK command is rejected."""
        self.handler.process(b"NICK\r\n", self.addr)
        text = _sent_text(self.server)
        assert ERR_NONICKNAMEGIVEN in text or ERR_NEEDMOREPARAMS in text


@pytest.mark.skipif(not _IMPORTS_OK, reason="Skipping tests because imports failed.")
class TestPrivateMessaging:
    """Tests for private message (PRIVMSG) handling."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup the test fixture."""
        self.server = _build_mock_server()
        self.file_handler = Mock()
        self.file_handler.sessions = {}
        self.handler = MessageHandler(self.server, self.file_handler)
        self.addr1 = ("127.0.0.1", 50001)
        self.addr2 = ("127.0.0.1", 50002)

    def test_privmsg_to_registered_user(self):
        """PRIVMSG to a registered user is delivered."""
        _register_client(self.handler, self.addr1, "Sender", self.server)
        _register_client(self.handler, self.addr2, "Receiver", self.server)
        
        self.server.sock_send.reset_mock()
        self.handler.process(b"PRIVMSG Receiver :Hello there\r\n", self.addr1)
        
        self.server.send_to_nick.assert_called()

    def test_privmsg_to_nonexistent_user(self):
        """PRIVMSG to a nonexistent user sends ERR_NOSUCHNICK."""
        _register_client(self.handler, self.addr1, "Sender", self.server)
        self.server.sock_send.reset_mock()
        
        self.handler.process(b"PRIVMSG NonExistent :Hello\r\n", self.addr1)
        text = _sent_text(self.server)
        assert ERR_NOSUCHNICK in text

    def test_privmsg_without_recipient(self):
        """PRIVMSG without recipient sends ERR_NORECIPIENT."""
        _register_client(self.handler, self.addr1, "Sender", self.server)
        self.server.sock_send.reset_mock()
        
        self.handler.process(b"PRIVMSG\r\n", self.addr1)
        text = _sent_text(self.server)
        assert ERR_NORECIPIENT in text or ERR_NEEDMOREPARAMS in text

    def test_privmsg_without_text(self):
        """PRIVMSG without message text sends ERR_NOTEXTTOSEND."""
        _register_client(self.handler, self.addr1, "Sender", self.server)
        self.server.sock_send.reset_mock()
        
        self.handler.process(b"PRIVMSG Receiver\r\n", self.addr1)
        text = _sent_text(self.server)
        assert ERR_NOTEXTTOSEND in text or ERR_NEEDMOREPARAMS in text

    def test_privmsg_from_unregistered_user(self):
        """PRIVMSG from unregistered user sends ERR_NOTREGISTERED."""
        addr_unreg = ("127.0.0.1", 50003)
        self.handler.process(b"PRIVMSG Someone :Hi\r\n", addr_unreg)
        text = _sent_text(self.server)
        assert ERR_NOTREGISTERED in text


@pytest.mark.skipif(not _IMPORTS_OK, reason="Skipping tests because imports failed.")
class TestChannelOperations:
    """Tests for channel JOIN, PART, and related operations."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup the test fixture."""
        self.server = _build_mock_server()
        self.file_handler = Mock()
        self.file_handler.sessions = {}
        self.handler = MessageHandler(self.server, self.file_handler)
        self.addr1 = ("127.0.0.1", 60001)
        self.addr2 = ("127.0.0.1", 60002)

    def test_join_channel(self):
        """JOIN command adds user to channel."""
        _register_client(self.handler, self.addr1, "User1", self.server)
        self.server.sock_send.reset_mock()
        
        self.handler.process(b"JOIN #testchan\r\n", self.addr1)
        
        channel = self.server.channel_manager.get_channel("#testchan")
        assert channel is not None
        assert "User1" in channel.members

    def test_part_channel(self):
        """PART command removes user from channel."""
        _register_client(self.handler, self.addr1, "User1", self.server)
        self.handler.process(b"JOIN #testchan\r\n", self.addr1)
        self.server.sock_send.reset_mock()
        
        self.handler.process(b"PART #testchan\r\n", self.addr1)
        
        channel = self.server.channel_manager.get_channel("#testchan")
        assert "User1" not in channel.members

    def test_list_channels(self):
        """LIST command returns list of channels."""
        _register_client(self.handler, self.addr1, "User1", self.server)
        self.handler.process(b"JOIN #chan1\r\n", self.addr1)
        self.handler.process(b"JOIN #chan2\r\n", self.addr1)
        self.server.sock_send.reset_mock()
        
        self.handler.process(b"LIST\r\n", self.addr1)
        text = _sent_text(self.server)
        assert RPL_LIST in text or "#chan1" in text or "#chan2" in text

    def test_names_in_channel(self):
        """NAMES command returns users in a channel."""
        _register_client(self.handler, self.addr1, "User1", self.server)
        _register_client(self.handler, self.addr2, "User2", self.server)
        self.handler.process(b"JOIN #testchan\r\n", self.addr1)
        self.handler.process(b"JOIN #testchan\r\n", self.addr2)
        self.server.sock_send.reset_mock()
        
        self.handler.process(b"NAMES #testchan\r\n", self.addr1)
        text = _sent_text(self.server)
        assert RPL_NAMREPLY in text or "User1" in text or "User2" in text

    def test_privmsg_to_channel(self):
        """PRIVMSG to a channel broadcasts message to all members."""
        _register_client(self.handler, self.addr1, "User1", self.server)
        _register_client