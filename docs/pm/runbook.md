# PM Decision Loop (Runbook)

## Every Cycle (run_cycle)

```
1. RECOVER
   - Scan workorders/wip/ for orphans (>10min, no queue entry)
   - Move orphans back to ready/
   - Clean stale state entries (files that no longer exist)

2. CHECK IF BUSY
   - Any .pid files in agents/*/queue/work/?    → WAIT
   - Any .md files in agents/*/queue/in/?       → WAIT
   - Any orders.md in agents/*/queue/work/?     → WAIT
   - If busy → return [] (patient, one at a time)

3. SCAN AND PRIORITISE ready/
   - Sort by: P0 > P1 > P2 > P3, then alphabetically
   - Skip: human-review flagged items

4. PICK ONE WORKORDER (highest priority)

5. SELECT AGENT
   a. Agent prefix in filename? (haiku-*, opus-*, etc.)
      → YES: use that agent (human override)
   b. Previous failures ≥ 2?
      → YES: escalate (flash→pro, pro→opus, haiku→pro)
   c. Default policy by category

6. ASSIGN (one only)
   - agent_service.assign(filename)
   - Record in pm_state.json
   - Return [(filename, agent)]
```

## Priority Tiers

```
P0 - Do Now (blocks everything)
    urgent*, fix_test_*, fix_*, security*

P1 - Force Multipliers
    queue_worker*, test_runner*, pm_*, agent_service*,
    csc_service*, csc_ctl*, infrastructure*

P2 - Features & Fixes
    Everything not P0/P1/P3

P3 - Documentation
    docs_*, docstring*, document_*
```

## Agent Selection

```
Workorder arrives
│
├─ Has agent prefix in filename? (haiku-*, opus-*, etc.)
│  └─ YES → use that agent (human override)
│
├─ Previous failures ≥ 2? Check escalation:
│  ├─ gemini-2.5-flash → gemini-3-pro
│  ├─ gemini-3-pro → opus
│  ├─ haiku → gemini-3-pro
│  └─ opus → flag for human review (stop retrying)
│
├─ Is it fix_test_* / run_test_* / docs_* / docstring*?
│  └─ YES → gemini-2.5-flash
│
├─ Is it an audit/review/validate task?
│  └─ YES → haiku
│
├─ Is it a debug/investigate task?
│  └─ YES → opus
│
├─ Is it a code task (feature/refactor/fix)?
│  └─ YES → gemini-3-pro
│
└─ Default → gemini-3-pro
```

## Completion Feedback Loop

```
Queue-worker detects agent exit:
│
├─ WIP last line == "COMPLETE"
│  └─ pm.mark_completed(filename)
│     → status = "completed" in pm_state.json
│     → Workorder moves to done/
│
└─ No COMPLETE marker
   └─ pm.mark_failed(filename)
      → attempts += 1
      → Workorder moves back to ready/
      ├─ attempts < 3: status = "retry" (same agent next time)
      ├─ attempts ≥ 3: escalate to stronger agent
      └─ no escalation possible: status = "human-review" (stops)
```

## Self-Healing

```
PM encounters unfixable problem
│
└─ create_fix_workorder(title, description)
   → Creates pm_fix_<title>.md in ready/
   → Another agent picks it up and resolves it
   → No duplicates (checks if file exists first)
```

## Recovery States

```
Orphaned WIP (>10min, no queue entry):
   → Move back to ready/
   → State set to "recovered"
   → Re-assigned on next cycle

Stale state (file deleted/moved manually):
   → Remove from pm_state.json
   → Prevents blocking re-assignment

Agent prefix override:
   → Filename starts with agent name
   → Overrides all other selection logic
```
