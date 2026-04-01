# PM Operating Procedures

## Overview

The PM is a Python module (`csc_service.infra.pm`) that runs as part of
csc-service. It classifies workorders by filename pattern and assigns them
to agents using the agent_service.assign() function.

The PM is NOT an AI agent - it's a rule-based decision engine.
It does NOT run in Docker with its own clone.

## How Assignment Works

The PM calls `agent_service.assign()` which does:

```
1. Find workorder in workorders/ready/
2. Check platform requirements (YAML front-matter vs platform.json)
3. Move workorder from ready/ → wip/
4. Read agent-specific orders.md-template from agents/<agent>/
5. Regex replace <wip_file_relative_pathspec> with actual WIP path
6. Combine template + workorder content
7. Write combined file to agents/<agent>/queue/in/<filename>.md
```

The queue-worker then picks up from queue/in/ and executes.

## Main Loop

The PM runs inside csc-service's main cycle:

```python
while True:
    git_pull()
    test_runner.run_cycle()      # run missing tests
    queue_worker.run_cycle()     # check agents, pick up work
    pm.run_cycle()               # classify and assign (ONE workorder max)
    git_push_if_changed()
    sleep(poll_interval)
```

## PM Cycle (`pm.run_cycle()`)

Each cycle does at most ONE assignment:

```python
def run_cycle():
    # 1. Recover orphaned WIP files (>10min with no queue entry)
    recover_orphaned_wip()

    # 2. Clean stale state entries (files that no longer exist)
    cleanup_stale_state()

    # 3. Check if queue-worker is busy → WAIT
    if is_queue_busy():
        return []  # Patient - one at a time

    # 4. Scan ready/ and sort by priority (P0 > P1 > P2 > P3)
    candidates = sorted(ready/*.md, key=priority)

    # 5. Pick ONE highest-priority workorder
    for candidate in candidates:
        # Skip human-review flagged items
        # Check agent prefix override
        # Pick agent (with escalation if previous failures)
        agent_svc.assign(candidate)
        return [(candidate, agent)]  # ONE only

    return []
```

## One-at-a-Time Constraint

**Critical**: PM assigns at most ONE workorder per cycle. It checks:
- `.pid` files in agents/*/queue/work/ (running agent)
- `.md` files in agents/*/queue/in/ (queued, waiting for queue-worker)
- `orders.md` in agents/*/queue/work/ (agent mid-execution)

If ANY of these exist, PM returns immediately and waits.

## Priority Tiers

| Priority | Pattern | Examples |
|----------|---------|----------|
| P0 | urgent, fix_test_, fix_, security | Blocks everything |
| P1 | queue_worker, test_runner, pm_, agent_service, csc_service | Force multipliers |
| P2 | Everything else | Features, refactors |
| P3 | docs_, docstring, document_ | Documentation |

## Failure Tracking & Escalation

Queue-worker calls `pm.mark_failed(filename)` when a workorder bounces
back to ready/ (no COMPLETE marker). PM tracks attempt counts:

```
Attempt 1-2: retry with same agent
Attempt 3+:  escalate:
    gemini-2.5-flash → gemini-3-pro
    gemini-3-pro     → opus
    haiku            → gemini-3-pro
    opus             → flag for human review (stops retrying)
```

## Agent Name Prefix Override

If a workorder filename starts with an agent name, that agent is used
regardless of classification:
- `haiku-audit-code.md` → haiku
- `opus_debug_crash.md` → opus
- `gemini-3-pro-feature.md` → gemini-3-pro

## Orphan Recovery

Every cycle, PM scans WIP for files older than 10 minutes that have
no matching queue entry (no agent running for them). These are moved
back to ready/ for re-assignment.

## Self-Healing

When PM encounters a problem it can't resolve, it creates a fix workorder:
- `pm_fix_<description>.md` in workorders/ready/
- Tagged with the problem description
- Another agent picks it up and fixes it

## State Tracking

PM maintains state in `pm_state.json`:

```json
{
    "assignments": {
        "PROMPT_fix_test_foo.md": {
            "agent": "gemini-2.5-flash",
            "category": "test-fix",
            "priority": "P0",
            "status": "assigned",
            "attempts": 1,
            "attempt_history": [{"agent": "gemini-2.5-flash", "ts": "...", "result": "incomplete"}],
            "timestamp": "2026-02-25T10:00:00"
        }
    }
}
```

Status values: assigned, completed, failed, error, retry, recovered,
escalated, human-review

## Workorder Classification

Pattern matching on filenames (no AI needed):

| Pattern | Category | Default Agent |
|---------|----------|---------------|
| `fix_test_*`, `run_test_*` | test-fix | gemini-2.5-flash |
| `docs_*`, `docstring*`, `document_*` | docs | gemini-2.5-flash |
| `audit*`, `review*`, `validate*` | audit | haiku |
| `debug*`, `investigate*` | debug | opus |
| `refactor*`, `rename*`, `migrate*` | refactor | gemini-3-pro |
| `fix_*` (non-test) | simple-fix | gemini-3-pro |
| Everything else | feature | gemini-3-pro |
