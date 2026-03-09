```python
import pytest
from unittest.mock import Mock, patch, MagicMock
import threading
import sys
import os


# Mock the dependencies before any imports
@pytest.fixture(autouse=True)
def mock_dependencies():
    """Mock external dependencies globally."""
    with patch("csc_claude.claude.get_claude_api_key", return_value="fake-api-key"), \
         patch("anthropic.Anthropic"), \
         patch("csc_client.client.Client.__init__", return_value=None):
        yield


@pytest.fixture
def claude_instance():
    """Create a Claude instance with all external dependencies mocked."""
    from csc_claude.claude import Claude

    instance = Claude.__new__(Claude)

    # Attributes normally set by Client.__init__
    instance.name = "Claude"
    instance.autonomous_mode = True
    instance.log_file = "Claude.log"
    instance.current_channel = "#general"
    instance.server_host = "127.0.0.1"
    instance.server_port = 9525
    instance.server_addr = ("127.0.0.1", 9525)
    instance._running = True
    instance.sock = Mock()

    # Mock data/persistence methods
    instance.get_data = Mock(return_value="")
    instance.put_data = Mock()
    instance.init_data = Mock()
    instance.log = Mock()
    instance.send = Mock()

    # Claude API mocks
    instance.CLAUDE_API_KEY = "fake-api-key"
    instance.CLAUDE_MODEL_NAME = "claude-sonnet-4-20250514"
    instance.system_instructions = "fake instructions"

    # Build a mock anthropic client with messages.create
    mock_text_block = Mock()
    mock_text_block.text = "test reply"
    mock_response = Mock()
    mock_response.content = [mock_text_block]

    mock_messages = Mock()
    mock_messages.create.return_value = mock_response
    mock_client = Mock()
    mock_client.messages = mock_messages

    instance.anthropic_client = mock_client
    instance.conversation_history = []
    instance._query_lock = threading.Lock()

    # Store for server change testing
    instance.command_server = Mock()

    return instance


# -----------------------------------------------------------------------
# handle_server_message - PRIVMSG parsing
# -----------------------------------------------------------------------
def test_privmsg_extracts_sender_and_text(claude_instance):
    """PRIVMSG from another user extracts sender and text, queries model."""
    claude_instance.handle_server_message(":nick!user@host PRIVMSG #general :hello")
    claude_instance.anthropic_client.messages.create.assert_called_once()
    call_kwargs = claude_instance.anthropic_client.messages.create.call_args[1]
    # The prompt should include sender and text
    last_msg = call_kwargs["messages"][-1]
    assert "<nick>" in last_msg["content"]
    assert "hello" in last_msg["content"]


def test_privmsg_reply_sent_to_channel(claude_instance):
    """Reply is sent as PRIVMSG to the same channel."""
    mock_text_block = Mock()
    mock_text_block.text = "model response"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    claude_instance.handle_server_message(":nick!user@host PRIVMSG #general :hello")
    claude_instance.send.assert_called_once_with("PRIVMSG #general :model response\r\n")


def test_privmsg_skips_own_messages(claude_instance):
    """Messages from 'Claude' (self) are skipped to avoid loops."""
    claude_instance.handle_server_message(":Claude!user@host PRIVMSG #general :hello")
    claude_instance.anthropic_client.messages.create.assert_not_called()
    claude_instance.send.assert_not_called()


def test_privmsg_skips_own_messages_case_insensitive(claude_instance):
    """Own-message detection is case-insensitive."""
    claude_instance.handle_server_message(":claude!user@host PRIVMSG #general :hello")
    claude_instance.anthropic_client.messages.create.assert_not_called()
    claude_instance.send.assert_not_called()


def test_privmsg_pm_replies_to_target(claude_instance):
    """PM (target is not a channel) replies to the PM target."""
    mock_text_block = Mock()
    mock_text_block.text = "pm reply"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    claude_instance.handle_server_message(":alice!user@host PRIVMSG Claude :hi there")
    claude_instance.send.assert_called_once_with("PRIVMSG alice :pm reply\r\n")


# -----------------------------------------------------------------------
# handle_server_message - PING handling
# -----------------------------------------------------------------------
def test_ping_sends_pong(claude_instance):
    """PING message triggers a PONG response with the same token."""
    claude_instance.handle_server_message("PING :token123")
    claude_instance.send.assert_called_once_with("PONG :token123\r\n")


def test_ping_no_model_query(claude_instance):
    """PING does not trigger a model query."""
    claude_instance.handle_server_message("PING :token123")
    claude_instance.anthropic_client.messages.create.assert_not_called()


# -----------------------------------------------------------------------
# handle_server_message - non-PRIVMSG messages
# -----------------------------------------------------------------------
def test_join_message_not_sent_to_model(claude_instance):
    """JOIN message is printed but not sent to the model."""
    claude_instance.handle_server_message(":nick!user@host JOIN #general")
    claude_instance.anthropic_client.messages.create.assert_not_called()
    claude_instance.send.assert_not_called()


def test_part_message_not_sent_to_model(claude_instance):
    """PART message is printed but not sent to the model."""
    claude_instance.handle_server_message(":nick!user@host PART #general")
    claude_instance.anthropic_client.messages.create.assert_not_called()
    claude_instance.send.assert_not_called()


def test_privmsg_empty_text_not_queried(claude_instance):
    """PRIVMSG with empty text does not query the model."""
    claude_instance.handle_server_message(":nick!user@host PRIVMSG #general :")
    claude_instance.anthropic_client.messages.create.assert_not_called()


# -----------------------------------------------------------------------
# handle_server_message - conversation_history
# -----------------------------------------------------------------------
def test_conversation_history_populated(claude_instance):
    """conversation_history is populated with messages."""
    mock_text_block = Mock()
    mock_text_block.text = "response"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    assert len(claude_instance.conversation_history) == 0
    claude_instance.handle_server_message(":nick!user@host PRIVMSG #general :hello")
    assert len(claude_instance.conversation_history) > 0


def test_conversation_history_includes_user_message(claude_instance):
    """User message is stored in conversation_history."""
    mock_text_block = Mock()
    mock_text_block.text = "response"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    claude_instance.handle_server_message(":nick!user@host PRIVMSG #general :hello")
    history_text = " ".join([msg.get("content", "") for msg in claude_instance.conversation_history])
    assert "hello" in history_text or "nick" in history_text


def test_conversation_history_includes_assistant_response(claude_instance):
    """Assistant response is stored in conversation_history."""
    mock_text_block = Mock()
    mock_text_block.text = "assistant response"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    claude_instance.handle_server_message(":nick!user@host PRIVMSG #general :hello")
    history_text = " ".join([msg.get("content", "") for msg in claude_instance.conversation_history])
    assert "assistant" in history_text or "response" in history_text


# -----------------------------------------------------------------------
# API error handling
# -----------------------------------------------------------------------
def test_api_error_does_not_crash(claude_instance):
    """API errors are caught and do not crash the handler."""
    claude_instance.anthropic_client.messages.create.side_effect = Exception("API Error")
    
    # Should not raise
    try:
        claude_instance.handle_server_message(":nick!user@host PRIVMSG #general :hello")
    except Exception:
        pytest.fail("handle_server_message should catch API errors")


# -----------------------------------------------------------------------
# Malformed message handling
# -----------------------------------------------------------------------
def test_malformed_privmsg_handled(claude_instance):
    """Malformed PRIVMSG messages do not crash."""
    # Missing components
    try:
        claude_instance.handle_server_message(":nick!user@host PRIVMSG")
        claude_instance.handle_server_message("PRIVMSG")
        claude_instance.handle_server_message("")
    except Exception:
        pytest.fail("Malformed messages should be handled gracefully")


# -----------------------------------------------------------------------
# Multiple channels
# -----------------------------------------------------------------------
def test_privmsg_different_channels(claude_instance):
    """Messages from different channels are handled correctly."""
    mock_text_block = Mock()
    mock_text_block.text = "response"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    claude_instance.handle_server_message(":nick!user@host PRIVMSG #general :hello")
    assert claude_instance.send.call_args[0][0].startswith("PRIVMSG #general")
    
    claude_instance.send.reset_mock()
    claude_instance.handle_server_message(":nick!user@host PRIVMSG #random :hi")
    assert claude_instance.send.call_args[0][0].startswith("PRIVMSG #random")


# -----------------------------------------------------------------------
# Special characters and edge cases
# -----------------------------------------------------------------------
def test_privmsg_with_special_characters(claude_instance):
    """PRIVMSG with special characters is handled."""
    mock_text_block = Mock()
    mock_text_block.text = "response"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    claude_instance.handle_server_message(":nick!user@host PRIVMSG #general :hello @!#$%^&*()")
    claude_instance.anthropic_client.messages.create.assert_called_once()


def test_privmsg_with_unicode(claude_instance):
    """PRIVMSG with unicode characters is handled."""
    mock_text_block = Mock()
    mock_text_block.text = "response"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    claude_instance.handle_server_message(":nick!user@host PRIVMSG #general :hello 你好 مرحبا")
    claude_instance.anthropic_client.messages.create.assert_called_once()


def test_privmsg_with_long_message(claude_instance):
    """PRIVMSG with very long text is handled."""
    mock_text_block = Mock()
    mock_text_block.text = "response"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    long_text = "hello " * 500
    claude_instance.handle_server_message(f":nick!user@host PRIVMSG #general :{long_text}")
    claude_instance.anthropic_client.messages.create.assert_called_once()


# -----------------------------------------------------------------------
# System instructions integration
# -----------------------------------------------------------------------
def test_system_instructions_used_in_query(claude_instance):
    """System instructions are passed to the API."""
    mock_text_block = Mock()
    mock_text_block.text = "response"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    claude_instance.handle_server_message(":nick!user@host PRIVMSG #general :hello")
    call_kwargs = claude_instance.anthropic_client.messages.create.call_args[1]
    assert "system" in call_kwargs


# -----------------------------------------------------------------------
# Threading safety
# -----------------------------------------------------------------------
def test_concurrent_messages_handled(claude_instance):
    """Multiple concurrent messages are handled safely."""
    from threading import Thread
    
    mock_text_block = Mock()
    mock_text_block.text = "response"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    def send_message(text):
        claude_instance.handle_server_message(f":nick!user@host PRIVMSG #general :{text}")
    
    threads = [Thread(target=send_message, args=(f"msg{i}",)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # Should have been called at least once without crashing
    assert claude_instance.anthropic_client.messages.create.call_count >= 1


# -----------------------------------------------------------------------
# Response formatting
# -----------------------------------------------------------------------
def test_response_formatting_with_newlines(claude_instance):
    """Responses with newlines are handled correctly."""
    mock_text_block = Mock()
    mock_text_block.text = "line1\nline2\nline3"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    claude_instance.handle_server_message(":nick!user@host PRIVMSG #general :hello")
    # Response should be sent, handling newlines appropriately
    assert claude_instance.send.called


def test_response_with_empty_content(claude_instance):
    """Empty response content is handled."""
    mock_text_block = Mock()
    mock_text_block.text = ""
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    try:
        claude_instance.handle_server_message(":nick!user@host PRIVMSG #general :hello")
    except Exception:
        pytest.fail("Empty responses should be handled gracefully")


# -----------------------------------------------------------------------
# Nick parsing
# -----------------------------------------------------------------------
def test_nick_parsing_with_numbers(claude_instance):
    """Nicks with numbers are parsed correctly."""
    mock_text_block = Mock()
    mock_text_block.text = "response"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    claude_instance.handle_server_message(":nick123!user@host PRIVMSG #general :hello")
    call_kwargs = claude_instance.anthropic_client.messages.create.call_args[1]
    last_msg = call_kwargs["messages"][-1]
    assert "nick123" in last_msg["content"]


def test_nick_parsing_with_special_chars(claude_instance):
    """Nicks with special characters are parsed correctly."""
    mock_text_block = Mock()
    mock_text_block.text = "response"
    claude_instance.anthropic_client.messages.create.return_value = Mock(content=[mock_text_block])
    
    claude_instance.handle_server_message(":nick-_[]!user@host PRIVMSG #general :hello")
    claude_instance.anthropic_client.messages.create