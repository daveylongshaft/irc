---
slug: proactive-tool-usage
name: Use memory, code maps, and agents proactively
description: Check memory at session start, use code maps as source of truth, save learnings immediately -- do not force Davey to repeat context.
type: feedback
status: reference
tags: [feedback, workflow, memory, tools]
related: [davey-collaboration-preferences]
updated: 2026-05-05T00:00:00Z
---

Davey gave tools (memory, code maps, specialized agents) -- use them proactively. Failing to do so forces him to repeat context.

**How to apply:**
- Check memory at session start. Do not re-ask questions or re-discover context.
- Use code maps (/irc/docs/tools/*.txt) as authoritative source before reading source code.
- Save learnings immediately when something important is discovered (architecture, workarounds, method signatures).
- Use Explore agent for open-ended codebase navigation ("find all X", "what files reference Y").
- Use Grep for specific known patterns; Read only for specific known files.

**The principle:** You do not have to tell me the same thing twice. If memory/maps/agents go unused, I am forcing you to repeat work.
