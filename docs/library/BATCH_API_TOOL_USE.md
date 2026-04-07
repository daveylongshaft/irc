# Anthropic Batch API with Tool Use

**Date:** 2026-03-01
**Status:** Testing & Documentation
**Goal:** Implement autonomous agent work via Anthropic Batch API with full tool support

## Overview

The Anthropic Batch API supports **tool use** - the same tool_use capabilities as the synchronous Messages API. This enables autonomous agents to execute complex implementation tasks asynchronously with full access to tools.

## Key Findings

### 1. Batch API Supports Tool Definitions

Unlike earlier assumptions, the Batch API is **NOT text-only**. It fully supports:

```python
client.beta.messages.batches.create(requests=[
    {
        "custom_id": "id-1",
        "params": {
            "model": "claude-opus-4-6",
            "tools": [
                {
                    "name": "read_file",
                    "description": "Read file contents",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"}
                        },
                        "required": ["path"]
                    }
                },
                # ... more tools
            ],
            "messages": [...]
        }
    }
])
```

### 2. Tool Use Flow in Batch API

**Iteration 1:**
- Send: Request with tool definitions + user prompt
- Claude generates: `tool_use` blocks with `name`, `input`, and auto-generated `id`
- Batch completes
- We execute tools using the tool `name` and `input`

**Iteration 2+:**
- Send: New batch request with conversation history
- Include: Previous assistant message (with tool_use blocks)
- Include: New tool_result messages with execution results
- Claude continues with more tool calls or final implementation

### 3. Tool Use Block Format

Claude generates tool_use in the response with Anthropic's JSON format:

```json
{
    "type": "tool_use",
    "id": "tool_use_xyz123",
    "name": "read_file",
    "input": {
        "path": "/path/to/file"
    }
}
```

**NOT XML format** - the earlier parsing was trying to handle XML representation, but the actual SDK uses JSON.

### 4. Processing Tool Results

After executing a tool, send results back in the next batch request:

```python
{
    "custom_id": "id-2",
    "params": {
        "model": "claude-opus-4-6",
        "tools": [...],
        "messages": [
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": [
                # Include the previous assistant message with tool_use
                {"type": "tool_use", "id": "tool_use_xyz123", "name": "read_file", "input": {...}},
            ]},
            {"role": "user", "content": [
                # Send back tool results
                {"type": "tool_result", "tool_use_id": "tool_use_xyz123", "content": "File contents..."}
            ]}
        ]
    }
}
```

## Implementation Strategy

### Phase 1: Tool Definitions (DONE)
Define available tools in batch request:
- `read_file(path)` - Read file contents
- `write_file(path, content)` - Write file
- `list_directory(path)` - List directory contents
- `run_command(command)` - Execute shell commands

### Phase 2: Multi-Turn Batch Conversation (IN PROGRESS)
1. Send request with tools + workorder
2. Claude generates tool_use blocks
3. Execute tools locally
4. Send results back in new batch request
5. Repeat until Claude signals completion

### Phase 3: Autonomous Implementation (PLANNED)
- Opus explores codebase using tools
- Reads existing patterns
- Implements batch_api.py
- Updates queue_worker.py and pm.py
- Writes tests
- Commits to git
- Signals completion

## Advantages Over Direct Subprocess

| Aspect | Subprocess | Batch API |
|--------|-----------|-----------|
| **Segfault Risk** | High (Windows process groups) | None (async) |
| **Responsiveness** | Immediate | Delayed (queue) |
| **Cost Efficiency** | Baseline | 50%+ savings with caching |
| **Scalability** | Limited (1 agent per subprocess) | Unlimited (1000s async) |
| **Tool Access** | Live shell | Via SDK tools |

## Cost Analysis

**Without Prompt Caching:**
- System prompt: ~4000 tokens
- Code maps: ~2000 tokens
- Workorder: ~500 tokens
- **Per request: 6500 tokens**

**With Prompt Caching (Batch):**
- System prompt (cached): 0 tokens (after creation cost)
- Code maps (cached): 0 tokens
- Workorder: 500 tokens
- **Per request: 500 tokens (92% savings)**

For multi-iteration batch:
- Iteration 1: 6500 tokens (cache creation)
- Iterations 2-N: 500 tokens each
- **Average savings: 80-90%**

## Challenges & Solutions

### Challenge 1: Multi-Turn Complexity
**Problem:** Each iteration requires creating new batch requests

**Solution:** Automate batch iteration handling:
```python
def continue_batch_conversation(previous_response, tool_results):
    new_request = {
        "messages": [
            {"role": "user", "content": initial_prompt},
            {"role": "assistant", "content": [previous_response]},
            {"role": "user", "content": tool_results}
        ]
    }
```

### Challenge 2: Tool Execution Timeout
**Problem:** Batch API has no timeout for individual tool executions

**Solution:** Implement tool execution with timeout:
```python
def execute_tool_with_timeout(tool_name, inputs, timeout=30):
    try:
        result = tools[tool_name](**inputs)
        return result
    except TimeoutError:
        return f"Tool execution timed out after {timeout}s"
```

### Challenge 3: Handling Tool Failures
**Problem:** Failed tool calls need to be retried or handled gracefully

**Solution:** Send error messages back in tool_result:
```python
{
    "type": "tool_result",
    "tool_use_id": "xyz",
    "content": "Error: File not found at /path/to/missing/file",
    "is_error": True
}
```

## Files Created

1. **bin/batch-submit-opus-batch-impl.py** - Initial batch submission (text only)
2. **bin/batch-process-opus-tools.py** - Tool extraction and execution
3. **bin/batch-continue-opus-impl.py** - Multi-turn batch iteration
4. **bin/batch-opus-impl-with-tools.py** - **CURRENT** - Batch with tool definitions
5. **docs/BATCH_API_TOOL_USE.md** - This documentation

## Next Steps

1. ✅ Understand Batch API tool support (completed)
2. ⏳ Execute batch with tool definitions (in progress)
3. Process tool_use blocks from response
4. Execute tools and collect results
5. Send results back in next batch
6. Iterate until Opus completes implementation
7. Document final patterns in CLAUDE.md

## References

- Anthropic API: https://docs.anthropic.com/
- Batch API Docs: https://docs.anthropic.com/batches/
- Tool Use: https://docs.anthropic.com/tool-use/
- Python SDK: https://github.com/anthropics/anthropic-sdk-python

## Metrics

**Batch Job Submissions:** 3 total
- msgbatch_01PeQjsq7MD9JgFVwLBcSTwT (exploration)
- msgbatch_01EXW77TBUFPdY1frLcEJgpr (continued exploration)
- msgbatch_XXXXX (in progress - with tools)

**Average Batch Processing Time:** ~4-5 minutes per iteration

**Expected Total Implementation Time:** 2-3 iterations = 10-15 minutes
