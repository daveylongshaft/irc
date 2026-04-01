# System Architecture Reference

How all the moving parts fit together.

## Directory Layout

```
csc/
├── workorders/              # Task queue
│   ├── ready/               # Queued - waiting for assignment
│   ├── wip/                 # In progress
│   ├── done/                # Completed
│   ├── hold/                # Parked - do NOT work on
│   └── archive/             # Dead-ended or obsolete
├── agents/                  # Agent configurations
│   ├── haiku/               # Each agent has:
│   │   ├── bin/             #   Agent launcher scripts
│   │   │   └── run_agent.sh #     Starts the AI CLI
│   │   ├── orders.md-template  # Template with <wip_file_relative_pathspec>
│   │   ├── context/         #   Context files (optional)
│   │   └── queue/           #   Per-agent task queue
│   │       ├── in/          #     Pending (PM puts combined .md files here)
│   │       ├── work/        #     Running (queue-worker moves here + .pid file)
│   │       └── out/         #     Finished (queue-worker moves here after)
│   ├── gemini-3-pro/
│   ├── gemini-2.5-flash/
│   ├── opus/
│   └── templates/           # Default template for new agents
├── tests/
│   ├── test_*.py            # Test files
│   ├── logs/                # Test output logs (log = lock)
│   └── platform_gate.py     # Cross-platform test gating
├── bin/
│   └── refresh-maps         # Regenerate code maps
├── tools/
│   ├── pm/                  # THIS DIRECTORY - PM knowledge base
│   ├── INDEX.txt            # Code map index
│   └── *.txt                # Per-package code maps
├── packages/
│   └── csc-service/         # Unified package
│       └── csc_service/
│           ├── infra/
│           │   └── pm.py    # PM classification and assignment
│           └── shared/
│               └── services/
│                   ├── agent_service.py     # assign() workflow
│                   └── queue_worker_service.py  # Execution lifecycle
├── agent_data.json          # Current running agent state
├── platform.json            # Platform detection results
├── .env                     # API keys
└── logs/                    # Runtime logs
```

## Data Flow: Complete Workorder Lifecycle

```
1. Workorder created in workorders/ready/
        ↓
2. PM classifies by filename → picks agent
        ↓
3. PM calls agent_service.assign():
   a. Move workorders/ready/X.md → workorders/wip/X.md
   b. Read agents/<agent>/orders.md-template
   c. Replace <wip_file_relative_pathspec> with "workorders/wip/X.md"
   d. Combine: template + workorder content
   e. Write to agents/<agent>/queue/in/X.md
        ↓
4. Queue-worker process_queue_in():
   a. Find .md files in agents/*/queue/in/
   b. Move queue/in/X.md → queue/work/X.md
   c. Start agent via agents/<agent>/bin/run_agent.sh
   d. Save PID in queue/work/X.md.pid
        ↓
5. Agent runs:
   - Reads queue/work/X.md as instructions (template + workorder)
   - Does the work (edits files, runs commands)
   - Journals progress to workorders/wip/X.md
   - Writes "COMPLETE" as last line when done
        ↓
6. Queue-worker process_queue_work():
   a. Check if PID is still alive → skip if yes
   b. PID dead → check workorders/wip/X.md for COMPLETE
   c. Move queue/work/X.md → queue/out/X.md
   d. Clean up .pid file
   e. If COMPLETE: move wip/X.md → done/X.md
      If INCOMPLETE: move wip/X.md → ready/X.md (retry)
   f. Run refresh-maps
   g. Git commit + push
```

## Subsystem: Queue Worker

The engine that executes agents. Part of csc-service.

### Key Methods

- `run_cycle()` - One complete cycle: git pull → process_queue_in → process_queue_work
- `process_queue_in()` - Scan queue/in/, move to queue/work/, start agents
- `process_queue_work()` - Check PIDs, handle completion/failure
- `spawn_agent()` - Find and run agents/<agent>/bin/run_agent.sh
- `check_wip_complete()` - Check if last non-empty line is "COMPLETE"

### Agent Execution

Queue-worker finds `agents/<agent>/bin/run_agent.sh` (or `.bat` on Windows).

**Claude agents** use:
```bash
claude --dangerously-skip-permissions --model <model> -p - < queue/work/orders.md
```

**Gemini agents** use:
```bash
npx @google/gemini-cli -y -m <model> -p " " < queue/work/orders.md
```

### Completion Detection

When an agent's PID dies, queue-worker reads `workorders/wip/<filename>`:
- Last non-empty line == "COMPLETE" → success → move to done/
- Anything else → incomplete → move back to ready/ for retry

### Post-Completion

After any completion (success or failure):
1. Run `refresh-maps --quick` to update code maps
2. `git add -A && git commit && git push`

## Subsystem: PM (`csc_service.infra.pm`)

Classifies and assigns workorders. No execution responsibility.

### Agent Selection Policy

| Category | Agent |
|----------|-------|
| docs, test-fix, validation | gemini-2.5-flash |
| feature, refactor, simple-fix, complex-fix | gemini-3-pro |
| audit | haiku |
| debug | opus |

No local agents used.

## Subsystem: Agent Service

Handles the assign() workflow called by PM or human via CLI.

### assign() Steps
1. Find prompt file in ready/ (by number or filename)
2. Check platform requirements vs platform.json
3. Move ready/ → wip/
4. Read agent's orders.md-template
5. Regex replace `<wip_file_relative_pathspec>` with WIP path
6. Combine template + workorder
7. Write to agents/<agent>/queue/in/

## agent_data.json

```json
{
    "selected_agent": "gemini-3-pro",
    "current_pid": null,
    "current_prompt": null,
    "current_log": null,
    "started_at": null
}
```
