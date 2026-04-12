# AI Client API Architecture

The `csc-ai-api` package provides a standardized abstraction layer for all AI agents in the CSC system. It sits between the low-level `csc-clients` (IRC protocol) and concrete agent implementations (Claude, Gemini, ChatGPT, etc.).

## Components

### 1. AIClient (Base Class)
- Inherits from `Client` (from `csc-clients`).
- Orchestrates specialized managers for context, timing, and engagement.
- Implements a threaded `respond()` loop to prevent IRC message processing from blocking.
- Automatically fires "perform" scripts from `client.conf` upon connection.

### 2. PerformManager
- Handles mIRC-style `post_start` and `post_connect` scripts.
- Supports variable substitution (e.g., `$nick`, `$channels`).
- Loads agent-specific settings from `ops/agents/<nick>/client.conf`.

### 3. StandoffManager
- Prevents response bursts when multiple agents are active.
- Coalesces incoming messages during a random 2-5 second "standoff" window.
- Resets the timer on every new message, allowing the conversation to "settle" before the AI responds.

### 4. ContextManager
- Maintains per-channel circular backscroll buffers (default 20 lines).
- Detects "direct mentions" using configurable wakewords.
- Provides clean history text for AI model prompts.

### 5. Ignore and Focus Managers
- **IgnoreManager**: Temporarily silences the agent via `!ignore` commands.
- **FocusManager**: Tracks an "engagement window" (default 5 min). If the agent responds to a mention, it enters "focus mode" where it will continue to respond to subsequent messages in that channel until the window expires.

## Configuration (`client.conf`)

Each agent is configured via an INI file in `ops/agents/<nick>/client.conf`.

```ini
[identity]
nick     = codex
channels = #dev #general

[perform]
post_connect =
    OPER codex secret
    JOIN $channels

[ai]
wakewords      = @$nick $nick:
focus_window   = 300
standoff_min   = 2000
standoff_max   = 5000
```

## Creating a New Agent

1. Inherit from `AIClient`.
2. Implement the `respond(context: list[str])` method.
3. Call the appropriate LLM API (OpenAI, Anthropic, Google, etc.).
