# Workorder Retry & Failure Handling Strategy

## Overview

No model admits defeat at a task. Instead of escalating to "better" models, the system:
1. **Retries relentlessly** (~10 times per agent)
2. **Switches agents** (different agent, same capability level)
3. **Analyzes failures** (debug agent after ~20 failures)
4. **Fixes the problem** (task breakdown, clarification, setup)

---

## Workflow

### Phase 1: Primary Agent (Attempts 1-10)

Agent assigned by PM works on workorder.

**If succeeds**: Move to done/. Done.

**If fails**:
- Queue-worker calls: `track-wo-failure.sh <workorder> <agent>`
- Failure count incremented
- Workorder moved back to ready/
- PM reassigns to same agent (retry)

After 10 failures → move to Phase 2

---

### Phase 2: Alternate Agent (Attempts 11-20)

PM detects 10 failures, assigns to **different agent** (same capability tier):

**Retry pattern**:
- gemini-flash → gemini-pro (or vice versa)
- haiku → gemini-flash (sideways, not escalation)

**If succeeds**: Move to done/. Done.

**If fails again**:
- Failure count incremented (11-20)
- Workorder moved back to ready/
- PM reassigns

After 20 failures → move to Phase 3

---

### Phase 3: Debug Analysis (Attempt 21+)

At ~20 failures:

1. **Workorder moved**: wip/ → failed/
2. **Debug workorder created**: ready/ with analysis prompt
3. **Debug agent assigned**: (sonnet, P1 priority)

Debug agent's job:
```
This workorder failed 20 times.
Figure out what's wrong:
  - Unclear requirements? (rewrite)
  - Needs breakdown? (split into tasks)
  - Missing setup? (add prerequisites)
  - Task impossible? (mark as such)

Fix it and restart.
```

---

## Implementation

### Queue-Worker Integration

When agent completes workorder:

```bash
if [ $exit_code -ne 0 ]; then
  # Failed
  bash /c/csc/bin/track-wo-failure.sh "$WO_FILE" "$AGENT"
  # Continues, PM will reassign
else
  # Success
  mv "$WO_FILE" "$CSC_ROOT/ops/wo/done/$WO_NAME"
fi
```

### Failure Tracking

Persistent log: `.wo-failures/<workorder-name>`

Contains: single integer = failure count

```
.wo-failures/
  ├── improve_test_coverage.md (3)
  ├── cleanup_temp_repos.md (0)
  └── fix_critical_bug.md (15)
```

---

## Agent Behavior: Retry vs Escalation

| Scenario | Old (Escalation) | New (Retry) |
|----------|------------------|------------|
| gemini-flash fails | → escalate to sonnet | → retry gemini-flash (try again) |
| Task has issues | → blame model quality | → analyze task, fix, retry |
| 10 failures | → too hard for haiku | → try gemini instead, same level |
| 20 failures | → impossible task | → debug agent figures it out |

**Key difference**: We assume tasks ARE doable, just need persistence and problem-solving.

---

## Thresholds

- **Per-agent retry**: ~10 attempts
- **Total before debug**: ~20 attempts
- **Debug agent**: P1 priority (gets immediate slot)

Tunable in: `track-wo-failure.sh` (lines with `10` and `20`)

---

## Files

- `bin/track-wo-failure.sh` - Failure counter + escalation logic
- `ops/wo/failed/` - Workorders that hit 20 failures (moved here)
- `ops/wo/templates/debug_failing_workorder.md` - Debug agent prompt template
- `.wo-failures/` - Persistent failure counts (not git-tracked)

---

## Example

### Workorder: `improve_error_handling.md`

```
Attempt 1-10:  gemini-flash (fails repeatedly)
               → track-wo-failure.sh → failure count = 10
               → moved back to ready/

Attempt 11-20: gemini-pro (alternate agent)
               → track-wo-failure.sh → failure count = 20
               → moved to failed/

Attempt 21:    debug_improve_error_handling_TIMESTAMP.md created
               → assigned to sonnet (debug agent)
               → sonnet analyzes:
                  "The task needs breaking into 3 smaller pieces.
                   Also missing setup for test environment.
                   Fixed both, splitting into ready/improve_error_handling_*.md"
               → new workorders created + requeued
               → original marked failed/improve_error_handling.md (archived)
```

---

## Success Metrics

- Most workorders finish in attempt 1-5
- Some need 10-15 attempts (persistence pays off)
- Debug agent (attempt 21+) fixes by:
  - Task redesign (40%)
  - Clearer requirements (30%)
  - Setup/dependencies (20%)
  - Splitting workorders (60%+ of debug cases)
