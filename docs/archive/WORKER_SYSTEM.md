# Worker System - Background Prompt Processing

The worker system is a background job orchestrator that processes prompts from a queue in persistent daemon processes.

## Architecture

```
workorders/wip/ (incoming queue)
    ↓
worker-daemon (background process)
    ├→ Reads prompt + metadata
    ├→ Runs inference (local-ai)
    ├→ Journals output to logs/
    └→ On completion:
        - Moves to workorders/done/
        - Updates maps (refresh-maps)
        - Commits to git
        - Pushes to remote
    ↓
workorders/done/ (completed queue)
```

Multiple workers can run in parallel, each pulling from the same queue.

## Quick Start

### 1. Run Preflight Check

Verify everything is ready before launching:

```bash
python bin/worker-manage preflight
```

Checks:
- Git synced with remote
- Maps current (within 5 mins of last commit)
- Directories exist
- No orphaned processes

**Output:**
```
[OK] Git status: clean and synced
[OK] Maps current: 0.1 mins behind commit 245a66c
[OK] Directories ready
[OK] No existing worker processes

Results: 4/4 checks passed

[OK] ALL CHECKS PASSED - Ready to launch workers
```

### 2. Start Workers

Launch N background daemons:

```bash
# Launch 3 workers with default model (qwen:7b)
python bin/worker-manage start 3

# Launch 2 workers with specific model
python bin/worker-manage start 2 --model deepseek-coder:6.7b

# Start single worker
python bin/worker-manage start 1 --model qwen:7b
```

Each worker runs independently and pulls prompts from the queue.

### 3. Monitor Status

```bash
# Show running workers and queue status
python bin/worker-manage status

# Tail logs in real-time
python bin/worker-manage logs --follow

# Show specific worker logs
python bin/worker-manage tail 1
```

### 4. Stop Workers

```bash
# Graceful shutdown of all workers
python bin/worker-manage stop
```

## Prompt Format

Prompts go in `workorders/wip/*.md` with optional YAML front-matter:

```markdown
---
model: qwen:7b
timeout: 10
stall_timeout: 120
---
# My Prompt

This is the prompt content that will be sent to the model.
```

**Front-matter options:**
- `model`: Override default model (e.g., `deepseek-coder:6.7b`, `codellama:7b`)
- `timeout`: Hard timeout in minutes (default: 10). Process killed if total time exceeds this.
- `stall_timeout`: Stall detection in seconds (default: 120). Process killed if no output for this many seconds.

**Stall Detection Strategy:**

- **No Hard Timeout**: Workers let processes run as long as they're producing output
- **Stall Detection**: Kill if no output appears for `stall_timeout` seconds
- **Output Monitoring**: Every byte of output resets the stall timer
- **Auto-Restart**: On stall detection, worker moves prompt back to `wip/` for retry with next available worker
- **Verbose Logging**: All model output streamed to logs so you can see the model's thinking

Example: Model thinking for 2 minutes but producing tokens = **NOT KILLED**. Model stuck for 2 minutes with no output = **KILLED AT 120s STALL**.

## Workflow

1. **Preflight Check**
   ```bash
   python bin/worker-manage preflight
   ```

2. **Add Prompt to Queue**
   - Create file: `workorders/wip/my-task.md`
   - Worker automatically detects it

3. **Workers Process Queue**
   - Each worker polls `workorders/wip/` for new files
   - Runs inference, journals output
   - Moves completed to `workorders/done/`
   - Updates maps, commits, pushes

4. **Monitor Progress**
   ```bash
   python bin/worker-manage status        # Quick status
   python bin/worker-manage logs --follow # Watch in real-time
   ```

5. **Stop When Done**
   ```bash
   python bin/worker-manage stop
   ```

## Verbose Output & Progress Monitoring

### Real-Time Streaming

Worker daemons stream all model output in real-time to logs. This lets you see:
- Model's intermediate reasoning
- Code generation as it happens
- Progress through long tasks
- Stuck detection and restarts

**Example log output with streaming:**
```
[2026-02-21T19:45:40.234567] [INFO] Starting: benchmark-hello-world.md
[2026-02-21T19:45:42.345678] [INFO]   [MODEL] Here is hello world in C++:
[2026-02-21T19:45:44.456789] [INFO]   [MODEL]
[2026-02-21T19:45:46.567890] [INFO]   [MODEL] ```cpp
[2026-02-21T19:45:48.678901] [INFO]   [MODEL] #include <iostream>
[2026-02-21T19:45:50.789012] [INFO]   [MODEL] int main() {
[2026-02-21T19:45:52.890123] [INFO]   [MODEL]     std::cout << "Hello, World!" << std::endl;
[2026-02-21T19:45:54.901234] [INFO]   [MODEL]     return 0;
[2026-02-21T19:45:56.012345] [INFO]   [MODEL] }
[2026-02-21T19:45:58.123456] [INFO]   [MODEL] ```
[2026-02-21T19:46:10.234567] [OK] Completed: benchmark-hello-world.md in 30.1s
```

### Stall Detection

If a process produces no output for `stall_timeout` seconds, it's killed:

```
[2026-02-21T19:46:20.123456] [INFO] Starting: complex-task.md (stall timeout: 120s)
[2026-02-21T19:46:22.234567] [INFO]   [MODEL] Analyzing input...
[2026-02-21T19:47:22.345678] [WARN] Process stalled (61s > 120s), killing and restarting
[2026-02-21T19:47:22.456789] [INFO] Job moved back to wip/ for retry
```

The prompt is moved back to `wip/` for the next available worker to retry.

## Logging & Journaling

### Log Files

`logs/worker-1.log` - Human-readable log for each worker (including all model output):
```
[2026-02-21T19:45:30.123456] [INFO] Worker 1 started (model: qwen:7b, poll: 10s)
[2026-02-21T19:45:40.234567] [INFO] Starting: benchmark-hello-world.md
[2026-02-21T19:46:10.345678] [OK] Completed: benchmark-hello-world.md in 30.1s
[2026-02-21T19:46:15.456789] [INFO] Updating maps...
```

### Journal Files

`logs/worker-1.journal` - Structured JSON events for programmatic access:
```json
{"timestamp": "2026-02-21T19:45:30.123456", "worker_id": 1, "event": "daemon_start", "data": {"model": "qwen:7b"}}
{"timestamp": "2026-02-21T19:45:40.234567", "worker_id": 1, "event": "job_start", "data": {"file": "benchmark-hello-world.md"}}
{"timestamp": "2026-02-21T19:46:10.345678", "worker_id": 1, "event": "job_complete", "data": {"file": "benchmark-hello-world.md", "elapsed": 30.1}}
```

### Viewing Logs

```bash
# Show recent logs (last 50 lines from top 3 workers)
python bin/worker-manage logs

# Watch logs in real-time
python bin/worker-manage logs --follow

# Tail specific worker
python bin/worker-manage tail 1

# Manual log inspection
cat logs/worker-1.log
cat logs/worker-1.journal | jq '.'  # Pretty-print JSON
```

## Manifest Check System

### What `worker-preflight` Verifies

1. **Git Status** ✓
   - No significant uncommitted changes (ignores transient `.log`, `.aider` files)
   - Synced with remote (not ahead/behind)

2. **Maps Currency** ✓
   - `tools/.lastrun` timestamp exists
   - Within 5 minutes of last commit
   - Accounts for legitimate resolution time between commit and run

3. **Directories** ✓
   - `workorders/wip/` exists and writable
   - `workorders/done/` exists and writable
   - `logs/` exists and writable

4. **Processes** ✓
   - No orphaned worker processes running

### Map Timestamp System

- **Created by**: `refresh-maps` at completion
- **File**: `tools/.lastrun` (contains Unix timestamp)
- **Tolerance**: 5 minutes (300 seconds)
- **Logic**:
  - Get last commit time: `git log -1 --format=%ct`
  - Get maps time: Read `tools/.lastrun`
  - If `|commit_time - maps_time| <= 300`: OK
  - Else: WARN (maps may be stale)

**Rationale**: Accounts for legitimate scenarios where conflict resolution or other work between commit and map refresh should not block workers.

## Configuration

Default settings are built-in. Override via command-line:

```bash
# Start with different model
python bin/worker-manage start 3 --model deepseek-coder:6.7b

# Individual worker with longer timeout
python bin/worker-daemon.py --id 1 --model codellama:7b --poll-interval 5
```

## Troubleshooting

### Workers Not Starting
```bash
python bin/worker-manage preflight --verbose
```
Verify all 4 checks pass before starting.

### Prompts Stuck in wip/
```bash
tail -f logs/worker-*.log
```
Check worker logs for errors. Prompts stay in `wip/` on failure (no auto-retry yet).

### Git Operations Failing
```bash
cd /opt/csc && git status
git pull
```
Workers require git access. Resolve conflicts manually if needed.

### Timeouts on Complex Tasks
Override timeout in prompt front-matter:
```markdown
---
model: qwen:7b
timeout: 600
---
```

## Examples

### Example 1: Simple Benchmark

**File**: `workorders/wip/test-hello-world.md`
```markdown
---
model: qwen:7b
timeout: 120
---
# Benchmark: Hello World

Generate working "Hello World" in 5 languages: Python, JavaScript, Bash, C++, Java
```

**Launch**:
```bash
python bin/worker-manage preflight && python bin/worker-manage start 1
python bin/worker-manage logs --follow  # Watch progress
```

### Example 2: Parallel Processing

**Queue setup**:
```
workorders/wip/
  ├─ task-1.md (FFT analysis)
  ├─ task-2.md (Code review)
  ├─ task-3.md (Documentation)
  └─ task-4.md (Refactoring)
```

**Launch**:
```bash
python bin/worker-manage preflight
python bin/worker-manage start 2  # 2 workers process in parallel
```

Result: Tasks 1-2 processed simultaneously, then 3-4.

### Example 3: Model Comparison

**Create prompts**:
```bash
# Same prompt, different models
cp workorders/wip/task.md workorders/wip/task-qwen.md
cp workorders/wip/task.md workorders/wip/task-deepseek.md
```

**Add model directive**:
```markdown
---
model: qwen:7b
---
# Task
```

**Launch all workers**:
```bash
python bin/worker-manage start 4 --model qwen:7b
# Reassign some to deepseek manually or via prompt directive
```

## Architecture Notes

### Atomic Operations

- **File move**: `wip/ → done/` with content appended
- **Git workflow**: `add → commit → push` as atomic sequence
- **Journal**: Append-only, no corruption risk

### Signal Handling

- `SIGINT` (Ctrl+C): Graceful shutdown
- `SIGTERM` (kill): Graceful shutdown
- Current job finishes before daemon exits

### Concurrency

- Multiple workers share queue via filesystem
- First-come-first-served (filesystem ordering)
- No explicit locking (not needed for this pattern)

### Polling Strategy

- Default: 10 second poll interval
- Configurable per worker
- Trade-off: Lower = more responsive, higher = less CPU

## See Also

- `bin/worker-preflight` - Pre-flight checks
- `bin/worker-daemon.py` - Main worker process
- `bin/worker-manage` - Management CLI
- `CLAUDE.md` - Project architecture
- `tools/benchmarks/` - Benchmark results
