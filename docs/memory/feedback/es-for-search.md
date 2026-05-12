---
slug: es-for-search
name: Use es (Everything CLI) for file searches
description: Prefer the es command for locating files by name; install CLI tools to ~/.local/bin/ exactly as directed.
type: feedback
status: reference
tags: [feedback, tooling, search, windows]
related: [no-find-grep-cat]
updated: 2026-04-14T00:00:00Z
---

Use `es` (Everything CLI, installed via `winget install -e --id voidtools.Everything.Cli`) for file and folder location searches. It is instant (indexed). Glob/Grep/find are slow by comparison for system-wide searches.

**When to use es:** Looking for files by name pattern across the system -- `es "*.py"`, `es -regex "pattern"`, `es -i "text"`.
**When NOT to use es:** Searching file contents (use Grep), or when Glob/Grep are already integrated in the workflow.

**Installation rule:** When installing command-line binaries, always put them in `~/.local/bin/`. Follow Davey's specified method exactly (e.g., the winget command above installs es.exe, not the GUI Everything.exe). Verify the correct binary is at the correct path before considering the task done.

**Why:** Davey was frustrated when es.exe (CLI) was confused with Everything.exe (GUI) and when binaries were placed in the wrong location. Precision and organization matter.
