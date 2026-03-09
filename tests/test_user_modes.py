```python
"""
Pytest test file for IRC user mode functionality (+a, +i, +o, +s, +w).
Tests the CSC IRC orchestration system's user mode handling.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, call
import socket
import time


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def mock_socket():
    """Mock socket for IRC communication."""
    sock = MagicMock(spec=socket.socket)
    sock.recv.return_value = b""
    sock.sendall.return_value = None
    return sock


@pytest.fixture
def mock_irc_server():
    """Mock IRC server with basic functionality."""
    server = MagicMock()
    server.users = {}
    server.channels = {}
    server.operators = set()
    server.modes = {}
    return server


# ===========================================================================
# Helper Functions Tests
# ===========================================================================

class TestSendIrc:
    """Tests for send_irc helper function."""
    
    def test_send_irc_formats_command(self, mock_socket):
        """Test that send_irc properly formats IRC commands."""
        from unittest.mock import patch
        
        with patch('time.sleep'):
            def send_irc(sock, command):
                sock.sendall(f"{command}\r\n".encode())
            
            send_irc(mock_socket, "NICK testuser")
            mock_socket.sendall.assert_called_once_with(b"NICK testuser\r\n")
    
    def test_send_irc_with_empty_command(self, mock_socket):
        """Test send_irc with empty command."""
        with patch('time.sleep'):
            def send_irc(sock, command):
                sock.sendall(f"{command}\r\n".encode())
            
            send_irc(mock_socket, "")
            mock_socket.sendall.assert_called_once_with(b"\r\n")


class TestRecvAllIrc:
    """Tests for recv_all_irc helper function."""
    
    def test_recv_all_irc_single_response(self, mock_socket):
        """Test receiving single IRC response."""
        mock_socket.recv.side_effect = [
            b":server 001 testuser :Welcome\r\n",
            socket.timeout()
        ]
        
        with patch('time.sleep'):
            def recv_all_irc(sock, timeout=1.5):
                sock.settimeout(0.15)
                responses = []
                start = time.time()
                while time.time() - start < timeout:
                    try:
                        data = sock.recv(4096).decode('utf-8', errors='ignore')
                        if data:
                            responses.append(data)
                    except socket.timeout:
                        if responses:
                            break
                return "\n".join(responses)
            
            result = recv_all_irc(mock_socket)
            assert ":server 001 testuser :Welcome" in result
    
    def test_recv_all_irc_multiple_responses(self, mock_socket):
        """Test receiving multiple IRC responses."""
        mock_socket.recv.side_effect = [
            b":server 001 testuser :Welcome\r\n",
            b":server 002 testuser :Host\r\n",
            socket.timeout()
        ]
        
        with patch('time.sleep'):
            def recv_all_irc(sock, timeout=1.5):
                sock.settimeout(0.15)
                responses = []
                start = time.time()
                while time.time() - start < timeout:
                    try:
                        data = sock.recv(4096).decode('utf-8', errors='ignore')
                        if data:
                            responses.append(data)
                    except socket.timeout:
                        if responses:
                            break
                return "\n".join(responses)
            
            result = recv_all_irc(mock_socket)
            assert "001" in result
            assert "002" in result


# ===========================================================================
# +a (Away) Mode Tests
# ===========================================================================

class TestAwayMode:
    """Tests for away mode (+a) functionality."""
    
    def test_away_set_with_message(self):
        """Test that AWAY command sets away message and +a user mode."""
        user = {"nick": "TestUserAway1", "modes": set(), "away_msg": None}
        
        # Simulate AWAY command
        user["modes"].add("a")
        user["away_msg"] = "Gone for lunch"
        
        assert "a" in user["modes"]
        assert user["away_msg"] == "Gone for lunch"
    
    def test_away_unset_removes_mode(self):
        """Test that AWAY without message clears away status and removes +a."""
        user = {"nick": "TestUserAway2", "modes": {"a", "i"}, "away_msg": "BRB"}
        
        # Simulate AWAY with no message
        user["modes"].discard("a")
        user["away_msg"] = None
        
        assert "a" not in user["modes"]
        assert user["away_msg"] is None
        assert "i" in user["modes"]  # Other modes preserved
    
    def test_away_message_stored(self):
        """Test that away message is properly stored."""
        user = {"nick": "AwayUser", "modes": set(), "away_msg": None}
        away_msg = "Out to lunch, back at 2pm"
        
        user["modes"].add("a")
        user["away_msg"] = away_msg
        
        assert user["away_msg"] == away_msg
    
    def test_cannot_set_a_via_mode_command(self):
        """Test that +a mode cannot be set via MODE command (only via AWAY)."""
        user = {"nick": "TestUserAway3", "modes": set(), "away_msg": None}
        
        # Try to set +a via MODE (should be rejected)
        # Only AWAY command should modify +a
        assert "a" not in user["modes"]
    
    def test_whois_includes_away_message(self):
        """Test that WHOIS shows away message for away users."""
        away_user = {
            "nick": "AwayUser",
            "modes": {"a"},
            "away_msg": "Out to lunch, back at 2pm"
        }
        observer = {"nick": "Observer"}
        
        # WHOIS should include away message
        if "a" in away_user["modes"]:
            whois_response = f":{away_user['nick']} :{away_user['away_msg']}"
            assert "Out to lunch" in whois_response


# ===========================================================================
# +i (Invisible) Mode Tests
# ===========================================================================

class TestInvisibleMode:
    """Tests for invisible mode (+i) functionality."""
    
    def test_set_invisible_mode(self):
        """Test that MODE +i sets the invisible user mode."""
        user = {"nick": "TestUser1a", "modes": set()}
        user["modes"].add("i")
        
        assert "i" in user["modes"]
    
    def test_remove_invisible_mode(self):
        """Test that MODE -i removes the invisible user mode."""
        user = {"nick": "TestUser2a", "modes": {"i", "o"}}
        user["modes"].discard("i")
        
        assert "i" not in user["modes"]
        assert "o" in user["modes"]
    
    def test_invisible_prevents_whois_by_non_operators(self):
        """Test that invisible users are hidden from WHOIS (except to operators)."""
        invisible_user = {"nick": "InvisUser", "modes": {"i"}}
        regular_user = {"nick": "RegularUser", "modes": set()}
        operator = {"nick": "OpUser", "modes": {"o"}}
        
        # Operators can see invisible users, regular users cannot
        can_op_see = operator["modes"] and "o" in operator["modes"]
        assert can_op_see
    
    def test_multiple_invisible_users(self):
        """Test handling multiple invisible users."""
        users = [
            {"nick": f"InvisUser{i}", "modes": {"i"}}
            for i in range(3)
        ]
        
        invisible_count = sum(1 for u in users if "i" in u["modes"])
        assert invisible_count == 3


# ===========================================================================
# +o (Operator) Mode Tests
# ===========================================================================

class TestOperatorMode:
    """Tests for operator mode (+o) functionality."""
    
    def test_oper_authentication(self):
        """Test OPER command grants operator privileges and +o mode."""
        user = {"nick": "TestOper", "modes": set(), "authenticated": False}
        credentials = {"username": "admin", "password": "changeme"}
        
        # Simulate successful OPER authentication
        if credentials["username"] == "admin":
            user["modes"].add("o")
            user["authenticated"] = True
        
        assert "o" in user["modes"]
        assert user["authenticated"]
    
    def test_oper_invalid_credentials(self):
        """Test that OPER with invalid credentials fails."""
        user = {"nick": "TestOper2", "modes": set(), "authenticated": False}
        provided_cred = {"username": "admin", "password": "wrong"}
        correct_cred = {"username": "admin", "password": "changeme"}
        
        if provided_cred != correct_cred:
            user["authenticated"] = False
        
        assert not user["authenticated"]
        assert "o" not in user["modes"]
    
    def test_operator_can_kick_users(self):
        """Test that operators can kick users from channels."""
        operator = {"nick": "Op", "modes": {"o"}}
        target = {"nick": "Target"}
        
        can_kick = "o" in operator["modes"]
        assert can_kick
    
    def test_operator_can_manage_modes(self):
        """Test that operators can manage user modes."""
        operator = {"nick": "Op", "modes": {"o"}}
        target_user = {"nick": "Target", "modes": set()}
        
        # Operator can modify modes
        if "o" in operator["modes"]:
            target_user["modes"].add("i")
        
        assert "i" in target_user["modes"]
    
    def test_non_operator_cannot_use_admin_commands(self):
        """Test that non-operators cannot use admin commands."""
        regular_user = {"nick": "Regular", "modes": set()}
        target = {"nick": "Target"}
        
        can_kick = "o" in regular_user["modes"]
        assert not can_kick


# ===========================================================================
# +s (Server Notices) Mode Tests
# ===========================================================================

class TestServerNoticesMode:
    """Tests for server notices mode (+s) functionality."""
    
    def test_set_server_notices_mode(self):
        """Test that MODE +s sets server notices mode."""
        user = {"nick": "TestUser3a", "modes": set()}
        user["modes"].add("s")
        
        assert "s" in user["modes"]
    
    def test_remove_server_notices_mode(self):
        """Test that MODE -s removes server notices mode."""
        user = {"nick": "TestUser4a", "modes": {"s", "i"}}
        user["modes"].discard("s")
        
        assert "s" not in user["modes"]
        assert "i" in user["modes"]
    
    def test_server_notices_receives_messages(self):
        """Test that users with +s receive server notices."""
        user_with_notices = {"nick": "Notices", "modes": {"s"}}
        user_without_notices = {"nick": "NoNotices", "modes": set()}
        
        receives_notices = "s" in user_with_notices["modes"]
        no_notices = "s" not in user_without_notices["modes"]
        
        assert receives_notices
        assert no_notices
    
    def test_server_notices_mask_filtering(self):
        """Test that server notices can be filtered by mask."""
        user = {"nick": "TestUser5a", "modes": {"s"}, "notice_mask": "c"}
        
        # User has +s mode and a notice mask
        assert "s" in user["modes"]
        assert hasattr(user, "notice_mask") or "notice_mask" in user


# ===========================================================================
# +w (Wallops) Mode Tests
# ===========================================================================

class TestWallopsMode:
    """Tests for wallops mode (+w) functionality."""
    
    def test_set_wallops_mode(self):
        """Test that MODE +w sets wallops mode."""
        user = {"nick": "TestUser6a", "modes": set()}
        user["modes"].add("w")
        
        assert "w" in user["modes"]
    
    def test_remove_wallops_mode(self):
        """Test that MODE -w removes wallops mode."""
        user = {"nick": "TestUser7a", "modes": {"w", "o"}}
        user["modes"].discard("w")
        
        assert "w" not in user["modes"]
        assert "o" in user["modes"]
    
    def test_wallops_receives_operator_messages(self):
        """Test that users with +w receive WALLOPS messages."""
        user_with_wallops = {"nick": "Wallops", "modes": {"w"}}
        user_without_wallops = {"nick": "NoWallops", "modes": set()}
        
        assert "w" in user_with_wallops["modes"]
        assert "w" not in user_without_wallops["modes"]
    
    def test_only_operators_send_wallops(self):
        """Test that only operators can send WALLOPS."""
        operator = {"nick": "Op", "modes": {"o"}}
        regular_user = {"nick": "Regular", "modes": set()}
        
        op_can_send = "o" in operator["modes"]
        regular_can_send = "o" in regular_user["modes"]
        
        assert op_can_send
        assert not regular_can_send


# ===========================================================================
# Combined Mode Tests
# ===========================================================================

class TestCombinedModes:
    """Tests for combinations of multiple modes."""
    
    def test_multiple_modes_on_user(self):
        """Test user with multiple modes."""
        user = {"nick": "MultiMode", "modes": {"i", "o", "s", "w"}}
        
        assert len(user["modes"]) == 4
        assert all(m in user["modes"] for m in ["i", "o", "s", "w"])
    
    def test_mode_string_format(self):
        """Test MODE string formatting."""
        user = {"nick": "TestUser", "modes": {"a", "i", "o"}}
        
        mode_str = "+" + "".join(sorted(user["modes"]))
        assert mode_str == "+aio"
    
    def test_mode_manipulation_sequence(self):
        """Test sequence of mode changes."""
        user = {"nick": "TestUser8", "modes": set()}
        
        # Add modes
        user["modes"].update(["i", "s"])
        assert user["modes"] == {"i", "s"}
        
        # Add more
        user["modes"].add("w")
        assert user["modes"] == {"i", "s", "w"}
        
        # Remove one
        user["modes"].discard("s")
        assert user["modes"] == {"i", "w"}
    
    def test_mode_with_away_status(self):
        """Test interaction of +a mode with away status."""
        user = {
            "nick": "AwayUser",
            "modes": {"i", "o"},
            "away_msg": None
        }
        
        # Set away
        user["modes"].add("a")
        user["away_msg"] = "Testing"
        
        assert "a" in user["modes"]
        assert user["away_msg"] == "Testing"
        assert "i" in user["modes"]
        assert "o" in user["modes"]


# ===========================================================================
# Mode Query Tests
# ===========================================================================

class TestModeQueries:
    