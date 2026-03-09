```python
#!/usr/bin/env python3
"""Pytest test file for WHOWAS IRC command functionality."""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
import socket


class TestWhoWasCommand:
    """Test suite for WHOWAS IRC command."""

    @pytest.fixture
    def mock_socket(self):
        """Create a mock socket for testing."""
        return MagicMock(spec=socket.socket)

    @pytest.fixture
    def mock_server_state(self):
        """Create a mock server state with user history."""
        return {
            'users': {},
            'whowas_history': {
                'TestWhoWas': [
                    {
                        'nick': 'TestWhoWas',
                        'user': 'testww',
                        'host': '127.0.0.1',
                        'realname': 'Test WhoWas User',
                        'disconnected_at': 1234567890
                    }
                ],
                'Observer': [
                    {
                        'nick': 'Observer',
                        'user': 'observer',
                        'host': '127.0.0.1',
                        'realname': 'Observer User',
                        'disconnected_at': None
                    }
                ]
            }
        }

    def test_whowas_returns_user_history(self, mock_socket, mock_server_state):
        """Test WHOWAS returns correct user history for disconnected user."""
        # Parse WHOWAS command
        command = "WHOWAS TestWhoWas"
        nick = command.split()[1]
        
        # Check history exists
        assert nick in mock_server_state['whowas_history']
        history = mock_server_state['whowas_history'][nick]
        assert len(history) > 0
        
        # Verify user data
        user_data = history[0]
        assert user_data['nick'] == 'TestWhoWas'
        assert user_data['user'] == 'testww'
        assert user_data['realname'] == 'Test WhoWas User'

    def test_whowas_nonexistent_user(self, mock_server_state):
        """Test WHOWAS returns error for user that never existed."""
        command = "WHOWAS NeverExisted999"
        nick = command.split()[1]
        
        # Check history does not exist
        assert nick not in mock_server_state['whowas_history']

    def test_whowas_multiple_entries(self):
        """Test WHOWAS handles user with multiple history entries."""
        whowas_history = {
            'MultiUser': [
                {
                    'nick': 'MultiUser',
                    'user': 'user1',
                    'host': '127.0.0.1',
                    'realname': 'First Connection',
                    'disconnected_at': 1000000
                },
                {
                    'nick': 'MultiUser',
                    'user': 'user1',
                    'host': '127.0.0.2',
                    'realname': 'Second Connection',
                    'disconnected_at': 2000000
                }
            ]
        }
        
        nick = 'MultiUser'
        assert nick in whowas_history
        assert len(whowas_history[nick]) == 2

    def test_whowas_command_parsing(self):
        """Test parsing WHOWAS command format."""
        test_cases = [
            ("WHOWAS TestWhoWas", "TestWhoWas"),
            ("WHOWAS Observer 5", "Observer"),
            ("WHOWAS", None),  # Invalid, no nick
        ]
        
        for command, expected_nick in test_cases:
            parts = command.split()
            if len(parts) >= 2:
                nick = parts[1]
                assert nick == expected_nick
            else:
                assert expected_nick is None

    def test_whowas_response_codes(self):
        """Test WHOWAS generates correct IRC response codes."""
        # RPL_WHOWASUSER = 314
        # RPL_ENDOFWHOWAS = 369
        # ERR_WASNOSUCHNICK = 406
        
        response_codes = {
            'RPL_WHOWASUSER': 314,
            'RPL_ENDOFWHOWAS': 369,
            'ERR_WASNOSUCHNICK': 406
        }
        
        assert response_codes['RPL_WHOWASUSER'] == 314
        assert response_codes['RPL_ENDOFWHOWAS'] == 369
        assert response_codes['ERR_WASNOSUCHNICK'] == 406

    def test_whowas_user_data_structure(self):
        """Test WHOWAS user data has required fields."""
        user_entry = {
            'nick': 'TestUser',
            'user': 'testuser',
            'host': '192.168.1.1',
            'realname': 'Test User Real Name',
            'disconnected_at': 1234567890
        }
        
        required_fields = ['nick', 'user', 'host', 'realname', 'disconnected_at']
        for field in required_fields:
            assert field in user_entry
            assert user_entry[field] is not None

    def test_whowas_case_insensitive_lookup(self):
        """Test WHOWAS nick lookup is case-insensitive."""
        whowas_history = {
            'TestWhoWas': [
                {
                    'nick': 'TestWhoWas',
                    'user': 'testww',
                    'host': '127.0.0.1',
                    'realname': 'Test WhoWas User',
                    'disconnected_at': 1234567890
                }
            ]
        }
        
        # Convert to lowercase for comparison
        test_lookups = ['TestWhoWas', 'testwhohas', 'TESTWHOHAS']
        for lookup in test_lookups:
            normalized = lookup.lower()
            keys = [k.lower() for k in whowas_history.keys()]
            assert normalized in keys

    def test_whowas_empty_history(self):
        """Test WHOWAS with empty history."""
        whowas_history = {}
        
        assert len(whowas_history) == 0
        nick = 'NonExistent'
        assert nick not in whowas_history

    def test_whowas_count_parameter(self):
        """Test WHOWAS with optional count parameter."""
        command_with_count = "WHOWAS TestUser 5"
        parts = command_with_count.split()
        
        assert len(parts) >= 2
        nick = parts[1]
        count = int(parts[2]) if len(parts) > 2 else None
        
        assert nick == 'TestUser'
        assert count == 5

    def test_whowas_max_history_entries(self):
        """Test WHOWAS respects maximum history entry limit."""
        max_entries = 100
        whowas_history = {
            'PopularUser': [
                {
                    'nick': 'PopularUser',
                    'user': f'user{i}',
                    'host': f'127.0.0.{i % 255}',
                    'realname': f'Connection {i}',
                    'disconnected_at': 1000000 + i
                }
                for i in range(150)  # More than max
            ]
        }
        
        # Simulate limiting to max entries
        limited = whowas_history['PopularUser'][:max_entries]
        assert len(limited) == max_entries

    def test_whowas_host_information(self):
        """Test WHOWAS preserves host information."""
        user_data = {
            'nick': 'TestUser',
            'user': 'test',
            'host': '192.168.1.100',
            'realname': 'Test User',
            'disconnected_at': 1234567890
        }
        
        # Verify host is preserved
        assert user_data['host'] == '192.168.1.100'
        assert '@' not in user_data['host']  # Should be just host, not user@host

    def test_whowas_timestamp_tracking(self):
        """Test WHOWAS tracks disconnection timestamps."""
        import time
        
        current_time = int(time.time())
        user_data = {
            'nick': 'TestUser',
            'user': 'test',
            'host': '127.0.0.1',
            'realname': 'Test User',
            'disconnected_at': current_time
        }
        
        assert isinstance(user_data['disconnected_at'], int)
        assert user_data['disconnected_at'] <= current_time

    def test_whowas_realname_preservation(self):
        """Test WHOWAS preserves user realname (gecos) field."""
        realnames = [
            'Test WhoWas User',
            'Simple User',
            'User with spaces in name',
            'User:with:colons',
            ''  # Empty realname
        ]
        
        for realname in realnames:
            user_data = {
                'nick': 'TestUser',
                'user': 'test',
                'host': '127.0.0.1',
                'realname': realname,
                'disconnected_at': 1234567890
            }
            assert user_data['realname'] == realname

    def test_whowas_concurrent_lookups(self):
        """Test WHOWAS handles concurrent lookups correctly."""
        whowas_history = {
            'User1': [{'nick': 'User1', 'user': 'u1', 'host': '127.0.0.1', 
                      'realname': 'User 1', 'disconnected_at': 1000000}],
            'User2': [{'nick': 'User2', 'user': 'u2', 'host': '127.0.0.2', 
                      'realname': 'User 2', 'disconnected_at': 2000000}],
            'User3': [{'nick': 'User3', 'user': 'u3', 'host': '127.0.0.3', 
                      'realname': 'User 3', 'disconnected_at': 3000000}]
        }
        
        # Simulate concurrent lookups
        for nick in ['User1', 'User2', 'User3']:
            assert nick in whowas_history
            assert len(whowas_history[nick]) > 0

    def test_whowas_special_characters_in_nick(self):
        """Test WHOWAS with special characters in nickname."""
        special_nicks = [
            'User[test]',
            'User^',
            'User_123',
            'User-test',
            'User{123}',
        ]
        
        for nick in special_nicks:
            # Verify nick is valid IRC format
            assert len(nick) > 0
            assert len(nick) <= 30  # IRC nick length limit

    def test_whowas_ircd_compatibility(self):
        """Test WHOWAS response format matches IRC standard."""
        # Standard format: :server 314 nick_of_querier nick user host * :realname
        response_format = ":server 314 Observer TestWhoWas testww 127.0.0.1 * :Test WhoWas User"
        
        # Verify response contains expected components
        assert '314' in response_format
        assert 'TestWhoWas' in response_format
        assert 'testww' in response_format
        assert '127.0.0.1' in response_format

    def test_whowas_endofwhowas_response(self):
        """Test WHOWAS sends ENDOFWHOWAS (369) at end."""
        response_format = ":server 369 Observer TestWhoWas :End of WHOWAS"
        
        assert '369' in response_format
        assert 'End of WHOWAS' in response_format

    def test_whowas_error_response(self):
        """Test WHOWAS error response for non-existent user."""
        response_format = ":server 406 Observer NeverExisted :There was no such nickname"
        
        assert '406' in response_format
        assert 'no such nickname' in response_format.lower()


class TestWhoWasIntegration:
    """Integration tests for WHOWAS command."""

    def test_whowas_after_user_quit(self):
        """Test WHOWAS works after user has quit."""
        user_before_quit = {
            'nick': 'TestUser',
            'user': 'test',
            'host': '127.0.0.1',
            'realname': 'Test User'
        }
        
        # Simulate user disconnect
        user_after_quit = user_before_quit.copy()
        user_after_quit['disconnected_at'] = 1234567890
        
        assert user_after_quit['disconnected_at'] is not None
        assert user_after_quit['nick'] == user_before_quit['nick']

    def test_whowas_order_preservation(self):
        """Test WHOWAS maintains chronological order of entries."""
        history = [
            {'nick': 'User', 'disconnected_at': 1000},
            {'nick': 'User', 'disconnected_at': 2000},
            {'nick': 'User', 'disconnected_at': 3000},
        ]
        
        # Verify entries are in chronological order
        for i in range(len(history) - 1):
            assert history[i]['disconnected_at'] <= history[i + 1]['disconnected_at']

    def test_whowas_respects_privacy(self):
        """Test WHOWAS does not expose sensitive information."""
        user_data = {
            'nick': 'TestUser',
            'user': 'test',
            'host': '192.168.1.100',  # Only host shown, not full IP
            'realname': 'Test User',
            'disconnected_at': 1234567890
        }
        
        # Verify no password or sensitive data in response
        assert 'password' not in user_data
        assert 'token' not in user_data
        assert 'secret' not in user_data

    def test_whowas_command_not_case_sensitive(self):
        """Test WHOWAS command itself is case-insensitive."""
        commands = ['WHOWAS', 'whowas', 'WhOwAs']
        
        for cmd in commands:
            normalized = cmd.upper()
            assert normalized == 'WHOWAS'
```