# Task Execution Modes: Queue vs Direct API

## Overview

CSC now supports **two execution modes** for running workorders and tasks:

| Mode | Use Case | Speed | Cost | Persistence | Tools |
|------|----------|-------|------|-------------|-------|
| **Queue** | Normal tasks (P2, P3), cost-sensitive | Slower (persistent) | Cheaper | Full journaling | All tools |
| **Direct API** | Urgent tasks (P0, P1), blocking | Fast (immediate) | Premium | No journaling | All tools |

---

## Quick Start

### Run a Task via Queue (Persistent)

```bash
# Create workorder
cat > workorders/ready/opus-feature-x.md << 'EOF'
---
urgency: P2
description: Implement feature X
---

Add a new feature X that does Y...
EOF

# Queue-worker auto-picks it up and executes with journaling
```

### Run a Task Directly (Blocking)

```bash
# Create JSON config with urgency P0 or P1
cat > /tmp/urgent-task.json << 'EOF'
{
  "task_name": "emergency-hotfix",
  "agent": "opus",
  "urgency": "P0",
  "content": "Fix critical bug in auth.py...",
  "execution_mode": "direct"
}
EOF

# Execute immediately
python -m csc_service.infra.pm_executor /tmp/urgent-task.json
```

---

## Task Converter: orders.md ↔ JSON

Convert between markdown workorders and JSON configs to run either mode.

### Convert Workorder to JSON

```bash
# Single file
python bin/task_converter.py to-json workorders/ready/opus-feature.md

# Output: workorders/ready/opus-feature.json

# With custom output path
python bin/task_converter.py to-json workorders/ready/opus-feature.md /tmp/feature.json
```

### Convert JSON Back to Markdown

```bash
# Single file
python bin/task_converter.py to-md /tmp/feature.json workorders/ready/

# Batch convert directory
python bin/task_converter.py batch to-md /tmp/json_tasks/ workorders/ready/

# With custom template
python bin/task_converter.py to-md /tmp/task.json --template agents/templates/orders.md-template
```

### Batch Conversions

```bash
# Convert all .md in ready/ to JSON
python bin/task_converter.py batch to-json workorders/ready/ /tmp/json_batch/

# Convert all JSON back to .md
python bin/task_converter.py batch to-md /tmp/json_batch/ workorders/ready/
```

---

## Execution Mode Selection Logic

### PM Auto-Selection

The enhanced PM automatically chooses mode based on:

1. **Cost Sensitivity** (highest priority)
   - `cost_sensitive: true` → Always queue (cheapest)
   - Example: Large batch jobs use queue with haiku

2. **Urgency Level**
   - **P0** (Critical) → Direct API with Sonnet
   - **P1** (High) → Direct API with Opus
   - **P2** (Normal) → Queue with Sonnet
   - **P3** (Low) → Queue with Haiku

3. **Tool Availability**
   - If requires special tools → Select capable agent
   - All agents support: Read, Write, Edit, Bash, Glob, Grep

4. **Agent Capability**
   - **Haiku**: Fast, cheap, good for simple tasks
   - **Sonnet**: Balanced, good for most work, default for P2
   - **Opus**: Most capable, for complex reasoning (P1 only)

### Examples

```json
// P0: Critical hotfix
{
  "urgency": "P0",
  "execution_mode": "direct",
  "agent": "sonnet"  // Fast, high-capability
}

// P2: Feature with cost concern
{
  "urgency": "P2",
  "cost_sensitive": true,
  "execution_mode": "queue",
  "agent": "haiku"  // Cheapest option
}

// P3: Maintenance task
{
  "urgency": "P3",
  "execution_mode": "queue",
  "agent": "haiku"  // Low cost, async
}
```

---

## Auto-Start Services

The enhanced PM detects and auto-starts required services (unless disabled):

### Service Auto-Start Configuration

Edit `csc-service.json`:

```json
{
  "pm": {
    "auto_start_services": true,
    "auto_start_queue_worker": true,
    "auto_start_test_runner": true,
    "queue_worker_poll_interval": 10,
    "test_runner_poll_interval": 60
  }
}
```

### Check Service Status

```bash
# Check if queue-worker is running
csc-ctl status queue-worker

# Check if test-runner is running
csc-ctl status test-runner

# Or manually
ps aux | grep queue_worker
ps aux | grep test_runner
```

### Disable Auto-Start

If you want to manually manage services:

```json
{
  "pm": {
    "auto_start_services": false
  }
}
```

---

## Workorder Metadata (YAML Front Matter)

All workorders support metadata to control execution:

```markdown
---
urgency: P0
description: Fix critical auth bug
model: claude-opus-4-6
requires: bash,git
platform: linux,macos
execution_mode: direct
cost_sensitive: false
max_tokens: 16384
---

Your task description here...
```

### Supported Fields

| Field | Values | Default | Purpose |
|-------|--------|---------|---------|
| `urgency` | P0, P1, P2, P3 | P2 | Priority level, affects execution mode |
| `description` | string | "" | Task summary |
| `model` | haiku, sonnet, opus | auto | Preferred model |
| `requires` | comma-separated | "" | Required tools/capabilities |
| `platform` | linux, macos, windows, docker | "" | Required OS |
| `execution_mode` | auto, direct, queue | auto | Execution mode (PM overrides if needed) |
| `cost_sensitive` | true, false | false | Force queue mode for cost optimization |
| `max_tokens` | number | 32768 | Max output tokens |

---

## Cost Comparison

### Direct API (Blocking)

```
Task: implement-feature (10 min, 100K input tokens, 5K output tokens)

Cost:
- Input: 100K × $0.80/1M = $0.08
- Output: 5K × $4.00/1M = $0.02
- Premium: 2.0× (for immediate execution) = $0.20
- TOTAL: ~$0.20
```

### Queue (Persistent)

```
Task: implement-feature (50 min, 100K input tokens, 5K output tokens)

Cost:
- Input: 100K × $0.80/1M = $0.08
- Output: 5K × $4.00/1M = $0.02
- Prompt caching hit (50% average): 0.5×
- TOTAL: ~$0.05

Advantage: Cache hits, retry resilience, journaling
```

---

## Integration Examples

### Batch Processing with Converter

```bash
#!/bin/bash

# Convert all pending workorders to JSON
python bin/task_converter.py batch to-json workorders/ready/ /tmp/batch_jobs/

# Process as JSON (review, modify urgency, etc.)
for job in /tmp/batch_jobs/*.json; do
    # Could filter by urgency, cost, etc.
    jq '.urgency = "P2"' "$job" > "${job}.tmp"
    mv "${job}.tmp" "$job"
done

# Convert back to markdown for queue-worker
python bin/task_converter.py batch to-md /tmp/batch_jobs/ workorders/ready/

# Queue-worker will pick up and execute
```

### Escalation with Direct API

```bash
# Task fails in queue (P2)
# PM escalates to P1 and runs direct API with Opus

python -c "
import json
from pathlib import Path

task = json.loads(Path('task.json').read_text())
task['urgency'] = 'P1'  # Escalate
task['execution_mode'] = 'direct'
task['agent'] = 'opus'

Path('task.json').write_text(json.dumps(task, indent=2))
"

# Run directly
python bin/task_converter.py to-md task.json /tmp/
# Or use PM executor directly
```

---

## Monitoring

### Queue Status

```bash
# See what's in queue
workorders status

# List ready workorders
workorders list ready

# List work in progress
workorders list wip

# Tail queue-worker progress
agent tail 50
```

### Direct API Execution

```bash
# Check results of direct API executions
ls -la /tmp/direct_results/*.json

# View specific result
cat /tmp/direct_results/task-1772567000.json | jq .
```

---

## Best Practices

### ✅ Do

- Use **Direct API (P0/P1)** for urgent hotfixes, blockers
- Use **Queue (P2/P3)** for normal features, refactoring
- Mark **cost_sensitive: true** for large batch jobs
- Use **Haiku for P3** tasks to minimize costs
- Leverage **prompt caching** by keeping queue-worker running
- Convert to **JSON** for programmatic task management

### ❌ Don't

- Run every task as P0 (expensive, doesn't actually speed up work)
- Disable auto-start without manual monitoring
- Leave orphaned WIP files (PM auto-recovers after 2 minutes)
- Run multiple competing direct tasks (they block each other)
- Assume tool availability without declaring in metadata

---

## Troubleshooting

### Queue-Worker Not Running

```bash
# Check if service is running
csc-ctl status queue-worker

# Start manually
python -m csc_service.infra.queue_worker --daemon

# Or trigger auto-start
python -m csc_service.infra.pm --cycle
```

### Direct API Failures

```bash
# Direct API doesn't journal, so check result JSON:
cat /tmp/direct_results/task-*.json | jq '.error'

# Re-run in queue mode for persistence:
python bin/task_converter.py to-md task.json workorders/ready/
```

### Orphaned WIP Files

```bash
# PM auto-recovers after 2 minutes
# Manual recovery:
mv workorders/wip/stuck-task.md workorders/ready/stuck-task.md

# Check PM orphan timeout
grep ORPHAN_TIMEOUT_SECS packages/csc-service/csc_service/infra/pm_executor.py
```

---

## API Reference

### task_converter.py

```
Usage: python bin/task_converter.py [command] [args]

Commands:
  to-json FILE [OUTPUT]              Convert .md workorder to JSON
  to-md FILE [OUTPUT]                Convert JSON config to .md
  batch to-json INPUT_DIR [OUTPUT]   Batch convert directory .md→JSON
  batch to-md INPUT_DIR [OUTPUT]     Batch convert directory JSON→.md

Options:
  --template PATH                    Custom orders.md template (for to-md)
```

### pm_executor.py

```python
from csc_service.infra.pm_executor import PMExecutor

executor = PMExecutor(csc_root=Path("/opt/csc"))

# Check service health
is_running, pid = executor.check_service_health("queue-worker")

# Auto-start missing services
results = executor.ensure_services_running()

# Select execution mode for a task
mode, agent = executor.select_execution_mode(task_config)

# Execute task directly
result = executor.execute_task_direct_api(task_config, agent="opus")
```
