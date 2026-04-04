# Anthropic Message Batches API Reference

Source: https://platform.claude.com/docs/en/docs/build-with-claude/batch-processing

## Overview

The Message Batches API processes large volumes of Messages requests asynchronously.
- 50% cost reduction vs standard API
- Most batches finish in < 1 hour (max 24 hours)
- Up to 100,000 requests or 256 MB per batch
- Results available for 29 days

## Supported Features

ALL Messages API features work in batch:
- Tool use (full tool definitions + tool_use/tool_result)
- Vision
- System messages
- Multi-turn conversations
- Prompt caching (best-effort, 30-98% hit rate)

## Pricing (50% of standard)

| Model | Batch Input | Batch Output |
|-------|------------|-------------|
| Claude Opus 4.6 | $2.50/MTok | $12.50/MTok |
| Claude Opus 4.5 | $2.50/MTok | $12.50/MTok |
| Claude Sonnet 4.6 | $1.50/MTok | $7.50/MTok |
| Claude Sonnet 4.5 | $1.50/MTok | $7.50/MTok |
| Claude Haiku 4.5 | $0.50/MTok | $2.50/MTok |

## SDK Usage (Python)

### Create Batch

```python
import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

client = anthropic.Anthropic()

message_batch = client.messages.batches.create(
    requests=[
        Request(
            custom_id="my-first-request",
            params=MessageCreateParamsNonStreaming(
                model="claude-opus-4-6",
                max_tokens=1024,
                messages=[
                    {"role": "user", "content": "Hello, world"}
                ],
            ),
        ),
        Request(
            custom_id="my-second-request",
            params=MessageCreateParamsNonStreaming(
                model="claude-opus-4-6",
                max_tokens=1024,
                messages=[
                    {"role": "user", "content": "Hi again, friend"}
                ],
            ),
        ),
    ]
)
```

**NOTE:** SDK method is `client.messages.batches.create()` (NOT `client.beta.messages.batches` - graduated from beta).

### Response on Creation

```json
{
  "id": "msgbatch_01HkcTjaV5uDC8jWR4ZsDV8d",
  "type": "message_batch",
  "processing_status": "in_progress",
  "request_counts": {
    "processing": 2,
    "succeeded": 0,
    "errored": 0,
    "canceled": 0,
    "expired": 0
  }
}
```

### Poll for Completion

```python
import time

while True:
    message_batch = client.messages.batches.retrieve(MESSAGE_BATCH_ID)
    if message_batch.processing_status == "ended":
        break
    print(f"Batch {MESSAGE_BATCH_ID} still processing...")
    time.sleep(60)
```

### Retrieve Results

```python
for result in client.messages.batches.results("msgbatch_01HkcTjaV5uDC8jWR4ZsDV8d"):
    match result.result.type:
        case "succeeded":
            print(f"Success! {result.custom_id}")
        case "errored":
            if result.result.error.type == "invalid_request":
                print(f"Validation error {result.custom_id}")
            else:
                print(f"Server error {result.custom_id}")
        case "expired":
            print(f"Request expired {result.custom_id}")
```

### List Batches

```python
for message_batch in client.messages.batches.list(limit=20):
    print(message_batch)
```

### Cancel Batch

```python
message_batch = client.messages.batches.cancel(MESSAGE_BATCH_ID)
```

## Result Types

| Type | Description |
|------|-------------|
| `succeeded` | Request completed. Message result included. |
| `errored` | Error occurred. Not billed. |
| `canceled` | User canceled before processing. Not billed. |
| `expired` | Batch expired (24h limit). Not billed. |

## Batch with Tools

Include tools in each request's params (same as Messages API):

```python
Request(
    custom_id="tool-request",
    params=MessageCreateParamsNonStreaming(
        model="claude-opus-4-6",
        max_tokens=1024,
        tools=[
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
            }
        ],
        messages=[{"role": "user", "content": "Read the config file"}],
    ),
)
```

**IMPORTANT:** Batch API returns tool_use blocks but does NOT execute tools.
You must execute tools locally and resubmit with tool_result if needed.

## Batch + Prompt Caching

Include identical `cache_control` blocks in every request for best-effort cache hits:

```python
Request(
    custom_id="cached-request",
    params=MessageCreateParamsNonStreaming(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": "Large system prompt...",
                "cache_control": {"type": "ephemeral"}
            }
        ],
        messages=[{"role": "user", "content": "..."}],
    ),
)
```

Use 1-hour cache (`"ttl": "1h"`) for better hit rates since batches can take > 5 minutes.

## Limitations

- Max 100,000 requests or 256 MB per batch
- Results expire after 29 days
- Processing may take up to 24 hours
- No streaming for batch requests
- Batches scoped to Workspace
- Cannot modify after submission
