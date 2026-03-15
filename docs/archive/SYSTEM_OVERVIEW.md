# CSC Complete System Overview

## Three-Layer Architecture

The CSC system now has three integrated layers for running AI models:

```
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 1: MULTI-AGENT MICROSERVICES                             │
│ (Persistent background agents with isolated queues)            │
│                                                                 │
│  agent-control setup code-reviewer                             │
│  agent-control start code-reviewer                             │
│  agents/code-reviewer/queue/{in,work,out}/                     │
│  agents/code-reviewer/context/*.md                             │
│                                                                 │
│  - Each agent: own queue, own context, own service             │
│  - Polls every 60s (light on resources)                        │
│  - Task: in → work → out (with PID tracking)                   │
│  - Persistent context loaded with every task                   │
│  - Ideal for: continuous services, specialized agents          │
└─────────────────────────────────────────────────────────────────┘
        ↓ Uses
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 2: WORKER QUEUE SYSTEM                                    │
│ (Shared queue with multiple parallel workers)                  │
│                                                                 │
│  worker-manage preflight                                        │
│  worker-manage start 3                                          │
│  workorders/{wip,done}/                                            │
│  bin/local-ai                                                   │
│                                                                 │
│  - Shared queue: workorders/wip/ (first-come, first-served)       │
│  - Multi-worker: 1-N workers process in parallel               │
│  - No hard timeouts: runs as long as producing output          │
│  - Stall detection: kills after 120s no output                 │
│  - Real-time streaming: see model thinking                     │
│  - Auto git workflow: maps → commit → push                     │
│  - Ideal for: batch processing, prompt experiments             │
└─────────────────────────────────────────────────────────────────┘
        ↓ Uses
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 3: LOCAL MODEL INFERENCE                                  │
│ (Streaming output, progress monitoring)                         │
│                                                                 │
│  local-ai prompt.md --model qwen:7b                            │
│  local-ai "Generate hello world" --stream                      │
│                                                                 │
│  - Ollama backend with 3 models: qwen, deepseek, codellama    │
│  - Streaming mode: see tokens as they arrive                   │
│  - Stall detection: know when process is stuck                 │
│  - Ideal for: real-time inference, testing models              │
└─────────────────────────────────────────────────────────────────┘
```

## Use Case Matrix

| Need | Layer | Command | When |
|------|-------|---------|------|
| **Specialized service** (code reviewer, doc gen) | Agent | `agent-control setup <name>` | Always running, continuous intake |
| **Batch processing** multiple prompts | Worker | `worker-manage start 3` | Run multiple tasks quickly |
| **Single inference** test/debug | Local | `local-ai prompt.md` | Interactive, one-off queries |
| **Long-running task** that might think | Any | All support no hard timeouts | Model takes 10+ minutes |
| **Stuck detection** | All | All monitor output | Process produces no output 120s |

## Command Cheat Sheet

### Agent System (Persistent Services)

```bash
# Set up agent
agent-control setup code-reviewer --model deepseek-coder:6.7b

# Edit context
vim agents/code-reviewer/context/system.md

# Start service (background)
agent-control start code-reviewer

# Submit work
agent-control submit code-reviewer "Your task"

# Monitor
agent-control status code-reviewer
agent-control queue code-reviewer
agent-control logs code-reviewer --follow

# Stop
agent-control stop code-reviewer
```

### Worker System (Parallel Processing)

```bash
# Verify ready
worker-manage preflight

# Start workers (3 in parallel)
worker-manage start 3

# Add prompt to queue
echo "---\nmodel: qwen:7b\n---\n# Task\nGenerate code" > workorders/wip/task.md

# Monitor
worker-manage status
worker-manage logs --follow

# Stop all
worker-manage stop
```

### Direct Inference (One-Off)

```bash
# Test model directly
local-ai "Generate hello world in Python"

# Run on specific prompt file
local-ai workorders/wip/my-prompt.md --model deepseek-coder:6.7b

# Check what models available
local-ai --models

# Verify services running
local-ai --check
```

## Architecture Decisions

### Why Three Layers?

1. **Agent Layer**: For persistent, specialized services
   - Each agent has its own queue, context, state
   - Runs continuously (checks every 60s)
   - Perfect for: code reviewer, doc generator, analyzer
   - Parallel processing via multiple agents

2. **Worker Layer**: For batch processing
   - Shared queue, multiple workers
   - No hard timeout (respects long thinking)
   - Auto git workflow (maps, commit, push)
   - Ideal for: benchmarks, prompt experiments, bulk tasks

3. **Local Layer**: For direct inference
   - Simple command-line interface
   - Streaming output for visibility
   - Used by both layers above

### Design Philosophy

**Light on Resources**
- Agent services: 60s poll interval (minimal CPU)
- Workers: Only run when needed
- Streaming: See progress without polling

**Graceful Degradation**
- No hard timeouts if producing output
- Stall detection: kill after 120s silence
- Auto-retry: tasks move back to queue on failure

**Observable**
- All output streamed (see model thinking)
- Structured logs (JSON events)
- State tracking (metrics, PIDs)
- Real-time monitoring commands

**Cross-Platform**
- Windows and Linux identical
- Same commands, same behavior
- Future: systemd/Windows Service wrappers

## File Structure

```
csc/
├── bin/
│   ├── agent-control.py        Main agent CLI
│   ├── agent-setup.py          Initialize agents
│   ├── agent-service.py        Background service
│   ├── worker-manage           Worker CLI
│   ├── worker-daemon.py        Background worker
│   ├── worker-preflight        Pre-flight checks
│   └── local-ai                Direct inference
│
├── agents/                      Agent instances
│   ├── code-reviewer/
│   │   ├── queue/{in,work,out}/
│   │   ├── context/
│   │   └── state.json
│   ├── doc-generator/
│   └── ...
│
├── workorders/                     Worker queue
│   ├── wip/                     Pending
│   ├── done/                    Completed
│   └── ready/                   Ready to run
│
├── logs/
│   ├── agents/                  Agent logs
│   │   └── <agent>/service.log
│   └── worker-*.log             Worker logs
│
└── tools/
    └── .lastrun                 Map timestamp
```

## Layer Integration

### Agent → Worker → Local

When you run an agent:

```
1. User adds task to agents/<name>/queue/in/

2. agent-service.py (background process)
   - Polls every 60s
   - Finds task in in/
   - Moves to work/
   - Combines context + task

3. Calls local-ai:
   python bin/local-ai <prompt> --model <model> --stream

4. local-ai calls ollama:
   curl http://localhost:11434/api/generate with streaming=true

5. ollama returns tokens:
   - Token stream appears in logs
   - Stall detection watches for output
   - Service tracks process/results

6. On completion:
   - Moves work/ → out/
   - Records results/PID/timestamp
   - Updates state.json
   - Ready for next task
```

## Running Everything Together

### Example: Multiple Services + Workers

```bash
# 1. Set up agent services
agent-control setup code-reviewer --model deepseek-coder:6.7b
agent-control setup doc-generator --model qwen:7b

# 2. Start agents (background)
agent-control start code-reviewer
agent-control start doc-generator

# 3. Start workers (background)
worker-manage preflight
worker-manage start 2

# 4. Submit work to agents
agent-control submit code-reviewer "Review my code"
agent-control submit doc-generator "Generate docs"

# 5. Add to worker queue
echo "Generate hello world" > workorders/wip/task1.md

# 6. Monitor everything
agent-control status code-reviewer
agent-control status doc-generator
worker-manage status
agent-control logs code-reviewer --follow &
worker-manage logs --follow &

# 7. Check results
cat agents/code-reviewer/queue/out/*.json
cat workorders/done/task1.md
```

Everything runs in parallel, independently, with full visibility.

## Configuration Examples

### Code Reviewer Agent

```bash
agent-control setup code-reviewer \
  --model deepseek-coder:6.7b \
  --desc "Reviews Python code for quality"
```

Edit `agents/code-reviewer/context/system.md`:
```markdown
# Code Reviewer

Review code for:
- Correctness
- Performance
- Security
- Style

Output: [Issue summary] [Recommendations] [Positive feedback]
```

### Batch Benchmark

```bash
worker-manage preflight
worker-manage start 3

for i in {1..10}; do
  cat > workorders/wip/benchmark-$i.md << EOF
# Benchmark $i

Generate hello world in 8 languages.
EOF
done

worker-manage logs --follow
```

### Development Workflow

```bash
# Quick test on specific prompt
local-ai workorders/wip/my-prompt.md --model qwen:7b

# See model options
local-ai --models

# Run full worker batch
worker-manage start 1
worker-manage submit workorders/wip/*.md
```

## Performance Notes

### Resource Usage

**Agent Services** (per agent):
- Memory: ~50MB (idle)
- CPU: <1% (polling every 60s)
- Network: Only when task running

**Worker Daemons** (per worker):
- Memory: ~100MB per running task
- CPU: 20-80% while processing
- Scales: 2-3 workers on typical machine

**Local Models** (ollama):
- Memory: 1-5GB (model dependent)
- CPU: High while generating
- GPU: Uses if available

### Tuning

**Light load:**
```bash
agent-control start agent-name --poll-interval 120  # Check 2x/min
```

**Responsive:**
```bash
agent-control start agent-name --poll-interval 10   # Check 6x/min
```

**Batch processing:**
```bash
worker-manage start 4  # 4 workers in parallel
```

## See Also

- `docs/AGENT_SYSTEM.md` - Full agent documentation
- `docs/WORKER_SYSTEM.md` - Full worker documentation
- `docs/WORKER_QUICKSTART.md` - Quick reference
- `docs/PREFLIGHT_CHECKS.md` - Pre-flight validation
- Individual `bin/*.py` files for implementation details
