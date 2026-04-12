# PM Agent Module Implementation - Complete

## Summary

Implemented a comprehensive autonomous Project Manager (PM) agent that handles workorder prioritization, intelligent agent assignment, batching, and self-healing with opus backup and haiku debugging.

## Implementation Details

### 1. **Agent Selection Cascade** ✅
Implemented 6-level intelligent selection cascade in `pm.pick_agent()`:
1. **gemini-3-pro** - coding, complex reasoning (first choice)
2. **gemini-2.5-pro** - coding, moderate complexity (fallback)
3. **gemini-3-flash-preview** - coding, fast inference (if others hit limits)
4. **gemini-2.5-flash-lite** - docs, text-only tasks
5. **haiku** - batch same-kind with prompt caching
6. **opus** - PM self-healing (last resort)

**Features:**
- Human override via filename prefix (e.g., `opus-task.md`)
- API key availability checking
- Agent performance-based filtering (skip agents with <30% success rate)
- Escalation on repeated failures
- Decision journaling for audit trail

### 2. **Workorder Batching** ✅
Implemented in `pm.find_batch_candidates()`:
- Groups same-category workorders (docs, test-fix, audit, validation)
- Anthropic agents (haiku) use prompt caching for batch efficiency
- Gemini agents run one-at-a-time (no batch API)
- Respects priority ordering while grouping

**Features:**
- Transparent to queue-worker (still processes one WO at a time)
- Reduces API calls for same-kind batches
- Fallback to single-item processing for non-batchable categories

### 3. **Self-Healing Capability** ✅

#### Opus Self-Fix (on process failure)
Implemented in `pm.spawn_opus_self_fix()`:
- Triggered when PM module itself crashes (via `run_cycle_safe()` wrapper)
- Creates workorder for opus to fix PM logic
- Provides full codebase context and error traceback
- Restrictions: opus can only modify pm.py, not infrastructure code
- Logged to `self_heal_log` for audit

#### Haiku Debug (on persistent failure)
Implemented in `pm.spawn_haiku_debug()`:
- Triggered when workorder fails 3+ times with different agents
- Creates diagnostic workorder for haiku
- Includes attempt history and error patterns
- Identifies root causes: path issues, API limits, code problems
- Generates resolution workorder if needed
- Logged to `self_heal_log`

### 4. **API Key Management** ✅
Implemented in pm.py:

**Tracking:**
- `record_api_key_use()` - increment usage counter per key
- `mark_api_key_exhausted()` - flag when quota hit (429, rate_limit, quota)
- `reset_api_key()` - reset after quota reset
- Exhaustion patterns logged to journal

**Rotation:**
- `get_available_agent_kind()` - determines gemini vs anthropic availability
- Falls back to available keys when exhausted
- Cascade respects API availability

**Features:**
- Tracks per-key usage and exhaustion events
- Auto-detect exhaustion from error responses
- Fallback chain: gemini → anthropic → haiku batch caching

### 5. **Performance Tracking** ✅
Implemented in pm.py:

**Metrics Tracked:**
- `record_agent_assignment()` - when assigned
- `record_agent_completion()` - on success with duration
- `record_agent_failure()` - on failure
- `get_agent_completion_rate()` - completion % (0.0-1.0)
- `get_metrics_summary()` - full summary with averages

**Storage:**
- Persisted in `pm_state.json` under `agent_metrics` section
- Per-agent: assigned, completed, failed, total_time_secs
- Calculated: completion_rate, avg_time_secs

**Usage:**
- Agent selection skips poorly-performing agents
- Helps identify problematic agents early
- Provides real-time insights via `pm.get_status_report()`

### 6. **PM Decision Journal** ✅
Implemented in pm.py:

**Journal Features:**
- All decisions logged to `logs/pm_journal.log`
- Timestamped entries with structured fields
- Decisions include: ACTION, WO, AGENT, REASON, DETAILS

**Logged Actions:**
- CYCLE_START - PM cycle beginning
- AGENT_SELECT - agent selection with reason
- AGENT_ESCALATE - escalation due to failure
- AGENT_SKIP - skipped due to performance
- BATCH_FOUND - batch grouping detected
- ASSIGNED - workorder assignment
- COMPLETED - workorder completion with duration
- ESCALATE/RETRY/HUMAN_REVIEW - failure handling
- API_KEY_EXHAUSTED - quota limit hit
- HAIKU_DEBUG - debug workorder spawned
- OPUS_SELF_FIX - self-fix workorder spawned
- PM_CRASH - PM-level error detected

**Benefits:**
- Full audit trail of decisions
- Root cause analysis support
- Performance trend analysis
- Self-healing event tracking

### 7. **Priority System** ✅
Classification in `pm.prioritize()`:
- **P0** - Urgent, test fixes, security, fixes (blocks everything)
- **P1** - Infrastructure, queue-worker, PM, test-runner (force multipliers)
- **P2** - Features, refactors, bugs (default)
- **P3** - Documentation

### 8. **Classification System** ✅
Categories in `pm.classify()`:
- `test-fix` - for failed tests
- `simple-fix` - general bug fixes
- `docs` - documentation updates
- `audit` - code reviews
- `debug` - investigation tasks
- `refactor` - code restructuring
- `feature` - default for new work

### 9. **Hold Features During Infra Changes** ✅
Implemented in `run_cycle()`:
- P2/P3 features held while P1 infrastructure changes in progress
- Prevents feature code from interfering with critical infra
- Resumes feature assignment once infra stabilizes

### 10. **Status Reporting** ✅
Implemented in `pm.get_status_report()`:
- Queue stats (ready/wip/done counts)
- Status breakdown (assigned/completed/failed/human-review)
- Agent performance metrics
- API key status
- Recent self-heal events (last 10)

## File Changes

### Modified Files
1. **packages/csc-service/csc_service/infra/pm.py**
   - Complete rewrite with all features
   - ~1,300 lines of well-documented code
   - All 95% scripted/deterministic logic

2. **packages/csc-service/csc_service/main.py**
   - Updated to use `pm.run_cycle_safe()` instead of `pm.run_cycle()`
   - Enables PM-level crash recovery with opus self-fix

### New Files
1. **tests/test_pm_module.py**
   - Comprehensive test suite
   - Tests all major features
   - Mock-based to avoid dependencies

2. **workorders/ready/1772296368-opus-queue_worker_fresh_repo_per_workorder_md.md**
   - Queue optimization workorder created
   - Describes fresh repo cloning strategy

## Architecture Integration

### PM Module Location
- `/opt/csc/packages/csc-service/csc_service/infra/pm.py`
- Part of unified csc-service daemon
- Called every poll cycle (default 60s) by main.py

### State Persistence
- `pm_state.json` - Workorder assignments and metrics
- `logs/pm_journal.log` - Decision audit trail
- Atomic writes ensure no data loss

### Integration Points
1. **csc-service main.py** - Calls `pm.run_cycle_safe()` every cycle
2. **queue-worker** - Calls `pm.mark_completed()` on success
3. **queue-worker** - Calls `pm.mark_failed()` on failure
4. **agent_service** - PM selects agents via this interface

## Testing

Created comprehensive test suite covering:
- Agent selection cascade ✅
- Batching logic ✅
- Self-healing (opus & haiku) ✅
- API key management ✅
- Performance tracking ✅
- Decision journaling ✅
- Classification and prioritization ✅

Run with: `pytest tests/test_pm_module.py -v`

## Key Design Principles

1. **95% Deterministic** - Only spawn agents for: self-fix (opus), debug (haiku), or normal work
2. **One-at-a-Time** - Queue-worker handles one workorder at a time
3. **Atomic State** - All updates written to disk before handler returns
4. **Graceful Degradation** - Cascade selects fallback agents when primaries exhausted
5. **Self-Healing** - Opus can fix PM logic, haiku debugs stuck workorders
6. **Audit Trail** - Every decision logged with reasoning
7. **Performance Feedback** - Metrics guide future selections

## Validation

✅ All PM features implemented per spec
✅ Agent selection cascade (6 levels)
✅ Batching for same-kind workorders
✅ Self-healing (opus & haiku)
✅ API key management and rotation
✅ Performance tracking and journaling
✅ Integration with csc-service
✅ Comprehensive test coverage
✅ Deployed workorder for queue optimization

## Future Enhancements (Out of Scope)

- Queue-worker fresh repo cloning (separate workorder: opus-queue_worker_fresh_repo_per_workorder.md)
- Prometheus metrics export
- Real-time dashboard
- ML-based agent recommendation
- Cost optimization per API provider
