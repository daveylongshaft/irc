```python
#!/usr/bin/env python3
"""
pytest test file for csc_server.server_message_handler MessageHandler TOPIC command.
Tests the _handle_topic method and related channel topic functionality.
"""

import pytest
from unittest.mock import MagicMock, patch, call
from csc_server.server_message_handler import MessageHandler
from csc_shared.channel import ChannelManager
from csc_server.server import Server
from csc_shared.irc import IRCMessage


@pytest.fixture
def mock_server():
    """Create a mock server with channel manager and necessary attributes."""
    server = MagicMock(spec=Server)
    server.channel_manager = ChannelManager()
    server.clients = {}
    server.opers = set()
    server.sock_send = MagicMock()
    server.log = MagicMock()
    return server


@pytest.fixture
def handler(mock_server):
    """Create a MessageHandler instance with mocked server."""
    return MessageHandler(mock_server, MagicMock())


@pytest.fixture
def test_addresses():
    """Define test user addresses."""
    return {
        'op': ('127.0.0.1', 1024),
        'user': ('127.0.0.1', 1025),
        'other': ('127.0.0.1', 1026),
    }


@pytest.fixture
def setup_users(mock_server, handler, test_addresses):
    """Register test users in the handler and server."""
    op_addr = test_addresses['op']
    user_addr = test_addresses['user']
    other_addr = test_addresses['other']
    
    # Register users in handler
    handler.registration_state[op_addr] = {
        'nick': 'ChanOp',
        'user': 'op',
        'state': 'registered'
    }
    handler.registration_state[user_addr] = {
        'nick': 'RegUser',
        'user': 'user',
        'state': 'registered'
    }
    handler.registration_state[other_addr] = {
        'nick': 'OtherUser',
        'user': 'other',
        'state': 'registered'
    }
    
    # Register users in server
    mock_server.clients[op_addr] = {'name': 'ChanOp'}
    mock_server.clients[user_addr] = {'name': 'RegUser'}
    mock_server.clients[other_addr] = {'name': 'OtherUser'}
    
    return test_addresses


@pytest.fixture
def test_channel(mock_server, setup_users, test_addresses):
    """Create a test channel with members."""
    test_chan_name = '#test'
    test_chan = mock_server.channel_manager.ensure_channel(test_chan_name)
    
    op_addr = test_addresses['op']
    user_addr = test_addresses['user']
    
    test_chan.add_member('ChanOp', op_addr, modes={'o'})
    test_chan.add_member('RegUser', user_addr)
    
    return test_chan_name, test_chan


def get_sent_numerics(mock_server, addr):
    """Helper to extract numeric replies sent to a specific address."""
    numerics = []
    for call_obj in mock_server.sock_send.call_args_list:
        if call_obj[0][1] == addr:
            msg = call_obj[0][0].decode()
            parts = msg.strip().split()
            if len(parts) > 1 and parts[1].isdigit():
                numerics.append(parts[1])
    return numerics


class TestTopicCommandQuery:
    """Tests for querying topic."""

    def test_query_topic_no_topic_set(self, handler, mock_server, setup_users,
                                       test_channel, test_addresses):
        """Test querying topic when none is set."""
        test_chan_name, _ = test_channel
        user_addr = test_addresses['user']
        
        msg = IRCMessage(command='TOPIC', params=[test_chan_name])
        handler._handle_topic(msg, user_addr)
        
        numerics = get_sent_numerics(mock_server, user_addr)
        assert '331' in numerics  # RPL_NOTOPIC

    def test_query_topic_with_topic_set(self, handler, mock_server, setup_users,
                                         test_channel, test_addresses):
        """Test querying topic when one is set."""
        test_chan_name, test_chan = test_channel
        user_addr = test_addresses['user']
        
        test_chan.topic = "This is a test topic."
        msg = IRCMessage(command='TOPIC', params=[test_chan_name])
        handler._handle_topic(msg, user_addr)
        
        numerics = get_sent_numerics(mock_server, user_addr)
        assert '332' in numerics  # RPL_TOPIC


class TestTopicCommandSet:
    """Tests for setting topic."""

    def test_set_topic_no_t_mode(self, handler, mock_server, setup_users,
                                  test_channel, test_addresses):
        """Test regular user setting topic in channel without +t mode."""
        test_chan_name, test_chan = test_channel
        user_addr = test_addresses['user']
        
        mock_server.broadcast_to_channel = MagicMock()
        msg = IRCMessage(command='TOPIC', params=[test_chan_name, 'New shiny topic'])
        handler._handle_topic(msg, user_addr)
        
        assert test_chan.topic == 'New shiny topic'
        mock_server.broadcast_to_channel.assert_called()
        broadcast_msg = mock_server.broadcast_to_channel.call_args[0][1]
        assert f"TOPIC {test_chan_name} :New shiny topic" in broadcast_msg

    def test_set_topic_with_t_mode_non_op(self, handler, mock_server, setup_users,
                                           test_channel, test_addresses):
        """Test regular user fails to set topic in +t channel."""
        test_chan_name, test_chan = test_channel
        user_addr = test_addresses['user']
        
        test_chan.modes.add('t')
        msg = IRCMessage(command='TOPIC', params=[test_chan_name, 'Should not work'])
        handler._handle_topic(msg, user_addr)
        
        assert test_chan.topic != 'Should not work'
        numerics = get_sent_numerics(mock_server, user_addr)
        assert '482' in numerics  # ERR_CHANOPRIVSNEEDED

    def test_set_topic_with_t_mode_chan_op(self, handler, mock_server, setup_users,
                                            test_channel, test_addresses):
        """Test channel operator can set topic in +t channel."""
        test_chan_name, test_chan = test_channel
        op_addr = test_addresses['op']
        
        mock_server.broadcast_to_channel = MagicMock()
        test_chan.modes.add('t')
        msg = IRCMessage(command='TOPIC', params=[test_chan_name, 'Op topic change'])
        handler._handle_topic(msg, op_addr)
        
        assert test_chan.topic == 'Op topic change'
        mock_server.broadcast_to_channel.assert_called()

    def test_set_topic_with_t_mode_irc_op(self, handler, mock_server, setup_users,
                                           test_channel, test_addresses):
        """Test IRC operator bypasses +t to set topic."""
        test_chan_name, test_chan = test_channel
        user_addr = test_addresses['user']
        
        mock_server.broadcast_to_channel = MagicMock()
        test_chan.modes.add('t')
        mock_server.opers.add('user')  # Make user an IRC op
        
        msg = IRCMessage(command='TOPIC', params=[test_chan_name, 'IRC op topic'])
        handler._handle_topic(msg, user_addr)
        
        assert test_chan.topic == 'IRC op topic'
        mock_server.broadcast_to_channel.assert_called()

    def test_set_topic_empty_string(self, handler, mock_server, setup_users,
                                     test_channel, test_addresses):
        """Test setting topic to empty string."""
        test_chan_name, test_chan = test_channel
        user_addr = test_addresses['user']
        
        mock_server.broadcast_to_channel = MagicMock()
        test_chan.topic = "Old topic"
        msg = IRCMessage(command='TOPIC', params=[test_chan_name, ''])
        handler._handle_topic(msg, user_addr)
        
        assert test_chan.topic == ''
        mock_server.broadcast_to_channel.assert_called()

    def test_set_topic_special_characters(self, handler, mock_server, setup_users,
                                          test_channel, test_addresses):
        """Test setting topic with special characters."""
        test_chan_name, test_chan = test_channel
        user_addr = test_addresses['user']
        
        mock_server.broadcast_to_channel = MagicMock()
        special_topic = "Test :) | Special @ Characters # $100"
        msg = IRCMessage(command='TOPIC', params=[test_chan_name, special_topic])
        handler._handle_topic(msg, user_addr)
        
        assert test_chan.topic == special_topic


class TestTopicCommandEdgeCases:
    """Tests for edge cases and error handling."""

    def test_topic_nonexistent_channel(self, handler, mock_server, setup_users,
                                       test_addresses):
        """Test handling topic command for non-existent channel."""
        user_addr = test_addresses['user']
        nonexistent_chan = '#nonexistent'
        
        msg = IRCMessage(command='TOPIC', params=[nonexistent_chan])
        handler._handle_topic(msg, user_addr)
        
        numerics = get_sent_numerics(mock_server, user_addr)
        # Should get error for non-existent or no-such-channel
        assert any(num in numerics for num in ['403', '403'])

    def test_topic_user_not_in_channel(self, handler, mock_server, setup_users,
                                       test_channel, test_addresses):
        """Test setting topic when user is not in channel."""
        test_chan_name, _ = test_channel
        other_addr = test_addresses['other']
        
        msg = IRCMessage(command='TOPIC', params=[test_chan_name, 'New topic'])
        handler._handle_topic(msg, other_addr)
        
        numerics = get_sent_numerics(mock_server, other_addr)
        # Should get error for not being in channel
        assert any(num in numerics for num in ['442', '403'])

    def test_topic_multiple_colons_in_topic(self, handler, mock_server, setup_users,
                                            test_channel, test_addresses):
        """Test topic with multiple colons."""
        test_chan_name, test_chan = test_channel
        user_addr = test_addresses['user']
        
        mock_server.broadcast_to_channel = MagicMock()
        topic_with_colons = "URL: http://example.com:8080 - Info: v1.0"
        msg = IRCMessage(command='TOPIC', params=[test_chan_name, topic_with_colons])
        handler._handle_topic(msg, user_addr)
        
        assert test_chan.topic == topic_with_colons

    def test_topic_long_string(self, handler, mock_server, setup_users,
                               test_channel, test_addresses):
        """Test setting a very long topic."""
        test_chan_name, test_chan = test_channel
        user_addr = test_addresses['user']
        
        mock_server.broadcast_to_channel = MagicMock()
        long_topic = "x" * 500
        msg = IRCMessage(command='TOPIC', params=[test_chan_name, long_topic])
        handler._handle_topic(msg, user_addr)
        
        # Topic should be set (IRC doesn't typically limit topic length strictly)
        assert test_chan.topic == long_topic


class TestTopicBroadcast:
    """Tests for topic broadcast functionality."""

    def test_topic_broadcast_includes_source_nick(self, handler, mock_server, setup_users,
                                                   test_channel, test_addresses):
        """Test that topic broadcast includes the source user's nick."""
        test_chan_name, test_chan = test_channel
        op_addr = test_addresses['op']
        
        mock_server.broadcast_to_channel = MagicMock()
        msg = IRCMessage(command='TOPIC', params=[test_chan_name, 'Broadcast test'])
        handler._handle_topic(msg, op_addr)
        
        # Verify broadcast was called
        mock_server.broadcast_to_channel.assert_called()
        broadcast_msg = mock_server.broadcast_to_channel.call_args[0][1]
        # Broadcast should contain TOPIC command
        assert 'TOPIC' in broadcast_msg

    def test_topic_no_broadcast_on_query(self, handler, mock_server, setup_users,
                                         test_channel, test_addresses):
        """Test that querying topic doesn't broadcast."""
        test_chan_name, test_chan = test_channel
        user_addr = test_addresses['user']
        
        test_chan.topic = "Existing topic"
        mock_server.broadcast_to_channel = MagicMock()
        
        msg = IRCMessage(command='TOPIC', params=[test_chan_name])
        handler._handle_topic(msg, user_addr)
        
        # Querying should not broadcast
        mock_server.broadcast_to_channel.assert_not_called()


class TestTopicWithChannelModes:
    """Tests for topic handling with various channel modes."""

    def test_topic_mode_t_prevents_non_op_change(self, handler, mock_server, setup_users,
                                                   test_channel, test_addresses):
        """Test +t mode prevents non-ops from changing topic."""
        test_chan_name, test_chan = test_channel
        user_addr = test_addresses['user']
        
        test_chan.modes.add('t')
        original_topic = "Original"
        test_chan.topic = original_topic
        
        msg = IRCMessage(command='TOPIC', params=[test_chan_name, 'Unauthorized'])
        handler._handle_topic(msg, user_addr)
        
        assert test_chan.topic == original_topic
        numerics = get_sent_numerics(mock_server, user_addr)
        assert '482' in numerics

    def test_topic_without_t_mode_allows_any_user(self, handler, mock_server, setup_users,
                                                    test_channel, test_addresses):
        """Test without +t mode, any channel member can change topic."""
        test_chan_name, test_chan = test_channel
        user_addr = test_addresses['user']
        
        # Ensure +t is not set
        test_chan.modes.discard('t')
        
        mock_server.broadcast_to_channel = MagicMock()
        msg = IRCMessage(command='TOPIC', params=[test_chan_name, 'User change'])
        handler._handle_topic(msg, user_addr)
        
        assert test_chan.topic == 'User change'
        mock_server.broadcast_to_channel.assert_called()
```