# Anthropic Prompt Caching Reference

Source: https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching

## Overview

Prompt caching allows resuming from specific prefixes in prompts.
- Reduces processing time and costs for repetitive tasks
- 5-minute default TTL (refreshed on each use), 1-hour optional
- Cache hits cost 10% of base input token price (90% savings)
- Cache writes cost 125% of base input token price

## Two Modes

### 1. Automatic Caching (Simplest)

Add `cache_control` at request top level. System auto-caches the last cacheable block.

```python
response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    cache_control={"type": "ephemeral"},  # Top-level = automatic
    system="You are a helpful assistant.",
    messages=[
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "What did I say?"},
    ],
)
```

### 2. Explicit Cache Breakpoints (Fine-grained)

Place `cache_control` on individual content blocks:

```python
response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    system=[
        {
            "type": "text",
            "text": "You are an AI assistant.",
        },
        {
            "type": "text",
            "text": "Here is a large document: [50 pages of text]",
            "cache_control": {"type": "ephemeral"}
        }
    ],
    messages=[
        {"role": "user", "content": "Summarize this document."}
    ],
)
```

## Pricing

| Model | Base Input | 5m Cache Write | 1h Cache Write | Cache Hit | Output |
|-------|-----------|---------------|----------------|-----------|--------|
| Opus 4.6 | $5/MTok | $6.25/MTok | $10/MTok | $0.50/MTok | $25/MTok |
| Sonnet 4.6 | $3/MTok | $3.75/MTok | $6/MTok | $0.30/MTok | $15/MTok |
| Haiku 4.5 | $1/MTok | $1.25/MTok | $2/MTok | $0.10/MTok | $5/MTok |

**Cache hits = 10% of base input price (90% savings!)**

## Minimum Cacheable Tokens

| Model | Minimum Tokens |
|-------|---------------|
| Claude Opus 4.6, Opus 4.5 | 4096 |
| Claude Sonnet 4.6 | 2048 |
| Claude Sonnet 4.5, Opus 4.1, Opus 4, Sonnet 4 | 1024 |
| Claude Haiku 4.5 | 4096 |

## Cache Order (Hierarchy)

Cache prefixes are created in order: `tools` → `system` → `messages`

Changes at each level invalidate that level AND all subsequent levels.

## What Can Be Cached

- Tool definitions (in `tools` array)
- System messages (content blocks in `system`)
- Text messages (in `messages.content`)
- Images & Documents
- Tool use and tool results

## What Invalidates Cache

| Change | Tools Cache | System Cache | Messages Cache |
|--------|-----------|-------------|---------------|
| Tool definitions | INVALID | INVALID | INVALID |
| Web search toggle | OK | INVALID | INVALID |
| Tool choice | OK | OK | INVALID |
| Images | OK | OK | INVALID |
| Thinking params | OK | OK | INVALID |

## Up to 4 Explicit Breakpoints

```python
response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    tools=[
        {"name": "tool1", ...},
        {"name": "tool2", ..., "cache_control": {"type": "ephemeral"}},  # BP 1
    ],
    system=[
        {"type": "text", "text": "Instructions...",
         "cache_control": {"type": "ephemeral"}},  # BP 2
        {"type": "text", "text": "Large context...",
         "cache_control": {"type": "ephemeral"}},  # BP 3
    ],
    messages=[
        {"role": "user", "content": [
            {"type": "text", "text": "Question",
             "cache_control": {"type": "ephemeral"}}  # BP 4
        ]},
    ],
)
```

## Token Usage Response Fields

```python
response.usage.cache_creation_input_tokens  # Tokens written to cache
response.usage.cache_read_input_tokens      # Tokens read from cache (cheap!)
response.usage.input_tokens                 # Tokens AFTER last cache breakpoint

# Total: cache_read + cache_creation + input_tokens
```

## 1-Hour Cache TTL

```python
"cache_control": {"type": "ephemeral", "ttl": "1h"}
```

- 2x base input token price for writes
- Better for Batch API (batches often take > 5 minutes)
- Same latency as 5-minute cache

## Combining Automatic + Explicit

```json
{
  "model": "claude-opus-4-6",
  "max_tokens": 1024,
  "cache_control": {"type": "ephemeral"},
  "system": [
    {
      "type": "text",
      "text": "System prompt",
      "cache_control": {"type": "ephemeral"}
    }
  ],
  "messages": [{"role": "user", "content": "Question"}]
}
```

## Caching with Tool Use (Multi-turn)

Each turn, mark the last block with `cache_control` for incremental caching:

```
Request 1: system(cached) + user(1)
Request 2: system(cache-hit) + user(1) + asst(1) + user(2, cached)
Request 3: system(cache-hit) + user(1) + asst(1) + user(2, cache-hit) + asst(2) + user(3, cached)
```

## Best Practices

1. Start with automatic caching for multi-turn conversations
2. Use explicit breakpoints for different change frequencies
3. Cache stable content: system instructions, large contexts, tool definitions
4. Place cached content at the beginning of prompts
5. 20-block lookback window for automatic cache checking
6. Analyze cache hit rates and adjust strategy
