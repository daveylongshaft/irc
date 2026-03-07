# batch_executor.py - Batch API Tool Loop Executor

Execute Anthropic Batch API requests with autonomous tool loop and retry/escalation.

## Overview

Executes submitted batch requests from the Batch API, implements the tool execution loop, handles tool results, and escalates to higher-capability models on failure.

Features:
- Tool loop execution (run_command, read_file, write_file, list_directory)
- Automatic retry with configurable max retries
- Model escalation chain: haiku → sonnet → opus
- Verbose logging of all tool executions
- Path normalization (Cygwin/Windows)
- Caching of batch results

## Usage

```bash
# Single batch
python3 /c/csc/bin/batch_executor.py msgbatch_01JoDGSYgfqHBQqMXh9jnUaK

# Multiple batches
python3 /c/csc/bin/batch_executor.py msgbatch_01... msgbatch_02... msgbatch_03...

# Execute all restructure phases
python3 /c/csc/bin/batch_executor.py --all-restructure-phases

# With options
python3 /c/csc/bin/batch_executor.py msgbatch_01... --max-retries 3 --max-iterations 20

# Dry run (preview without execution)
python3 /c/csc/bin/batch_executor.py msgbatch_01... --dry-run
```

## Command Line Options

### Positional Arguments
- `batch_ids` - One or more batch IDs to process

### Optional Arguments
- `--all-restructure-phases` - Execute all 5 CSC restructure phases
- `--phase N` - Execute specific phase number
- `--with-retry` - Enable retry on failures
- `--max-retries N` - Maximum retries per phase (default: 2)
- `--sequential` - Process batches sequentially (waits for each to complete)
- `--max-iterations N` - Max iterations per batch (default: 20)
- `--dry-run` - Show what would happen without executing

## Environment Variables

Required:
- `ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY_3` - API key for Anthropic

Optional:
- `CSC_ROOT` - Root directory (defaults to /c/csc)

## Tool Execution

Executor automatically executes these tools returned by Claude:

### run_command
Execute bash command locally
```python
{
    "type": "tool_use",
    "name": "run_command",
    "input": {
        "command": "ls -la /c/csc"
    }
}
```

### read_file
Read file contents
```python
{
    "type": "tool_use",
    "name": "read_file",
    "input": {
        "path": "/c/csc_old/packages/csc-service/main.py"
    }
}
```

### write_file
Write or create file
```python
{
    "type": "tool_use",
    "name": "write_file",
    "input": {
        "path": "/c/csc/new_file.txt",
        "content": "file contents here"
    }
}
```

### list_directory
List directory contents
```python
{
    "type": "tool_use",
    "name": "list_directory",
    "input": {
        "path": "/c/csc/irc"
    }
}
```

## Retry and Escalation

When a tool execution fails:
1. Tool error is captured
2. Sent back to Claude for analysis
3. Claude retries with same model (up to max_retries)
4. If all retries fail, escalates to next model in chain
5. Escalation chain: haiku → sonnet → opus

Example log:
```
[TOOL_EXEC] run_command START: git push
[TOOL_EXEC] run_command DONE: returncode=1, output_len=256
[SUBMIT] Result has error, submitting for retry...
[Retry 1/2 with haiku]
[TOOL_EXEC] run_command START: git pull && git push
[TOOL_EXEC] run_command DONE: returncode=0
[+] Tool succeeded on retry
```

## Logging Output

Verbose logging shows:

```
[timestamp] [+] Batch submitted: msgbatch_01...
[timestamp] [~] Batch msgbatch_01... status: in_progress
[timestamp] [+] Result custom_id: stop_reason=tool_use
[timestamp] [>] [TOOL_EXEC] run_command START: command here
[timestamp] [>] [TOOL_EXEC] run_command DONE: returncode=0, output_len=512, time=45ms
[timestamp] [>] [TOOL_EXEC] run_command OUTPUT: (command output)
[timestamp] [+] [SUBMIT] New batch submitted: msgbatch_02...
[timestamp] [+] Reached end_turn - loop complete
```

## Examples

### Execute a single batch
```bash
export ANTHROPIC_API_KEY="sk-ant-api03-..."
python3 /c/csc/bin/batch_executor.py msgbatch_01JoDGSYgfqHBQqMXh9jnUaK
```

### Execute CSC restructure phases
```bash
python3 /c/csc/bin/batch_executor.py --all-restructure-phases
```

### Execute with custom retry count
```bash
python3 /c/csc/bin/batch_executor.py msgbatch_01... --max-retries 5 --max-iterations 30
```

### Watch execution in real-time
```bash
python3 /c/csc/bin/batch_executor.py msgbatch_01... 2>&1 | tee execution.log
```

## Configuration

### Escalation Chain
Located in batch_executor.py:
```python
ESCALATION_CHAIN = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514"
]
```

### Default Retries
```python
DEFAULT_MAX_RETRIES = 2
```

## Execution States

- `in_progress` - Batch still processing at API
- `ended` - Batch completed, results available
- `stop_reason=tool_use` - Claude returned tool calls
- `stop_reason=end_turn` - Claude finished, no more tool calls
- `errored` - Batch or iteration failed

## Output Files

Execution logs saved to:
- `/c/csc/logs/batch_executor_YYYYMMDD_HHMMSS.json` - Full execution log

## Return Codes

- `0` - Success
- `1` - Failure (batch error, API error, or timeout)
- `143` - Terminated by signal

## Notes

- Paths use Cygwin format `/c/...` and are automatically converted to Windows format
- Tool results are cached locally in execution log
- Maximum iterations prevents infinite loops
- Batches run sequentially by default
- Each tool execution has 120s timeout
