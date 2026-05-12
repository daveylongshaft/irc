---
slug: code-maps
name: CSC Code Maps
description: /irc/docs/tools/ has auto-generated authoritative code maps for all CSC services and methods; use instead of reading source.
type: reference
status: reference
tags: [reference, csc, code-maps, documentation]
related: [pm-queue-worker, proactive-tool-usage]
updated: 2026-05-05T00:00:00Z
---

Location: /irc/docs/tools/ (relative to csc repo root)

Key files:
- csc-services.txt -- All services and methods (workorders, agent, builtin, backup, benchmark, botserv, catalog, curl, moltbook, nickserv, ntfy, patch, pki, platform, version, wakeword)
- csc-loop.txt -- PM, queue-worker, scheduler
- csc-platform.txt -- Platform class methods
- XREF.txt -- Cross-reference of all classes/methods
- analysis_report.json -- Undocumented items audit
- README.md -- How to regenerate maps with refresh-maps script

Format: `def method_name(args) -> return_type  # Docstring`

Always consult code maps first before reading source. They are auto-generated (authoritative), complete, and fast.
