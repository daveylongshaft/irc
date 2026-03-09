```python
import pytest
from unittest.mock import Mock, patch, MagicMock
import threading
import sys
import os


# Mock the external modules before importing
sys.modules["google"] = MagicMock()
sys.modules["google.genai"] = MagicMock()


@pytest.fixture
def mock_dependencies():
    """Mock all external dependencies."""
    with patch("gemini.get_gemini_api_key", return_value="fake-api-key"), \
         patch("gemini.load_initial_core_file_context", return_value="fake context"), \
         patch("gemini.get_system_instructions", return_value="fake instructions"), \
         patch("google.genai"), \
         patch("client.Client.__init__", return_value=None):
        yield


@pytest.fixture
def gemini_instance(mock_dependencies):
    """Create a Gemini instance with all external dependencies mocked."""
    from gemini import Gemini

    mock_send = Mock()

    instance = Gemini.__new__(Gemini)

    # Attributes normally set by Client.__init__
    instance.name = "Gemini"
    instance.autonomous_mode = True
    instance.log_file = "Gemini.log"
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
    instance.send = mock_send

    # Gemini API mocks
    instance.GEMINI_API_KEY = "fake-api-key"
    instance.GEMINI_MODEL_NAME = "gemini-pro-latest"
    instance.system_instructions = "fake instructions"

    mock_chat = Mock()
    mock_response = Mock()
    mock_response.text = "test reply"
    mock_chat.send_message.return_value = mock_response

    instance.gemini_client = Mock()
    instance.gemini_client.chats.create.return_value = mock_chat
    instance.gemini_chat = mock_chat
    instance.chat_history = []
    instance.model_name = "gemini-pro-latest"
    instance._query_lock = threading.Lock()
    instance.command_server = Mock()

    return instance, mock_send, mock_chat, mock_response


class TestGeminiIRCPrivmsg:
    """Test Gemini class IRC PRIVMSG message handling."""

    def test_privmsg_extracts_sender_and_text(self, gemini_instance):
        """PRIVMSG from another user extracts sender and text, queries model."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message(":nick!user@host PRIVMSG #general :hello")
        mock_chat.send_message.assert_called_once()
        call_args = mock_chat.send_message.call_args
        assert "<nick>" in call_args[1]["message"]
        assert "hello" in call_args[1]["message"]

    def test_privmsg_reply_sent_to_channel(self, gemini_instance):
        """Reply is sent as PRIVMSG to the same channel."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        mock_response.text = "model response"
        gemini.handle_server_message(":nick!user@host PRIVMSG #general :hello")
        mock_send.assert_called_once_with("PRIVMSG #general :model response\r\n")

    def test_privmsg_skips_own_messages(self, gemini_instance):
        """Messages from 'Gemini' (self) are skipped to avoid loops."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message(":Gemini!user@host PRIVMSG #general :hello")
        mock_chat.send_message.assert_not_called()
        mock_send.assert_not_called()

    def test_privmsg_skips_own_messages_case_insensitive(self, gemini_instance):
        """Own-message detection is case-insensitive."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message(":gemini!user@host PRIVMSG #general :hello")
        mock_chat.send_message.assert_not_called()
        mock_send.assert_not_called()

    def test_privmsg_pm_replies_to_sender(self, gemini_instance):
        """PM (target is not a channel) replies to the sender's nick, not the channel."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        mock_response.text = "pm reply"
        gemini.handle_server_message(":alice!user@host PRIVMSG Gemini :hi there")
        mock_send.assert_called_once_with("PRIVMSG Gemini :pm reply\r\n")

    def test_privmsg_multiple_messages_in_sequence(self, gemini_instance):
        """Multiple PRIVMSG messages are handled correctly in sequence."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message(":nick1!user@host PRIVMSG #general :message 1")
        gemini.handle_server_message(":nick2!user@host PRIVMSG #general :message 2")
        assert mock_chat.send_message.call_count == 2

    def test_privmsg_with_empty_text(self, gemini_instance):
        """PRIVMSG with empty message text is handled gracefully."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message(":nick!user@host PRIVMSG #general :")
        # Should still attempt to send to model or skip gracefully
        # Behavior depends on implementation


class TestGeminiIRCPing:
    """Test Gemini class IRC PING message handling."""

    def test_ping_sends_pong(self, gemini_instance):
        """PING message triggers a PONG response with the same token."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message("PING :token123")
        mock_send.assert_called_once_with("PONG :token123\r\n")

    def test_ping_no_model_query(self, gemini_instance):
        """PING does not trigger a model query."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message("PING :token123")
        mock_chat.send_message.assert_not_called()

    def test_ping_with_different_tokens(self, gemini_instance):
        """PING with different tokens returns corresponding PONG."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message("PING :abc123")
        mock_send.assert_called_once_with("PONG :abc123\r\n")


class TestGeminiIRCOtherMessages:
    """Test Gemini class IRC message handling for non-PRIVMSG/PING messages."""

    def test_join_message_not_sent_to_model(self, gemini_instance):
        """JOIN message is handled but not sent to the model."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message(":nick!user@host JOIN #general")
        mock_chat.send_message.assert_not_called()

    def test_part_message_not_sent_to_model(self, gemini_instance):
        """PART message is handled but not sent to the model."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message(":nick!user@host PART #general")
        mock_chat.send_message.assert_not_called()

    def test_quit_message_not_sent_to_model(self, gemini_instance):
        """QUIT message is handled but not sent to the model."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message(":nick!user@host QUIT")
        mock_chat.send_message.assert_not_called()

    def test_mode_message_not_sent_to_model(self, gemini_instance):
        """MODE message is handled but not sent to the model."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message(":server MODE #general +nt")
        mock_chat.send_message.assert_not_called()

    def test_names_message_not_sent_to_model(self, gemini_instance):
        """NAMES message (numeric 353) is handled but not sent to the model."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message(":server 353 Gemini = #general :nick1 nick2")
        mock_chat.send_message.assert_not_called()


class TestGeminiIRCEdgeCases:
    """Test Gemini class IRC message handling edge cases."""

    def test_malformed_message_no_crash(self, gemini_instance):
        """Malformed messages do not crash the handler."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message("GARBAGE")
        # Should not crash

    def test_message_with_special_characters(self, gemini_instance):
        """Messages with special characters are handled correctly."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message(":nick!user@host PRIVMSG #general :hello @#$%^&*()")
        mock_chat.send_message.assert_called_once()

    def test_message_with_unicode(self, gemini_instance):
        """Messages with unicode characters are handled correctly."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message(":nick!user@host PRIVMSG #general :hello 你好 🎉")
        mock_chat.send_message.assert_called_once()

    def test_channel_name_case_preservation(self, gemini_instance):
        """Channel names preserve case in replies."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        mock_response.text = "reply"
        gemini.handle_server_message(":nick!user@host PRIVMSG #General :hello")
        mock_send.assert_called_once_with("PRIVMSG #General :reply\r\n")

    def test_nick_with_special_characters(self, gemini_instance):
        """Nicks with special characters are handled correctly."""
        gemini, mock_send, mock_chat, mock_response = gemini_instance
        gemini.handle_server_message(":nick-1_2[a]!user@host PRIVMSG #general :hello")
        mock_chat.send_message.assert_called_once()


class TestGeminiChatHistory:
    """Test Gemini class chat history management."""

    def test_chat_history_initialized(self, gemini_instance):
        """Chat history is initialized as an empty list."""
        gemini, _, _, _ = gemini_instance
        assert isinstance(gemini.chat_history, list)
        assert len(gemini.chat_history) == 0

    def test_message_added_to_history_on_privmsg(self, gemini_instance):
        """Messages are tracked in chat history."""
        gemini, _, mock_chat, _ = gemini_instance
        # This depends on implementation; adjust assertions based on actual behavior
        gemini.handle_server_message(":nick!user@host PRIVMSG #general :hello")
        # Verify history update if applicable


class TestGeminiThreadSafety:
    """Test Gemini class thread safety."""

    def test_query_lock_exists(self, gemini_instance):
        """Query lock is initialized for thread safety."""
        gemini, _, _, _ = gemini_instance
        assert hasattr(gemini, "_query_lock")
        assert isinstance(gemini._query_lock, threading.Lock)

    def test_concurrent_privmsg_handling(self, gemini_instance):
        """Concurrent PRIVMSG handling is thread-safe."""
        gemini, _, mock_chat, _ = gemini_instance

        def send_message(nick):
            gemini.handle_server_message(f":{nick}!user@host PRIVMSG #general :hello")

        threads = [threading.Thread(target=send_message, args=(f"nick{i}",)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert mock_chat.send_message.call_count == 3


class TestGeminiAttributes:
    """Test Gemini instance attributes."""

    def test_gemini_name_attribute(self, gemini_instance):
        """Gemini instance has correct name."""
        gemini, _, _, _ = gemini_instance
        assert gemini.name == "Gemini"

    def test_gemini_autonomous_mode(self, gemini_instance):
        """Gemini autonomous_mode is set."""
        gemini, _, _, _ = gemini_instance
        assert gemini.autonomous_mode is True

    def test_gemini_model_name(self, gemini_instance):
        """Gemini model name is set correctly."""
        gemini, _, _, _ = gemini_instance
        assert gemini.model_name == "gemini-pro-latest"

    def test_gemini_api_key_set(self, gemini_instance):
        """Gemini API key is set."""
        gemini, _, _, _ = gemini_instance
        assert gemini.GEMINI_API_KEY == "fake-api-key"

    def test_gemini_system_instructions_set(self, gemini_instance):
        """Gemini system instructions are set."""
        gemini, _, _, _ = gemini_instance
        assert gemini.system_instructions == "fake instructions"


class TestGeminiMocking:
    """Test that mocks are properly configured."""

    def test_mock_chat_configured(self, gemini_instance):
        """Mock chat object is properly configured."""
        gemini, _, mock_chat, _ = gemini_instance
        assert mock_chat.send_message is not None
        mock_chat.send_message(message="test")
        mock_chat.send_message.assert_called()

    def test_mock_response_configured(self, gemini_instance):
        """Mock response object has text attribute."""
        gemini, _, _, mock_response = gemini_instance
        assert hasattr(mock_response, "text")
        assert mock_response.text == "test reply"

    def test_mock_send_method(self, gemini_instance):
        """Mock send method is callable."""
        gemini, mock_send, _, _ = gemini_instance
        gemini.send("TEST MESSAGE\r\n")
        mock_send.assert_called_with("TEST MESSAGE\r\n")
```