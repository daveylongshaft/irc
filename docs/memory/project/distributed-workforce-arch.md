---
slug: distributed-workforce-arch
name: Distributed Workforce Architecture
description: Eggdrop bot + background services + shared ops/ filesystem; no root required, everything in user home dirs.
type: project
status: reference
tags: [csc, architecture, eggdrop, distributed]
related: [phase1-dispatcher, pm-queue-worker, haven-script-server]
updated: 2026-05-05T00:00:00Z
---

Two account model:
1. Eggdrop account (~/ + eggdrop binary + scripts/ + csc-packages/ + shared ops/)
2. Linger account (PM daemon + queue-worker daemon + PR reviewer + polling services + shared ops/)

Shared ops/ filesystem is the coordination point:
- wo/ -- workorder pool (ready/wip/done/archive/)
- agents/ -- agent configs + queues (in/work/out/)
- logs/ -- operation logs

Key constraints:
- No system-wide installation; everything in user home dirs.
- Each account has its own isolated venv.
- No root; agents and bots run as unprivileged users.
- High-range ports only (no root required).

Connection model: IRC users/DCC -> Eggdrop (Tcl) -> ops/ filesystem -> PM/queue-worker (Python) -> agent subprocesses in temp clones -> ops/ filesystem results back to Eggdrop -> IRC response.

CSC integration: csc-lin Tcl module handles linger account install/config (.lin install/status/start/stop/logs/update). set ::env(PYTHONPATH) in eggdrop.conf exposes csc/src to python.so.
