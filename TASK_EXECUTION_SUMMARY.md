# Task Execution Infrastructure - Complete Implementation

## What We Built

A flexible dual-mode task execution system for CSC that enables:
1. **Queue-Worker Mode** (persistent, journaled, cost-efficient)
2. **Direct API Mode** (fast, blocking, urgent tasks)

---

## Components

### 1. Task Converter (`bin/task_converter.py`)

**Purpose**: Bidirectional conversion between orders.md workorders and JSON task configs.

**Features**:
- ✓ Convert single files or batch directories
- ✓ Preserve metadata (urgency, model, cost_sensitive, execution_mode, etc.)
- ✓ Support custom orders.md templates
- ✓ YAML front-matter extraction and generation

**Usage**:
```bash
# Single conversions
python bin/task_converter.py to-json workorders/ready/task.md
python bin/task_converter.py to-md task.json workorders/ready/

# Batch conversions
python bin/task_converter.py batch to-json workorders/ready/ /tmp/json/
python bin/task_converter.py batch to-md /tmp/json/ workorders/ready/
```

**Supported Metadata**:
- `urgency` (P0-P3) — Priority level, controls execution mode
- `description` — Task summary
- `model` — Preferred Claude model (haiku/sonnet/opus)
- `requires` — Required tools (bash, git, docker, etc.)
- `platform` — Required OS (linux, macos, windows, docker)
- `execution_mode` — auto/direct/queue (PM can override)
- `cost_sensitive` — Force queue mode for cost optimization
- `max_tokens` — Maximum output tokens

---

### 2. PM Executor (`packages/csc-service/csc_service/infra/pm_executor.py`)

**Purpose**: Smart execution mode selection and service lifecycle management.

**Features**:
- ✓ Service health checks (queue-worker, test-runner)
- ✓ Auto-start missing services (configurable)
- ✓ Intelligent execution mode selection based on:
  - Urgency level (P0 → Direct, P3 → Queue)
  - Cost sensitivity
  - Agent capability
  - Tool requirements
- ✓ Direct API execution with full tools (Read, Write, Edit, Bash, Glob, Grep)
- ✓ Orphaned task recovery

**Execution Mode Selection Logic**:

| Urgency | Cost-Sensitive | Mode | Agent | Reason |
|---------|---|------|-------|--------|
| P0 | any | Direct | Sonnet | Critical: immediate execution, high-capability |
| P1 | any | Direct | Opus | High priority: needs deep reasoning |
| P2 | false | Queue | Sonnet | Normal: good balance, persistent journaling |
| P2 | true | Queue | Haiku | Cost: cheap, queue caches help |
| P3 | any | Queue | Haiku | Low priority: cheapest option, async |

**Configuration** (`csc-service.json`):
```json
{
  "pm": {
    "auto_start_services": true,
    "auto_start_queue_worker": true,
    "auto_start_test_runner": true,
    "queue_worker_poll_interval": 10,
    "test_runner_poll_interval": 60
  },
  "execution": {
    "default_mode": "auto",
    "direct_api_capable": true
  }
}
```

**API**:
```python
from csc_service.infra.pm_executor import PMExecutor

executor = PMExecutor(csc_root=Path("/opt/csc"))

# Auto-start services
results = executor.ensure_services_running()

# Select execution mode
mode, agent = executor.select_execution_mode(task_config)

# Execute directly
result = executor.execute_task_direct_api(task_config, agent="opus")

# Check service health
is_running, pid = executor.check_service_health("queue-worker")
```

---

### 3. Documentation (`docs/TASK_EXECUTION_MODES.md`)

Comprehensive guide covering:
- Quick start examples
- Execution mode details and cost comparison
- Task metadata reference
- Best practices
- Troubleshooting
- API reference

---

## Execution Modes in Practice

### Scenario 1: Normal Feature (P2)

```markdown
---
urgency: P2
description: Implement feature X
cost_sensitive: false
---

Add feature X that does Y...
```

→ **Queue-Worker** with **Haiku** or **Sonnet**
- Runs persistently with journaling
- Can be paused/resumed
- Benefits from prompt caching
- Costs ~$0.05 (with cache hits)

### Scenario 2: Critical Hotfix (P0)

```json
{
  "task_name": "emergency-hotfix",
  "urgency": "P0",
  "execution_mode": "direct",
  "agent": "sonnet",
  "content": "Fix critical bug in auth.py..."
}
```

→ **Direct API** with **Sonnet**
- Immediate blocking execution
- Full tool support (Read, Write, Edit, Bash, Glob, Grep)
- No journaling (no recovery if interrupted)
- Costs ~$0.20 (premium for immediate execution)
- Result in `/tmp/direct_results/task-*.json`

### Scenario 3: Batch Job (Cost-Optimized)

```json
{
  "task_name": "refactor-all-modules",
  "urgency": "P3",
  "cost_sensitive": true,
  "execution_mode": "queue",
  "agent": "haiku"
}
```

→ **Queue-Worker** with **Haiku**
- Cheapest option: haiku + queue caching
- Large batch jobs perfect for this
- Can be paused if needed
- Full tool support with journaling
- Costs ~$0.02 (with cache hits)

---

## How They Work Together

```
[User] creates workorder
  ↓
[task_converter] ← → converts to/from JSON as needed
  ↓
[PM] receives workorder/task
  ├─ [pm_executor] analyzes urgency, cost, capability
  ├─ Selects execution mode (queue vs direct)
  ├─ Picks agent (haiku/sonnet/opus)
  └─ Routes task
       ├─ P0/P1 → [Direct API] → [Anthropic API] → Result JSON
       └─ P2/P3 → [queue-worker] → [run_agent.py] → Full tools → Journaling
```

---

## Integration Points

### With Existing Systems

✓ **Workorders**: Continue using orders.md (PM now converts as needed)
✓ **Queue-Worker**: Unchanged, picks up P2/P3 tasks from workorders/wip/
✓ **run_agent.py**: Unchanged, provides full tools for both modes
✓ **Test-Runner**: Auto-starts with queue-worker (configurable)

### With Benchmarking

✓ **Benchmarks**: Can convert benchmark JSON to workorders
✓ **Direct API**: Same infrastructure as benchmark runner
✓ **Prompt Caching**: Works in both queue and direct modes

---

## Cost Comparison

### 100K-token task execution cost

| Mode | Agent | Cost | Benefits |
|------|-------|------|----------|
| Queue | Haiku | $0.05 | Cached, persistent, resumable |
| Queue | Sonnet | $0.10 | Cached, persistent, better reasoning |
| Direct | Sonnet | $0.20 | Immediate, blocking, high-capability |
| Direct | Opus | $0.30 | Immediate, blocking, deepest reasoning |

**Savings with prompt caching**: ~90% on cache hits

---

## Migration Guide

### For Existing Workorders

No changes needed! Continue using orders.md:

```bash
# Same workflow as before
cat > workorders/ready/opus-feature.md << 'EOF'
---
urgency: P2
---
Add feature...
EOF

# PM will handle execution automatically
```

### For New Urgent Tasks

Use direct API:

```bash
# Create JSON config
cat > /tmp/urgent.json << 'EOF'
{
  "task_name": "hotfix",
  "urgency": "P0",
  "execution_mode": "direct",
  "content": "Fix bug..."
}
EOF

# Convert to workorder if needed
python bin/task_converter.py to-md /tmp/urgent.json workorders/ready/

# Or execute directly
python -m csc_service.infra.pm_executor /tmp/urgent.json
```

### For Batch Jobs

Use converter for cost optimization:

```bash
# Convert workorders to JSON
python bin/task_converter.py batch to-json workorders/ready/ /tmp/batch/

# Modify urgency/cost_sensitive in JSON
jq '.urgency = "P3" | .cost_sensitive = true' /tmp/batch/*.json

# Convert back and execute
python bin/task_converter.py batch to-md /tmp/batch/ workorders/ready/
```

---

## Testing

### Test Task Converter

```bash
# Create test workorder
cat > /tmp/test.md << 'EOF'
---
urgency: P1
description: Test task
---
Do something...
EOF

# Convert to JSON
python bin/task_converter.py to-json /tmp/test.md /tmp/test.json

# Convert back
python bin/task_converter.py to-md /tmp/test.json /tmp/test2.md

# Verify round-trip
diff /tmp/test.md /tmp/test2.md  # Should be identical
```

### Test PM Executor

```bash
# Create test task
cat > /tmp/test_config.json << 'EOF'
{
  "task_name": "test-task",
  "urgency": "P1",
  "agent": "opus",
  "content": "What is 2+2?"
}
EOF

# Check what mode PM would select
python -c "
from csc_service.infra.pm_executor import PMExecutor
import json
from pathlib import Path

executor = PMExecutor(Path('.'))
task = json.loads(Path('/tmp/test_config.json').read_text())
mode, agent = executor.select_execution_mode(task)
print(f'Mode: {mode}, Agent: {agent}')
"
```

---

## Next Steps (Optional Enhancements)

- [ ] Add streaming support for long-running direct API tasks
- [ ] Implement automatic escalation (P3 → P2 → P1 on repeated failure)
- [ ] Add cost estimation before execution
- [ ] Create web UI for task submission and monitoring
- [ ] Implement task grouping/dependencies
- [ ] Add metrics/analytics (success rate, avg cost, avg time per model)

---

## Files Changed/Created

**New Files**:
- `bin/task_converter.py` — Task converter script (423 lines)
- `packages/csc-service/csc_service/infra/pm_executor.py` — PM executor module (352 lines)
- `docs/TASK_EXECUTION_MODES.md` — Comprehensive documentation

**Modified Files**:
- None yet (PM integration pending)

**Ready for Integration**:
- pm_executor.py into main PM loop
- Auto-start logic in pm.py
- Execution mode selection in task assignment

---

## Usage Summary

```bash
# Convert workorder to JSON
python bin/task_converter.py to-json workorders/ready/task.md task.json

# Convert JSON to workorder
python bin/task_converter.py to-md task.json workorders/ready/

# Batch convert directory
python bin/task_converter.py batch to-json workorders/ready/ /tmp/json/

# Check execution mode selection
python -c "
from csc_service.infra.pm_executor import PMExecutor
import json
executor = PMExecutor(path)
mode, agent = executor.select_execution_mode(task_config)
print(f'{mode} via {agent}')
"
```

---

## Questions?

See `docs/TASK_EXECUTION_MODES.md` for:
- Detailed API reference
- Best practices
- Troubleshooting
- Examples and patterns
