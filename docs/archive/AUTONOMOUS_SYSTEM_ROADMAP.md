# Autonomous CSC System - Activation Roadmap

**Status:** ACTIVATED - 2026-02-28 10:14 UTC
**API Quota Strategy:** Gemini first, Anthropic fallback, haiku batch caching
**Target:** Fully autonomous workorder processing with real-time PR verification

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AUTONOMOUS CSC SYSTEM                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  1. SERVER (auto-starts on boot)                            │
│     ├─ Port 9525 (UDP)                                      │
│     ├─ Encryption enabled (AES + DH)                        │
│     ├─ Service discovery (builtin, nickserv, botserv, etc)  │
│     └─ Auto-restarts on failure                             │
│                                                               │
│  2. BRIDGE (auto-starts, connects to fahu)                  │
│     ├─ Port 9666 (TCP inbound)                              │
│     ├─ Encryption passthrough (AES + DH)                    │
│     ├─ Route to fahu (facingaddictionwithhope.com:9525)     │
│     └─ Auto-restarts on failure                             │
│                                                               │
│  3. PM (Project Manager) - BEING IMPLEMENTED NOW            │
│     ├─ Auto-prioritize: infra → bugs → tests → docs → feat  │
│     ├─ Auto-select agents: gemini-3-pro → gemini-2.5 → ...  │
│     ├─ Auto-batch: group same-kind workorders               │
│     ├─ Auto-cascade: infra changes trigger test regen       │
│     ├─ Auto-heal: opus fixes PM logic, haiku debugs WOs     │
│     ├─ Auto-rotate: API key quota management                │
│     └─ Self-modifying: can update own logic                 │
│                                                               │
│  4. AGENTS (on demand)                                       │
│     ├─ gemini-3-pro (primary: coding + complex reasoning)   │
│     ├─ gemini-2.5-pro (fallback: coding + moderate)         │
│     ├─ gemini-3-flash-preview (fast coding)                 │
│     ├─ haiku (batch caching: groups of same-kind)           │
│     ├─ opus (PM self-repair, debugging)                     │
│     └─ test-runner (auto-triggered on code changes)         │
│                                                               │
│  5. TEST INTEGRATION                                         │
│     ├─ test_0000_verify_client_bridge_localserver_...       │
│     ├─ Auto-runs when log missing                           │
│     ├─ 4 diagnostics: bridge, encryption, commands, shutdown│
│     ├─ Auto-generates fix workorders on failure             │
│     └─ Self-healing through test-driven diagnostics         │
│                                                               │
│  6. GIT & PR VERIFICATION                                   │
│     ├─ Path-based protection: infrastructure → PR review     │
│     ├─ AI reviewer: verifies scope compliance               │
│     ├─ Auto-merge: direct push for queue/services           │
│     ├─ Real-time: PRs merged as they pass review            │
│     └─ Audit trail: all decisions logged                    │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Processing Pipeline (Real-Time, API Quota Permitting)

```
1. WORKORDER ENTRY
   ├─ Ready/ workorders awaiting assignment
   ├─ 105 items currently queued
   └─ New items auto-discovered every cycle

2. PM PRIORITIZATION
   ├─ Infrastructure changes (PRIORITY 1)
   ├─ Bug fixes (PRIORITY 2)
   ├─ Test fix auto-generation (PRIORITY 3)
   ├─ Docstring regeneration (PRIORITY 4)
   ├─ Documentation (PRIORITY 5)
   └─ Features (held until infra stabilizes)

3. AGENT ASSIGNMENT
   ├─ gemini-3-pro: primary for all coding
   ├─ gemini-2.5-pro: fallback if 3-pro quota hit
   ├─ gemini-3-flash-preview: if both gemini exhausted
   ├─ haiku: batch same-kind with prompt caching
   ├─ opus: PM self-repair + high-complexity debugging
   └─ Rotation based on API quota availability

4. BATCHING & OPTIMIZATION
   ├─ Group identical workorders (all test fixes, all docs)
   ├─ Anthropic batch API with prompt caching
   ├─ Gemini one-at-a-time (no batch API)
   ├─ ~70% token savings with cached prompts
   └─ Cost optimization per API key

5. EXECUTION
   ├─ Agent processes workorder
   ├─ Writes journal to WIP file (real-time feedback)
   ├─ Commits code changes to feature branch
   ├─ Pushes to GitHub
   └─ All changes logged

6. PR VERIFICATION (Real-Time)
   ├─ GitHub Actions triggered on push
   ├─ AI Reviewer runs (opus or gemini-3-pro)
   ├─ Path-based checks:
   │  ├─ Unprotected (queue/, services/): direct merge
   │  └─ Protected (packages/, bin/): PR → AI review → merge
   ├─ Verification: scope compliance + security + architecture
   └─ Auto-merge if approved (real-time)

7. CASCADE TRIGGERS
   ├─ Infrastructure done → test-runner auto-regenerates fix prompts
   ├─ Code changes → docstring regen auto-triggered
   ├─ Test failures → auto-generate fix workorders
   ├─ Persistent failures → opus diagnostic + resolution
   └─ Feedback loop continues until stable

8. COMPLETION
   ├─ Workorder moved to done/
   ├─ Journal logged to workorders/done/
   ├─ All changes in main branch
   ├─ Tests passing
   └─ Ready for next workorder

```

---

## Currently Queued Work (105 items)

### ACTIVE ASSIGNMENTS (in progress)

**PHASE 0: PM System Bootstrap**
- ✅ **ASSIGNED:** opus → `1772268800-pm_agent_module_implementation.md`
  - Implement PM module with full orchestration logic
  - When done: PM can auto-prioritize, batch, and route all future work

- ✅ **ASSIGNED:** haiku → `1772271036-test_pm_agent_module_md.md`
  - Test PM module comprehensively
  - Verify prioritization, batching, agent selection, API quota rotation
  - When done: PM fully validated and production-ready

### QUEUED FOR PM (after bootstrap complete)

**PHASE 1: Service Infrastructure**
- RENAME_queue-worker_to_queue.md - Shorter service names
- ADD_csc-ctl_command_abbreviations.md - `cy q`, `cy ru` syntax
- RENAME_test-runner_to_runner.md - Consistency with queue rename
- ENHANCE_platform_layer_path_resolution.md - Cross-platform paths
- ARCHITECTURE_cross_platform_path_resolution_system.md - System-wide

**PHASE 2: Critical Fixes**
- FIX_log_module_path_initialization.md - Lazy init for paths
- FIX_server_path_resolution.md - Remove hardcoded /opt/csc
- FIX_agent_monitoring_tools_md.md - UTF-8 output handling
- EXTEND_syslog_monitor_internal_logging.md - Config-driven logging

**PHASE 3: Path-Based Git Protection**
- 1_github_workflow_ai_code_review.md - GitHub Actions setup
- 2_github_codeowners_file.md - File ownership tracking
- 3_ai_reviewer_script.md - AI review automation
- 4_pr_creator_module.md - PR creation helper
- 5_queue_worker_path_protection.md - Detect protected files
- 6_config_and_gitignore_updates.md - Config updates
- 7_testing_and_validation.md - Validate protection

**PHASE 4: Testing & Validation**
- 48+ documentation and feature workorders

---

## Success Criteria

✅ **System Online When:**
1. Server auto-starts on boot (csc-ctl install server)
2. Bridge connects to fahu with encryption
3. PM module running and processing workorders
4. Agents assigned automatically based on priority
5. PRs verified and merged in real-time
6. Test runner detects failures and generates fixes
7. System self-heals on failures

✅ **Fully Autonomous When:**
- PM decides workorder priority
- Agents auto-selected based on complexity + quota
- Same-kind workorders batched for efficiency
- API keys rotated as quotas exhausted
- Cascading triggered (infra → tests → docs)
- PR reviews completed in minutes
- All changes tested before merge

---

## API Quota Strategy

**Primary (Gemini):**
- gemini-3-pro: Complex coding tasks
- gemini-2.5-pro: Moderate coding tasks
- gemini-3-flash-preview: Fast coding
- gemini-2.5-flash-lite: Documentation

**Fallback (Anthropic):**
- haiku: Batch processing same-kind workorders (prompt caching)
- opus: PM self-repair + high-complexity debugging

**Rotation Logic:**
1. Try gemini-3-pro
2. If quota hit → gemini-2.5-pro
3. If quota hit → gemini-3-flash-preview
4. If quota hit → haiku (with batch caching)
5. If persistent failure → opus (diagnostic)

**Optimization:**
- Track completion rate per API key
- Rate keys by efficiency (cost/tokens)
- Reorder cascade based on real usage
- Log all quota decisions in PM journal

---

## Real-Time Feedback

**Monitor Progress:**
```bash
# Watch active agent
agent tail 50

# Check PM decisions
cat workorders/wip/pm-execution-journal.md

# See test results
tail logs/test-runner.log

# Monitor API usage
grep -i "quota\|rotation\|fallback" logs/agent_*.log
```

---

## Deployment Checklist

- ✅ Server code fixed and service management ready
- ✅ Bridge configured with encryption to fahu
- ✅ Test framework with auto-run and diagnostics
- ✅ Service renaming workorders queued
- ✅ PM module implementation assigned to opus
- ✅ PM test assigned to haiku
- ✅ 105 workorders queued for processing
- ⏳ **Waiting for:** PM implementation to complete, then system goes fully autonomous

---

## Timeline

**Now - 2026-02-28 10:14:**
- ✅ PM workorders assigned
- ✅ System architecture online
- ✅ 105 items queued

**Next (Opus implementing):**
- PM module logic complete
- PM tested and validated

**Then (All systems go):**
- Queue auto-processes all 105 items
- Real-time PR merging
- Self-healing on failures
- Cascading triggers (infra → tests → docs)

**Final (Fully Autonomous):**
- No manual workorder assignment needed
- AI makes all priority decisions
- API quotas managed automatically
- System self-improves via opus repairs

---

**Status: READY FOR AUTONOMOUS OPERATION**

All infrastructure in place. Waiting for PM module implementation to complete.
