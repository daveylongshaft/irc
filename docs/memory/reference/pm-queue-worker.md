---
slug: pm-queue-worker
name: PM and Queue-Worker methods
description: Orchestration layer: PM.classify/pick_agent/run_cycle and queue_worker.process_inbox/monitor_active_tasks.
type: reference
status: reference
tags: [reference, csc, orchestration, pm, queue-worker]
related: [code-maps, distributed-workforce-arch]
updated: 2026-05-05T00:00:00Z
---

From /irc/docs/tools/csc-loop.txt.

PM (csc_loop/infra/pm.py):
- classify(filename) -- classify workorder by role (front-matter > filename pattern)
- prioritize(filename) -- assign priority tier P0-P3
- pick_agent(category, filename, state) -- select agent (front-matter override > escalation path: gemini-2.5-flash -> gemini-2.5-pro -> chatgpt -> ...)
- is_queue_busy() -- check if any agent has work in progress
- run_cycle() -- one cycle: scan ready/, classify, pick agent, assign (max one per cycle)

Queue-Worker (csc_loop/infra/queue_worker.py):
- process_inbox() -- scan all agents' queue/in/ directories
- monitor_active_tasks() -- poll active PIDs every N seconds
- process_finished_work(task) -- handle completed/failed workorders
- run_cycle() -- one cycle: process inbox, monitor active, handle finished
- create_agent_temp_repo() -- clone shallow temp repo for agent execution
- is_complete_marker(content) -- check for COMPLETE marker in WIP file

Constants: STALE_THRESHOLD=10s, AGENT_MAX_TOTAL_RUNTIME_SECONDS=3600.

Flow: Dispatcher creates workorder in ops/wo/ready/ -> PM.run_cycle() classifies + assigns -> queue entry in ops/agents/<agent>/queue/in/ -> queue-worker spawns subprocess in temp clone -> monitors PID -> on completion moves to done/ + git commit/push.
