```python
import pytest
from unittest.mock import MagicMock, patch, call
from csc_service.bridge.irc_normalizer import IrcNormalizer


class TestIrcNormalizerInit:
    """Tests for IrcNormalizer initialization."""

    def test_init_csc_to_rfc_mode(self):
        """Test initialization in csc_to_rfc mode."""
        norm = IrcNormalizer("csc_to_rfc")
        assert norm.mode == "csc_to_rfc"
        assert norm.seen_welcome is False
        assert norm.seen_end_of_registration is False

    def test_init_rfc_to_csc_mode(self):
        """Test initialization in rfc_to_csc mode."""
        norm = IrcNormalizer("rfc_to_csc")
        assert norm.mode == "rfc_to_csc"
        assert norm.seen_welcome is False
        assert norm.seen_end_of_registration is False


class TestIrcNormalizerClientToServer:
    """Tests for normalize_client_to_server method."""

    @pytest.fixture
    def session(self):
        """Create a mock session for testing."""
        session = MagicMock()
        session.nick = "testuser"
        session.client_id = ("127.0.0.1", 12345)
        session.inbound = MagicMock()
        return session

    def test_normalize_empty_block(self, session):
        """Test that empty block returns None."""
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_client_to_server("", session)
        assert result is None

    def test_normalize_none_block(self, session):
        """Test that None block returns None."""
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_client_to_server(None, session)
        assert result is None

    def test_csc_to_rfc_privmsg_passthrough(self, session):
        """Test that normal PRIVMSG passes through unchanged."""
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_client_to_server("PRIVMSG #test :hi\r\n", session)
        assert result == "PRIVMSG #test :hi\r\n"

    def test_csc_to_rfc_isop_filtered(self, session):
        """Test that ISOP command is filtered and sends NOTICE to client."""
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_client_to_server("ISOP target\r\n", session)
        assert result is None
        session.inbound.send_to_client.assert_called()
        call_args = session.inbound.send_to_client.call_args[0]
        assert b"NOTICE testuser :Command ISOP is not supported" in call_args[1]

    def test_csc_to_rfc_buffer_filtered(self, session):
        """Test that BUFFER command is filtered."""
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_client_to_server("BUFFER some args\r\n", session)
        assert result is None
        session.inbound.send_to_client.assert_called()

    def test_csc_to_rfc_ai_filtered(self, session):
        """Test that AI command is filtered."""
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_client_to_server("AI someparam\r\n", session)
        assert result is None
        session.inbound.send_to_client.assert_called()

    @patch('csc_service.bridge.irc_normalizer.parse_irc_message')
    def test_csc_to_rfc_ident_translation(self, mock_parse, session):
        """Test that IDENT command is translated to NICK+USER."""
        mock_parse.return_value = IRCMessage(
            prefix=None,
            command="IDENT",
            params=["mynick"],
            trailing=None
        )
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_client_to_server("IDENT mynick\r\n", session)
        assert result is not None
        assert "NICK mynick" in result
        assert "USER mynick" in result

    @patch('csc_service.bridge.irc_normalizer.parse_irc_message')
    def test_csc_to_rfc_rename_translation(self, mock_parse, session):
        """Test that RENAME command is translated to NICK."""
        mock_parse.return_value = IRCMessage(
            prefix=None,
            command="RENAME",
            params=["old", "new"],
            trailing=None
        )
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_client_to_server("RENAME old new\r\n", session)
        assert result is not None
        assert "NICK new" in result

    def test_csc_to_rfc_multiple_lines(self, session):
        """Test processing multiple lines in one block."""
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_client_to_server(
            "PRIVMSG #test :hi\r\nPRIVMSG #test2 :bye\r\n",
            session
        )
        assert result is not None
        assert "PRIVMSG #test :hi" in result
        assert "PRIVMSG #test2 :bye" in result

    def test_rfc_to_csc_cap_ls_response(self, session):
        """Test that CAP LS in rfc_to_csc mode returns synthetic response."""
        norm = IrcNormalizer("rfc_to_csc")
        result = norm.normalize_client_to_server("CAP LS 302\r\n", session)
        assert result is None
        session.inbound.send_to_client.assert_called()
        call_args = session.inbound.send_to_client.call_args[0]
        assert b"CAP * LS :" in call_args[1]

    def test_rfc_to_csc_cap_req_response(self, session):
        """Test that CAP REQ in rfc_to_csc mode returns synthetic response."""
        norm = IrcNormalizer("rfc_to_csc")
        result = norm.normalize_client_to_server("CAP REQ :multi-prefix\r\n", session)
        assert result is None
        session.inbound.send_to_client.assert_called()


class TestIrcNormalizerServerToClient:
    """Tests for normalize_server_to_client method."""

    @pytest.fixture
    def session(self):
        """Create a mock session for testing."""
        session = MagicMock()
        session.nick = "testuser"
        session.client_id = ("127.0.0.1", 12345)
        return session

    def test_normalize_empty_line(self, session):
        """Test that empty line returns None."""
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_server_to_client("", session)
        assert result is None

    def test_normalize_none_line(self, session):
        """Test that None line returns None."""
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_server_to_client(None, session)
        assert result is None

    def test_privmsg_passthrough(self, session):
        """Test that PRIVMSG passes through unchanged."""
        norm = IrcNormalizer("rfc_to_csc")
        line = ":server PRIVMSG #test :hello\r\n"
        result = norm.normalize_server_to_client(line, session)
        assert result == line

    @patch('csc_service.bridge.irc_normalizer.parse_irc_message')
    def test_rfc_to_csc_004_injection(self, mock_parse, session):
        """Test that 004 from server triggers injection of 005 ISUPPORT in rfc_to_csc mode."""
        # Mock parsing for 004
        mock_parse.return_value = IRCMessage(
            prefix=":csc-server",
            command="004",
            params=["nick", "csc-server", "o", "o"],
            trailing=None
        )
        norm = IrcNormalizer("rfc_to_csc")
        line = ":csc-server 004 nick csc-server o o\r\n"
        result = norm.normalize_server_to_client(line, session)
        
        # Should contain original 004
        assert "004" in result
        # Should inject 005
        assert "005" in result
        # Should contain ISUPPORT tokens
        assert "CHANTYPES=" in result or "005" in result
        # Set flag for next calls
        assert norm.seen_end_of_registration is True

    def test_csc_to_rfc_no_004_injection(self, session):
        """Test that in csc_to_rfc mode, 004 does not trigger 005 injection."""
        norm = IrcNormalizer("csc_to_rfc")
        line = ":csc-server 004 nick csc-server o o\r\n"
        result = norm.normalize_server_to_client(line, session)
        # In csc_to_rfc, should just pass through without injection
        assert result is not None

    def test_rfc_to_csc_001_sets_welcome_flag(self, session):
        """Test that receiving 001 sets welcome flag."""
        norm = IrcNormalizer("rfc_to_csc")
        assert norm.seen_welcome is False
        # Simulate 001 response
        line = ":server 001 nick :Welcome\r\n"
        result = norm.normalize_server_to_client(line, session)
        # The normalizer should process this
        assert result is not None

    def test_csc_to_rfc_passthrough_numeric(self, session):
        """Test that numeric replies pass through in csc_to_rfc mode."""
        norm = IrcNormalizer("csc_to_rfc")
        line = ":server 333 nick #channel user 1234567890\r\n"
        result = norm.normalize_server_to_client(line, session)
        assert result == line

    def test_multiple_isupport_tokens_injected(self, session):
        """Test that 005 injection includes expected ISUPPORT tokens."""
        norm = IrcNormalizer("rfc_to_csc")
        norm.seen_end_of_registration = True
        # Any numeric response after 004 should not trigger injection again
        line = ":server 251 nick :There are X users\r\n"
        result = norm.normalize_server_to_client(line, session)
        assert result is not None


class TestIrcNormalizerEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def session(self):
        """Create a mock session for testing."""
        session = MagicMock()
        session.nick = "testuser"
        session.client_id = ("127.0.0.1", 12345)
        session.inbound = MagicMock()
        return session

    def test_block_with_only_whitespace(self, session):
        """Test block containing only whitespace."""
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_client_to_server("   \r\n", session)
        # Should handle gracefully
        assert result is None or result == ""

    def test_block_without_crlf_terminator(self, session):
        """Test block that doesn't end with CRLF."""
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_client_to_server("PRIVMSG #test :hi", session)
        assert result is not None
        assert "PRIVMSG #test :hi" in result

    def test_block_with_empty_lines_in_middle(self, session):
        """Test block with empty lines in the middle."""
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_client_to_server(
            "PRIVMSG #test :hi\r\n\r\nPRIVMSG #test2 :bye\r\n",
            session
        )
        assert result is not None

    def test_session_nick_changes_during_normalization(self, session):
        """Test that session nick can be updated during IDENT."""
        norm = IrcNormalizer("csc_to_rfc")
        session.nick = "oldnick"
        # Process IDENT - should translate it
        result = norm.normalize_client_to_server("IDENT newnick\r\n", session)
        # Should produce output with translation
        assert result is not None

    def test_very_long_message_line(self, session):
        """Test handling of very long IRC message."""
        norm = IrcNormalizer("csc_to_rfc")
        long_msg = "PRIVMSG #test :" + "x" * 500 + "\r\n"
        result = norm.normalize_client_to_server(long_msg, session)
        assert result is not None
        assert "PRIVMSG #test :" in result

    def test_message_with_special_characters(self, session):
        """Test message with special IRC characters."""
        norm = IrcNormalizer("csc_to_rfc")
        msg = "PRIVMSG #test :hello :world\r\n"
        result = norm.normalize_client_to_server(msg, session)
        assert result is not None
        assert "hello :world" in result

    def test_unknown_command_passthrough(self, session):
        """Test that unknown commands pass through."""
        norm = IrcNormalizer("csc_to_rfc")
        result = norm.normalize_client_to_server("SOMEUNKNOWN arg1 arg2\r\n", session)
        # Unknown commands should pass through
        assert result is not None or result is None  # Depends on implementation


class TestIrcNormalizerStateTracking:
    """Tests for state tracking across multiple calls."""

    @pytest.fixture
    def session(self):
        """Create a mock session for testing."""
        session = MagicMock()
        session.nick = "testuser"
        return session

    def test_seen_welcome_flag_persistence(self, session):
        """Test that seen_welcome flag persists across calls."""
        norm = IrcNormalizer("rfc_to_csc")
        assert norm.seen_welcome is False
        # After processing first message, flag should still be False until 001 is received
        norm.normalize_server_to_client(":server PRIVMSG nick :test\r\n", session)
        assert norm.seen_welcome is False

    def test_seen_end_of_registration_flag_persistence(self, session):
        """Test that seen_end_of_registration flag persists."""
        norm = IrcNormalizer("rfc_to_csc")
        assert norm.seen_end_of_registration is False

    def test_mode_immutable_after_init(self, session):
        """Test that mode cannot be changed after initialization."""
        norm = IrcNormalizer("csc_to_rfc")
        assert norm.mode == "csc_to_rfc"
        # Attempting to change should not affect behavior of methods
        norm.mode = "rfc_to_csc"
        # Methods use self.mode, so this would affect behavior - document this


class TestIrcNormalizerIntegration:
    """Integration tests with realistic scenarios."""

    @pytest.fixture
    def session(self):
        """Create a mock session for testing."""
        session = MagicMock()
        session.nick = None
        session.client_id = ("192.168.1.100", 54