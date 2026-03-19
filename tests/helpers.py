"""Common test helpers and utilities for CSC test suite.

This module provides helper functions to reduce boilerplate in tests
and provide consistent patterns for testing IRC functionality.
"""

from typing import Optional, List, Dict, Any
from unittest.mock import Mock


# ============================================================================
# IRC Message Creation Helpers
# ============================================================================

def create_irc_message(command: str, params: Optional[List[str]] = None, 
                      prefix: Optional[str] = None, tags: Optional[Dict[str, str]] = None):
    """Helper to create IRC message dict for testing.
    
    Args:
        command: IRC command (e.g., 'PRIVMSG', 'JOIN')
        params: List of command parameters
        prefix: Optional message prefix (sender)
        tags: Optional IRCv3 tags dictionary
    
    Returns:
        dict with IRC message structure
    
    Example:
        msg = create_irc_message('PRIVMSG', ['#test', 'hello world'])
    """
    return {
        'command': command,
        'params': params or [],
        'prefix': prefix,
        'tags': tags or {}
    }


def create_privmsg(target: str, text: str, sender: Optional[str] = None):
    """Create a PRIVMSG message.
    
    Args:
        target: Channel or nick to send to
        text: Message text
        sender: Optional sender prefix
    
    Returns:
        IRC message dict
    """
    return create_irc_message('PRIVMSG', [target, text], prefix=sender)


def create_join(channel: str, sender: Optional[str] = None):
    """Create a JOIN message.
    
    Args:
        channel: Channel name to join
        sender: Optional sender prefix
    
    Returns:
        IRC message dict
    """
    return create_irc_message('JOIN', [channel], prefix=sender)


def create_part(channel: str, reason: Optional[str] = None, sender: Optional[str] = None):
    """Create a PART message.
    
    Args:
        channel: Channel name to part
        reason: Optional part message
        sender: Optional sender prefix
    
    Returns:
        IRC message dict
    """
    params = [channel]
    if reason:
        params.append(reason)
    return create_irc_message('PART', params, prefix=sender)


def create_mode(target: str, modes: str, params: Optional[List[str]] = None):
    """Create a MODE message.
    
    Args:
        target: Channel or nick
        modes: Mode string (e.g., '+o', '-v')
        params: Optional mode parameters (e.g., nicks)
    
    Returns:
        IRC message dict
    """
    mode_params = [target, modes]
    if params:
        mode_params.extend(params)
    return create_irc_message('MODE', mode_params)


# ============================================================================
# Assertion Helpers
# ============================================================================

def assert_irc_reply(mock_send, code: str, contains: Optional[str] = None):
    """Assert that IRC numeric reply was sent.
    
    Args:
        mock_send: Mock send function to check
        code: IRC reply code (e.g., '353', 'ERR_NEEDMOREPARAMS')
        contains: Optional text that should be in the reply
    
    Example:
        assert_irc_reply(mock_server.send_message, '353', '#test')
    """
    assert mock_send.called, f"Expected send to be called for reply {code}"
    call_args = mock_send.call_args
    
    # Handle both positional and keyword arguments
    if call_args[0]:
        message = str(call_args[0])
    else:
        message = str(call_args[1])
    
    assert code in message, f"Expected reply code {code} in message: {message}"
    
    if contains:
        assert contains in message, \
            f"Expected '{contains}' in message: {message}"


def assert_channel_message_sent(mock_broadcast, channel: str, 
                                command: str, contains: Optional[str] = None):
    """Assert that a message was broadcast to a channel.
    
    Args:
        mock_broadcast: Mock broadcast function
        channel: Expected channel name
        command: Expected IRC command
        contains: Optional text that should be in message
    """
    assert mock_broadcast.called, \
        f"Expected broadcast to {channel} for {command}"
    
    call_args = mock_broadcast.call_args[0]
    sent_channel = call_args[0] if call_args else None
    sent_message = call_args[1] if len(call_args) > 1 else str(call_args)
    
    assert sent_channel == channel, \
        f"Expected channel {channel}, got {sent_channel}"
    assert command in sent_message, \
        f"Expected command {command} in message: {sent_message}"
    
    if contains:
        assert contains in sent_message, \
            f"Expected '{contains}' in message: {sent_message}"


def assert_not_called_with(mock_obj, *args, **kwargs):
    """Assert that mock was not called with specific arguments.
    
    Args:
        mock_obj: Mock object to check
        *args: Positional arguments to check
        **kwargs: Keyword arguments to check
    """
    for call in mock_obj.call_args_list:
        if call[0] == args and call[1] == kwargs:
            raise AssertionError(
                f"Mock was called with {args}, {kwargs} but should not have been"
            )


def assert_log_contains(mock_log, message: str, level: Optional[str] = None):
    """Assert that a log message was logged.
    
    Args:
        mock_log: Mock log function
        message: Expected message substring
        level: Optional log level tag (e.g., '[ERROR]', '[INFO]')
    """
    assert mock_log.called, "Expected log to be called"
    
    for call in mock_log.call_args_list:
        log_msg = str(call[0][0]) if call[0] else str(call)
        if message in log_msg:
            if level:
                assert level in log_msg, \
                    f"Expected level {level} in log: {log_msg}"
            return
    
    raise AssertionError(
        f"Expected log message containing '{message}' not found in {len(mock_log.call_args_list)} log calls"
    )


# ============================================================================
# Client Registration Helpers
# ============================================================================

def simulate_registration(handler, addr: tuple, nick: str = 'testuser',
                         username: str = 'testuser', realname: str = 'Test User'):
    """Simulate full client registration sequence.
    
    Args:
        handler: MessageHandler instance
        addr: Client address tuple
        nick: Nickname to register
        username: Username for USER command
        realname: Real name for USER command
    
    Returns:
        addr tuple (for chaining)
    """
    # Send NICK
    nick_msg = f'NICK {nick}\r\n'.encode()
    handler.process(nick_msg, addr)
    
    # Send USER
    user_msg = f'USER {username} 0 * :{realname}\r\n'.encode()
    handler.process(user_msg, addr)
    
    return addr


def create_registered_client(clients_dict: dict, addr: tuple,
                            nick: str = 'testuser', **extra_fields):
    """Add a registered client to a clients dictionary.
    
    Args:
        clients_dict: Dictionary to add client to
        addr: Client address tuple
        nick: Client nickname
        **extra_fields: Additional fields to add to client record
    
    Returns:
        The created client dict
    """
    client = {
        'nick': nick,
        'user': extra_fields.get('user', nick),
        'realname': extra_fields.get('realname', f'User {nick}'),
        'addr': addr,
        'registered': True,
        'modes': extra_fields.get('modes', set()),
    }
    client.update(extra_fields)
    clients_dict[addr] = client
    return client


# ============================================================================
# Channel Helpers
# ============================================================================

def populate_channel(channel, members: List[tuple]):
    """Populate a channel with members.
    
    Args:
        channel: Channel instance
        members: List of (nick, addr) or (nick, addr, modes) tuples
    
    Example:
        populate_channel(ch, [
            ('alice', ('127.0.0.1', 1001)),
            ('bob', ('127.0.0.1', 1002), {'o'}),  # bob is op
        ])
    """
    for member_info in members:
        if len(member_info) == 2:
            nick, addr = member_info
            modes = None
        else:
            nick, addr, modes = member_info
        channel.add_member(nick, addr, modes)


def assert_channel_has_member(channel, nick: str):
    """Assert that a channel has a specific member.
    
    Args:
        channel: Channel instance
        nick: Nickname to check for
    """
    assert channel.has_member(nick), \
        f"Expected {nick} to be in channel {channel.name}"


def assert_channel_lacks_member(channel, nick: str):
    """Assert that a channel does NOT have a specific member.
    
    Args:
        channel: Channel instance
        nick: Nickname to check for
    """
    assert not channel.has_member(nick), \
        f"Expected {nick} NOT to be in channel {channel.name}"


def assert_member_has_mode(channel, nick: str, mode: str):
    """Assert that a channel member has a specific mode.
    
    Args:
        channel: Channel instance
        nick: Member nickname
        mode: Mode character (e.g., 'o', 'v')
    """
    member = channel.get_member(nick)
    assert member, f"Member {nick} not found in channel {channel.name}"
    assert mode in member.get('modes', set()), \
        f"Expected mode {mode} for {nick} in {channel.name}"


# ============================================================================
# Data Validation Helpers
# ============================================================================

def assert_valid_irc_nick(nick: str):
    """Assert that a string is a valid IRC nickname.
    
    Args:
        nick: Nickname to validate
    """
    import re
    nick_re = re.compile(r'^[A-Za-z\[\]\\`_^{|}][A-Za-z0-9\[\]\\`_^{|}\-]*$')
    assert nick_re.match(nick), f"Invalid IRC nick: {nick}"


def assert_valid_channel_name(channel: str):
    """Assert that a string is a valid IRC channel name.
    
    Args:
        channel: Channel name to validate
    """
    assert channel, "Channel name cannot be empty"
    assert channel[0] in '#&+!', \
        f"Channel name must start with #, &, +, or !: {channel}"


# ============================================================================
# Mock Configuration Helpers
# ============================================================================

def configure_mock_channel(mock_channel_manager, channel_name: str, 
                          members: Optional[List[str]] = None,
                          modes: Optional[set] = None):
    """Configure a mock channel manager to return a specific channel.
    
    Args:
        mock_channel_manager: Mock ChannelManager instance
        channel_name: Name of channel to configure
        members: Optional list of member nicks
        modes: Optional set of channel modes
    
    Returns:
        The configured mock channel
    """
    from unittest.mock import MagicMock
    
    mock_channel = MagicMock()
    mock_channel.name = channel_name
    mock_channel.members = {}
    mock_channel.modes = modes or set()
    
    if members:
        for nick in members:
            mock_channel.members[nick.lower()] = {
                'nick': nick,
                'addr': ('127.0.0.1', hash(nick) % 50000 + 10000),
                'modes': set()
            }
    
    mock_channel.has_member = Mock(side_effect=lambda n: n.lower() in mock_channel.members)
    mock_channel.get_member = Mock(side_effect=lambda n: mock_channel.members.get(n.lower()))
    
    mock_channel_manager.get_channel.return_value = mock_channel
    return mock_channel
