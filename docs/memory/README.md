# Durable Memory

This directory is the durable, indexed context store for ongoing collaboration.
It is the shared memory layer for repo-launched CLI sessions such as Codex,
Claude, and Gemini when they are run against this checkout.

Use it like this:

1. Read `INDEX.md` to see what memory exists.
2. Read `STATUS.md` to see what is active, stashed, blocked, done, or just reference material.
3. Read `XREF.md` when a topic spans multiple entries.
4. Open only the specific entry files that match the current task.

Conventions:

- Each memory entry lives in a category directory such as `user/`, `workflow/`, `environment/`, or `tasks/`.
- `index.json` is the structured index. `INDEX.md` is the human summary of the same catalog.
- `xref.json` and `XREF.md` track cross-topic relationships.
- This shared store is additive. Existing per-agent `memory.db` files are left intact.
- This store is for cross-CLI collaboration memory, not for changing Anthropic/Google
  message APIs or the existing `ops/agents/*` execution setup.
- Task-like entries must use a status from: `active`, `stashed`, `blocked`, `done`, `reference`.
- Interrupted work should be marked `stashed` with enough summary and update notes to resume without rereading the whole session.
- Completed work should be marked `done` instead of deleted.

Maintenance:

- Prefer updating memory through `python bin/csc-memory.py ...` or `csc_data.memory_store.MemoryStore`.
- The helper rewrites `INDEX.md`, `STATUS.md`, and `XREF.md` automatically.
