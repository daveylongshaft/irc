
import pytest
from unittest.mock import MagicMock, call

from csc_service.server.server import Server
from csc_service.server.server_message_handler import MessageHandler
from csc_service.shared.irc import IRCMessage


@pytest.fixture
def mock_server():
    server = MagicMock(spec=Server)
    server.channel_manager = MagicMock()
    server.chat_buffer = MagicMock()
    server.clients = {}
    server.opers = set()
    server.get_data.return_value = {}
    server.log = MagicMock()
    server.sock_send = MagicMock()
    return server

@pytest.fixture
def message_handler(mock_server):
    file_handler = MagicMock()
    handler = MessageHandler(mock_server, file_handler)
    handler._get_nick = MagicMock(return_value="testuser")
    handler._is_registered = MagicMock(return_value=True)
    return handler

def test_privmsg_channel_name_normalization(message_handler, mock_server):
    # Arrange
    channel_name_mixed_case = "#General"
    channel_name_lowercase = "#general"
    message_text = "hello"
    
    channel_mock = MagicMock()
    channel_mock.has_member.return_value = True
    channel_mock.can_speak.return_value = True
    mock_server.channel_manager.get_channel.return_value = channel_mock

    msg = IRCMessage(command="PRIVMSG", params=[channel_name_mixed_case, message_text])
    addr = ("127.0.0.1", 12345)

    # Act
    message_handler._handle_privmsg(msg, addr)

    # Assert
    # Check that the message is broadcast with the lowercase channel name
    # The actual broadcast is tested in the server tests, here we check the call to format_irc_message
    
    # We need to find the call to format_irc_message
    # Since it's imported, we can't easily mock it. Instead, we'll check the broadcast call
    
    assert mock_server.broadcast_to_channel.call_count == 1
    call_args = mock_server.broadcast_to_channel.call_args
    sent_message = call_args[0][1]
    
    # The message should contain the lowercase channel name
    assert f"PRIVMSG {channel_name_lowercase} :{message_text}" in sent_message

    # Check that chat buffer also uses the lowercase name
    mock_server.chat_buffer.append.assert_called_once_with(channel_name_lowercase, "testuser", "PRIVMSG", message_text)


def test_notice_channel_name_normalization(message_handler, mock_server):
    # Arrange
    channel_name_mixed_case = "#General"
    channel_name_lowercase = "#general"
    message_text = "hello"
    
    channel_mock = MagicMock()
    channel_mock.has_member.return_value = True
    mock_server.channel_manager.get_channel.return_value = channel_mock

    msg = IRCMessage(command="NOTICE", params=[channel_name_mixed_case, message_text])
    addr = ("127.0.0.1", 12345)

    # Act
    message_handler._handle_notice(msg, addr)

    # Assert
    assert mock_server.broadcast_to_channel.call_count == 1
    call_args = mock_server.broadcast_to_channel.call_args
    sent_message = call_args[0][1]

    assert f"NOTICE {channel_name_lowercase} :{message_text}" in sent_message

    mock_server.chat_buffer.append.assert_called_once_with(channel_name_lowercase, "testuser", "NOTICE", message_text)

