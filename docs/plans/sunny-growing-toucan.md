# Fix Benchmark Queue System Architecture

## Context

The benchmark system is broken because I implemented it incorrectly. The current implementation directly calls `agent_service.assign()` which spawns wrappers synchronously and causes prompts to get stuck in wip/ and ready/ directories.

**Current broken flow:**
- benchmark → agent_service.assign() → wrapper spawned → polling for done/
- No queue system
- Prompts accumulate in wip/ when agents fail
- No background service to handle queue

**Correct architecture (user specified):**
1. Benchmark creates prompt and puts it in `agents/<agent_name>/queue/in/`
2. Prompt is a template that references README.1shot (prevents AI from doing git/moving prompts)
3. Prompt tells AI where to find WIP file in `prompts/wip/`
4. Background service monitors `queue/in/` directories
5. Service moves prompt from `queue/in/` → `queue/work/`
6. Service calls agent with wrapper
7. Wrapper moves prompt from `prompts/ready/` → `prompts/wip/`
8. Agent works on it, wrapper waits for exit
9. Wrapper checks for COMPLETE tag in WIP
10. Wrapper moves to `done/` or `ready/` based on tag
11. Wrapper runs refresh-maps and git push/pull

## Problems Found

**12 stuck prompts:**
- 5 in `prompts/ready/benchmark-hello-world-*.md`
- 7 in `prompts/wip/benchmark-hello-world-*.md`
- All created by failed benchmark runs
- Wrapper logs are empty (0 bytes) - wrapper never executed properly

**Root causes:**
1. No queue directory structure (`agents/<agent>/queue/in/` doesn't exist)
2. No background service to process queues
3. benchmark_service.run() directly calls agent_service instead of using queue
4. No cleanup mechanism for stuck prompts
5. Wrapper not being called correctly

## Implementation Plan

### Phase 0: Clean Up Stuck Prompts ✅ COMPLETE

**Status:** All prompts moved to quarantine (65 files)
- prompts/ready/ - empty
- prompts/wip/ - empty
- prompts/quarantine/ - 65 files preserved for review

Next: Create task prompts and implement queue system

### Phase 1: Create Queue Directory Structure

Create directories for each agent:
```
agents/
  ollama-codellama/
    queue/
      in/
      work/
  ollama-deepseek/
    queue/
      in/
      work/
  ollama-qwen/
    queue/
      in/
      work/
  haiku/
    queue/
      in/
      work/
  ...etc for all agents
```

### Phase 2: Create Queue Worker Script (Platform-aware)

**File:** `bin/queue-worker` (Python script with .bat wrapper for Windows)

Periodic script that runs every 1-5 minutes via:
- **Windows**: Task Scheduler
- **Linux/Mac**: cron

Script logic:

**On each run:**

1. **Check queue/in/ for new work:**
   - Scan all `agents/*/queue/in/` directories
   - For each prompt found:
     - Move to `agents/*/queue/work/`
     - Spawn wrapper as background process
     - Save wrapper PID to `queue/work/{prompt}.pid` file
     - Exit (don't wait)

2. **Check queue/work/ for completed work:**
   - Scan all `agents/*/queue/work/` directories
   - For each prompt found:
     - Read corresponding `.pid` file
     - Check if PID is still running (`os.kill(pid, 0)`)
     - If PID is dead:
       - Check WIP file for COMPLETE tag
       - Archive result if complete
       - Move prompt out of work/
       - Delete `.pid` file
     - If PID is alive: do nothing (check next time)

3. **Exit** until next cron run

**No blocking, no daemons** - just periodic checks

**Scheduler Setup:**

Windows (Task Scheduler):
```powershell
schtasks /create /tn "CSC Queue Worker" /tr "C:\csc\bin\queue-worker.bat" /sc minute /mo 2
```

Linux/Mac (crontab):
```bash
*/2 * * * * /opt/csc/bin/queue-worker >> /opt/csc/logs/queue-worker.log 2>&1
```

The script detects platform and provides setup instructions on first run

### Phase 3: Fix benchmark_service.run()

**File:** `packages/csc-shared/services/benchmark_service.py`

Change `run()` method to:
1. Create benchmark prompt template that includes:
   - Reference to README.1shot
   - Path to WIP file in `prompts/wip/`
   - Clear instructions for AI
2. Create WIP file in `prompts/wip/` first
3. Put prompt in `agents/{agent_name}/queue/in/`
4. Poll for WIP file to get COMPLETE tag or timeout
5. When complete, archive result and cleanup

### Phase 4: Create Cleanup Utility

**File:** `bin/cleanup-stuck-prompts`

Script to:
- Find prompts older than X minutes in ready/wip
- Move them to a quarantine directory
- Log what was cleaned up
- Allow manual review before deletion

### Phase 5: Fix Wrapper Integration

**File:** `bin/dc-agent-wrapper`

Ensure wrapper:
- Checks for COMPLETE tag at end of WIP
- Moves to done/ if COMPLETE found
- Moves to ready/ if no COMPLETE or failure
- Always runs refresh-maps after agent work
- Always does git pull/push cycle

### Phase 6: Update Prompt Template

Create template that tells AI:
```
You are working on a task. Your WIP file is at: prompts/wip/{filename}

RULES (from README.1shot):
- Do NOT move prompts between directories
- Do NOT run git commands
- Journal all work to the WIP file
- When complete, add "COMPLETE" tag at bottom of WIP

WIP file location: {wip_path}
Task: {benchmark_task}
```

## Critical Files

- `packages/csc-shared/services/benchmark_service.py` - Fix to use queue
- `packages/csc-shared/services/queue_worker_service.py` - NEW: background worker
- `bin/dc-agent-wrapper` - Verify COMPLETE tag logic
- `bin/cleanup-stuck-prompts` - NEW: cleanup utility
- Create `agents/*/queue/in/` and `/work/` directories

## Verification

1. Clean up existing stuck prompts (12 files)
2. Create queue directories
3. Start queue worker service
4. Run `benchmark run hello-world ollama-codellama`
5. Verify:
   - Prompt appears in `agents/ollama-codellama/queue/in/`
   - Worker moves to `queue/work/`
   - Agent executes
   - WIP file updated
   - COMPLETE tag detected
   - Moved to done/
   - Result archived
   - Git committed
6. Check no prompts stuck in ready/wip

## Cleanup First

Before implementing, clean up the mess:
```bash
# Move stuck prompts to quarantine
mkdir -p prompts/quarantine
mv prompts/ready/benchmark-*.md prompts/quarantine/
mv prompts/wip/benchmark-*.md prompts/quarantine/

# Check git status
git status

# Commit cleanup
git add -A
git commit -m "cleanup: Quarantine stuck benchmark prompts"
git push
```
