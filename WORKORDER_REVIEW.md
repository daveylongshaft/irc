# Workorder Review: Technical Issues Found

**Status**: 🔴 STOP — Fix before assigning to Haiku

**Workorders**:
- PROMPT_csc_major_restructure_all_steps.md
- PROMPT_csc_restructure_full_lifecycle.md

---

## Issue 1: Service Names Are Wrong in Lifecycle Workorder

**Severity**: 🔴 CRITICAL — Will fail at Phase 1 & 6

**Location**: Lifecycle workorder, Phases 1.2 and 6.1-6.4

**Problem**: Service names don't match actual csc-ctl outputs

**Current (WRONG)**:
```
csc-ctl stop csc-service      # WRONG - doesn't exist
csc-ctl stop csc-server       # WRONG - should be "server"
csc-ctl stop csc-claude       # WRONG - should be "gemini" or similar
csc-ctl stop csc-bridge       # WRONG - should be "bridge"
```

**Actual Service Names** (from `csc-ctl status`):
```
- queue-worker        (enable_queue_worker)
- test-runner         (enable_test_runner)
- pm                  (enable_pm)
- server              (enable_server)
- bridge              (enable_bridge)
- gemini              (client, under "clients")
```

**Fix Required**:
Replace Phase 1.2 and Phase 6 service names with actual names:

```
CORRECT PHASE 1.2 SHUTDOWN ORDER:
1. queue-worker
2. test-runner
3. pm
4. server
5. bridge
6. gemini (and any other clients)

CORRECT PHASE 6 STARTUP ORDER:
1. server              (core)
2. queue-worker       (processes tasks)
3. test-runner        (runs tests)
4. pm                 (manages processes)
5. bridge             (optional, IRC bridge)
6. gemini             (if enabled)
```

**Also note**: claude-api will be a NEW client after restructure. Add to startup after gemini:
```
7. claude-api (new streaming API runner)
```

---

## Issue 2: common.py Path Logic Is Incomplete

**Severity**: 🔴 CRITICAL — Code will break after restructure

**Location**: Restructure workorder, Part 4.5, and lifecycle workorder Phase 5.2

**Problem**: common.py path resolution will be wrong after restructure

**Current** (in /c/csc/bin/claude-batch/common.py, line 91):
```python
BASE_DIR = Path(__file__).resolve().parent  # = /c/csc/bin/claude-batch/
def repo_root() -> Path:
    return BASE_DIR.parent.parent  # = /c/csc/ (current, correct)
```

**After Restructure** (in /c/csc/irc/bin/claude-batch/common.py):
```python
BASE_DIR = Path(__file__).resolve().parent  # = /c/csc/irc/bin/claude-batch/
def repo_root() -> Path:
    return BASE_DIR.parent.parent  # = /c/csc/irc/ (WRONG! needs umbrella root)
```

**Fix Required**:
Update line 91 to use 3 parents instead of 2:
```python
def repo_root() -> Path:
    return BASE_DIR.parent.parent.parent  # Now = /c/csc/ (umbrella root, correct)
```

**Workorder Action**: Add this to Part 4.5:
> Update line 91: Change `BASE_DIR.parent.parent` to `BASE_DIR.parent.parent.parent`

---

## Issue 3: Missing GitHub Username Placeholder

**Severity**: 🟡 MEDIUM — Will block at Phase 2 (GitHub operations)

**Location**: Both workorders, Part 2 and Phase 2

**Problem**: Workorder uses "USER/REPO" but doesn't ask Haiku for their GitHub username

**References**:
- Restructure Part 2.1: `gh repo clone USER/REPO`
- Restructure Part 2.3: `github.com/USER/csc`
- Lifecycle Phase 2 (implied)

**Fix Required**: Add a clarification section at the start of both workorders:

> **Before starting:** What is your GitHub username? (Used for all `github.com/USER/...` URLs)
> Record it and replace all "USER" placeholders with your actual username.

---

## Issue 4: Submodule Linking Order May Fail

**Severity**: 🟡 MEDIUM — Could fail at Part 5.4 (submodule setup)

**Location**: Restructure workorder, Part 5.4

**Problem**: Linking submodules before the remote repos are fully initialized

**Current Order**:
1. Part 5.1: `git init` umbrella repo, create .gitmodules
2. Part 5.2: `git init` irc/, commit, push to remote
3. Part 5.3: `git init` ops/, commit, push to remote
4. Part 5.4: Link submodules (requires remotes to be ready)

**Issue**: If Part 5.2/5.3 pushes take too long, Part 5.4 may fail to fetch submodules.

**Fix Required**: Add waiting step after each push:

> After pushing irc/ to remote (line 336), wait 10 seconds for GitHub to process:
> ```bash
> sleep 10
> ```
>
> Repeat after pushing ops/ to remote.

---

## Summary Table

| Issue | Severity | Fix Type | Effort |
|-------|----------|----------|--------|
| Service names wrong | 🔴 CRITICAL | Edit workorder Phases 1 & 6 | 2 min |
| common.py path is off-by-one | 🔴 CRITICAL | Edit Part 4.5 | 1 min |
| GitHub username missing | 🟡 MEDIUM | Add clarification section | 2 min |
| Submodule timing | 🟡 MEDIUM | Add sleep commands | 1 min |

---

## Recommendation

**Fix all 4 issues before assigning to Haiku.** They're straightforward edits:

1. Replace service names in Phases 1–6 (lifecycle workorder)
2. Add `.parent` to common.py line 91 (restructure workorder, Part 4.5)
3. Add GitHub username clarification (top of both workorders)
4. Add `sleep 10` after git push commands (restructure workorder, Part 5.2 & 5.3)

**Total fix time**: ~6 minutes of editing

**After fixes**: Haiku can proceed safely.

