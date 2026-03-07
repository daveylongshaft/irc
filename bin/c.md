# c.py - Quick Command Executor

Fast Python REPL wrapper for quick code execution and testing.

## Overview

Interactive Python shell with CSC modules pre-imported for quick experimentation and testing.

Features:
- Pre-imported CSC modules
- Direct access to IRC classes
- Quick testing environment
- Python REPL with history

## Usage

```bash
# Start interactive shell
python3 /c/csc/bin/c.py

# Execute code and exit
python3 /c/csc/bin/c.py -c "code here"

# Run script
python3 /c/csc/bin/c.py script.py

# Import modules on startup
python3 /c/csc/bin/c.py --import "csc_server.server:Server"
```

## Command Line Options

- `-c, --code <code>` - Execute code and exit
- `-i, --interactive` - Interactive mode after code
- `--import <module:class>` - Pre-import modules
- `--no-csc` - Don't pre-import CSC modules

## Pre-imported Modules

When started, automatically imports:

```python
from csc_shared.irc import IRCMessage, IRCReply
from csc_shared.channel import Channel
from csc_shared.user import User
from csc_server.server import Server
from csc_server.storage import Storage
```

## Examples

### Interactive shell
```bash
$ python3 /c/csc/bin/c.py
>>> msg = IRCMessage("PRIVMSG #general :hello")
>>> print(msg.command)
PRIVMSG
>>> exit()
```

### Quick code execution
```bash
python3 /c/csc/bin/c.py -c "print(IRCMessage('JOIN #test').command)"
```

### Test IRC message parsing
```bash
python3 /c/csc/bin/c.py << 'EOF'
msg = IRCMessage(":alice!alice@host PRIVMSG #test :hello world")
print(f"From: {msg.nick}")
print(f"Command: {msg.command}")
print(f"Target: {msg.params[0]}")
print(f"Text: {msg.params[1]}")
EOF
```

### Load custom modules
```bash
python3 /c/csc/bin/c.py --import "mymodule:MyClass"
```

## Interactive Commands

In interactive mode:

```
>>> help()              # Python help
>>> dir()               # List variables
>>> import sys          # Import more modules
>>> exit()              # Exit shell
```

## Common Tasks

### Test channel creation
```python
ch = Channel("#test")
ch.add_member("alice")
print(ch.members)
```

### Test user parsing
```python
user = User("alice")
user.add_mode("o")
print(user.modes)
```

### Test IRC replies
```python
reply = IRCReply(001, ["nick", "Welcome"])
print(reply.build())
```

### Test message building
```python
msg = IRCMessage()
msg.command = "PRIVMSG"
msg.params = ["#test", "hello"]
print(msg.build())
```

## Notes

- REPL style is standard Python prompt
- Tab completion available
- Command history saved
- Ctrl+D or exit() to quit
- Requires CSC modules installed
