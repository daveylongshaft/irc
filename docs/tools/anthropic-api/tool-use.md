# Anthropic Tool Use Reference

Source: https://platform.claude.com/docs/en/docs/build-with-claude/tool-use

## Overview

Claude can interact with tools/functions you define. You specify available
operations; Claude decides when and how to call them.

## Tool Definition Format

```python
tools = [
    {
        "name": "get_weather",
        "description": "Get the current weather in a given location",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city and state, e.g. San Francisco, CA"
                },
                "unit": {
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                    "description": "Temperature unit"
                }
            },
            "required": ["location"]
        }
    }
]
```

## How It Works

1. You provide tools + user prompt in API request
2. Claude decides to use a tool → response has `stop_reason: "tool_use"`
3. You execute the tool locally and return results as `tool_result`
4. Claude uses results to formulate final response

## Response with Tool Use

```json
{
  "stop_reason": "tool_use",
  "content": [
    {
      "type": "text",
      "text": "I'll check the weather."
    },
    {
      "type": "tool_use",
      "id": "toolu_01A09q90qw90lq917835lq9",
      "name": "get_weather",
      "input": {"location": "San Francisco, CA", "unit": "celsius"}
    }
  ]
}
```

## Returning Tool Results

Send results back in a `user` message with `tool_result` blocks:

```python
messages = [
    {"role": "user", "content": "What's the weather in SF?"},
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "I'll check the weather."},
            {
                "type": "tool_use",
                "id": "toolu_01A09q90qw90lq917835lq9",
                "name": "get_weather",
                "input": {"location": "San Francisco, CA", "unit": "celsius"}
            }
        ]
    },
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_01A09q90qw90lq917835lq9",
                "content": "15 degrees celsius, partly cloudy"
            }
        ]
    }
]
```

## Parallel Tool Use

Claude can call multiple tools in a single response. All `tool_use` blocks
appear in one assistant message. Return ALL results in one user message:

```python
# Response has multiple tool_use blocks
content = [
    {"type": "tool_use", "id": "tool_1", "name": "get_weather", "input": {...}},
    {"type": "tool_use", "id": "tool_2", "name": "get_time", "input": {...}},
]

# Return all results together
messages.append({
    "role": "user",
    "content": [
        {"type": "tool_result", "tool_use_id": "tool_1", "content": "15°C"},
        {"type": "tool_result", "tool_use_id": "tool_2", "content": "3:00 PM"},
    ]
})
```

## Sequential Tool Use

Claude calls one tool at a time when outputs are dependent:

```
User: "What's the weather where I am?"
Assistant: [tool_use: get_location]
User: [tool_result: "San Francisco, CA"]
Assistant: [tool_use: get_weather, input: {location: "San Francisco, CA"}]
User: [tool_result: "15°C, cloudy"]
Assistant: "The weather in San Francisco is 15°C and cloudy."
```

## Agentic Tool Loop Pattern

```python
messages = [{"role": "user", "content": task}]

while True:
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        tools=tools,
        system=system_prompt,
        messages=messages,
    )

    # Add assistant response to conversation
    messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason == "end_turn":
        break  # Done!

    if response.stop_reason == "tool_use":
        # Execute all tool calls
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        # Send results back
        messages.append({"role": "user", "content": tool_results})
```

## Tool Use with Caching

Cache tool definitions by placing `cache_control` on the LAST tool:

```python
tools = [
    {"name": "tool1", "description": "...", "input_schema": {...}},
    {"name": "tool2", "description": "...", "input_schema": {...},
     "cache_control": {"type": "ephemeral"}},  # Caches ALL tools
]
```

## Token Cost

Tool use adds tokens from:
- `tools` parameter (definitions)
- `tool_use` blocks in responses
- `tool_result` blocks in requests
- System prompt for tool use: ~346 tokens (auto/none), ~313 tokens (any/tool)

## stop_reason Values

| Value | Meaning |
|-------|---------|
| `end_turn` | Claude finished responding (no more tools needed) |
| `tool_use` | Claude wants to call tools (execute and return results) |
| `max_tokens` | Hit max_tokens limit |
| `pause_turn` | Server tool loop hit 10-iteration limit |

## Strict Tool Use (Structured Outputs)

Add `strict: true` to guarantee schema conformance:

```python
{
    "name": "get_weather",
    "description": "...",
    "strict": true,
    "input_schema": {
        "type": "object",
        "properties": {...},
        "required": [...]
    }
}
```
