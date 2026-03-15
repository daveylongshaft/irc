# CSC Restructure Phase 3: Execute Detailed Restructure

**Agent**: Sonnet
**Priority**: P0
**Duration**: 30-45 minutes
**Goal**: Execute the comprehensive folder migration, path updates, and git setup

---

## PHASE 3: Execute Restructure

At this point, all services are stopped and packages are uninstalled. The system is in a clean state.

With the system in a clean state, execute the comprehensive restructure plan which covers:
1. GitHub repo operations (backup old repos, create new ones)
2. Folder migration (copy /c/csc/ → /c/new_csc/irc/ and ops/)
3. Path constants updates (6 files with line-by-line edits)
4. Git and submodule setup
5. Agent status bug fix
6. Testing and verification
7. Final swap (csc → csc_old; new_csc → csc)

### 3.1 Execute the Detailed Restructure Plan

**Reference file**: `/c/csc_revamp/PROMPT_csc_restructure_full_lifecycle.md` (lines 152-199 for context)

The complete detailed plan is at: `/c/csc_revamp/PROMPT_csc_major_restructure_all_steps.md`

This is a comprehensive plain-English plan with 10 major sections. Execute sections 1–9 fully:

1. Current state review (read-only)
2. GitHub repo operations (backup old, delete old, create new)
3. Folder migration (copy packages, bin, tests, etc.)
4. Path constants updates (6 files)
5. Git and submodule setup
6. Agent status bug fix
7. cagent_run.py architecture (design only)
8. Testing & verification
9. Final swap (csc → csc_old; new_csc → csc)

**Do NOT proceed to section 10 (post-swap tasks)** — we'll do that in a later phase.

As you work through the plan:
- Read every file before editing (confirm line numbers)
- Test each major section (folder copy, git init, path update)
- Use git commands to verify submodule setup
- Report any failures immediately — don't continue if something breaks

### 3.2 After Section 9 Complete: Verify Structure

When section 9 completes (folder swap), verify:

```
ls -la /c/csc/
```

Should show: irc/, ops/, .git/, .gitmodules, csc-service.json, platform.json

```
ls -la /c/csc/irc/packages/
```

Should show all packages: csc-shared/, csc-server/, csc-service/, etc.

```
ls -la /c/csc/ops/wo/
```

Should show: ready/, wip/, done/, hold/, archive/, results/, batch/

```
ls -la /c/csc/ops/agents/
```

Should show: haiku/, sonnet/, opus/, claude-api/, gemini/

**If all directories exist and are not empty, report structure is correct.**

**If anything is missing, STOP immediately and report what's missing. Do not continue.**

### 3.3 Completion Report

When complete, provide:
- GitHub repos backed up and deleted (Y/N)
- New repos created on GitHub (Y/N)
- Folder migration complete (/c/new_csc/ populated) (Y/N)
- Path constants updated in all 6 files (Y/N)
- Git and submodules initialized (Y/N)
- Agent status bug fixed (Y/N)
- Final folder swap completed (Y/N)
- New structure verified (all directories present and populated) (Y/N)
