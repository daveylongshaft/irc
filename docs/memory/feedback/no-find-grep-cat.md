---
slug: no-find-grep-cat
name: Never use find/grep/cat via Bash
description: Always use dedicated tools (Glob/Grep/Read/Edit); never reach for find/grep/cat/head/tail/sed/awk in Bash.
type: feedback
status: reference
tags: [feedback, tooling, bash]
related: [es-for-search]
updated: 2026-04-12T00:00:00Z
---

Never use `find`, `grep`, `rg`, `cat`, `head`, `tail`, `sed`, or `awk` via the Bash tool. Always use the dedicated tools: Glob for file patterns, Grep for content search, Read for file contents, Edit for edits.

**Why:** (1) CLAUDE.md says so explicitly. (2) Davey flagged it after Bash `find` was used as a fallback when Glob timed out. (3) Dedicated tools give better visibility and are permission-aware.

**How to apply:** If Glob times out, fix is a tighter pattern or a direct Read on the likely path -- NOT a Bash find. If Grep output is too big, narrow with type/glob/path params. Bash is reserved for actual system commands: process control, package managers, git, service restarts, interpreter invocation.
