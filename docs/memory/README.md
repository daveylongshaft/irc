# Shared Agent Memory

Durable, indexed memory for all agents working against this tree (Claude, Codex, Gemini, etc.).

## How to use

1. Read INDEX.md -- one line per entry, enough to decide what to open.
2. Read STATUS.md -- see what is active, stashed, blocked, or done.
3. Read XREF.md -- when a topic spans multiple entries.
4. Open only the specific files you need.

## File format

Each memory file has YAML frontmatter:

```
---
slug:        unique identifier, matches index.json key
name:        human title
description: one line -- this is what INDEX.md shows
type:        user | feedback | environment | workflow | task | topic | reference
status:      reference | active | stashed | blocked | done
tags:        [...]
related:     [other slugs]
updated:     ISO 8601 timestamp
---
```

Body is plain prose. No markdown list metadata blocks.

## Updating

- Edit files directly; keep frontmatter in sync with index.json and INDEX.md.
- Or use `python bin/csc-memory.py` if available (reads frontmatter, rewrites index files).
- When adding an entry: create the file, add it to index.json and INDEX.md, update XREF.md if it has relations, update STATUS.md.

## Scope

This store is for everything an agent needs to serve Davey well: user preferences, feedback rules, environment facts, workflow conventions, stashed tasks, and tracked world topics. It is not limited to CSC project internals.
