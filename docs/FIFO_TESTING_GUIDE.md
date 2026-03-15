# FIFO Testing Guide

How to write tests for CSC using the FIFO client.

## Overview

Tests communicate with the IRC server by:
1. Starting `csc-client --fifo` in the background
2. Writing IRC commands to a named pipe (FIFO)
3. Client reads and executes commands
4. Test reads output file to verify behavior
5. Test logs results back to IRC for traceability

## Quick Start

### Simplest Test (3 lines)

```python
from tests.fifo_client_helper import quick_test

output = quick_test(
    commands=["test message"],
    check_output_contains="test message",
)
```

Done! The helper:
- Starts the client
- Connects and identifies
- Joins #general by default
- Sends your text (client knows the channel)
- Cleans up

## Using FIFOClientTest Directly

For more control:

```python
from tests.fifo_client_helper import FIFOClientTest

with FIFOClientTest() as test:
    # Connect and identify (auto-done by helper init)
    # Client is already connected and in #general

    # Change channel (needs / operator, or it's treated as a message)
    test.send_command("/JOIN #mychannel")

    # Send text (client knows current channel, no PRIVMSG needed)
    test.send_command("hello world")
    test.send_command("testing feature")

    # Read output
    output = test.read_output()

    # Assert
    assert "testing feature" in output, f"Expected message. Got: {output}"

    # Log result back to IRC (appears in current channel)
    test.log_result("PASSED")

    # No need to send QUIT - client stays online, cleaner for repeated tests
```

## API Reference

### FIFOClientTest

#### __init__

```python
FIFOClientTest(
    csc_root=None,              # Project root (auto-detect if None)
    server_host="localhost",    # Server hostname
    server_port=9525,           # Server port
    timeout=10,                 # Max seconds to wait for FIFO
)
```

#### send_command

```python
test.send_command(cmd, delay=0.1)
```
- `cmd`: IRC command string (e.g., "PRIVMSG #channel :message")
- `delay`: Sleep time after sending (seconds)

#### send_commands

```python
test.send_commands(commands, delay=0.1)
```
- `commands`: List of command strings
- `delay`: Sleep between each command

#### read_output

```python
output = test.read_output(clear=True)
```
- Returns accumulated output from client
- `clear=True`: Clear output file after reading
- Output contains all IRC protocol messages

#### log_result

```python
test.log_result("PASSED")  # or "FAILED"
```
- Sends result message to #test channel
- Results appear in output for debugging

#### cleanup

```python
test.cleanup()
```
- Stops client process
- Removes FIFO files
- Auto-called by context manager

### quick_test

```python
output = quick_test(
    commands=[...],                      # Commands to send (after connect)
    check_output_contains=None,          # String to assert in output
    csc_root=None,                       # Project root
)
```

Auto-connects, joins channels, runs commands, verifies output.

## Test Patterns

### Pattern 1: Simple Assertion

```python
def test_message():
    output = quick_test(
        commands=["test message"],
        check_output_contains="test message",
    )
```

### Pattern 2: Multiple Messages in One Channel

```python
def test_sequence():
    with FIFOClientTest() as test:
        # Connected and in #general by default
        test.send_commands([
            "first message",
            "second message",
            "third message",
        ])
        output = test.read_output()
        assert "first message" in output
        assert "second message" in output
        assert "third message" in output
```

### Pattern 3: Channel Switching

```python
def test_channels():
    with FIFOClientTest() as test:
        # Start in #general
        test.send_command("hello from general")

        # Switch to another channel (needs / operator)
        test.send_command("/JOIN #mychannel")
        test.send_command("hello from mychannel")

        output = test.read_output()
        assert "hello from general" in output
        assert "hello from mychannel" in output
        # (or check for channel JOIN confirmation)
```

### Pattern 4: Oper Commands

```python
def test_oper_command():
    with FIFOClientTest() as test:
        # Client auto-opers during setup (via quick_test)
        # For manual setup:
        test.send_command("/OPER admin changeme")
        test.send_command("/MODE #general +m")  # Set moderate

        output = test.read_output()
        assert "MODE" in output or "general" in output
```

## IRC Protocol Reference

Commands must use `/` operator, or client treats them as messages to current channel:

```
/<server <host> <port>         # Connect to server (only if changing servers)
/USER <name> 0 0 :<realname>   # Set user info (auto-done by helper)
/NICK <nickname>               # Set nickname (auto-done by helper)
/OPER <user> <password>        # Gain operator status (auto-done by quick_test)
/JOIN <channel>                # Switch to a channel (/ operator required!)
/PART <channel>                # Leave a channel
/QUIT                          # Disconnect (only if cycling server)
/WHOIS <nick>                  # Query user info
<text>                         # Send message to current channel (no / = PRIVMSG)
```

**Command operator rules**:
- Commands starting with `/` are parsed as IRC commands
- Plain text without `/` is sent as PRIVMSG to current channel
- Example: `/JOIN #channel` works, but `JOIN #channel` sends "JOIN #channel" as a message

**Best practice**: Don't send QUIT at test end — client stays online, cleaner for repeated tests.
Send QUIT only if cycling/restarting the server and worried about ghost clients holding nicks.

## Output Format

`client.out` contains IRC protocol messages:

```
:server.name 001 nickname :Welcome to CSC IRC
:server.name 002 nickname :Your host is server.name
:nickname JOIN #channel
:nickname!user@host PRIVMSG #channel :message text
```

Parse with:
```python
# Simple string search
assert "PRIVMSG" in output

# Check for specific message
assert "message text" in output

# Count occurrences
count = output.count("PRIVMSG")
```

## Common Issues

### FIFO Not Created

- Server must be running (`csc-server` in another terminal)
- Check `tmp/csc/run/` directory exists
- Timeout may be too short (increase timeout param)

### Commands Not Processed

- Add `time.sleep(0.1)` between commands
- Use `test.send_commands()` with delay param
- Wait longer before reading output

### Output Empty

- Verify server is running and connected
- Check that commands were actually sent
- Ensure output file exists (may be cleared)

### Cannot Import Helper

- Ensure CSC_ROOT is in sys.path
- Check tests/ dir is importable
- Try: `python -m pytest tests/test_example_fifo.py -v`

## Performance Notes

- Each test takes ~1-2 seconds (client startup/teardown)
- Use `quick_test()` for fast simple tests
- Use context manager for multi-step tests
- Avoid excessive output reads (they're sequential)

## Integration with Test Runner

The test runner (cron-based) will:
1. Discover `test_*.py` files in tests/
2. Run them (don't call manually)
3. Capture output in `tests/logs/<name>.log`
4. Auto-generate fix workorders on failure

So write your test, but **don't run it** — let the test runner handle execution.

## Debugging

### Print Output

```python
output = test.read_output()
print(f"Output:\n{output}")  # See all responses
print(f"First 500 chars: {output[:500]}")
```

### Log Results Back to IRC

```python
test.log_result("DEBUG: checking channel state")
# Appears in output
output = test.read_output()
print(output)  # Shows debug message
```

### Inspect Raw FIFO Files

```bash
# On Windows:
type tmp\csc\run\client.out

# On Linux:
cat tmp/csc/run/client.out
```

## Examples

See `tests/test_example_fifo.py` for working examples:
- `test_basic_message()` - Simplest test
- `test_channel_join()` - Verify state
- `test_multiple_messages()` - Sequential commands
- `test_with_explicit_output()` - Full flow
