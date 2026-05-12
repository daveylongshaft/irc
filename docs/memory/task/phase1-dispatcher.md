---
slug: phase1-dispatcher
name: Phase 1 - CSC Dispatcher
description: Eggdrop dispatcher with dual access (DCC + IRC channel), event-driven workorder monitoring, mircryption. COMPLETE 2026-05-05.
type: task
status: done
tags: [csc, eggdrop, dispatcher, phase1]
related: [csc-bot-package, distributed-workforce-arch]
updated: 2026-05-05T00:00:00Z
---

Status: COMPLETE 2026-05-05.
Branch: feat/phase-1-dispatcher (4 commits, 1230 lines).
Location: /c/csc/tmp/clones/csc/irc/packages/csc-eggdrop/

What is built:
- csc_dispatcher.tcl (656 lines) -- command routing, workorder creation, event-driven monitoring
- csc_auth.tcl (321 lines) -- RSA cert + password, +s flag enforcement
- csc_lin.tcl -- linger account manager (.lin install/status/start/stop/logs/update)
- COMMANDS.md (166 lines) -- authoritative syntax from code maps
- Package structure: pyproject.toml, __init__.py, README.md

Dual access:
- DCC: requires auth (RSA/password) + +s flag, direct putdcc responses
- IRC #csc: requires +v flag, encrypted with mircryption Blowfish, broadcast results

Event-driven architecture:
- Commands create workorder in ops/wo/ready/
- Monitor spawns immediately (100ms delay, non-blocking)
- Monitors watch ready/ -> wip/ -> done/
- Fallback polling (10s) catches orphaned messages

Next phase: integration testing with actual PM + agents.
