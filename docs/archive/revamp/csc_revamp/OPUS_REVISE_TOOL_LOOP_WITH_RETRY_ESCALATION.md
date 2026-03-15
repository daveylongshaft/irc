# Revise Tool Loop Executor - Add Retry + Model Escalation

**Agent**: Opus
**Priority**: P0
**Depends on**: batch_executor.py exists at /c/csc/bin/batch_executor.py

## Problem

Current executor runs all 5 phases in sequence without validation. If Phase 1 fails:
- Phase 2 still runs (wrong - built on broken state)
- No retry logic
- No escalation to higher-capability models

## Solution

Revise `/c/csc/bin/batch_executor.py` to add:

### 1. Sequential Phase Validation
```
Phase 1 (haiku) → Check success
  ├─ If success: proceed to Phase 2
  ├─ If fail: Retry Phase 1 (2-3x with haiku)
  │  ├─ If still fail: Escalate to sonnet
  │  └─ If sonnet fails: Escalate to opus
  └─ Only after Phase 1 succeeds: move to Phase 2
```

### 2. Retry Logic
- Re-run same batch (same batch_id) up to 2-3 times before escalation
- Capture full tool execution log
- Show which tool failed and why

### 3. Model Escalation
```python
ESCALATION_CHAIN = ["haiku", "sonnet", "opus"]

# If current model fails N times, try next model
# Pass full conversation history to escalated model so it understands context
```

### 4. Success Criteria Per Phase
Each phase completes when:
- All tool_use blocks executed without error
- `stop_reason == "end_turn"` (no more tools pending)
- All file operations verified (check /c/csc/ structure after each phase)

### 5. Logging
Log per phase:
- Which model ran it (haiku/sonnet/opus)
- How many retries before success
- Tool execution times and outputs
- Any errors encountered

## Implementation

Modify `batch_executor.py`:

1. Add `execute_phase_with_retry(batch_id, phase_num, max_retries=2)` function
2. Track which model is running each batch (current_model param)
3. On tool execution failure:
   - Log error details
   - Increment retry counter
   - If retries exhausted: escalate_to_next_model()
4. Before proceeding to next phase: verify phase success
   - Check file system state
   - Check all tools executed (stop_reason="end_turn")
   - Log success confirmation

## Execution

Test with Phase 1 batch:
```bash
python /c/csc/bin/batch_executor.py msgbatch_01JoDGSYgfqHBQqMXh9jnUaK --phase=1 --max-retries=2
```

Output should show:
```
[PHASE 1]
  Model: haiku
  Attempt 1: FAILED (tool X error)
  Attempt 2: SUCCESS
  → Proceed to Phase 2
```

Then manually test phases 2-5 sequentially.

## Success Criteria

- Phase 1 completes successfully (tools execute, stop_reason="end_turn")
- Phase 2 completes successfully
- ... Phase 3, 4, 5
- Final state: /c/csc/irc/ and /c/csc/ops/ exist and populated
- /c/csc_old/ backup in place

Do not proceed to next phase until current one succeeds.
