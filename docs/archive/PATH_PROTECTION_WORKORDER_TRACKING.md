# Path-Based Git Protection System - Workorder Tracking

**Created:** 2026-02-28 03:25 UTC
**Status:** All 8 workorders queued and in WIP (agents actively processing)

## Workorders

| ID | WO # | Title | Agent | Status | Priority |
|----|------|-------|-------|--------|----------|
| 1 | - | Fix agent command segfault (Windows MSYS2) | Opus | 🟡 WIP | 🔴 CRITICAL |
| 2 | 1 | GitHub Actions Workflow (ai-code-review.yml) | Gemini-3-Flash | 🟡 WIP | 🟡 Medium |
| 3 | 2 | CODEOWNERS file | Gemini-3-Flash | 🟡 WIP | 🟡 Medium |
| 4 | 3 | AI Reviewer Script (bin/ai-reviewer.py) | Opus | 🟡 WIP | 🟠 Hard |
| 5 | 4 | PR Creator Module (pr_creator.py) | Opus | 🟡 WIP | 🟠 Hard |
| 6 | 5 | Queue Worker Path Protection | Opus | 🟡 WIP | 🔴 HARDEST |
| 7 | 6 | Config & .gitignore Updates | Gemini-3-Flash | 🟡 WIP | 🟡 Medium |
| 8 | 7 | Testing & Validation | Gemini-3-Flash | 🟡 WIP | 🟡 Medium |

## Processing Strategy

**Gemini Phase (Cheaper):**
- 4 workorders: #1, 2, 6, 7 (easy/medium)
- Estimated cost: ~$0.02
- Will exhaust Gemini API

**Opus Phase (Harder):**
- 4 workorders: SEGFAULT, 3, 4, 5 (medium/hard)
- Estimated cost: ~$0.15
- Fallback for anything Gemini can't handle

**Total Estimated Cost:** ~$0.17 (vs ~$1.50+ without batch optimization)

## Files Created

These will be created by the agents as they process:

### GitHub Configuration
- `.github/workflows/ai-code-review.yml` - GitHub Actions workflow
- `.github/CODEOWNERS` - Protected path ownership rules

### Python Modules
- `bin/ai-reviewer.py` - AI code reviewer (Gemini → Opus fallback)
- `packages/csc-service/csc_service/infra/pr_creator.py` - PR creation helper

### Modified Files
- `packages/csc-service/csc_service/infra/queue_worker.py` - Add path protection logic
- `csc-service.json` - Add GitHub configuration
- `.gitignore` - Ignore reviewer output files

### Documentation
- All WIPs will be updated with work logs

## System Flow (Once All Complete)

```
Agent commits code change
    ↓
Queue Worker detects changes in temp repo
    ↓
Check: Protected path modified?
    ├─ YES: Create feature branch → Push to origin → Create PR
    │       ↓
    │       GitHub Actions Trigger: ai-code-review.yml
    │       ↓
    │       AI Reviewer (Gemini-3-Pro first, Opus fallback)
    │       ↓
    │       Post review to PR (APPROVE or REQUEST_CHANGES)
    │       ↓
    │       Cannot merge without approval
    │
    └─ NO: Direct push to main (no PR, no delay)
        ↓
        All systems pull latest immediately
```

## Monitoring

**Check Progress:**
```bash
wo status                    # Queue stats
agent status                 # Running agents
wo list wip | grep "1772"   # Path protection workorders
agent tail 50               # Agent work log (last 50 lines)
```

**When Complete (WIPs → Done):**
```bash
# All 8 should move to done/ as agents finish
wo list done | grep "1772"
```

## Known Issues / Fallbacks

1. **Segfault Fix Blocks Everything**
   - Created as WO with highest priority
   - Opus will investigate and fix
   - System won't proceed smoothly until fixed
   - But WOs are queued, system will retry

2. **Gemini API Exhaustion**
   - Expected after 4 workorders (~$0.02)
   - Fallback: Use Opus (higher cost but works)
   - No impact on system function

3. **PR Creation Fails**
   - If GitHub token invalid/missing
   - Queue worker will log error
   - WO moves to done anyway (PR creation is non-blocking)
   - Can retry after fixing config

## Success Criteria

✅ All 8 workorders moved to done/
✅ No INCOMPLETE markers in WIPs
✅ Files created in correct locations
✅ Git diffs show expected changes
✅ Testing WO passes all checks
✅ System ready for deployment

## Timeline Estimate

- **Now** → WOs all queued, agents processing
- **5-10 min** → Gemini finishes easy ones (WO #1, 2, 6, 7)
- **10-15 min** → Opus finishes hard ones (SEGFAULT, #3, 4, 5)
- **5 min** → Verify files, test system
- **Total: ~20-30 min** to fully deployed system

(Parallel processing makes it faster than sequential)

## Created By

Assistant (Claude Code) - 2026-02-28 03:25 UTC

## Related Documents

- `PATH_PROTECTION_BATCH_STRATEGY.md` - Batch processing approach
- `CLAUDE.md` - System operating instructions
- Individual workorders in `workorders/ready/` and `workorders/wip/`
