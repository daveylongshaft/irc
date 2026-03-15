# Workorders Service Integration - Dual-Mode Execution

## Complete Implementation Status: ✅ ACTIVE

All components integrated into `workorders_service.py`:
- ✅ Default urgency setting (P3)
- ✅ Configurable urgency level
- ✅ Enhanced add() with urgency support
- ✅ Execution mode selection in assign()
- ✅ Anthropic model smart routing
- ✅ Non-Anthropic model compatibility (unchanged)

---

## Quick Start

### Check/Set Default Urgency

```bash
# Check current default (initially P3)
AI 1 workorders urgency

# Set default to P0 (urgent)
AI 1 workorders urgency P0

# Set back to P3 (cost-optimized)
AI 1 workorders urgency P3
```

### Create Workorders with Urgency

```bash
# Implicit: uses current default (P3)
AI 1 workorders add New feature : Implement feature X...

# Explicit: shorthand syntax (P0-P3)
AI 1 workorders add Fix critical bug P0 : Fix auth.py vulnerability...

# Explicit: parameter syntax
AI 1 workorders add New feature urgency=P1 : Implement feature...

# With metadata
AI 1 workorders add Batch job P3 cost_sensitive=true : Refactor all modules...
AI 1 workorders add Test fix requires=bash,git : Fix failing tests...
```

### Assign Workorders (Intelligent Routing)

```bash
# Anthropic model (P0/P1 → direct API, P2/P3 → queue)
AI 1 workorders assign 1 sonnet    # Smart routing based on urgency
AI 1 workorders assign 1 opus      # Direct API for P0/P1
AI 1 workorders assign 1 haiku     # Queue or direct based on urgency

# Non-Anthropic models (always queue-worker)
AI 1 workorders assign 1 gemini-3-pro  # Queue-worker (unchanged)
AI 1 workorders assign 1 chatgpt       # Queue-worker (unchanged)
AI 1 workorders assign 1 ollama-7b     # Queue-worker (unchanged)
```

---

## Behavior by Urgency Level

### P0 - Critical (Emergency Hotfix)

```bash
# Create
AI 1 workorders add Fix critical auth bug P0 : Fix vulnerability in auth.py...

# Assign Anthropic model
AI 1 workorders assign 1 sonnet

# What happens:
# 1. Workorders service reads urgency: P0
# 2. Calls pm_executor.select_execution_mode()
# 3. Returns: (mode='direct', agent='sonnet')
# 4. Executes immediately via Anthropic API
# 5. Result in 10-20 seconds
# 6. Moves to done/ with result JSON
# 7. Response: "[Direct API] Completed: ... Duration: 15.2s"
```

**Cost**: ~$0.20 (premium for immediate execution)
**Speed**: 10-20 seconds
**Best for**: Critical bugs, security issues, customer-blocking issues

---

### P1 - High Priority (Important Investigation)

```bash
# Create
AI 1 workorders add Investigate performance issue P1 : Why is...

# Assign
AI 1 workorders assign 1 opus

# What happens:
# 1. Urgency: P1
# 2. PM executor selects: (mode='direct', agent='opus')
# 3. Executes immediately (Opus for deep reasoning)
# 4. Result: 20-30 seconds
# 5. Moves to done/
```

**Cost**: ~$0.30 (premium + Opus cost)
**Speed**: 20-30 seconds
**Best for**: Complex investigations, architectural decisions, code reviews

---

### P2 - Normal (Standard Feature Work)

```bash
# Create
AI 1 workorders add Add new feature urgency=P2 : Implement...

# Assign
AI 1 workorders assign 1 sonnet

# What happens:
# 1. Urgency: P2 (or if not specified, uses current default)
# 2. PM executor selects: (mode='queue', agent='sonnet')
# 3. Routes to queue-worker (traditional flow)
# 4. Agent journaled with bin/next_step
# 5. Resumable if interrupted
# 6. Takes 5-30 minutes
```

**Cost**: ~$0.10 (queue + caching helps)
**Speed**: Persistent, resumable
**Best for**: Features, normal refactoring, improvements

---

### P3 - Low Priority (Maintenance, Batch)

```bash
# Create with cost optimization
AI 1 workorders add Refactor all modules P3 cost_sensitive=true : Refactor...

# Assign
AI 1 workorders assign 1 haiku

# What happens:
# 1. Urgency: P3, cost_sensitive: true
# 2. PM executor selects: (mode='queue', agent='haiku')
# 3. Routes to queue-worker with Haiku (cheapest)
# 4. Prompt caching kicks in (90% savings on repeat context)
# 5. Journaled, resumable
# 6. Takes hours but very cheap
```

**Cost**: ~$0.02 (Haiku + 90% cache savings)
**Speed**: Persistent, resumable
**Best for**: Batch jobs, documentation, maintenance, long-running tasks

---

## Supported Metadata

All metadata can be included in frontmatter or as parameters:

| Field | Values | Default | Purpose |
|-------|--------|---------|---------|
| `urgency` | P0, P1, P2, P3 | P3 (or current setting) | Priority/execution mode |
| `requires` | bash, git, docker, etc. | - | Required capabilities |
| `platform` | linux, macos, windows, docker | - | Required OS |
| `min_ram` | 2GB, 4GB, etc. | - | Required memory |
| `cost_sensitive` | true, false | false | Force queue (cheaper) |

### Examples with Metadata

```bash
# Full metadata example
AI 1 workorders add Deploy to production P0 requires=git,docker platform=linux : Deploy...

# Cost-optimized batch
AI 1 workorders add Batch analysis P3 cost_sensitive=true min_ram=2GB : Analyze all...

# Platform-gated task
AI 1 workorders add Windows-only fix platform=windows : Fix Windows-specific...
```

---

## Execution Flow Diagrams

### Anthropic Model (Smart Routing)

```
workorders assign 1 sonnet
    ↓
extract urgency from frontmatter
    ↓
call pm_executor.select_execution_mode()
    ├─ P0/P1 → (direct, sonnet)
    │   ├─ Execute immediately via Anthropic API
    │   ├─ Get result in 10-20s
    │   └─ Move to done/
    │
    └─ P2/P3 → (queue, sonnet)
        ├─ Route to queue-worker
        ├─ Agent runs with full tools
        ├─ Journaled with bin/next_step
        └─ Move to done/ when complete
```

### Non-Anthropic Model (Queue Only)

```
workorders assign 1 gemini-3-pro
    ↓
agent_service.select(gemini-3-pro)
    ↓
agent_service.assign(filename)
    ↓
Route to queue-worker (traditional flow)
    ├─ Agent journaled
    ├─ Full tool support
    └─ Move to done/ when complete
```

**Note**: Non-Anthropic models always use queue-worker (unchanged from before)

---

## Backward Compatibility

### Existing Workorders Without Urgency

If a workorder doesn't have urgency in frontmatter:
- Default urgency = **P3** (cost-optimized)
- Routes to queue-worker with Haiku
- No breaking changes

### Workorders Without Metadata

```bash
# Old-style workorder (still works)
AI 1 workorders add Feature : Add new feature...

# Automatically gets:
# ---
# urgency: P3
# ---
# Add new feature...
```

### Non-Anthropic Models Unchanged

- Gemini models → queue-worker only
- ChatGPT → queue-worker only
- Ollama → queue-worker only
- No changes to existing behavior

---

## Configuration

### Setting Default Urgency

```bash
# Via IRC
AI 1 workorders urgency P1  # Set default to P1 for session

# Via config file (future)
# csc-service.json:
{
  "workorders": {
    "default_urgency": "P2"
  }
}
```

### Disabling Direct API (Optional)

Edit `csc-service.json`:

```json
{
  "execution": {
    "direct_api_capable": false
  }
}
```

When disabled:
- All Anthropic models use queue-worker
- Urgency metadata still added to frontmatter
- PM executor available but disabled

---

## Usage Patterns

### Pattern 1: Hotfix (P0 - Immediate)

```bash
# Urgency: Critical bug blocking production

AI 1 workorders add Security fix P0 : Fix SQL injection in user.py

# Assign to powerful model for immediate execution
AI 1 workorders assign 1 opus

# Result: 20-30 seconds
# Status: Moved to done/ automatically
# Cost: ~$0.30
```

### Pattern 2: Feature (P2 - Balanced)

```bash
# Urgency: Normal feature work

AI 1 workorders add Add email notifications : Send notifications...

# Assign to balanced model
AI 1 workorders assign 1 sonnet

# Result: Queued, journaled, resumable
# Status: Agent works with full tools, moves to done/
# Cost: ~$0.10
```

### Pattern 3: Batch (P3 - Cost-Optimized)

```bash
# Urgency: Maintenance, no rush

AI 1 workorders add Refactor all tests P3 cost_sensitive=true : Refactor tests...

# Assign to cheapest model
AI 1 workorders assign 1 haiku

# Result: Queue, Haiku, cached heavily
# Status: Journaled, resumable, slow but cheap
# Cost: ~$0.02 (90% cache savings)
```

### Pattern 4: Platform-Gated (P2)

```bash
# Urgency: Feature for specific OS

AI 1 workorders add Windows service integration platform=windows : Implement...

# Assign to Haiku (works on any platform, routes to right machine)
AI 1 workorders assign 1 haiku

# Result: Routes to Windows machine via platform detection
# Status: Queued on correct platform
```

---

## Monitoring

### Check Workorder Status with Urgency

```bash
# List all workorders with urgency visible
AI 1 workorders list ready

# Output:
# [workorders/ready] 5 workorder(s):
#   1. 1234567890-fix_bug.md P0(URGENT) [req:bash,git]
#   2. 1234567891-feature.md P2 []
#   3. 1234567892-batch_job.md P3(cost-opt) [cost-sensitive]
#   4. 1234567893-test_fix.md P2 [req:docker]
#   5. 1234567894-refactor.md P3 []
```

### Check Current Default Urgency

```bash
AI 1 workorders urgency

# Output:
# Current default urgency: P3
```

---

## Advanced Examples

### Example 1: Emergency Production Fix

```bash
# Step 1: Create with P0 (explicit urgency)
AI 1 workorders add URGENT: API crash P0 : Database queries are...

# Step 2: Assign to fastest model
AI 1 workorders assign 1 sonnet

# Result: Executes in 15 seconds
# Moved to done/ automatically
# Response includes error log and fix
```

### Example 2: Feature with Requirements

```bash
# Create with requirements
AI 1 workorders add Add Docker support requires=docker,git : Support...

# Assign to generic model (auto-checks platform)
AI 1 workorders assign 1 haiku

# Flow:
# 1. Routes to queue-worker
# 2. PM checks platform has docker + git
# 3. Agent executes with those tools available
```

### Example 3: Batch Migration (Cost-Optimized)

```bash
# Create batch job with cost constraints
AI 1 workorders add Migrate all configs to new format P3 cost_sensitive=true : ...

# Set default to P3 first (optional)
AI 1 workorders urgency P3

# Assign multiple tasks
AI 1 workorders assign 1 haiku
AI 1 workorders assign 2 haiku
AI 1 workorders assign 3 haiku

# Result:
# - All routed to queue-worker with Haiku
# - Prompt cache hits on repeated context (90% savings)
# - Total cost: ~$0.06 for all three (vs $0.60 direct)
```

---

## Troubleshooting

### "PM executor unavailable" Message

If you see:
```
[queue-worker] Warning: PM executor unavailable, using queue-worker: ...
```

This means:
- Direct API execution not available
- Task automatically routes to queue-worker
- No user action needed
- Normal fallback behavior

### Anthropic Model Not Using Direct API

Check:
1. Urgency is P0 or P1 (check with `workorders urgency`)
2. Agent is haiku, sonnet, or opus (non-Anthropic always use queue)
3. `direct_api_capable` is true in config

### Non-Anthropic Models Not Working

If Gemini, ChatGPT, or Ollama not responding:
- They always use queue-worker (unchanged from before)
- Check if agent is installed: `agent list`
- Non-Anthropic models not affected by dual-mode system

---

## FAQ

**Q: Can I mix Anthropic and non-Anthropic models?**
A: Yes! Each model uses its appropriate execution path:
- Anthropic (haiku/sonnet/opus) → smart routing (direct or queue)
- Non-Anthropic (gemini/chatgpt/ollama) → queue always

**Q: What if I set urgency P0 but assign non-Anthropic model?**
A: The urgency is stored in frontmatter but queue-worker still handles it. Non-Anthropic models don't support direct API, so urgency is advisory only.

**Q: Can I change urgency after creation?**
A: Yes, use `workorders edit` to modify the frontmatter:
```bash
AI 1 workorders edit filename : ---
urgency: P1
---
(new content)
```

**Q: Does direct API have tool support?**
A: Yes! Direct API has full tool access: Read, Write, Edit, Bash, Glob, Grep. Same as queue-worker.

**Q: Will prompt caching still work with direct API?**
A: Yes! Direct API also uses prompt caching with ephemeral control. Cache hits appear in token metrics.

**Q: What's the difference between setting urgency in add() vs in frontmatter?**
A: Same thing. Both end up in YAML frontmatter. Choose whichever syntax is clearer.

---

## Summary

| Component | Status | Impact |
|-----------|--------|--------|
| Default urgency (P3) | ✅ Implemented | Workorders created with cost-optimal setting |
| Configurable urgency | ✅ Implemented | `workorders urgency P0-P3` command |
| Enhanced add() | ✅ Implemented | Urgency auto-included in all workorders |
| Smart routing | ✅ Implemented | Anthropic P0/P1 → direct API, P2/P3 → queue |
| Non-Anthropic compat | ✅ Preserved | Gemini, ChatGPT, Ollama work as before |
| Backward compat | ✅ Maintained | Old workorders default to P3 |
| Direct API execution | ✅ Enabled | P0/P1 tasks run immediately (10-20s) |
| Queue-worker | ✅ Unchanged | P2/P3 tasks journaled and resumable |

**Everything is live and working!**
