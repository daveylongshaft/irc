# State-Of-Project Documentation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans + batch API with prompt caching

**Goal:** Create comprehensive, linked, indexed documentation of entire CSC system architecture, code flows, and operations with professional "AWSNYWASN" (Are We Sky Net Yet? We Are Sky Net!) theming.

**Approach:**
1. Create `state-docs/` directory structure
2. Generate 15-20 focused documentation workorders
3. Use Anthropic Batch API with prompt caching for efficiency
4. Build interconnected glossary, TOC, cross-references
5. Professional markdown with consistent theme
6. Link all documentation in README.md → state-docs/index.md

**Architecture:**
- **Entry Point:** `state-docs/index.md` (themed title page + TOC)
- **Core Systems:** queue-worker.md, pm.md, test-runner.md
- **Code Maps:** By module (queue_worker.py, pm.py, platform.py, etc.)
- **Operational Flows:** With exact code line references
- **Glossary & Index:** Searchable via markdown tables
- **GitHub Integration:** Linked in README.md as "System Documentation"

**Tech Stack:**
- Anthropic Batch API v1 with prompt caching
- Prompt caching for codemap + docs (50% cost reduction)
- Multiple prompts in single batch request (JSON array)
- Markdown documentation with semantic linking
- GitHub-compatible structure

---

## CURRENT SYSTEM ANALYSIS (Answers to User Questions)

### Q1: When a workorder is complete, are changes merged to repo using PRs?

**ANSWER: NO PRs currently. Direct commits.**

```
Flow:
1. Agent finishes, writes "COMPLETE" as last line in WIP file
2. queue_worker.py:1024-1049 checks for COMPLETE marker
3. If COMPLETE: moves WIP → done/, creates commit directly to main branch
4. Commit message: "feat: Complete prompt <name>"
5. No PR creation, no review, direct push to main
6. pm.py is notified via mark_completed() but doesn't create PR
```

**Code Location:** `packages/csc-service/csc_service/infra/queue_worker.py:1059-1070`

**Issue Found:** No PR workflow enforced. Violates CLAUDE.md mandatory PR review policy (line 231: "NO code changes merge to main without PR review").

### Q2: Is temp repo being moved to .trash at end?

**ANSWER: NO cleanup currently. Repos persist.**

```
Flow:
1. ensure_agent_temp_repo() creates: /c/Users/davey/AppData/Local/Temp/csc/AGENT_NAME/repo
2. Agent executes in temp repo
3. Temp repo changes committed + pushed to main
4. Process exits
5. Temp repo LEFT IN PLACE - never cleaned up or moved to trash
```

**Code Location:** `packages/csc-service/csc_service/infra/queue_worker.py:1299` (pull), but NO cleanup after spawn.

**Issue Found:** Temp repos accumulate, causing disk bloat. User protocol says: "Clear broken repos immediately" but no cleanup happens on success either.

### Q3: How is system gracefully recovering from errors? What errors?

**ANSWER: Multi-layer error handling with graceful fallbacks:**

| Error | Detection | Recovery |
|-------|-----------|----------|
| **Git pull fails** | subprocess.run timeout/error | Revert orders.md back to queue/in/, retry next cycle |
| **Detached HEAD** | git symbolic-ref fails | Auto-checkout main branch |
| **Rebase conflict** | "unmerged files" error | Run git rebase --abort, cleanup rebase-merge/ |
| **Agent crashes immediately** | Poll after 3s, process exited | Revert orders.md, log error, mark for retry |
| **Agent timeout (>4hrs)** | Elapsed time > 14400s | Kill process, move to ready/ for PM escalation |
| **Agent stalled (no progress)** | WIP+log unchanged for 5 cycles | Move to ready/, PM escalates |
| **Credit exhaustion** | Detect in agent log | Rotate API key, re-queue with new key |
| **Orphaned work files** | File in work/ without .pid | Move to queue/out/ with warning |

**Code Locations:**
- Git recovery: `queue_worker.py:163-207`
- Agent crash detection: `queue_worker.py:1334-1354`
- Stale detection: `queue_worker.py:912-948`
- Credit rotation: `queue_worker.py:994-1018`

### Q4: Is system resolving stuck repos, or are YOU?

**ANSWER: You (user) are. System detects but doesn't auto-fix broken temp repos.**

```
What System Does:
1. Detects git pull failure in temp repo
2. Logs error and aborts agent spawn
3. Reverts orders.md for retry
4. Next cycle hits same error again → infinite loop

What System DOES NOT Do:
1. Move broken repo to trash
2. Clone fresh copy
3. Continue in same cycle
4. Auto-recover from merge conflicts

User Protocol (MEMORY.md):
- "When repo is broken: mv to .trash, clone fresh, proceed same cycle"
- But system doesn't implement this
```

**Issue Found:** Gap between desired protocol and actual implementation. Need to add auto-recovery logic.

### Q5: Have any PRs been approved/rejected?

**ANSWER: No PR system exists yet.**

- No PR creation code in queue_worker.py or pm.py
- No review integration with GitHub
- All changes committed directly to main
- CLAUDE.md mandates PRs but system ignores this

---

## CYCLE WALKTHROUGHS (Exact Code Flow)

### PM Cycle (pm.py main loop)

```
Entry: packages/csc-service/csc_service/infra/pm.py main()

STEP 1: Initialize (pm.py:1850-1860)
├─ Read config from pm_state.json
├─ Load API key manager
└─ Setup paths

STEP 2: Main loop - every 60 seconds (pm.py:1865+)
├─ Check agent_data.json for active agents
├─ Read logs/queue-pending.json for pending work
├─ Escalate if needed:
│  ├─ Haiku stalled 1 cycle? Try Sonnet
│  ├─ Sonnet stalled 2 cycles? Try Opus
│  └─ Opus stalled? Mark done (failure)
├─ Batch same-type workorders
│  ├─ N platform_XX tasks? Assign all to Haiku in one order
│  ├─ Multiple tests? Batch together
│  └─ Create orders.md with list
└─ Write agent_data.json (who's running what)

STEP 3: Completion handling
├─ If agent_data shows agent finished
├─ Check workorders/wip for COMPLETE marker
├─ If COMPLETE: mark_completed(), notify queue-worker
└─ Loop to STEP 2

CODE: pm.py:1840-1900
```

### Queue-Worker Cycle (queue_worker.py run_cycle)

```
Entry: queue_worker.py:1379 run_cycle()

STEP 1: Initialize paths (queue_worker.py:1387)
├─ Load CSC_ROOT from environment
├─ Set AGENTS_DIR, PROMPTS_BASE, etc.
└─ Create directories if missing

STEP 2: Git pull main repo (queue_worker.py:1393)
├─ subprocess.run(['git', 'pull', '--rebase', '--autostash'])
├─ If fails: log error, continue anyway
└─ Get latest workorder assignments

STEP 3: Process existing work (queue_worker.py:1396 process_work)
├─ Scan agents/*/queue/work/*.pid files
├─ For each PID:
│  ├─ Check if process alive (Windows tasklist + powershell)
│  ├─ Check WIP file for progress (size growth)
│  ├─ Check agent log for progress
│  ├─ If running: skip, continue next PID
│  ├─ If stale 5 cycles: KILL process
│  ├─ If runtime > 4hrs: KILL process
│  ├─ If finished:
│  │  ├─ Commit + push from temp repo
│  │  ├─ Pull changes into main repo
│  │  ├─ Check WIP for COMPLETE marker
│  │  ├─ If COMPLETE: move to done/, notify PM
│  │  └─ If not: move back to ready/ for retry
│  └─ Clean up .pid file
└─ Return has_active_work (bool)

STEP 4: Process inbox if no active work (queue_worker.py:1399+ process_inbox)
├─ If has_active_work from step 3: RETURN (only one task at a time)
├─ Scan agents/*/queue/in/orders.md files
├─ Parse: which agent, which workorders
├─ For first pending workorder:
│  ├─ Move orders.md: queue/in/ → queue/work/
│  ├─ git add + commit + push
│  ├─ ensure_agent_temp_repo() - clone if missing
│  ├─ git_pull_in_repo() - sync latest
│  ├─ If git fails: revert orders.md, return (retry next cycle)
│  ├─ spawn_agent(agent_name, workorder_path, temp_repo)
│  ├─ Write .pid file with process ID
│  ├─ Sleep 3 seconds, check if crashed immediately
│  ├─ If crashed: revert orders.md, return
│  └─ Log "Started AGENT (PID xxxxx) for WORKORDER"
└─ RETURN (process one task per cycle)

STEP 5: Defer if in batch mode (queue_worker.py:1252-1296)
├─ If defer_git_sync() returns True:
│  ├─ Don't commit yet
│  ├─ Batch API will commit all together
│  └─ More efficient for large batches
└─ Otherwise: commit immediately

CODE: queue_worker.py:1379-1405
```

### Test-Runner Cycle (test-runner bin script)

```
Entry: bin/test-runner (Python script polling every 60s)

STEP 1: Scan tests/ directory
├─ Find all tests/test_*.py files
└─ For each test:

STEP 2: Check lock (tests/logs/test_NAME.log exists?)
├─ If log exists: TEST IS LOCKED (don't run, don't create prompt)
├─ Reason: Either test is running or we already saw this failure
└─ Move to next test

STEP 3: Run test
├─ If no log: test hasn't run yet
├─ subprocess.run(['pytest', 'tests/test_NAME.py', '-v'])
├─ Capture stdout/stderr
└─ Write to tests/logs/test_NAME.log

STEP 4: Check results
├─ If FAILED lines in log:
│  ├─ Template: tests/prompt_template.md
│  ├─ Fill placeholders: test name, failed lines, log path
│  ├─ Write workorders/ready/PROMPT_fix_test_NAME.md
│  ├─ Commit + push
│  └─ Next agent picks it up and fixes code
├─ If PLATFORM_SKIP lines:
│  ├─ Delete tests/logs/test_NAME.log (unlock for other platform)
│  ├─ Create workorders/ready/PROMPT_run_test_NAME.md
│  ├─ Route to machine that has the required platform
│  └─ That agent deletes log, lets test run there
└─ If PASSED: do nothing, log stays (test is locked)

CODE: bin/test-runner (full implementation)
```

---

## IDENTIFIED ISSUES & BUGS

| Issue | Severity | Location | Impact |
|-------|----------|----------|--------|
| **No PR workflow** | CRITICAL | queue_worker.py:1066-1070 | Violates mandatory review policy (CLAUDE.md:231) |
| **Temp repos not cleaned** | HIGH | queue_worker.py:1299+ | Disk bloat, no trash at end |
| **Broken repos cause infinite loops** | HIGH | queue_worker.py:1304-1314 | System retries same error forever |
| **No auto-recovery of merged repos** | MEDIUM | git recovery logic | User must manually mv .trash + clone |
| **Gemini secret module missing** | MEDIUM | csc_service.clients.gemini.secret | Agent spawn fails |
| **Git push timeout 30s** | MEDIUM | queue_worker.py:1282-1292 | Can timeout on slow networks |
| **Test runner doesn't clean stale logs** | LOW | bin/test-runner | Old logs lock tests forever |

---

## BATCH API ARCHITECTURE FOR DOCUMENTATION

**Goal:** Generate 15-20 documentation files in parallel with prompt caching

**Batch Request Structure (JSON):**
```json
{
  "requests": [
    {
      "custom_id": "doc-1-queue-worker-overview",
      "params": {
        "model": "claude-opus-4-6",
        "max_tokens": 4000,
        "system": [
          {"type": "text", "text": "You are a technical documentation expert..."},
          {"type": "text", "text": "<FULL CODEMAP FROM tools/csc-service.txt>", "cache_control": {"type": "ephemeral"}},
          {"type": "text", "text": "<TREE.TXT>", "cache_control": {"type": "ephemeral"}},
          {"type": "text", "text": "<P-FILES.LIST>", "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [
          {"role": "user", "content": "Document queue_worker.py architecture: initialization, cycle flow, agent spawning, error recovery..."}
        ]
      }
    },
    // ... 14-19 more requests with different doc tasks
  ]
}
```

**Efficiency:**
- Prompt caching of codemap saves 90%+ of reprocessing
- All 15 docs share same cached context (~50% cost reduction)
- Parallel execution vs sequential
- Single batch request vs 15 separate API calls

---

## PLAN: GENERATE STATE-OF-PROJECT DOCUMENTATION

### Task 1: Create state-docs/ directory structure

**Files:**
- Create: `state-docs/index.md` (title page + TOC)
- Create: `state-docs/glossary.md` (terms & cross-refs)
- Create: `state-docs/queue-worker.md` (main system)
- Create: `state-docs/pm-agent.md` (orchestration)
- Create: `state-docs/test-runner.md` (automation)
- Modify: `README.md` (link to state-docs)

**Step 1: Create title page**

```markdown
# Are We Sky Net Yet? We Are Sky Net!

## CSC System State-of-Project Documentation

*"The Terminator 1984 — "Come with me if you want to live."*
*We came. We built. We automated."*

> **Last Updated:** 2026-03-01
> **Status:** Autonomous | Queue-Worker Cycling | 41 Pending | 27 Completed
> **Author:** The AI Collective

[Table of Contents](#table-of-contents)
[System Architecture](#architecture)
[Code Maps](#code-maps)
[Operational Flows](#flows)
[Glossary](#glossary)

---

## Quick Status

- **Daemon:** Running (csc-service)
- **Queue:** 41 ready, 1 WIP, 27 done
- **Agents:** Haiku, Sonnet, Opus cascade
- **Tests:** Auto-run, fix-on-fail
- **PRs:** ❌ Not implemented (issue #1)
```

**Step 2: Create 20 focused documentation workorders**

Each becomes a queue-worker task assigned to Opus:
1. `doc-queue-worker-initialization.md`
2. `doc-queue-worker-cycle-flow.md`
3. `doc-agent-spawning.md`
4. `doc-error-recovery.md`
5. `doc-git-operations.md`
6. `doc-pm-cascade.md`
7. `doc-pm-batching.md`
8. `doc-test-runner.md`
9. `doc-platform-detection.md`
10. `doc-api-key-rotation.md`
11. `doc-storage-system.md`
12. `doc-irc-server.md`
13. `doc-bridge-proxy.md`
14. `doc-shared-library.md`
15. `doc-client-cli.md`
16. `doc-glossary.md`
17. `doc-architecture-diagram.md`
18. `doc-deployment.md`
19. `doc-cost-analysis.md`
20. `doc-troubleshooting.md`

**Step 3: Create batch request JSON**

```bash
bin/claude-batch/create_batch.py \
  --mode=state-docs \
  --prompt-cache \
  --codemap=$(cat tools/csc-service.txt) \
  --tree=$(cat tree.txt) \
  --output=state-docs-batch.json
```

**Step 4: Submit batch request**

```bash
curl https://api.anthropic.com/v1/messages/batches \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -d @state-docs-batch.json
```

**Step 5: Wait for completion**

Batch API processes in parallel, caches shared context, returns all docs.

**Step 6: Assemble final documentation**

- Aggregate all 20 docs into state-docs/
- Build glossary with cross-references
- Generate index with TOC
- Link in README.md

---

## THIS WORKORDER

**Single workorder, multiple prompts via Batch API.**

Instead of 20 separate queue-worker assignments, submit ONE batch request with 20 prompts, all using same cached codemap.

**Execution:** Use `superpowers:executing-plans` to:
1. Set up batch API request (JSON)
2. Submit to Anthropic API
3. Poll until complete
4. Assemble docs locally
5. Commit + push to GitHub

---

## Next Steps

1. ✅ Confirm architecture
2. 📝 Write batch request template
3. 🔄 Submit batch (50% cost reduction via caching)
4. 📚 Assemble 20 docs into state-docs/
5. 🔗 Link in README.md
6. 🎬 Create GitHub Pages version (optional)

