```python
import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from shared.irc import (
        parse_irc_message, format_irc_message, numeric_reply, IRCMessage,
        SERVER_NAME, RPL_WELCOME, RPL_YOURHOST, RPL_TOPIC,
        ERR_NOSUCHNICK, ERR_NICKNAMEINUSE, ERR_NEEDMOREPARAMS,
    )
    HAS_IRC_MODULE = True
except ImportError:
    HAS_IRC_MODULE = False


pytestmark = pytest.mark.skipif(not HAS_IRC_MODULE, reason="shared.irc module not available")


class TestParseIrcMessage:
    """Test suite for parse_irc_message function."""

    def test_simple_command(self):
        """Test parsing a simple command with one param: NICK testuser"""
        msg = parse_irc_message("NICK testuser")
        assert msg.prefix is None
        assert msg.command == "NICK"
        assert msg.params == ["testuser"]
        assert msg.trailing is None

    def test_command_with_prefix(self):
        """Test parsing a command with prefix: :nick!user@host PRIVMSG #channel :hello world"""
        msg = parse_irc_message(":nick!user@host PRIVMSG #channel :hello world")
        assert msg.prefix == "nick!user@host"
        assert msg.command == "PRIVMSG"
        assert msg.params == ["#channel", "hello world"]
        assert msg.trailing == "hello world"

    def test_command_with_trailing(self):
        """Test parsing a command with trailing: PRIVMSG #general :this is a message"""
        msg = parse_irc_message("PRIVMSG #general :this is a message")
        assert msg.prefix is None
        assert msg.command == "PRIVMSG"
        assert msg.params == ["#general", "this is a message"]
        assert msg.trailing == "this is a message"

    def test_command_with_multiple_params(self):
        """Test parsing USER command with multiple params and trailing."""
        msg = parse_irc_message("USER testuser 0 * :Real Name")
        assert msg.prefix is None
        assert msg.command == "USER"
        assert msg.params == ["testuser", "0", "*", "Real Name"]
        assert msg.trailing == "Real Name"

    def test_empty_line(self):
        """Test parsing an empty line returns empty IRCMessage."""
        msg = parse_irc_message("")
        assert msg.command == ""
        assert msg.prefix is None
        assert msg.params == []
        assert msg.trailing is None

    def test_prefix_only(self):
        """Test parsing a line with only a prefix and no command."""
        msg = parse_irc_message(":someprefix")
        assert msg.prefix == "someprefix"
        assert msg.command == ""
        assert msg.params == []

    def test_numeric_reply(self):
        """Test parsing a numeric reply: :csc-server 001 nick :Welcome"""
        msg = parse_irc_message(":csc-server 001 nick :Welcome")
        assert msg.prefix == "csc-server"
        assert msg.command == "001"
        assert msg.params == ["nick", "Welcome"]
        assert msg.trailing == "Welcome"

    def test_ping(self):
        """Test parsing PING :token123"""
        msg = parse_irc_message("PING :token123")
        assert msg.prefix is None
        assert msg.command == "PING"
        assert msg.params == ["token123"]
        assert msg.trailing == "token123"

    def test_join(self):
        """Test parsing JOIN with prefix: :nick!user@host JOIN #channel"""
        msg = parse_irc_message(":nick!user@host JOIN #channel")
        assert msg.prefix == "nick!user@host"
        assert msg.command == "JOIN"
        assert msg.params == ["#channel"]
        assert msg.trailing is None

    def test_kick_with_reason(self):
        """Test parsing KICK with a reason in trailing."""
        msg = parse_irc_message(":op!op@host KICK #chan victim :reason text")
        assert msg.prefix == "op!op@host"
        assert msg.command == "KICK"
        assert msg.params == ["#chan", "victim", "reason text"]
        assert msg.trailing == "reason text"

    def test_no_trailing(self):
        """Test parsing a command with params but no trailing (no colon)."""
        msg = parse_irc_message("MODE #channel +o nick")
        assert msg.prefix is None
        assert msg.command == "MODE"
        assert msg.params == ["#channel", "+o", "nick"]
        assert msg.trailing is None

    def test_trailing_with_colons(self):
        """Test that colons within the trailing text are preserved."""
        msg = parse_irc_message("PRIVMSG #ch :hello: world: foo")
        assert msg.command == "PRIVMSG"
        assert msg.params == ["#ch", "hello: world: foo"]
        assert msg.trailing == "hello: world: foo"

    def test_raw_is_preserved(self):
        """Test that the raw field stores the original line (stripped of newlines)."""
        msg = parse_irc_message("NICK test\r\n")
        assert msg.raw == "NICK test"

    def test_command_is_uppercased(self):
        """Test that the command is always uppercased."""
        msg = parse_irc_message("nick testuser")
        assert msg.command == "NICK"

    def test_quit_with_message(self):
        """Test parsing QUIT with a message."""
        msg = parse_irc_message(":nick!user@host QUIT :Goodbye")
        assert msg.prefix == "nick!user@host"
        assert msg.command == "QUIT"
        assert msg.params == ["Goodbye"]
        assert msg.trailing == "Goodbye"

    def test_part_with_message(self):
        """Test parsing PART with a message."""
        msg = parse_irc_message(":nick!user@host PART #channel :leaving")
        assert msg.prefix == "nick!user@host"
        assert msg.command == "PART"
        assert msg.params == ["#channel", "leaving"]
        assert msg.trailing == "leaving"

    def test_mode_command_multiple_params(self):
        """Test parsing MODE with multiple parameters."""
        msg = parse_irc_message("MODE #channel +oo nick1 nick2")
        assert msg.command == "MODE"
        assert msg.params == ["#channel", "+oo", "nick1", "nick2"]

    def test_whitespace_handling(self):
        """Test that extra whitespace is handled correctly."""
        msg = parse_irc_message("NICK   testuser")
        assert msg.command == "NICK"
        assert msg.params == ["testuser"]

    def test_irc_message_attributes(self):
        """Test that IRCMessage object has all expected attributes."""
        msg = parse_irc_message(":prefix CMD param :trail")
        assert hasattr(msg, 'raw')
        assert hasattr(msg, 'prefix')
        assert hasattr(msg, 'command')
        assert hasattr(msg, 'params')
        assert hasattr(msg, 'trailing')


class TestFormatIrcMessage:
    """Test suite for format_irc_message function."""

    def test_with_prefix_command_params_trailing(self):
        """Test formatting a full message with prefix, params, and trailing."""
        result = format_irc_message("nick!user@host", "PRIVMSG", ["#channel"], "hello world")
        assert result == ":nick!user@host PRIVMSG #channel :hello world"

    def test_without_prefix(self):
        """Test formatting a message without a prefix."""
        result = format_irc_message(None, "NICK", ["testuser"], None)
        assert result == "NICK testuser"

    def test_with_empty_params(self):
        """Test formatting a message with empty params list."""
        result = format_irc_message("nick!user@host", "QUIT", [], "Goodbye")
        assert result == ":nick!user@host QUIT :Goodbye"

    def test_multiple_params_with_trailing(self):
        """Test formatting with multiple params and trailing."""
        result = format_irc_message(None, "USER", ["testuser", "0", "*"], "Real Name")
        assert result == "USER testuser 0 * :Real Name"

    def test_multiple_params_no_trailing(self):
        """Test formatting with multiple params but no trailing."""
        result = format_irc_message(None, "MODE", ["#channel", "+o", "nick"], None)
        assert result == "MODE #channel +o nick"

    def test_command_only(self):
        """Test formatting with only command."""
        result = format_irc_message(None, "PING", [], None)
        assert result == "PING"

    def test_prefix_and_command(self):
        """Test formatting with prefix and command only."""
        result = format_irc_message("server", "NOTICE", [], None)
        assert result == ":server NOTICE"

    def test_command_and_params(self):
        """Test formatting with command and params, no prefix or trailing."""
        result = format_irc_message(None, "PRIVMSG", ["#channel"], None)
        assert result == "PRIVMSG #channel"

    def test_numeric_reply_formatting(self):
        """Test formatting a numeric reply."""
        result = format_irc_message("server", "001", ["nick"], "Welcome")
        assert result == ":server 001 nick :Welcome"

    def test_privmsg_with_spaces(self):
        """Test formatting PRIVMSG with spaces in trailing text."""
        result = format_irc_message(None, "PRIVMSG", ["#channel"], "this is a long message")
        assert result == "PRIVMSG #channel :this is a long message"


class TestNumericReply:
    """Test suite for numeric_reply function."""

    def test_welcome_reply(self):
        """Test generating a welcome (001) reply."""
        result = numeric_reply("testuser", RPL_WELCOME, "Welcome to the network")
        assert SERVER_NAME in result
        assert "001" in result
        assert "testuser" in result
        assert "Welcome to the network" in result

    def test_yourhost_reply(self):
        """Test generating a YOURHOST (002) reply."""
        result = numeric_reply("testuser", RPL_YOURHOST, "your host")
        assert SERVER_NAME in result
        assert "002" in result
        assert "testuser" in result

    def test_topic_reply(self):
        """Test generating a TOPIC (332) reply."""
        result = numeric_reply("testuser", RPL_TOPIC, "channel topic")
        assert SERVER_NAME in result
        assert "332" in result

    def test_nosuchnick_error(self):
        """Test generating a NOSUCHNICK error."""
        result = numeric_reply("testuser", ERR_NOSUCHNICK, "nonexistent")
        assert SERVER_NAME in result
        assert "401" in result
        assert "nonexistent" in result

    def test_nicknameinuse_error(self):
        """Test generating a NICKNAMEINUSE error."""
        result = numeric_reply("testuser", ERR_NICKNAMEINUSE, "nick")
        assert SERVER_NAME in result
        assert "433" in result

    def test_needmoreparams_error(self):
        """Test generating a NEEDMOREPARAMS error."""
        result = numeric_reply("testuser", ERR_NEEDMOREPARAMS, "PRIVMSG")
        assert SERVER_NAME in result
        assert "461" in result
        assert "PRIVMSG" in result

    def test_reply_format_structure(self):
        """Test that numeric_reply returns a properly formatted IRC message."""
        result = numeric_reply("nick", "001", "test message")
        # Should start with colon (prefix)
        assert result.startswith(":")
        # Should contain numeric code
        assert "001" in result


class TestIRCMessageClass:
    """Test suite for IRCMessage class/namedtuple."""

    def test_irc_message_creation_with_parse(self):
        """Test that parse_irc_message returns a valid IRCMessage."""
        msg = parse_irc_message("NICK testuser")
        assert isinstance(msg, IRCMessage)
        assert msg.command == "NICK"
        assert msg.params == ["testuser"]

    def test_irc_message_raw_attribute(self):
        """Test that raw attribute contains the original message."""
        original = "PRIVMSG #channel :test"
        msg = parse_irc_message(original)
        assert msg.raw == original

    def test_irc_message_none_values(self):
        """Test that None values are preserved in IRCMessage."""
        msg = parse_irc_message("NICK test")
        assert msg.prefix is None
        assert msg.trailing is None


class TestEdgeCases:
    """Test suite for edge cases and special scenarios."""

    def test_message_with_crlf_line_ending(self):
        """Test parsing message with CRLF line endings."""
        msg = parse_irc_message("NICK test\r\n")
        assert msg.command == "NICK"
        assert msg.raw == "NICK test"

    def test_message_with_lf_line_ending(self):
        """Test parsing message with LF line ending."""
        msg = parse_irc_message("NICK test\n")
        assert msg.command == "NICK"
        assert msg.raw == "NICK test"

    def test_params_with_special_characters(self):
        """Test parsing params that contain special characters."""
        msg = parse_irc_message("PRIVMSG #channel :hello@world#test")
        assert "hello@world#test" in msg.params

    def test_empty_trailing_after_colon(self):
        """Test parsing message with colon but empty trailing."""
        msg = parse_irc_message("PRIVMSG #channel :")
        assert msg.trailing == ""

    def test_numeric_command(self):
        """Test parsing numeric commands."""
        msg = parse_irc_message(":server 404 nick #channel :no such channel")
        assert msg.command == "404"
        assert msg.prefix == "server"

    def test_very_long_message(self):
        """Test parsing a very long IRC message."""
        long_text = "x" * 400
        msg = parse_irc_message(f"PRIVMSG #channel :{long_text}")
        assert msg.trailing == long_text

    def test_case_insensitive_command(self):
        """Test that lowercase commands are converted to uppercase."""
        msg1 = parse_irc_message("privmsg #channel :test")
        msg2 = parse_irc_message("PRIVMSG #channel :test")
        assert msg1.command == msg2.command == "PRIVMSG"

    def test_format_roundtrip(self):
        """Test that parse and format can roundtrip messages."""
        original = ":nick!user@host PRIVMSG #channel :hello world"
        parsed = parse_irc_message(original)
        formatted = format_irc_message(parsed.prefix, parsed.command, 
                                      parsed.params[:-1], parsed.trailing)
        reparsed = parse_irc_message(formatted)
        assert reparsed.command == parsed.command
        assert reparsed.prefix == parsed.prefix
        assert reparsed.trailing == parsed.trailing


class TestConstants:
    """Test suite for IRC constants."""

    def test_server_name_exists(self):
        """Test that SERVER_NAME constant is defined."""
        assert SERVER_NAME is not None
        