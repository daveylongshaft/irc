# Preflight Checks - Worker Launch Validation

The preflight system ensures workers launch on clean, synchronized state. It verifies 4 key areas before workers start processing.

## Design Philosophy

**Don't launch workers on broken state** - It's better to detect issues upfront than have workers fail silently or commit bad state.

Preflight is idempotent and safe to run multiple times. It doesn't modify state, only checks it.

## The 4 Checks

### 1. Git Status: Clean and Synced

**What it checks:**
- No uncommitted changes (ignores transient logs, caches)
- Local branch synced with remote (not ahead/behind)

**Why it matters:**
- Workers commit on completion - need clean starting point
- If ahead/behind, push/pull may fail

**Example output:**
```
[OK] Git status: clean and synced
[!] Git has uncommitted changes: [list of files]
[!] Git is not synced with remote: ## main...origin/main [ahead 3]
```

**What counts as "uncommitted changes":**
- Modified source files (bad)
- New feature code (bad)
- .aider, .log, __pycache__, etc. (ignored - transient)

**Auto-fix:**
```bash
python bin/worker-manage preflight --fix
```
Runs `git pull` to sync if behind. Doesn't fix ahead (requires review).

### 2. Maps Current: tools/.lastrun Within 5 Minutes of Last Commit

**What it checks:**
- File `tools/.lastrun` exists
- Timestamp difference: `|tools/.lastrun - last_commit| <= 5 minutes`

**Why it matters:**
- Workers reference maps in code exploration
- Stale maps send agents to dead files
- But not every git operation needs map refresh

**Example output:**
```
[OK] Maps current: 0.1 mins behind commit 245a66c
[!] Maps stale: 15.3 mins behind commit 245a66c (tolerance: 5 mins)
[!] Maps not current (tools/.lastrun missing or invalid)
```

**The 5-Minute Window:**

Accounts for legitimate scenarios:
- Merged a branch (no code changes)
- Resolved conflicts (maps still valid)
- Config updates (no new files)
- Time between git ops and map refresh

**If maps are stale:**
1. Run `refresh-maps` manually
2. Commit
3. Then start workers

```bash
python bin/refresh-maps --quick  # Fast refresh
git add analysis_report.json
git commit -m "chore: Refresh maps"
git push
python bin/worker-manage preflight  # Should pass now
```

### 3. Directories: Exist and Writable

**What it checks:**
- `workorders/wip/` exists
- `workorders/done/` exists
- `logs/` exists
- All writable

**Why it matters:**
- Workers poll `wip/` for incoming prompts
- Write completed work to `done/`
- Journal events to `logs/`

**Example output:**
```
[OK] Directories ready
[OK] Creating missing directory: workorders/wip
[X] Failed to create workorders/done: Permission denied
```

If a directory is missing, preflight creates it automatically.

### 4. Worker Processes: No Orphaned Processes

**What it checks:**
- No existing worker daemon processes running
- (Prevents multiple workers fighting over same queue)

**Why it matters:**
- Only one set of workers should process queue
- Orphaned process from crashed run would cause conflicts

**Example output:**
```
[OK] No existing worker processes
[!] Found existing worker processes: [1234, 5678]
```

**If processes exist:**
```bash
# Kill them (forcefully if needed)
python bin/worker-manage stop
ps aux | grep worker-daemon  # Verify gone

# Then run preflight again
python bin/worker-manage preflight
```

## Running Preflight

### Before Launching Workers (Required)
```bash
python bin/worker-manage preflight
```

Must see:
```
Results: 4/4 checks passed

[OK] ALL CHECKS PASSED - Ready to launch workers
```

### Verbose Output (Troubleshooting)
```bash
python bin/worker-manage preflight --verbose
```

Shows detailed output for each check.

### Auto-Fix Mode (Limited)
```bash
python bin/worker-manage preflight --fix
```

Attempts to fix `git pull` if behind remote. Doesn't fix other issues.

## Common Preflight Failures

### Failure 1: Git Status Not Clean
```
[!] Git has uncommitted changes:
M src/main.py
? new-feature.md
```

**Fix:**
```bash
git status  # See what changed
git add .
git commit -m "description of changes"
git push
python bin/worker-manage preflight
```

### Failure 2: Git Not Synced (Behind)
```
[!] Git is not synced with remote: ## main...origin/main [behind 3]
```

**Fix:**
```bash
git pull
python bin/worker-manage preflight --fix  # Auto-does git pull
```

### Failure 3: Git Not Synced (Ahead)
```
[!] Git is not synced with remote: ## main...origin/main [ahead 3]
```

**Fix:**
```bash
# Review your commits
git log -3

# Push if they look good
git push
python bin/worker-manage preflight
```

### Failure 4: Maps Stale
```
[!] Maps stale: 25.3 mins behind commit 6df9a75 (tolerance: 5 mins)
```

**Fix:**
```bash
python bin/refresh-maps --quick
git add analysis_report.json
git commit -m "chore: Refresh maps"
git push
python bin/worker-manage preflight
```

### Failure 5: Missing Directory
```
[!] Failed to create workorders/wip: Permission denied
```

**Fix:**
```bash
# Check permissions
ls -la workorders/
chmod 755 workorders/

# Create manually if needed
mkdir -p workorders/wip workorders/done

python bin/worker-manage preflight
```

### Failure 6: Existing Worker Processes
```
[!] Found existing worker processes: [1234, 5678]
```

**Fix:**
```bash
python bin/worker-manage stop
sleep 2
ps aux | grep worker  # Verify gone

python bin/worker-manage preflight
```

## Full Workflow

```bash
# 1. Make your code changes
vim src/module.py

# 2. Commit and sync
git add .
git commit -m "feat: Add new feature"
git push

# 3. Refresh maps if needed
python bin/refresh-maps --quick
git add analysis_report.json
git commit -m "chore: Refresh maps"
git push

# 4. Verify ready
python bin/worker-manage preflight

# 5. Launch workers
python bin/worker-manage start 3

# 6. Monitor
python bin/worker-manage logs --follow
```

## Implementation Details

### Git Status Check

```python
git status --porcelain  # Get list of changed files
# Filter out transient: .aider, .log, __pycache__, .egg-info
# If any significant changes remain → FAIL
```

### Maps Currency Check

```python
last_commit_time = git log -1 --format=%ct  # Unix timestamp
maps_time = float(open("tools/.lastrun").read())  # Unix timestamp
diff = abs(last_commit_time - maps_time)
if diff <= 300:  # 5 minutes
    PASS
else:
    WARN
```

### Transient File Ignore List

Files that don't block preflight (logs, caches, etc.):
- `.aider*` - Aider session files
- `.log` - Log files
- `__pycache__` - Python cache
- `.egg-info` - Package metadata

### Process Detection

**Linux/Mac:**
```bash
pgrep -f worker-daemon  # Find running worker processes
```

**Windows:**
```bash
tasklist /FI "IMAGENAME eq python.exe"  # List Python processes
```

## FAQ

**Q: Can I run preflight multiple times?**
A: Yes, it's idempotent. Safe to run before every `worker-manage start`.

**Q: What if preflight keeps failing on maps?**
A: Manually run `refresh-maps --quick`, commit, push, then preflight again.

**Q: Can I skip a check?**
A: No - all 4 must pass. If one can't be fixed, it needs investigation.

**Q: What if maps are exactly 5 minutes old?**
A: Preflight uses `<=` so 5 min exactly passes.

**Q: What if I'm actively working on code while workers run?**
A: Stop workers (`worker-manage stop`) before committing, then restart.

## See Also

- `docs/WORKER_SYSTEM.md` - Full system overview
- `bin/worker-preflight` - Implementation
- `bin/refresh-maps` - Map generation
- `CLAUDE.md` - Project architecture
