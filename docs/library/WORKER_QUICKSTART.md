# Worker System Quick Start

## System Overview

**Worker Daemons** process prompts from a background queue with real-time progress monitoring:

1. **No hard timeouts** - Workers let processes run indefinitely if they're producing output
2. **Stall detection** - Kill if no output for N seconds (default: 120s), auto-retry
3. **Real-time streaming** - See model's thinking as it happens
4. **Automatic workflow** - On completion: maps update → commit → push

## 5-Minute Setup

### 1. Verify System Ready
```bash
python bin/worker-manage preflight
```

Output should show: `[OK] ALL CHECKS PASSED`

### 2. Start Workers
```bash
# Launch 3 background workers
python bin/worker-manage start 3

# Or with specific model
python bin/worker-manage start 2 --model deepseek-coder:6.7b
```

### 3. Add Prompt to Queue
```bash
cat > workorders/wip/my-task.md << 'EOF'
---
model: qwen:7b
timeout: 10
stall_timeout: 120
---
# Generate Hello World

Write hello world in Python with comments.
EOF
```

### 4. Watch Progress
```bash
# See running workers and queue
python bin/worker-manage status

# Watch logs in real-time
python bin/worker-manage logs --follow

# Or tail specific worker
python bin/worker-manage tail 1
```

### 5. Stop When Done
```bash
python bin/worker-manage stop
```

## Real-Time Output Example

Watch the model thinking as it generates code:

```bash
$ python bin/worker-manage logs --follow

[2026-02-21T19:45:40] [INFO] Starting: my-task.md
[2026-02-21T19:45:42] [INFO]   [MODEL] Here's a Python hello world:
[2026-02-21T19:45:44] [INFO]   [MODEL]
[2026-02-21T19:45:46] [INFO]   [MODEL] ```python
[2026-02-21T19:45:48] [INFO]   [MODEL] # Generated: 2026-02-21T19:45:48Z
[2026-02-21T19:45:50] [INFO]   [MODEL] print("Hello, World!")
[2026-02-21T19:45:52] [INFO]   [MODEL] ```
[2026-02-21T19:46:10] [OK] Completed: my-task.md in 30.1s
[2026-02-21T19:46:15] [INFO] Updating maps...
[2026-02-21T19:46:20] [INFO] Committed to git
[2026-02-21T19:46:25] [INFO] Pushed to remote
```

## Stall Detection Example

If a model gets stuck:

```bash
[2026-02-21T19:50:00] [INFO] Starting: complex-task.md (stall timeout: 120s)
[2026-02-21T19:50:05] [INFO]   [MODEL] Analyzing the codebase...
[2026-02-21T19:51:05] [WARN] Process stalled (61s no output), killing and restarting
[2026-02-21T19:51:05] [INFO] Prompt returned to wip/ for retry
```

The prompt stays in `wip/` and the next available worker picks it up.

## Prompt Configuration

### Minimal Prompt
```markdown
# Generate Code

Write a Python function that adds two numbers.
```

### With Overrides
```markdown
---
model: deepseek-coder:6.7b
timeout: 15
stall_timeout: 60
---
# Complex Task

Analyze this codebase and suggest optimizations.
```

**Options:**
- `model`: Which model to use (qwen:7b, deepseek-coder:6.7b, codellama:7b)
- `timeout`: Max time in minutes (default: 10). Process killed if exceeded.
- `stall_timeout`: Kill if no output for N seconds (default: 120)

## Commands Reference

### Management
```bash
# Pre-flight check (must pass before starting)
python bin/worker-manage preflight

# Start N workers
python bin/worker-manage start 3
python bin/worker-manage start 2 --model deepseek-coder:6.7b

# Stop all workers gracefully
python bin/worker-manage stop

# Check status (workers, queue, recent activity)
python bin/worker-manage status
```

### Monitoring
```bash
# Show recent logs (all workers)
python bin/worker-manage logs

# Watch logs live
python bin/worker-manage logs --follow

# Watch specific worker
python bin/worker-manage tail 1
python bin/worker-manage tail 2

# Manual inspection
cat logs/worker-1.log
cat logs/worker-1.journal | jq '.'  # JSON events
```

## Architecture

```
┌─ User adds prompt to workorders/wip/
│
├─ Worker daemon polls wip/
│
├─ local-ai streams output to worker logs
│   └─ Model thinking visible in real-time
│
├─ Stall detection monitors for output
│   ├─ Output received? → Reset stall timer
│   └─ No output 120s? → Kill & retry
│
└─ On completion:
    ├─ Move to done/
    ├─ Append results
    ├─ refresh-maps
    ├─ git commit
    └─ git push

    Then poll wip/ for next prompt
```

## Troubleshooting

### Workers Won't Start
```bash
python bin/worker-manage preflight --verbose
```
Fix any failing checks (git sync, maps, directories, processes).

### Process Killed Immediately
Check logs:
```bash
tail logs/worker-1.log
```

Likely causes:
- Model not available (check `local-ai --models`)
- Ollama not running (check `local-ai --check`)
- Prompt syntax error

### No Output Appearing
```bash
# Check if model is loaded
python bin/local-ai --check

# Test direct inference
echo "Say hello" | python bin/local-ai
```

### Prompts Stuck in wip/
Check logs for why they're failing. Move to `workorders/wip/` and restart workers.

## Performance Tips

### Model Selection
- **qwen:7b** - Balanced, good code generation (4.5GB)
- **deepseek-coder:6.7b** - Specialized for code (3.8GB)
- **codellama:7b** - Classic coder model (3.8GB)

### Worker Count
- **1 worker** - Single task at a time, minimal resource use
- **2-3 workers** - Parallel processing, good throughput
- **4+ workers** - For many small tasks, may stress resources

### Stall Timeout
- **60s** - Fast model, simple tasks
- **120s** - Balanced (default)
- **300s** - Complex code generation, debugging

## Examples

### Benchmark Run
```bash
# Create benchmark prompt
cat > workorders/wip/benchmark.md << 'EOF'
---
model: qwen:7b
timeout: 5
---
# Benchmark: Hello World

Generate hello world in: Python, JavaScript, Bash, C++
EOF

# Start worker and watch
python bin/worker-manage start 1
python bin/worker-manage logs --follow

# Results appear in workorders/done/benchmark.md
cat workorders/done/benchmark.md
```

### Parallel Processing
```bash
# Add multiple tasks
for i in {1..5}; do
  cat > workorders/wip/task-$i.md << EOF
# Task $i

Generate code example #$i
EOF
done

# Process in parallel
python bin/worker-manage start 3
python bin/worker-manage status

# Watch progress
python bin/worker-manage logs --follow
```

## See Also

- `docs/WORKER_SYSTEM.md` - Complete reference
- `bin/worker-daemon.py` - Implementation details
- `bin/local-ai` - Model interface
- `bin/worker-manage` - Full CLI reference
