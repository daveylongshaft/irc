[← Back to README](../README.md)

# Client Terminal Documentation

The `csc-client` is a feature-rich human-facing terminal client for the CSC IRC ecosystem. It provides a standard IRC-like interface while adding advanced capabilities for automation, file management, and protocol translation.

---

## 🚦 Getting Started

### 1. Installation & Configuration
The client is configured via `client_config.json`. On the first run, it will create a default configuration pointing to `127.0.0.1:9525`.

```bash
# Start the client
python main.py [optional_config.json]
```

### 2. Identity & Registration
Upon startup, the client automatically sends the `NICK` and `USER` commands to register with the server. If you have registered your nickname with `NickServ`, you should use `/msg NickServ IDENTIFY <password>` after connecting.

## 🤖 Programmatic Usage

The CSC Client supports **headless operation for automated, scripted workflows**. This is critical for the AI task execution system where agents must programmatically assign tasks, send commands, and verify responses without human interaction.

### Core Flags

#### `--infile <file>`
Read commands sequentially from a text file instead of stdin. The client processes each line as a command and exits cleanly after the last command.

**File Format**: One command per line, same syntax as interactive mode (including `/` prefix for local commands).

**Example file (commands.txt):**
```
/join #general
/msg #general Hello from automation
/status
/quit
```

The client will:
1. Connect to the server
2. Execute `/join #general`
3. Send the message to #general
4. Print the `/status` output
5. Exit via `/quit`

#### `--outfile <file>`
Append all client output to a file instead of stdout. Output includes:
- Server welcome messages
- Command responses
- Channel messages
- Connection status
- Errors and warnings

**Mode**: Output file is opened in append mode (`'a'`) with line buffering (1-character buffer), so data is written immediately.

#### `--detach`
Run in **non-interactive mode**:
- Disables readline (command history, tab completion)
- Disables stdin polling
- Client runs to completion silently (no prompt)
- Useful for background jobs and cron execution

### Flag Combinations & Use Cases

#### Pattern 1: Simple Sequential Commands (Interactive Feedback)
For testing or debugging where you want to see output:
```bash
python packages/csc_client/client.py --infile commands.txt --outfile log.txt
# Note: No --detach, so uses readline if available
```

Output appears in `log.txt` as commands execute. Useful for verification before fully automating.

#### Pattern 2: Capturing Output for Verification
For automation where you need to parse results:
```bash
python packages/csc_client/client.py --infile commands.txt --outfile result.log --detach
grep "success" result.log && echo "OK" || echo "FAILED"
```

Example infile:
```
/join #channel
/msg #channel test message
/part
/quit
```

The `result.log` will contain all output including confirmations. You can then parse it for verification.

#### Pattern 3: Error Detection & Response
Create an infile that tests for errors and logs them:
```bash
cat > test_cmds.txt <<'EOF'
/join #nonexistent
/nick newname
/whois newname
/quit
EOF

python packages/csc_client/client.py --infile test_cmds.txt --outfile test.log --detach
if grep -q "error\|Error\|ERR" test.log; then
  echo "Command failed" >&2
  cat test.log
  exit 1
fi
```

#### Pattern 4: Task Assignment Workflow (PRIMARY USE CASE)
This is the standard pattern for AI agents to assign tasks to other agents:

```bash
# Step 1: Create infile with task assignment sequence
cat > assign_task.txt <<'EOF'
/join #general
AI agent assign PROMPT_expand_client_programmatic_docs.md
/quit
EOF

# Step 2: Run client detached and capture output
python packages/csc_client/client.py --infile assign_task.txt --outfile assign.log --detach

# Step 3: Verify assignment success
if grep -q "Agent assigned\|task.*accepted" assign.log; then
  echo "Task successfully assigned"
  # Optional: Log the assignment
  echo "Assigned PROMPT_expand_client_programmatic_docs.md at $(date)" >> assignments.log
else
  echo "Task assignment failed"
  tail -10 assign.log  # Show last 10 lines of error
  exit 1
fi

# Cleanup
rm assign_task.txt
```

See the **"Task Assignment via Programmatic Mode"** section below for complete details.

#### Pattern 5: Long-Running Operations with Detach
For operations that take time (file uploads, bulk messaging):
```bash
cat > bulk_ops.txt <<'EOF'
/join #archive
/send large_dataset.txt
/part
/quit
EOF

# Run detached so shell prompt returns immediately
python packages/csc_client/client.py --infile bulk_ops.txt --outfile bulk.log --detach

# Check status later
sleep 5
if grep -q "uploaded\|Uploaded" bulk.log; then
  echo "Upload complete"
else
  echo "Still uploading or failed"
fi
```

### Best Practices for Programmatic Mode

#### 1. Structure Infiles Reliably
- **One command per line** — Each line is a separate command
- **Include explicit exit** — Always end with `/quit` so the client exits cleanly
- **Use absolute paths** — For file operations (e.g., `/send /absolute/path/file.txt`)
- **Avoid fancy escaping** — Keep commands simple; the client handles quoting

**Good infile:**
```
/join #general
/msg #general Starting task batch
/part
/quit
```

**Avoid:**
```
# Comments don't work
/join #general && /msg ...  # Shell syntax doesn't apply
"quoted" commands          # Quote handling differs
```

#### 2. Timeout & Reliability Considerations
- **Network delays**: Server may take time to process commands. Build in small waits if parsing output:
  ```bash
  python packages/csc_client/client.py --infile cmds.txt --outfile out.txt --detach
  sleep 1  # Give client time to flush output
  grep "expected" out.txt
  ```
- **File I/O**: Output file uses line buffering, so data is written immediately but shell may cache
- **Connection drops**: If server is unreachable, client will log connection errors to output file

#### 3. Exit Code Handling
The client exits with:
- **0** - All commands processed successfully (or last command was `/quit`)
- **1** - Initialization failure (config file error, output file open failed, connection refused)

**Capture exit code:**
```bash
python packages/csc_client/client.py --infile cmds.txt --outfile out.txt --detach
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
  echo "Client initialization failed"
  exit 1
fi
```

Note: Individual command failures (e.g., `/join #nonexistent`) do NOT cause non-zero exit code. You must parse the output file to detect command-level failures.

#### 4. Logging & Debugging
- **Always use `--outfile`** for automation — stdout may not be captured in cron/background jobs
- **Timestamp your logs** — Add markers to correlate with system events:
  ```bash
  echo "=== Task assignment at $(date -u +%Y-%m-%dT%H:%M:%S) ===" >> task.log
  python packages/csc_client/client.py --infile assign.txt --outfile task_detail.log --detach
  cat task_detail.log >> task.log
  ```
- **Log the infile too** — Save what you sent for debugging:
  ```bash
  cp assign_cmds.txt assign_cmds.$(date +%s).txt  # Archive with timestamp
  ```

### Advanced: Service Commands in Programmatic Mode

Service commands (`AI <token> <service> <method> [args]`) work normally in infiles:

```bash
cat > service_cmds.txt <<'EOF'
/join #service_channel
AI prompts list ready
AI prompts read PROMPT_myfile.md
/quit
EOF

python packages/csc_client/client.py --infile service_cmds.txt --outfile service.log --detach

# Parse service responses from output
grep "ready/" service.log | wc -l  # Count ready prompts
```

Service commands send through the normal PRIVMSG path and responses appear in the output log.

---

## Task Assignment via Programmatic Mode

This is the **primary use case** for programmatic mode: AI agents assigning tasks to other agents through the CSC ecosystem.

### Standard Workflow

All AI agents follow this pattern to assign tasks:

1. **Create a temporary infile** with the assignment command
2. **Run the client detached** with output capture
3. **Verify success** by parsing the output
4. **Clean up** temporary files

### Complete Example: Assigning a Task to Another Agent

```bash
#!/bin/bash
# Assign a task via CSC Client in programmatic mode

TASK_FILE="PROMPT_expand_client_programmatic_docs.md"
INFILE="/tmp/assign_${TASK_FILE%.md}_$$.txt"  # Use PID for uniqueness
OUTFILE="/tmp/assign_out_$$.txt"

# Step 1: Create infile with assignment command
cat > "$INFILE" <<EOF
/join #general
AI agent assign $TASK_FILE
/quit
EOF

# Step 2: Run client detached
python3 packages/csc_client/client.py \
  --infile "$INFILE" \
  --outfile "$OUTFILE" \
  --detach

# Step 3: Check exit code
if [ $? -ne 0 ]; then
  echo "ERROR: Client failed to start"
  cat "$OUTFILE"
  rm "$INFILE" "$OUTFILE"
  exit 1
fi

# Step 4: Verify assignment success
sleep 1  # Give server time to process
if grep -q "assigned\|success" "$OUTFILE"; then
  echo "✓ Task $TASK_FILE assigned successfully"
  RESULT=0
else
  echo "✗ Task assignment failed"
  echo "Output was:"
  cat "$OUTFILE"
  RESULT=1
fi

# Step 5: Cleanup
rm "$INFILE" "$OUTFILE"
exit $RESULT
```

### Integration with Prompt/Agent System

When assigned via `AI agent assign PROMPT_*.md`, the server:
1. Parses the PROMPT filename from the command
2. Reads the file from the prompts directory
3. Assigns it to an available agent
4. Moves it from `ready/` to `wip/`
5. Responds with confirmation message

Your programmatic client waits for the response, so sequential assignments work:

```bash
for prompt_file in PROMPT_task1.md PROMPT_task2.md PROMPT_task3.md; do
  # Assign each task
  python packages/csc_client/client.py \
    --infile <(echo -e "/join #general\nAI agent assign $prompt_file\n/quit") \
    --outfile /tmp/assign_$prompt_file.log \
    --detach

  # Verify before next iteration
  if ! grep -q "assigned" /tmp/assign_$prompt_file.log; then
    echo "Failed to assign $prompt_file"
    exit 1
  fi

  # Small delay between assignments
  sleep 0.5
done
```

---

## Programmatic Mode Examples: Common Scenarios

### Scenario 1: Join Multiple Channels and Send Messages

```bash
cat > multi_channel.txt <<'EOF'
/join #general
/msg #general Channel one message
/join #engineering
/msg #engineering Channel two message
/part #engineering
/part #general
/quit
EOF

python packages/csc_client/client.py --infile multi_channel.txt --outfile channels.log --detach
```

### Scenario 2: File Upload in Programmatic Mode

```bash
cat > upload.txt <<'EOF'
/join #data
/send /path/to/local/file.txt
/part
/quit
EOF

python packages/csc_client/client.py --infile upload.txt --outfile upload.log --detach

# Verify upload
if grep -q "uploaded\|transferred" upload.log; then
  echo "File uploaded successfully"
fi
```

### Scenario 3: Service Command Execution

```bash
cat > service.txt <<'EOF'
/join #service
AI prompts list ready
AI prompts read PROMPT_example.md
/quit
EOF

python packages/csc_client/client.py --infile service.txt --outfile service.log --detach

# Parse results
echo "Ready prompts:"
grep "ready/" service.log
```

### Scenario 4: Batch Operations with Verification

```bash
#!/bin/bash
# Verify multiple operations

OPS=(
  "/msg #test op1"
  "/msg #test op2"
  "/msg #test op3"
)

INFILE="/tmp/batch_$$.txt"
OUTFILE="/tmp/batch_out_$$.txt"

# Build infile
{
  echo "/join #test"
  for op in "${OPS[@]}"; do
    echo "$op"
  done
  echo "/quit"
} > "$INFILE"

# Execute
python packages/csc_client/client.py --infile "$INFILE" --outfile "$OUTFILE" --detach

# Count successes
COUNT=$(grep -c "op[1-3]" "$OUTFILE")
echo "Completed $COUNT of ${#OPS[@]} operations"

# Cleanup
rm "$INFILE" "$OUTFILE"
```

---

## Error Handling & Debugging

### Detecting Connection Errors

```bash
python packages/csc_client/client.py --infile cmds.txt --outfile out.txt --detach

# Check for common error patterns
if grep -qi "connection refused\|timeout\|unreachable" out.txt; then
  echo "Server connection failed"
  exit 1
fi

if grep -qi "unknown command\|invalid" out.txt; then
  echo "Command syntax error"
  exit 1
fi
```

### Interpreting Client Exit Codes

```bash
python packages/csc_client/client.py --infile cmds.txt --outfile out.txt --detach
RESULT=$?

case $RESULT in
  0) echo "Success" ;;
  1) echo "Client initialization failed (config/file/connection issue)"
     echo "See output file:"
     head -20 out.txt ;;
  *) echo "Unknown exit code: $RESULT" ;;
esac
```

### Logging Troubleshooting Tips

- **All output is in the output file** — The client logs everything to `--outfile`, not stdout
- **Check for buffering delays** — Add `sleep 1` after client completes before parsing
- **Review server logs** — If client works but operations don't, check server logs for the actual command processing
- **Test commands interactively first** — Before automating, run commands manually to verify they work

### Recovery Strategies

If a task assignment fails:

```bash
#!/bin/bash
# Robust task assignment with retry

MAX_RETRIES=3
RETRY=0

while [ $RETRY -lt $MAX_RETRIES ]; do
  python packages/csc_client/client.py \
    --infile assign.txt \
    --outfile assign_$RETRY.log \
    --detach

  if grep -q "assigned" assign_$RETRY.log; then
    echo "Assignment succeeded on attempt $((RETRY+1))"
    exit 0
  fi

  RETRY=$((RETRY+1))
  sleep 1  # Wait before retry
done

echo "Assignment failed after $MAX_RETRIES attempts"
exit 1
```

---

## 💬 Command Reference

### Messaging & Channels
- `/join #channel`: Join a channel (e.g., `/join #general`).
- `/part [#channel] [reason]`: Leave the current or specified channel.
- `/msg <target> <text>`: Send a private message to a user or channel.
- `/notice <target> <text>`: Send a notice (non-query) message.
- `/me <action>`: Send an emote/action message (e.g., `/me waves hello`).
- `/topic [#channel] [new_topic]`: View or set the channel topic.
- `/list`: List all public channels on the server.
- `/names [#channel]`: List users in a channel.
- `/buffer [target]`: Request a replay of the chat buffer for a channel or PM.

### Connection & Network Control
- `/server <host> [port]`: Disconnect from the current server and connect to a new one.
- `/reconnect`: Force a disconnect and reconnect to the current server.
- `/disconnect`: Gracefully disconnect from the server.
- `/status`: Display detailed connection, registration, and operator status.
- `/ping`: Measure network latency to the server.
- `/translator <host> <port>`: Route your connection through a CSC Bridge/Translator proxy.
- `/translator off`: Disable the translator and connect directly.

### User & Admin Operations
- `/nick <new_name>`: Change your nickname.
- `/whois <nick>`: View information about a user (host, channels, oper status).
- `/who <channel|mask>`: List users matching a mask.
- `/whowas <nick>`: View history for a recently disconnected nickname.
- `/oper <name> <password>`: Authenticate as an IRC Operator.
- `/kick #channel <nick> [reason]`: Remove a user from a channel (requires Op).
- `/mode <target> <modes> [params]`: Change user or channel modes.
- `/motd`: View the server's Message of the Day.

### File & Service Operations
- `/send <filepath>`: Upload a local text file to the current channel.
- `/dcc send <nick> <pathspec>`: Send one or more files directly to another client using standard CTCP DCC SEND offers (mIRC/BitchX/ircii style).
- `/dcc ports <low[-high]>`: Pin outgoing DCC listener to a fixed port or an inclusive port range.
- `AI <token> <service> <method> [args]`: Execute a server-side service command.
- **Multi-line Paste**: You can paste blocks of text starting with `<begin file="name">` and ending with `<end file>`. The client will buffer the lines and send them as a single block.

---

## 📦 DCC File Transfers & Chat (CTCP DCC SEND / CHAT)

CSC clients now support interoperable DCC SEND and DCC CHAT behavior for peer-to-peer file exchange and private, channel-less interactive chat:

- **Offer format**: CTCP `DCC SEND` is emitted in standard style: filename, numeric IPv4, TCP port, and file size.
- **Send command**: `/dcc send <nick> <pathspec>` where `pathspec` supports glob matching (`*.py`, `logs/*.txt`, etc.).
- **Auto-receive**: Incoming DCC SEND offers are automatically accepted and downloaded without manual prompt.
- **Download location**: Files are saved into the client runtime download directory: `run/downloads/`.
- **ACK behavior**: Receiver sends 32-bit cumulative ACK counters during transfer for compatibility with traditional DCC senders.
- **Port control**: `/dcc ports` persists preferred DCC listen port(s) into client data storage, so the setting survives restarts.
- **Auto reverse fallback**: If receiver cannot connect back to sender (firewall/NAT path failure), it automatically requests reverse direction and sender connects to receiver listener to retry transfer.

### Command Examples

```bash
# Use fixed DCC listen port (single port mode)
/dcc ports 5000

# Use inclusive DCC listen range
/dcc ports 5000-5010

# Send one file
/dcc send Gemini ./services/builtin_service.py

# If connect-back fails, client auto-requests reverse fallback (no extra command needed)

# Send multiple files using glob
/dcc send Claude ./services/*.py

# Send log bundle to human operator nick
/dcc send dave ./csc-logs/*.log

# Initiate a DCC CHAT with another nick
/dcc chat Alice

# Manually accept an incoming DCC CHAT offer
/dcc chat accept Bob

# Close an active DCC CHAT session
/dcc chat close

# Check DCC CHAT session statuses
/dcc chat status
```

### Behavioral Notes

1. **Direct peer TCP path**: DCC payload bytes move over a temporary TCP socket between sender and receiver clients.
2. **Bridge compatibility goal**: CTCP DCC offers are sent as normal IRC `PRIVMSG` payloads so bridge-connected clients can parse them as standard CTCP.
3. **Security/safety**:
   - Received filename is sanitized to basename before writing.
   - Transfers write to a temporary `.part` file and then atomically move to final filename on success.
4. **Error reporting**: Transfer failures include specific diagnostics (offer timeout, malformed SEND payload, size mismatch, socket errors) to simplify troubleshooting.

---

## 🛠️ Advanced Features

### Aliases
Create custom shortcuts for complex commands.
- `/alias <name> = <command>`: Define an alias (e.g., `/alias ls = /list`).
- `/unalias <name>`: Remove an alias.
- `/aliases`: List all defined aliases.
- **Positional Args**: Use `$1`, `$2`, etc., in your alias template (e.g., `/alias greet = /msg $1 Hello!`).

### Macros
Sequence multiple commands together.
- `/macro <name> = <cmd1>; <cmd2>; ...`: Define a macro (e.g., `/macro start = /join #general; /msg #general I'm here!`).
- `/unmacro <name>`: Remove a macro.
- `/macros`: List all defined macros.

### Nick-Prefixed Remote Execution
Authorized users (you, server, or channel ops) can trigger commands on your client remotely by prefixing them with your nickname:
- `YourNick AI ...`: Executes a local service plugin.
- `YourNick <begin file=...>`: Uploads a file directly to your client's `plugins/` directory.

---

## 💾 State Persistence
The client automatically saves your session state in `client_state.json`. When you restart the client and register with the same name, it will automatically:
1.  Restore your user modes.
2.  Rejoin all channels you were previously in.

---

## ⌨️ Interaction Tips
- **Readline Support**: Use Arrow Keys to navigate command history and Tab for basic completion (on supported systems).
- **Formatting**: The client automatically formats incoming `PRIVMSG` and `NOTICE` events for readability.
- **Security**: The client implements root confinement for incoming file uploads, ensuring remote users cannot write files outside the client's directory.

---
*The CSC Client is designed for power users who need CLI-driven control over a distributed AI ecosystem.*

[Prev: Bridge & Translator](bridge.md) | [Next: Protocol & Shared](protocol.md)
