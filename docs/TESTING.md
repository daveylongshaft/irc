# Testing Guide for CSC IRC Service

This guide explains how to write and run tests for the CSC IRC service.

## Quick Start

### Running Tests

```bash
# Run all tests
cd irc
pytest

# Run with coverage
pytest --cov=csc_service --cov-report=html

# Run specific test file
pytest tests/test_channel.py

# Run specific test
pytest tests/test_channel.py::TestChannelBasics::test_channel_creation

# Run tests matching a pattern
pytest -k "registration"

# View coverage report
open htmlcov/index.html  # or firefox htmlcov/index.html
```

### Coverage Goals

- **Overall**: 70% minimum
- **Core modules**:
  - `shared/channel.py`: 90%
  - `server/server_message_handler.py`: 80%
  - `shared/data.py`: 85%
  - `server/server.py`: 75%

## Test Structure

### Directory Layout

```
irc/tests/
├── conftest.py           # Pytest fixtures
├── helpers.py            # Test utility functions
├── test_channel.py       # Channel tests
├── test_registration.py  # Registration tests
├── test_modes.py         # Mode handling tests
├── test_*.py            # Other test files
└── ...
```

### Test File Organization

Organize tests using classes that group related functionality:

```python
"""Tests for IRC channel operations."""
import pytest
from tests.helpers import create_irc_message, assert_irc_reply


class TestChannelCreation:
    """Test channel creation and initialization."""
    
    def test_create_channel(self):
        """Test creating a new channel."""
        # Test implementation
        pass


class TestChannelMembership:
    """Test channel member operations."""
    
    def test_add_member(self):
        """Test adding a member to channel."""
        pass
    
    def test_remove_member(self):
        """Test removing a member from channel."""
        pass
```

## Using Fixtures

Fixtures provide reusable test setup. They are defined in `conftest.py`.

### Core Fixtures

#### `mock_server`

Provides a mocked IRC server for testing:

```python
def test_something(mock_server):
    """Test using mock server."""
    mock_server.log("Test message")
    assert mock_server.log.called
```

#### `mock_file_handler`

Provides a mocked file handler:

```python
def test_file_upload(mock_file_handler, test_addr):
    """Test file upload handling."""
    mock_file_handler.sessions[test_addr] = {...}
    assert test_addr in mock_file_handler.sessions
```

#### `message_handler`

Provides a MessageHandler with mocked dependencies:

```python
def test_privmsg(message_handler, test_addr):
    """Test PRIVMSG command."""
    msg = create_irc_message('PRIVMSG', ['#test', 'hello'])
    message_handler._handle_privmsg(msg, test_addr)
```

#### `registered_client`

Provides a pre-registered client:

```python
def test_channel_join(mock_server, registered_client):
    """Test joining a channel."""
    # registered_client is already registered
    # Use it directly
    assert registered_client in mock_server.clients
```

#### `test_channel`

Provides a channel with test members:

```python
def test_channel_message(test_channel):
    """Test sending message to channel."""
    assert test_channel.has_member('alice')
    assert test_channel.has_member('bob')
```

### Custom Fixtures

Create fixtures specific to your test file:

```python
@pytest.fixture
def channel_with_ops():
    """Channel with operator members."""
    from csc_service.shared.channel import Channel
    channel = Channel('#ops')
    channel.add_member('op1', ('127.0.0.1', 1001), modes={'o'})
    channel.add_member('op2', ('127.0.0.1', 1002), modes={'o'})
    return channel


def test_op_commands(channel_with_ops):
    """Test operator commands."""
    assert channel_with_ops.is_op('op1')
```

## Helper Functions

Use helper functions from `tests/helpers.py` to reduce boilerplate.

### Creating IRC Messages

```python
from tests.helpers import create_irc_message, create_privmsg, create_join

# Generic message
msg = create_irc_message('NICK', ['alice'])

# PRIVMSG
msg = create_privmsg('#test', 'hello world')

# JOIN
msg = create_join('#test', sender='alice!user@host')
```

### Assertions

```python
from tests.helpers import assert_irc_reply, assert_channel_message_sent

# Check IRC reply code was sent
assert_irc_reply(mock_server.send_message, '353', contains='#test')

# Check channel message was broadcast
assert_channel_message_sent(mock_server.broadcast_to_channel, 
                           '#test', 'PRIVMSG', contains='hello')

# Check log message
from tests.helpers import assert_log_contains
assert_log_contains(mock_server.log, 'Client registered', level='[INFO]')
```

### Client Registration

```python
from tests.helpers import simulate_registration, create_registered_client

# Simulate full registration flow
addr = simulate_registration(handler, ('127.0.0.1', 12345), nick='alice')

# Add registered client to mock
create_registered_client(mock_server.clients, addr, nick='alice', modes={'o'})
```

### Channel Population

```python
from tests.helpers import populate_channel

# Add multiple members to channel
populate_channel(channel, [
    ('alice', ('127.0.0.1', 1001)),
    ('bob', ('127.0.0.1', 1002), {'o'}),  # bob is op
    ('charlie', ('127.0.0.1', 1003), {'v'}),  # charlie has voice
])
```

## Mocking Best Practices

### Mock External Dependencies

Always mock:
- File I/O
- Network operations
- Time functions
- External services

```python
from unittest.mock import patch

@patch('time.time')
def test_with_fixed_time(mock_time):
    """Test with fixed timestamp."""
    mock_time.return_value = 1234567890.0
    # Test code here
```

### Isolate Tests

Each test should be independent:

```python
def test_isolated(mock_server):
    """Test is isolated - mock_server is fresh."""
    # This won't affect other tests
    mock_server.clients['test'] = {...}
```

### Use Descriptive Mocks

Configure mocks to match expected behavior:

```python
def test_channel_lookup(mock_server):
    """Test channel lookup."""
    # Configure mock to return specific channel
    mock_channel = MagicMock()
    mock_channel.name = '#test'
    mock_server.channel_manager.get_channel.return_value = mock_channel
    
    # Test code
    channel = mock_server.channel_manager.get_channel('#test')
    assert channel.name == '#test'
```

## Parametrized Tests

Test multiple inputs with `@pytest.mark.parametrize`:

```python
@pytest.mark.parametrize("nick,expected", [
    ("alice", True),
    ("Alice", True),
    ("ALICE", True),
    ("bob", False),
])
def test_channel_membership(test_channel, nick, expected):
    """Test channel membership for various nick cases."""
    result = test_channel.has_member(nick)
    assert result == expected
```

## Testing Patterns

### Arrange-Act-Assert

Structure tests clearly:

```python
def test_join_channel(handler, mock_server, registered_client):
    """Test joining a channel."""
    # Arrange
    channel_name = '#test'
    msg = create_join(channel_name)
    
    # Act
    handler._handle_join(msg, registered_client)
    
    # Assert
    assert mock_server.channel_manager.ensure_channel.called
    assert_irc_reply(mock_server.send_message, 'JOIN')
```

### Test One Thing

Each test should verify one behavior:

```python
# Good
def test_join_creates_channel(handler, mock_server, registered_client):
    """Test that JOIN creates channel if it doesn't exist."""
    # Test channel creation only
    pass

def test_join_sends_names(handler, mock_server, registered_client):
    """Test that JOIN sends NAMES reply."""
    # Test NAMES reply only
    pass

# Bad
def test_join_everything(handler, mock_server, registered_client):
    """Test everything about JOIN."""
    # Tests too many things at once
    pass
```

### Test Edge Cases

Always test:
- Empty inputs
- Invalid inputs
- Boundary conditions
- Error conditions

```python
def test_channel_name_empty():
    """Test empty channel name is rejected."""
    # Test implementation

def test_channel_name_too_long():
    """Test very long channel name handling."""
    # Test implementation

def test_channel_name_invalid_chars():
    """Test channel name with invalid characters."""
    # Test implementation
```

## Debugging Tests

### Run with verbose output

```bash
pytest -vv
```

### Show print statements

```bash
pytest -s
```

### Drop into debugger on failure

```bash
pytest --pdb
```

### Run only failed tests

```bash
pytest --lf
```

### See full traceback

```bash
pytest --tb=long
```

## Coverage Reports

### Generate HTML coverage report

```bash
pytest --cov=csc_service --cov-report=html
```

### View which lines are missing

```bash
pytest --cov=csc_service --cov-report=term-missing
```

### Check coverage threshold

```bash
pytest --cov=csc_service --cov-fail-under=70
```

## Continuous Integration

Tests are automatically run on:
- Pull requests
- Push to main branch
- Scheduled nightly builds

CI configuration ensures:
- All tests pass
- Coverage meets minimum threshold (70%)
- No test warnings

## Writing Good Tests

### Good Test Characteristics

1. **Fast**: Tests should run quickly (< 1 second each)
2. **Isolated**: No dependencies between tests
3. **Repeatable**: Same result every time
4. **Self-validating**: Pass/fail is automatic
5. **Timely**: Written before or with code

### Test Naming

Use descriptive names that explain what is being tested:

```python
# Good
def test_join_creates_channel_if_not_exists(handler, mock_server):
    """Test that JOIN creates a new channel if it doesn't exist."""
    pass

# Bad
def test_join(handler, mock_server):
    """Test join."""
    pass
```

### Documentation

Every test should have a docstring explaining:
- What is being tested
- Why it matters
- Any special setup or conditions

```python
def test_banned_user_cannot_join(handler, mock_server, test_channel):
    """Test that a banned user cannot join a channel.
    
    This ensures the ban list is checked during JOIN processing
    and that ERR_BANNEDFROMCHAN is sent to banned users.
    """
    # Test implementation
```

## Common Pitfalls

### Don't Test Implementation Details

Test behavior, not implementation:

```python
# Bad - tests internal structure
def test_clients_dict_exists(server):
    assert hasattr(server, 'clients')
    assert isinstance(server.clients, dict)

# Good - tests behavior
def test_server_tracks_registered_clients(server, test_addr):
    server.register_client(test_addr, 'alice')
    assert server.is_registered(test_addr)
```

### Avoid Test Interdependence

Tests should not depend on each other:

```python
# Bad - tests depend on execution order
def test_1_create_channel():
    global channel
    channel = Channel('#test')

def test_2_add_member():
    channel.add_member('alice', addr)  # Uses global from test_1

# Good - each test is independent
def test_create_channel():
    channel = Channel('#test')
    assert channel.name == '#test'

def test_add_member():
    channel = Channel('#test')
    channel.add_member('alice', addr)
    assert channel.has_member('alice')
```

### Mock at the Right Level

Mock external boundaries, not internal logic:

```python
# Good - mock external file I/O
@patch('builtins.open')
def test_save_data(mock_open):
    save_data_to_file({'key': 'value'})
    mock_open.assert_called()

# Bad - mock internal helper
@patch('module.internal_helper')
def test_main_function(mock_helper):
    # Tests become brittle if implementation changes
    pass
```

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [unittest.mock guide](https://docs.python.org/3/library/unittest.mock.html)
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- Project tests: `irc/tests/`
- Test helpers: `irc/tests/helpers.py`
- Fixtures: `irc/tests/conftest.py`

## Getting Help

If you need help with testing:
1. Check this guide
2. Look at existing tests for examples
3. Review test helpers in `helpers.py`
4. Check pytest documentation
5. Ask the team

## Contributing Tests

When adding new features:
1. Write tests first (TDD) or alongside code
2. Aim for >80% coverage of new code
3. Include edge cases and error conditions
4. Update this guide if you add new patterns
5. Run full test suite before committing

```bash
# Before committing
pytest --cov=csc_service --cov-fail-under=70
```
