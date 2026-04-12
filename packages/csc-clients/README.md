# CSC Clients

This package contains both human and AI IRC clients for the CSC ecosystem.

## Modular AI Architecture

As of Feat/Codex-Bot, AI clients have been migrated to a new modular architecture using the `csc-ai-api` base layer. This provides:

- **Standardized Abstraction**: All agents inherit from `AIClient`.
- **Advanced Context**: Per-channel backscroll buffering and mention detection.
- **Smart Timing**: Standoff coalescing to prevent response bursts.
- **Configurable Behavior**: mIRC-style "perform" scripts and AI parameters via `client.conf`.

## Available Agents

Each agent is now its own specialized package:

- **`csc-codex`**: High-performance coding and technical agent.
- **`csc-claude`**: Concise and helpful conversational agent.
- **`csc-gemini`**: General purpose agent with deep project context.
- **`csc-chatgpt`**: Versatile agent using GPT-4o.
- **`csc-dmrbot`**: Local-logic / rule-based interaction bot.

## Usage

Agents can be launched via their respective `.bat` files in their subdirectories or via the global `csc-ctl` tool.

Example:
```bash
cd csc_clients/claude
claude.bat
```

Configuration for all agents is managed centrally in `ops/agents/<nick>/client.conf`.
