# AIDER.md

This file provides project context for aider when running inside the coding-agent Docker container.

---

## Project Overview

**CSC (Client-Server-Commander)** is an IRC-based multi-AI orchestration system consisting of:

- **Server**: Central IRC server implementing RFC 2812 protocol with persistent storage
- **Clients**: Multiple AI agents (Claude, Gemini, ChatGPT, Ollama) and human CLI client
- **Bridge**: Protocol bridge proxy for external IRC clients
- **Shared Library**: Core IRC protocol and utilities used by all components

**Type**: Python 3.8+ with pip-installable packages

---

## Quick Orientation

### Find files fast

```bash
# Code map — classes, methods, signatures per package
cat tools/INDEX.txt

# Detailed map for a specific package
cat tools/csc-server.txt

# Find files by name
grep <keyword> p-files.list

# Directory tree
cat tree.txt
```

**Always check the code maps before reading source files.** They show every class and method signature like C++ header files.

### Key file locations

| Location | Purpose |
|----------|---------|
| `packages/csc-shared/` | Shared IRC protocol library (imported by all) |
| `packages/csc-server/` | Main server; storage, message routing, IRC handler |
| `packages/csc-client/` | Human CLI client |
| `packages/csc-claude/` | Claude AI client via Anthropic API |
| `packages/csc-gemini/` | Gemini AI client via Google API |
| `packages/csc-chatgpt/` | ChatGPT AI client via OpenAI API |
| `packages/coding-agent/` | Docker-based coding agent (this container) |
| `packages/csc-bridge/` | Protocol bridge proxy for external IRC |
| `tests/` | Integration & unit tests |
| `tools/` | Generated code maps (one per package) |

---

## Rules

### DO NOT run tests

Cron handles all test execution. Your job:
1. Write the code
2. Write test files in `tests/test_<name>.py`
3. Delete the stale log: `rm tests/logs/test_<name>.log`
4. Commit and push
5. Cron runs the tests later

### Journal to WIP file

Before every action, log what you're doing and why:

```bash
echo "reading server.py to understand message routing" >> prompts/wip/TASK_NAME.md
echo "fixing handle_privmsg to check channel modes before broadcast" >> prompts/wip/TASK_NAME.md
```

### Refresh maps before commit

```bash
python bin/refresh-maps --quick
git add -A
git commit -m "description of changes"
git push
```

### No AI attribution in commits

Never add Co-Authored-By, Signed-off-by, or any AI credit in commit messages.

### End with STATUS: COMPLETE

When your task is fully done (code written, tests written, committed), append this as the last line of the WIP file:

```bash
echo "STATUS: COMPLETE" >> prompts/wip/TASK_NAME.md
```

---

## Architecture

### IRC Message Handling

All IRC commands flow through `server_message_handler.py`. Each command has a handler:

```python
def handle_privmsg(self, client_addr, nick, target, message_text):
    # target = "#channel" or "nick"
```

### Persistent Storage

Atomic JSON writes (temp file -> fsync -> rename). Files:
- `channels.json` — channel state, members, modes, bans
- `users.json` — user credentials, modes
- `opers.json` — operator passwords (read from disk every access)
- `bans.json` — ban masks
- `history.json` — disconnection history

Key invariant: every state change is written to disk before the handler returns.

### On-Demand Disk Reading

`server.oper_credentials`, `server.opers`, `server.client_registry` are `@property` methods that read from disk on every access. Edit the JSON files while server is running and changes take effect immediately.

### Platform Detection

`packages/csc_shared/platform.py` detects hardware, OS, Docker, AI agents. Persists to `platform.json`.

---

## Python Guidelines

- Python 3.8+ compatible
- Use `pathlib.Path` for all file paths (cross-platform)
- Use `encoding='utf-8'` for all file I/O
- Follow existing code style in the package you're modifying

---

## Common Patterns

### Adding a new IRC command handler

1. Read `tools/csc-server.txt` to find `ServerMessageHandler`
2. Add `handle_<command>` method
3. Register in the dispatch dict
4. Write test in `tests/test_server_irc.py`

### Modifying shared library

1. Read `tools/csc-shared.txt` for the API
2. Edit files in `packages/csc-shared/`
3. All packages import from here, so be careful with breaking changes

---

## References

- `tools/INDEX.txt` — master code map index
- `README.1st` — startup guide and crash recovery
- `docs/platform.md` — cross-platform support
- `PERMANENT_STORAGE_SYSTEM.md` — storage architecture
