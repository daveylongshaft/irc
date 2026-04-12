# Multi-Agent System - Queue-Based Task Processing

CSC's multi-agent system allows you to run multiple specialized AI agents as background services. Each agent:

- Has an **isolated queue** for task distribution
- Maintains **persistent context** for consistent behavior
- Runs as a **system service** (Windows/Linux identical)
- Processes tasks **asynchronously** without blocking
- Tracks **state and metrics** for monitoring

## Architecture

```
┌─ User submits task
│  agent-control submit code-reviewer "Review this code"
│
├─ Task lands in queue/in/
│  agents/code-reviewer/queue/in/20260221-194530.json
│
├─ Service polls queue (every 60s by default)
│  agent-service code-reviewer
│
├─ Moves to queue/work/ + spawns worker
│  agents/code-reviewer/queue/work/...
│
├─ Worker loads agent context + task
│  agents/code-reviewer/context/*.md
│
├─ Passes to model (local-ai + streaming)
│  local-ai --model qwen:7b < combined_prompt.md
│
└─ On completion:
    - Moves to queue/out/
    - Records PID, timestamps, results
    - Service logs everything
    - Ready for next task
```

## Quick Start

### 1. Set Up Agent

```bash
# Create new agent
agent-control setup code-reviewer --model deepseek-coder:6.7b

# Directory structure created:
# agents/code-reviewer/
# ├── queue/
# │   ├── in/      ← Submit tasks here
# │   ├── work/    (processing)
# │   └── out/     (results)
# ├── context/
# │   ├── system.md
# │   ├── model-settings.json
# │   └── guidelines.md
# └── state.json
```

### 2. Configure Agent (Edit Context)

Edit `agents/code-reviewer/context/system.md`:

```markdown
# Code Reviewer Agent

You are an expert code reviewer focusing on:
- Code quality and style
- Performance optimization
- Security issues
- Best practices

## Review Criteria

1. Functionality - Does it work?
2. Readability - Is it clear?
3. Performance - Is it efficient?
4. Security - Are there vulnerabilities?
5. Maintainability - Can others understand it?

## Output Format

Provide:
- Summary of findings
- Issues found (high/medium/low priority)
- Specific recommendations
- Positive feedback
```

### 3. Start Service

```bash
# Start agent service (runs forever, checks queue every 60s)
agent-control start code-reviewer

# Verify running
agent-control status code-reviewer
```

### 4. Submit Tasks

```bash
# Submit task via CLI
agent-control submit code-reviewer "Review the following Python code..."

# Or create task JSON directly
cat > agents/code-reviewer/queue/in/my-task.json << 'EOF'
{
  "id": "review-001",
  "submitted": "2026-02-21T19:45:00Z",
  "content": "Review this function: def add(a, b): return a+b",
  "model": "deepseek-coder:6.7b"
}
EOF
```

### 5. Monitor Progress

```bash
# Check agent status
agent-control status code-reviewer

# View detailed queue
agent-control queue code-reviewer

# Watch logs in real-time
agent-control logs code-reviewer --follow

# Results in queue/out/ when complete
ls agents/code-reviewer/queue/out/
```

## Directory Structure

```
csc/agents/
└── <agent-name>/
    ├── queue/
    │   ├── in/          [Submit tasks here]
    │   ├── work/        [Currently processing]
    │   └── out/         [Completed tasks]
    ├── context/         [Agent instructions]
    │   ├── system.md         (main instructions)
    │   ├── model-settings.json (config)
    │   ├── guidelines.md      (optional extra guidance)
    │   └── *.md, *.txt, *.json (your files)
    └── state.json       [Agent state/metrics]

csc/logs/agents/
└── <agent-name>/
    └── service.log      [Service logs]
```

## Task Format

Submit JSON files to `queue/in/`:

```json
{
  "id": "unique-task-id",
  "submitted": "2026-02-21T19:45:00Z",
  "content": "The actual task/prompt content",
  "model": "qwen:7b",
  "timeout": 10,
  "stall_timeout": 120
}
```

**Fields:**
- `id`: Unique identifier (auto-generated if omitted)
- `submitted`: Timestamp (auto-generated if omitted)
- `content`: The task/prompt (REQUIRED)
- `model`: Override agent's default model (optional)
- `timeout`: Max time in minutes (optional, uses default)
- `stall_timeout`: Kill if no output for N seconds (optional)

## Command Reference

### Setup & Control

```bash
# Create new agent
agent-control setup code-reviewer --model deepseek-coder:6.7b

# Start agent service (background)
agent-control start code-reviewer

# Stop agent service
agent-control stop code-reviewer

# Check agent status and metrics
agent-control status code-reviewer

# List all agents
agent-control list
```

### Queue & Tasks

```bash
# Submit task from command line
agent-control submit code-reviewer "Your task here"

# View queue details (pending/processing/completed)
agent-control queue code-reviewer

# Submit task from file
cat my-task.json > agents/code-reviewer/queue/in/task-1.json
```

### Monitoring

```bash
# Show agent logs (last 100 lines)
agent-control logs code-reviewer

# Follow logs in real-time (Ctrl+C to stop)
agent-control logs code-reviewer --follow

# Manual log inspection
tail -f logs/agents/code-reviewer/service.log
```

## Context Files

All files in `context/` are loaded and passed to the model with every task.

### system.md

Main instructions for the agent. Tell the model:
- Its role and expertise
- What tasks it handles
- Output format expectations
- Any constraints or guidelines

### model-settings.json

Configuration for the model:

```json
{
  "model": "deepseek-coder:6.7b",
  "temperature": 0.3,
  "top_p": 0.9,
  "timeout_minutes": 10,
  "stall_timeout_seconds": 120
}
```

### guidelines.md

Optional additional guidance:
- Domain-specific rules
- Best practices for your use case
- Examples of good/bad outputs
- Integration notes

### Custom Context Files

Add any `.md`, `.txt`, or `.json` files:

```
context/
├── system.md
├── model-settings.json
├── guidelines.md
├── coding-standards.md     ← Your file
├── api-reference.json      ← Your file
└── examples/
    ├── good-review.md      ← Your file
    └── bad-review.md       ← Your file
```

All loaded automatically for every task.

## Service Behavior

### Startup

```bash
agent-control start code-reviewer
```

- Initializes agent directory if needed
- Loads context files
- Starts background service process
- Service begins polling queue every 60 seconds

### Queue Processing

Every 60 seconds (configurable):

1. Check `queue/in/` for new tasks
2. For each task:
   - Move to `queue/work/`
   - Record PID and timestamp
   - Spawn worker process
   - Pass context + task content to model
   - Stream output in real-time
   - Monitor for stalls (120s no output by default)
3. On completion or failure:
   - Move to `queue/out/` with results
   - Update state.json with metrics
   - Ready for next task

### Logging

Service logs to `logs/agents/<agent-name>/service.log`:

```
[2026-02-21T19:45:30] [INFO] Agent service 'code-reviewer' started
[2026-02-21T19:45:30] [INFO] Loading 3 context files
[2026-02-21T19:46:00] [INFO] Polling queue...
[2026-02-21T19:46:05] [INFO] Found task: review-001
[2026-02-21T19:46:05] [INFO] Processing task: review-001
[2026-02-21T19:46:05] [INFO] Spawning worker: PID 1234
[2026-02-21T19:46:10] [INFO]   [MODEL] I'll analyze this code for quality...
[2026-02-21T19:47:30] [OK] Task review-001 completed (85.3s)
[2026-02-21T19:48:00] [INFO] Polling queue...
```

### State Tracking

`state.json` tracks agent metrics:

```json
{
  "agent": "code-reviewer",
  "description": "Code review specialist",
  "model": "deepseek-coder:6.7b",
  "created": "2026-02-21T19:30:00Z",
  "tasks_processed": 42,
  "tasks_failed": 2,
  "status": "running",
  "updated": "2026-02-21T19:48:00Z"
}
```

## Deployment

### Windows

Service runs as background process:

```bash
# Start (runs in background)
agent-control start code-reviewer

# Verify running
tasklist | findstr agent-service

# Stop
agent-control stop code-reviewer
```

Future: Can wrap as Windows Service for auto-restart on reboot.

### Linux/macOS

Service runs as background process:

```bash
# Start (runs in background)
agent-control start code-reviewer

# Verify running
ps aux | grep agent-service

# Stop
agent-control stop code-reviewer

# Future: Can wrap as systemd service
```

Both platforms support identical setup.

## Examples

### Example 1: Code Reviewer

```bash
agent-control setup code-reviewer \
  --model deepseek-coder:6.7b \
  --desc "Reviews code for quality and security"

# Edit agents/code-reviewer/context/system.md with review criteria

agent-control start code-reviewer

agent-control submit code-reviewer "
Review this Python function for:
- Code quality
- Performance
- Security issues

def process_data(data):
    for item in data:
        if len(item) > 0:
            print(item.upper())
"

# Wait 60 seconds for queue check
sleep 60

# Check results
agent-control queue code-reviewer
cat agents/code-reviewer/queue/out/*.json
```

### Example 2: Documentation Generator

```bash
agent-control setup doc-generator \
  --model qwen:7b \
  --desc "Generates API documentation"

# Edit context files with documentation standards

agent-control start doc-generator

# Submit code for documentation
agent-control submit doc-generator "
Generate API documentation for this function:
def get_user(user_id: int) -> User:
    '''Get a user by ID.'''
    return db.get(user_id)
"

# Results appear in queue/out/
```

### Example 3: Multiple Agents

```bash
# Set up multiple specialized agents
agent-control setup code-reviewer --model deepseek-coder:6.7b
agent-control setup doc-generator --model qwen:7b
agent-control setup bug-analyzer --model deepseek-coder:6.7b

# Start all services
agent-control start code-reviewer
agent-control start doc-generator
agent-control start bug-analyzer

# Submit tasks to different agents
agent-control submit code-reviewer "Review my code..."
agent-control submit doc-generator "Generate docs for..."
agent-control submit bug-analyzer "Analyze this bug..."

# All process independently in background
agent-control list
```

## Troubleshooting

### Agent Won't Start

```bash
# Check if service spawned
ps aux | grep agent-service

# Check logs
agent-control logs code-reviewer

# Verify agent directory
ls -la agents/code-reviewer/
```

### Tasks Stuck in queue/work/

```bash
# Check logs
tail -f logs/agents/<agent>/service.log

# Manual recovery: Move stuck task back to in/
mv agents/<agent>/queue/work/task.json \
   agents/<agent>/queue/in/task.json
```

### No Output After Submission

```bash
# Service checks every 60 seconds by default
# Wait 60+ seconds, then:
agent-control status <agent>
agent-control queue <agent>

# To check faster (optional):
agent-control stop <agent>
agent-control start <agent> --poll-interval 5  # Check every 5s
```

### Check System Resources

```bash
# Verify agent service running
ps aux | grep agent-service

# Check queue usage
du -sh agents/*/queue/

# Check log size
du -sh logs/agents/
```

## Performance Tips

### Poll Interval

- **Default 60s**: Light on resources, 1-minute latency
- **30s**: Faster response, still efficient
- **10s or less**: Responsive but uses more CPU

```bash
agent-control start code-reviewer --poll-interval 10
```

### Model Selection

- **qwen:7b**: Balanced, good for general tasks
- **deepseek-coder:6.7b**: Best for code-related tasks
- **codellama:7b**: Classic, reliable for coding

### Context Size

Keep context files reasonably sized:
- Small files load fast
- Large contexts take more model tokens
- Consider: quality vs. processing speed

### Concurrent Tasks

Multiple agents can run simultaneously:

```bash
agent-control start code-reviewer
agent-control start doc-generator
agent-control start bug-analyzer
# All 3 process queues independently
```

## See Also

- `bin/agent-control.py` - Main CLI
- `bin/agent-service.py` - Service implementation
- `bin/agent-setup.py` - Agent initialization
- `docs/WORKER_SYSTEM.md` - Worker/queue details
- `docs/WORKER_QUICKSTART.md` - Quick reference
