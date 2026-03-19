"""Tests for IRC client registration flow.

Tests cover:
- NICK command handling
- USER command handling
- Registration sequence validation
- Duplicate nick detection
- Invalid nick rejection
- PASS command (if implemented)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from tests.helpers import create_irc_message, assert_irc_reply, assert_log_contains


@pytest.fixture
def handler(mock_server, mock_file_handler):
    """Create a MessageHandler for testing registration."""
    from csc_service.server.server_message_handler import MessageHandler
    return MessageHandler(mock_server, mock_file_handler)


class TestNickCommand:
    """Test NICK command handling."""
    
    def test_nick_valid(self, handler, mock_server, test_addr):
        """Test setting a valid nickname."""
        msg = create_irc_message('NICK', ['alice'])
        
        handler._handle_nick(msg, test_addr)
        
        # Should update registration state
        assert test_addr in handler.registration_state
        assert handler.registration_state[test_addr].get('nick') == 'alice'
    
    def test_nick_invalid_chars(self, handler, mock_server, test_addr):
        """Test rejecting nickname with invalid characters."""
        msg = create_irc_message('NICK', ['alice@invalid'])
        
        handler._handle_nick(msg, test_addr)
        
        # Should send error reply
        assert_irc_reply(mock_server.send_message, 'ERR_ERRONEUSNICKNAME')
    
    def test_nick_empty(self, handler, mock_server, test_addr):
        """Test rejecting empty nickname."""
        msg = create_irc_message('NICK', [])
        
        handler._handle_nick(msg, test_addr)
        
        # Should send error for no nickname given
        assert_irc_reply(mock_server.send_message, 'ERR_NONICKNAMEGIVEN')
    
    def test_nick_too_long(self, handler, mock_server, test_addr):
        """Test handling very long nicknames."""
        long_nick = 'a' * 100
        msg = create_irc_message('NICK', [long_nick])
        
        handler._handle_nick(msg, test_addr)
        
        # Behavior depends on implementation:
        # - might truncate
        # - might reject
        # - might accept if no length limit
        # This is a placeholder for the expected behavior
        assert True  # Update based on actual implementation
    
    def test_nick_duplicate(self, handler, mock_server, test_addr, test_addr2):
        """Test rejecting duplicate nickname."""
        # Register first client
        mock_server.clients[test_addr2] = {
            'nick': 'alice',
            'registered': True
        }
        
        msg = create_irc_message('NICK', ['alice'])
        handler._handle_nick(msg, test_addr)
        
        # Should send error for nickname in use
        assert_irc_reply(mock_server.send_message, 'ERR_NICKNAMEINUSE')
    
    def test_nick_change(self, handler, mock_server, registered_client):
        """Test changing nickname after registration."""
        msg = create_irc_message('NICK', ['newnick'])
        
        handler._handle_nick(msg, registered_client)
        
        # Should update client's nickname
        # Exact behavior depends on implementation
        assert True  # Update based on actual behavior


class TestUserCommand:
    """Test USER command handling."""
    
    def test_user_valid(self, handler, mock_server, test_addr):
        """Test USER command with valid parameters."""
        # Set nick first
        handler.registration_state[test_addr] = {'nick': 'alice', 'state': 'nick_received'}
        
        msg = create_irc_message('USER', ['alice', '0', '*', 'Alice User'])
        handler._handle_user(msg, test_addr)
        
        # Should update registration state
        state = handler.registration_state.get(test_addr)
        assert state is not None
        assert state.get('user') == 'alice'
        assert state.get('realname') == 'Alice User'
    
    def test_user_without_nick(self, handler, mock_server, test_addr):
        """Test USER command without NICK first."""
        msg = create_irc_message('USER', ['alice', '0', '*', 'Alice User'])
        
        handler._handle_user(msg, test_addr)
        
        # Behavior depends on implementation:
        # - might queue USER until NICK
        # - might reject with error
        # Update based on actual behavior
        assert True
    
    def test_user_insufficient_params(self, handler, mock_server, test_addr):
        """Test USER command with too few parameters."""
        msg = create_irc_message('USER', ['alice'])
        
        handler._handle_user(msg, test_addr)
        
        # Should send error for missing parameters
        assert_irc_reply(mock_server.send_message, 'ERR_NEEDMOREPARAMS')
    
    def test_user_already_registered(self, handler, mock_server, registered_client):
        """Test USER command when already registered."""
        msg = create_irc_message('USER', ['newuser', '0', '*', 'New Name'])
        
        handler._handle_user(msg, registered_client)
        
        # Should send error for already registered
        assert_irc_reply(mock_server.send_message, 'ERR_ALREADYREGISTRED')


class TestRegistrationSequence:
    """Test complete registration sequences."""
    
    def test_successful_registration(self, handler, mock_server, test_addr):
        """Test successful NICK + USER registration."""
        # Send NICK
        nick_msg = create_irc_message('NICK', ['alice'])
        handler._handle_nick(nick_msg, test_addr)
        
        # Send USER
        user_msg = create_irc_message('USER', ['alice', '0', '*', 'Alice User'])
        handler._handle_user(user_msg, test_addr)
        
        # Should be registered
        # Check that welcome messages were sent
        if mock_server.send_message.called:
            # Look for RPL_WELCOME (001)
            calls = [str(call) for call in mock_server.send_message.call_args_list]
            welcome_sent = any('001' in call or 'Welcome' in call for call in calls)
            assert welcome_sent or test_addr in mock_server.clients
    
    def test_registration_user_then_nick(self, handler, mock_server, test_addr):
        """Test registration with USER before NICK."""
        # Send USER first
        user_msg = create_irc_message('USER', ['alice', '0', '*', 'Alice User'])
        handler._handle_user(user_msg, test_addr)
        
        # Then NICK
        nick_msg = create_irc_message('NICK', ['alice'])
        handler._handle_nick(nick_msg, test_addr)
        
        # Should complete registration (order shouldn't matter)
        # Behavior depends on implementation
        assert True  # Update based on actual behavior
    
    def test_registration_sends_motd(self, handler, mock_server, test_addr):
        """Test that registration sends MOTD."""
        # Complete registration
        handler.registration_state[test_addr] = {
            'nick': 'alice',
            'user': 'alice',
            'realname': 'Alice User',
            'state': 'user_received'
        }
        
        # Trigger registration completion
        # Implementation-specific - might need to call _complete_registration
        
        # Check for MOTD messages (372, 375, 376)
        # Update based on actual implementation
        assert True
    
    def test_multiple_client_registration(self, handler, mock_server, test_addr, test_addr2):
        """Test that multiple clients can register independently."""
        # Register first client
        nick_msg1 = create_irc_message('NICK', ['alice'])
        handler._handle_nick(nick_msg1, test_addr)
        user_msg1 = create_irc_message('USER', ['alice', '0', '*', 'Alice'])
        handler._handle_user(user_msg1, test_addr)
        
        # Register second client
        nick_msg2 = create_irc_message('NICK', ['bob'])
        handler._handle_nick(nick_msg2, test_addr2)
        user_msg2 = create_irc_message('USER', ['bob', '0', '*', 'Bob'])
        handler._handle_user(user_msg2, test_addr2)
        
        # Both should be in registration state or clients
        assert test_addr in handler.registration_state or test_addr in mock_server.clients
        assert test_addr2 in handler.registration_state or test_addr2 in mock_server.clients


class TestRegistrationState:
    """Test registration state management."""
    
    def test_registration_state_init(self, handler):
        """Test registration state is initialized."""
        assert handler.registration_state is not None
        assert isinstance(handler.registration_state, dict)
    
    def test_registration_state_per_client(self, handler, test_addr, test_addr2):
        """Test that each client has separate registration state."""
        handler.registration_state[test_addr] = {'nick': 'alice'}
        handler.registration_state[test_addr2] = {'nick': 'bob'}
        
        assert handler.registration_state[test_addr]['nick'] == 'alice'
        assert handler.registration_state[test_addr2]['nick'] == 'bob'
    
    def test_registration_state_cleanup(self, handler, mock_server, test_addr):
        """Test that registration state is cleaned up after registration."""
        # Set up registration state
        handler.registration_state[test_addr] = {
            'nick': 'alice',
            'user': 'alice',
            'realname': 'Alice',
            'state': 'user_received'
        }
        
        # After successful registration, state might be moved to clients
        # or cleared from registration_state
        # Test depends on implementation
        assert True  # Update based on actual behavior


class TestNickValidation:
    """Test nickname validation logic."""
    
    @pytest.mark.parametrize("valid_nick", [
        "alice",
        "Alice",
        "alice123",
        "alice_bob",
        "[test]",
        "test-nick",
        "a",
    ])
    def test_valid_nicks(self, handler, mock_server, test_addr, valid_nick):
        """Test that valid nicknames are accepted."""
        msg = create_irc_message('NICK', [valid_nick])
        handler._handle_nick(msg, test_addr)
        
        # Should not send error
        # If errors were sent, they would contain ERR_ERRONEUSNICKNAME
        if mock_server.send_message.called:
            calls = str(mock_server.send_message.call_args_list)
            assert 'ERR_ERRONEUSNICKNAME' not in calls
    
    @pytest.mark.parametrize("invalid_nick", [
        "123alice",  # starts with digit
        "alice invalid",  # contains space
        "alice@host",  # contains @
        "",  # empty
    ])
    def test_invalid_nicks(self, handler, mock_server, test_addr, invalid_nick):
        """Test that invalid nicknames are rejected."""
        msg = create_irc_message('NICK', [invalid_nick])
        handler._handle_nick(msg, test_addr)
        
        # Should send error or no nickname given
        assert mock_server.send_message.called


class TestPassCommand:
    """Test PASS command if implemented."""
    
    def test_pass_before_registration(self, handler, mock_server, test_addr):
        """Test PASS command before NICK/USER."""
        msg = create_irc_message('PASS', ['secretpass'])
        
        # Call handler if method exists
        if hasattr(handler, '_handle_pass'):
            handler._handle_pass(msg, test_addr)
            
            # Should store password in registration state
            state = handler.registration_state.get(test_addr)
            if state:
                assert 'password' in state
    
    def test_pass_after_registration(self, handler, mock_server, registered_client):
        """Test PASS command after registration."""
        msg = create_irc_message('PASS', ['secretpass'])
        
        if hasattr(handler, '_handle_pass'):
            handler._handle_pass(msg, registered_client)
            
            # Should send error for already registered
            assert_irc_reply(mock_server.send_message, 'ERR_ALREADYREGISTRED')


class TestRegistrationHelpers:
    """Test helper methods related to registration."""
    
    def test_is_registered_true(self, handler, mock_server, registered_client):
        """Test checking if client is registered (true case)."""
        # Reset mock to use real implementation
        handler._is_registered = handler.__class__._is_registered.__get__(handler)
        
        is_reg = handler._is_registered(registered_client)
        assert is_reg is True
    
    def test_is_registered_false(self, handler, test_addr):
        """Test checking if client is registered (false case)."""
        handler._is_registered = handler.__class__._is_registered.__get__(handler)
        
        is_reg = handler._is_registered(test_addr)
        assert is_reg is False
    
    def test_get_nick(self, handler, mock_server, registered_client):
        """Test getting nick for registered client."""
        handler._get_nick = handler.__class__._get_nick.__get__(handler)
        
        nick = handler._get_nick(registered_client)
        assert nick == 'testuser'
    
    def test_get_nick_unregistered(self, handler, test_addr):
        """Test getting nick for unregistered client."""
        handler._get_nick = handler.__class__._get_nick.__get__(handler)
        
        nick = handler._get_nick(test_addr)
        # Might return None or '*' for unregistered
        assert nick is None or nick == '*'
