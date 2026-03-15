# CSC Restructure Phase 5: Verify Filesystem & Data Files

**Agent**: Haiku
**Priority**: P0
**Duration**: 10 minutes
**Goal**: Verify all data files and path constants are correctly positioned and accessible

---

## PHASE 5: Verify Filesystem & Data Files

Packages are reinstalled. Now verify that the restructure didn't lose data and all paths are correct.

### 5.1 Check Config Files Exist

```
ls -la /c/csc/csc-service.json
ls -la /c/csc/platform.json
```

Both should exist and be readable. If missing, the restructure failed. Report if either is missing.

### 5.2 Verify Path Constants in Code

For each file listed below, **read the specified lines and confirm the paths are correct**:

**File: /c/csc/irc/packages/csc-service/csc_service/shared/services/agent_service.py**
- Line 33: Should say `PROJECT_ROOT / "ops" / "wo"` (not "workorders")
- Line 662: Should say `PROJECT_ROOT / "ops" / "agents"`
- Confirm PROJECT_ROOT resolves to /c/csc/ (umbrella root)

Read the file, verify these lines, report what you find.

**File: /c/csc/irc/packages/csc-service/csc_service/infra/queue_worker.py**
- Lines 54–58: Should reference "ops/wo" and "ops/agents" (not old paths)
- Verify no references to `/c/csc/workorders` (old path)

Read the file, verify these lines, report what you find.

**File: /c/csc/irc/bin/agent**
- Line 46: Path resolution should go up 3 levels (irc/bin → irc → umbrella root)

Read the file, verify this line, report what you find.

**File: /c/csc/irc/CLAUDE.md**
- Search for "workorders/": All examples should say "ops/wo/"
- Search for "/c/csc/": All examples should reference correct paths
- Spot-check 5–10 examples to confirm they match new structure

Report results.

### 5.3 Check Data Files Reachable

Test that the system can find data files:

```
python -c "from pathlib import Path; print(Path('/c/csc/csc-service.json').exists())"
```

Should print: True

```
python -c "from pathlib import Path; print(Path('/c/csc/ops/wo/ready/').exists())"
```

Should print: True

Both should print True. If either prints False, data files are in wrong location. Report which check failed.

### 5.4 Verify Git Structure

```
cd /c/csc/
git submodule status
```

Should show both submodules linked:
```
+<hash> irc (HEAD detached at <hash>)
+<hash> ops (HEAD detached at <hash>)
```

If you see errors about submodules not found, the restructure failed. Report the output.

### 5.5 Verify Workorders & Agents Accessible

```
ls /c/csc/ops/wo/ready/ | wc -l
```

Should show a count > 0 (number of ready workorders)

```
ls /c/csc/ops/agents/haiku/queue/in/ | wc -l
```

Should show a count >= 0 (may be empty)

If you get "directory not found" errors, the ops/ folder structure is wrong. Report the errors.

### 5.6 Completion Report

When complete, report:
- Config files (csc-service.json, platform.json) exist and readable (Y/N)
- Path constants updated in agent_service.py (Y/N)
- Path constants updated in queue_worker.py (Y/N)
- Path constants updated in bin/agent (Y/N)
- CLAUDE.md examples reference correct paths (Y/N)
- Data files reachable via Python (Y/N)
- Git submodules linked correctly (Y/N)
- Workorders accessible at /c/csc/ops/wo/ready/ (count: ___)
- Agent queues accessible at /c/csc/ops/agents/ (Y/N)
