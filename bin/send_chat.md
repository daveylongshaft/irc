# send_chat.py - IRC Chat Sender

Send messages to CSC IRC server from command line.

## Overview

Simple utility to send chat messages to CSC IRC channels and users without interactive client.

Useful for:
- Scripting IRC notifications
- Bot integrations
- Automated messages
- Testing IRC connectivity

## Usage

```bash
python3 /c/csc/bin/send_chat.py [options] <target> <message>

# Send to channel
python3 /c/csc/bin/send_chat.py "#engineering" "Build complete"

# Send to user
python3 /c/csc/bin/send_chat.py "alice" "Meeting in 5 mins"

# With custom server
python3 /c/csc/bin/send_chat.py -s localhost -p 9525 "#general" "test"

# Multi-line message
python3 /c/csc/bin/send_chat.py "#dev" "Line 1
Line 2
Line 3"
```

## Command Line Options

### Required
- `target` - Channel (#channel) or user (nick)
- `message` - Message text to send

### Optional
- `-s, --server <host>` - IRC server host (default: localhost)
- `-p, --port <port>` - IRC server port (default: 9525)
- `-n, --nick <nick>` - Sender nickname (default: csc-cli)
- `--timeout <seconds>` - Connection timeout (default: 5)

## Examples

### Send notification to ops channel
```bash
python3 /c/csc/bin/send_chat.py "#ops" "Deployment successful"
```

### Send DM to user
```bash
python3 /c/csc/bin/send_chat.py "bob" "Your request is approved"
```

### From another server
```bash
python3 /c/csc/bin/send_chat.py -s 192.168.1.100 -p 9525 "#general" "Hello"
```

### In a script
```bash
#!/bin/bash
STATUS=$1
python3 /c/csc/bin/send_chat.py "#builds" "Build status: $STATUS"
```

### Multi-line message
```bash
python3 /c/csc/bin/send_chat.py "#alerts" \
  "Error in production:
   Service: auth-service
   Status: Down
   Action: Restarting..."
```

## Return Codes

- `0` - Message sent successfully
- `1` - Connection error
- `2` - Invalid arguments
- `3` - Message send timeout

## Notes

- Messages limited to IRC line length (512 chars)
- Special characters in messages should be quoted
- Requires IRC server running on specified host:port
- No authentication required (unless server configured)
- Sender nick is optional, defaults to "csc-cli"
