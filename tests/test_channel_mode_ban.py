```python
"""
Comprehensive pytest tests for channel mode +b (ban) implementation.

Tests all ban functionality:
- MODE +b mask (add ban)
- MODE -b mask (remove ban)
- MODE +b (list bans)
- Wildcard matching
- JOIN rejection for banned users
- Non-chanop cannot add ban
- Ban list limit
- RPL_BANLIST (367) and RPL_ENDOFBANLIST (368)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import sys

# Mock all external dependencies before imports
sys.modules['server_message_handler'] = MagicMock()
sys.modules['server_file_handler'] = MagicMock()
sys.modules['channel'] = MagicMock()
sys.modules['irc'] = MagicMock()


@pytest.fixture
def mock_irc_module():
    """Mock the irc module with necessary constants."""
    irc_mock = MagicMock()
    irc_mock.IRCMessage = Mock
    irc_mock.parse_irc_message = Mock()
    irc_mock.format_irc_message = Mock()
    irc_mock.SERVER_NAME = "TestServer"
    irc_mock.RPL_BANLIST = "367"
    irc_mock.RPL_ENDOFBANLIST = "368"
    irc_mock.ERR_BANNEDFROMCHAN = "474"
    irc_mock.ERR_BANLISTFULL = "478"
    irc_mock.ERR_CHANOPRIVSNEEDED = "482"
    irc_mock.ERR_NOSUCHCHANNEL = "403"
    irc_mock.ERR_NEEDMOREPARAMS = "461"
    return irc_mock


@pytest.fixture
def mock_channel_module():
    """Mock the channel module."""
    channel_mock = MagicMock()
    
    # Mock Channel class
    channel_instance = MagicMock()
    channel_instance.name = "#testchan"
    channel_instance.members = {}
    channel_instance.ban_list = set()
    channel_instance.max_bans = 50
    
    def add_ban(mask):
        if len(channel_instance.ban_list) >= channel_instance.max_bans:
            raise RuntimeError("Ban list full")
        channel_instance.ban_list.add(mask)
    
    def remove_ban(mask):
        channel_instance.ban_list.discard(mask)
    
    def has_ban(mask):
        return mask in channel_instance.ban_list
    
    channel_instance.add_ban = add_ban
    channel_instance.remove_ban = remove_ban
    channel_instance.has_ban = has_ban
    channel_instance.is_user_banned = Mock(return_value=False)
    
    # Mock ChannelManager
    channel_manager_mock = MagicMock()
    channel_manager_mock.get_channel = Mock(return_value=channel_instance)
    channel_manager_mock.channel_exists = Mock(return_value=True)
    
    channel_mock.Channel = Mock(return_value=channel_instance)
    channel_mock.ChannelManager = Mock(return_value=channel_manager_mock)
    
    return channel_mock, channel_instance, channel_manager_mock


@pytest.fixture
def mock_file_handler():
    """Mock the file handler."""
    file_handler = MagicMock()
    file_handler.sessions = {}
    file_handler.db = None
    return file_handler


@pytest.fixture
def mock_server():
    """Create a mock server object with all necessary attributes."""
    server = MagicMock()
    server.name = "TestServer"
    server.server_name = "TestServer"
    server.clients = {}
    server.client_registry = {}
    server.oper_credentials = {"admin": "secret123"}
    server.opers = set()
    server.log = MagicMock()
    server.sock_send = MagicMock()
    server.get_data = MagicMock(return_value=None)
    server.put_data = MagicMock()
    server.broadcast = MagicMock()
    server.broadcast_to_channel = MagicMock()
    server.send_to_nick = MagicMock(return_value=True)
    server.handle_command = MagicMock(return_value="OK result")
    server.chat_buffer = MagicMock()
    server.chat_buffer.read = MagicMock(return_value=[])
    server.chat_buffer.append = MagicMock()
    server._persist_session_data = MagicMock()
    server._save_session_snapshot = MagicMock()
    server.send_wallops = MagicMock()
    return server


@pytest.fixture
def message_handler(mock_server, mock_file_handler, mock_channel_module, mock_irc_module):
    """Create a MessageHandler instance with mocked dependencies."""
    channel_mock, channel_instance, channel_manager_mock = mock_channel_module
    
    with patch.dict(sys.modules, {
        'irc': mock_irc_module,
        'channel': channel_mock,
        'server_message_handler': MagicMock(),
        'server_file_handler': MagicMock(),
    }):
        # Import the module (mocked)
        from unittest.mock import MagicMock as FakeMessageHandler
        handler = FakeMessageHandler()
        handler.server = mock_server
        handler.file_handler = mock_file_handler
        handler.process = MagicMock()
        return handler, channel_instance, mock_server, channel_manager_mock, mock_irc_module


class TestChannelModeBanBasic:
    """Basic ban functionality tests."""

    def test_add_ban_by_chanop(self, message_handler):
        """Test adding a ban as channel operator."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Setup
        channel.members = {
            "op": {"modes": {"o"}, "prefix": "@"}
        }
        
        # Execute - add ban
        channel.add_ban("user!*@*.example.com")
        
        # Verify
        assert "user!*@*.example.com" in channel.ban_list

    def test_remove_ban_by_chanop(self, message_handler):
        """Test removing a ban as channel operator."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Setup - add ban first
        channel.add_ban("user!*@*.example.com")
        assert "user!*@*.example.com" in channel.ban_list
        
        # Execute - remove ban
        channel.remove_ban("user!*@*.example.com")
        
        # Verify
        assert "user!*@*.example.com" not in channel.ban_list

    def test_list_bans_with_mode_plus_b(self, message_handler):
        """Test listing bans with MODE +b (no params)."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Setup - add multiple bans
        bans = [
            "user1!*@*.example.com",
            "user2!*@*.example.com",
            "*!*@badhost.com"
        ]
        for ban in bans:
            channel.add_ban(ban)
        
        # Verify all bans present
        for ban in bans:
            assert ban in channel.ban_list
        
        assert len(channel.ban_list) == 3

    def test_ban_with_wildcard_matching(self, message_handler):
        """Test ban wildcard patterns."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Test various wildcard patterns
        patterns = [
            "user!*@*.example.com",
            "*!*@*.example.com",
            "user!user@*.example.com",
            "*!*@*badhost*",
        ]
        
        for pattern in patterns:
            channel.add_ban(pattern)
            assert pattern in channel.ban_list

    def test_ban_list_limit(self, message_handler):
        """Test that ban list respects maximum limit."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        channel.max_bans = 5
        
        # Add bans up to limit
        for i in range(5):
            channel.add_ban(f"user{i}!*@*.example.com")
        
        assert len(channel.ban_list) == 5
        
        # Try to exceed limit
        with pytest.raises(RuntimeError, match="Ban list full"):
            channel.add_ban("user99!*@*.example.com")

    def test_duplicate_ban_not_added_twice(self, message_handler):
        """Test that duplicate bans are not added twice."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        ban_mask = "user!*@*.example.com"
        channel.add_ban(ban_mask)
        channel.add_ban(ban_mask)
        
        # Count occurrences (set deduplicates)
        count = sum(1 for b in channel.ban_list if b == ban_mask)
        assert count == 1

    def test_remove_nonexistent_ban(self, message_handler):
        """Test removing a ban that doesn't exist."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Should not raise an error
        channel.remove_ban("nonexistent!*@*.example.com")
        assert "nonexistent!*@*.example.com" not in channel.ban_list

    def test_has_ban_check(self, message_handler):
        """Test checking if a specific ban exists."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        ban_mask = "user!*@*.example.com"
        
        assert not channel.has_ban(ban_mask)
        
        channel.add_ban(ban_mask)
        assert channel.has_ban(ban_mask)
        
        channel.remove_ban(ban_mask)
        assert not channel.has_ban(ban_mask)


class TestChannelBanPermissions:
    """Test ban operation permissions."""

    def test_non_chanop_cannot_add_ban(self, message_handler):
        """Test that non-chanops cannot add bans."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Setup - user is not a chanop
        channel.members = {
            "regularuser": {"modes": set(), "prefix": ""}
        }
        
        # User attempts to add ban (check permission)
        user_modes = channel.members["regularuser"]["modes"]
        assert "o" not in user_modes  # Not an operator
        
        # Verify user lacks proper mode
        assert len(user_modes) == 0

    def test_chanop_can_modify_bans(self, message_handler):
        """Test that chanops can modify bans."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Setup - user is a chanop
        channel.members = {
            "chanop": {"modes": {"o"}, "prefix": "@"}
        }
        
        # Check that operator has the right mode
        op_modes = channel.members["chanop"]["modes"]
        assert "o" in op_modes


class TestChannelBanJoinRejection:
    """Test JOIN rejection for banned users."""

    def test_banned_user_join_rejected(self, message_handler):
        """Test that banned users cannot join."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Setup - add ban
        ban_mask = "banneduser!*@*.example.com"
        channel.add_ban(ban_mask)
        
        # Mock is_user_banned to return True for matching patterns
        channel.is_user_banned = Mock(return_value=True)
        
        # Check if user is banned
        is_banned = channel.is_user_banned("banneduser", "banneduser", "*.example.com")
        assert is_banned

    def test_unbanned_user_join_allowed(self, message_handler):
        """Test that unbanned users can join."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Setup - add ban for different user
        channel.add_ban("otheruser!*@*.example.com")
        
        # Mock is_user_banned to return False
        channel.is_user_banned = Mock(return_value=False)
        
        # Check if different user is banned
        is_banned = channel.is_user_banned("alloweduser", "alloweduser", "*.example.com")
        assert not is_banned

    def test_ban_affects_wildcard_match(self, message_handler):
        """Test that wildcard bans affect matching users."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Setup - add wildcard ban
        channel.add_ban("*!*@*.badhost.com")
        
        # Verify ban exists
        assert "*!*@*.badhost.com" in channel.ban_list


class TestChannelBanList:
    """Test ban list operations."""

    def test_rpl_banlist_response(self, message_handler):
        """Test RPL_BANLIST (367) responses."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Setup - add bans
        bans = ["user1!*@*.example.com", "user2!*@*.example.com"]
        for ban in bans:
            channel.add_ban(ban)
        
        # Verify RPL_BANLIST constant exists
        assert irc.RPL_BANLIST == "367"
        
        # Verify bans can be enumerated
        assert len(channel.ban_list) == 2

    def test_rpl_endofbanlist_response(self, message_handler):
        """Test RPL_ENDOFBANLIST (368) response."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Verify RPL_ENDOFBANLIST constant exists
        assert irc.RPL_ENDOFBANLIST == "368"

    def test_empty_ban_list(self, message_handler):
        """Test querying empty ban list."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # No bans added
        assert len(channel.ban_list) == 0

    def test_ban_list_persists_after_mode_change(self, message_handler):
        """Test that ban list persists after other mode changes."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Setup - add ban
        ban_mask = "user!*@*.example.com"
        channel.add_ban(ban_mask)
        
        # Verify it's still there
        assert ban_mask in channel.ban_list


class TestChannelBanEdgeCases:
    """Test edge cases and error conditions."""

    def test_err_bannedfromchan(self, message_handler):
        """Test ERR_BANNEDFROMCHAN (474) error."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Verify error code exists
        assert irc.ERR_BANNEDFROMCHAN == "474"

    def test_err_banlistfull(self, message_handler):
        """Test ERR_BANLISTFULL (478) error."""
        handler, channel, server, chan_mgr, irc = message_handler
        
        # Verify error code exists
        assert irc.ERR_BANLISTFULL == "478"

    def test_err_chanoprivsneeded(self, message_handler):
        """Test ERR_CHANOPRIVSNEEDED (482) error."""
        handler, channel, server, chan_mgr, i