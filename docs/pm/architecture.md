# CSC Service Architecture

## The Unified Service: `csc-service`

One process that runs all three subsystems: test-runner, queue-worker, PM.

### Modes

**Bare metal (local mode, default)**:
```bash
csc-service --daemon --local     # operate directly on csc/ directory
```

**Bare metal (with clone)**:
```bash
csc-service --daemon --dir /opt/csc-worker  # own git clone
```

**Docker** (optional):
```bash
docker run csc-service:latest    # containerized
```

### How It Works

```
csc-service
├── Subsystem: test-runner    (checks tests, generates fix prompts)
├── Subsystem: queue-worker   (spawns agents, tracks completion)
├── Subsystem: pm             (classifies work, assigns to agents)
└── Git sync layer            (pull/push for cross-machine coordination)
```

Each subsystem runs its cycle function sequentially:

```python
while True:
    git_pull()
    test_runner.run_cycle()      # run missing tests
    queue_worker.run_cycle()     # check agents, pick up work
    pm.run_cycle()               # classify and assign
    git_push_if_changed()
    sleep(poll_interval)
```

### Direct Communication (Same Machine)

When all three run in the same csc-service, they share state directly.
PM's assignments are picked up by queue-worker in the same cycle.

```
pm.run_cycle() → assigns workorder → creates queue/in/ file
    ↓ (same process, next cycle)
queue_worker.run_cycle() → picks up queue/in/ → spawns agent
```

### Cross-Machine (Git Sync)

When tasks need a different platform, the workorder stays in ready/.
Another machine's csc-service pulls and picks it up.

### Platform Awareness

Each csc-service instance knows its capabilities via `platform.json`.
Workorders with YAML front-matter requirements are checked before assignment:

```python
def can_run_locally(workorder):
    requirements = parse_frontmatter(workorder)
    if requirements.get("platform"):
        if platform.os not in requirements["platform"]:
            return False
    return True
```

## Agent Execution (run_agent.sh)

Each agent has its own launcher in `agents/<agent>/bin/run_agent.sh`.

**Claude agents** (haiku, sonnet, opus):
```bash
claude --dangerously-skip-permissions --model "$MODEL" -p - < "$WORKORDER"
```

**Gemini agents** (gemini-3-pro, gemini-2.5-flash, etc.):
```bash
npx @google/gemini-cli -y -m "$MODEL" -p " " < "$WORKORDER"
```

No external tools like cagent are used. The run_agent.sh scripts invoke
the AI CLIs directly.

## Template System

Each agent has an `orders.md-template` that gets combined with the workorder:

```
orders.md-template content (project context, journaling rules)
  + regex replace <wip_file_relative_pathspec> with actual WIP path
  + workorder content appended
  = agents/<agent>/queue/in/<filename>.md
```

This ensures every agent gets consistent project context and mandatory
WIP journaling instructions along with the specific workorder task.

## Configuration

`csc-service.json`:
```json
{
    "poll_interval": 60,
    "enable_test_runner": true,
    "enable_queue_worker": true,
    "enable_pm": true,
    "local_mode": true
}
```

Managed via `csc-ctl`:
```bash
csc-ctl status
csc-ctl enable queue-worker
csc-ctl set poll_interval 120
```
