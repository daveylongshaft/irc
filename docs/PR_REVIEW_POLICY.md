# PR Review Policy - CSC Project

## Principle

**NO code merges to main without PR review by Opus or Gemini-3-Pro with full context.**

This is the only safeguard against breaking changes that cascade through a complex, distributed system.

## Why This Matters

The CSC system is wide-spread and interconnected:
- Changes to queue-worker affect PM, which affects all agents
- Changes to server can break IRC protocol for all clients
- Changes to shared libraries cascade everywhere
- One agent might not see the full impact of their changes

**A code reviewer with full context (architecture, dependencies, recent changes) must approve every change before it lands.**

## Workflow

### 1. Developer (Agent) Creates Feature Branch
```bash
git checkout -b feature/description
# Make changes
git add .
git commit -m "feat: description"
git push -u origin feature/description
```

### 2. Create PR
```bash
gh pr create --title "Brief title" \
  --body "$(cat <<'EOF'
## What Changed
- List the changes

## Why
- Reason for the changes

## Impact Analysis
- What breaks if this is wrong?
- What else might be affected?
- Did you check [queue-worker/pm/server/shared]?

## Testing
- How was this tested?
- Edge cases considered?
EOF
)"
```

### 3. Route to Code Reviewer

**Assign PR to**: Opus or Gemini-3-Pro (whoever is available)

**Provide Context**:
```markdown
## Review Context

Full system context for this PR:

### Recent Architecture
[Include last 3-5 commits and what they changed]

### Component Dependencies
[Show what depends on the changed files]

### Full Code Map
[Include tools/csc-service.txt or relevant maps]

### Critical Invariants
[From CLAUDE.md - what must always be true]

### Related Workorders
[Any other concurrent changes]
```

### 4. Code Review Process

Reviewer checks:
- [ ] Does this break any invariants from CLAUDE.md?
- [ ] Are all related components updated?
- [ ] Could this break tests?
- [ ] Does this match project patterns?
- [ ] Are error cases handled?
- [ ] Does this affect security (auth, encryption, access control)?
- [ ] Is storage atomic if needed?
- [ ] Will this cascade to other systems?

### 5. Approval & Merge

- Reviewer approves with `gh pr review -a`
- Author runs tests locally
- Author merges: `gh pr merge --merge`
- **Branch auto-deletes**

## Exceptions

### All Code (Single Review Required)
**Either Opus OR Gemini-3-Pro can approve and merge.**

If either reviewer requests changes → must revise and resubmit.

Critical files (deeper scrutiny, but single review):
- `packages/csc-service/csc_service/infra/queue-worker.py`
- `packages/csc-service/csc_service/infra/pm.py`
- `packages/csc-service/csc_service/main.py`
- Server core protocol handling
- Agent service entry points

### Hotfixes (Only in Emergencies)
If main is broken:
1. Create feature branch from main
2. Create minimal fix
3. Fast-track review (30 min SLA)
4. Merge and cherry-pick if needed

## Review Checklist for Opus/Gemini-3-Pro

When reviewing a PR, load this context:

```bash
# 1. Code maps
cat tools/csc-service.txt  # see what changed

# 2. Recent commits
git log --oneline -10  # understand context

# 3. CLAUDE.md invariants
grep -A 5 "Important Invariants" CLAUDE.md

# 4. Changed files
git show --stat <pr-branch>

# 5. Test impacts
find tests/ -name "*.py" | xargs grep -l <changed-module>

# 6. Dependent code
grep -r "from.*<changed-module>" packages/ --include="*.py"
```

## Enforcement

- **Main branch is protected** - no direct commits
- **All PRs require review** - no auto-merge
- **Status checks must pass** - tests, linting, etc.
- **Context is mandatory** - empty PRs are rejected

## Tools

```bash
# List open PRs
gh pr list

# View PR details
gh pr view <number>

# Review a PR (as Opus/Gemini)
gh pr review <number> --approve
gh pr review <number> --request-changes

# Merge after approval
gh pr merge <number>
```

## Examples

### ✅ Good PR: "Fix queue-worker segfault"
```
## What Changed
- Replace subprocess with async in queue-worker
- Fixes Windows MSYS2 segmentation fault
- Maintains same interface

## Impact Analysis
- Affects: queue-worker only (isolated change)
- Related systems: PM (consumes queue-worker output) - no change needed
- Tests: queue-worker tests must pass, PM tests should pass

## Testing
- Ran locally on Windows MSYS2
- 10+ cycles without segfault
- No performance regression
```

### ❌ Bad PR: "Update some files"
```
## What Changed
[blank]

## Why
[blank]

## Testing
[blank]
```
→ **Rejected**: No context, no impact analysis, no testing

---

## Current Status

**Starting now**: All code changes require PR review + approval before merge.

**Reviewers**: Opus and Gemini-3-Pro (with full system context)

**Goal**: Zero breaking changes that weren't carefully considered.
