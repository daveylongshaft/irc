# CSC Restructure - Session Context & Current Status

**Date**: 2026-03-05
**Status**: ✅ RESTRUCTURE COMPLETE - Ready for GitHub push

## Restructure Complete

### New Directory Structure (/c/csc_new/)
```
/c/csc_new/
├── irc/                          (all code)
│   ├── packages/                 (csc-service, csc-docker, etc.)
│   ├── bin/                      (batch_executor.py, batch_dir.py, agent scripts, etc.)
│   ├── tests/                    (test suite)
│   └── [other code dirs]
├── ops/                          (operations & workorders)
│   ├── wo/                       (workorder pool)
│   │   ├── archive/              (completed & archived tasks)
│   │   ├── batch/                (batches of related tasks)
│   │   ├── done/                 (finished workorders)
│   │   ├── gemini-api/           (Gemini-specific workorders)
│   │   ├── hold/                 (on-hold tasks)
│   │   ├── ready/                (available to agents)
│   │   ├── results/              (batch results)
│   │   ├── review/               (awaiting review)
│   │   ├── run_next/             (queued to run)
│   │   ├── wip/                  (work-in-progress)
│   │   └── README.md
│   └── agents/                   (agent queue directories)
│       ├── haiku/queue/          (in/, work/, out/)
│       ├── sonnet/queue/         (in/, work/, out/)
│       ├── opus/queue/           (in/, work/, out/)
│       ├── gemini/queue/         (in/, work/, out/)
│       └── [other agents]/queue/
├── docs/                         (documentation & tools)
│   ├── tools/                    (code maps, INDEX.txt, tree.txt, etc.)
│   ├── *.md files                (CLAUDE.md, README.md, etc.)
│   └── [other docs]
├── logs/                         (runtime logs)
├── tmp/                          (temporary files)
├── csc-service.json              (service configuration)
├── platform.json                 (platform detection config)
└── requires.txt                  (Python requirements)
```

## GitHub Repository Structure (Ready to Push)

### Repositories
| Repo | URL | Purpose | Status |
|------|-----|---------|--------|
| **csc** (Main) | https://github.com/daveylongshaft/csc | Umbrella repo, coordination | ✅ READY TO PUSH |
| **csc-irc** | https://github.com/daveylongshaft/csc-irc | Code repo (future extraction) | Created (empty) |
| **csc-ops** | https://github.com/daveylongshaft/csc-ops | Ops repo (future extraction) | Created (empty) |

### Main Repository Structure (Ready on /c/csc_new/)
```
https://github.com/daveylongshaft/csc/
├── irc/                          (all executable code & tests)
│   ├── packages/
│   ├── bin/                      (includes migrated scripts from old csc/bin/)
│   ├── tests/
│   └── [other directories]
├── ops/                          (workorders & agent queues)
│   ├── wo/                       (all workorder directories with content)
│   └── agents/                   (all agent queue directories with content)
├── docs/                         (documentation & code maps)
│   ├── tools/                    (INDEX.txt, per-package maps, tree.txt, etc.)
│   └── *.md files
├── logs/                         (empty, ready for runtime logs)
├── tmp/                          (empty, ready for temp files)
├── csc-service.json
├── platform.json
├── requires.txt
└── .git/
```

### Clone Instructions for External Teams
```bash
# Clone main repo (private repo)
git clone --recursive https://github.com/daveylongshaft/csc.git
cd csc
git checkout main  # default branch

# View specific directories
cd irc/packages/   # For TASK A (path updates)
cd ops/            # For TASK B (architecture)
```

### GitHub Authentication (for Private Repo Access)

**If prompted for authentication:**

```bash
# Use GitHub PAT (Personal Access Token) when prompted for password
Username: daveylongshaft
Password: (use the token below)
```

**GitHub Personal Access Token:**
```
REDACTED
```

**Or configure git to use token:**
```bash
git config --global credential.helper store
# When prompted, use token as password above
# Credentials will be cached in ~/.git-credentials

# Or set directly:
git config user.name "daveylongshaft"
git config credential.https://github.com.username daveylongshaft
git config credential.https://github.com.password REDACTED
```

**Verify access:**
```bash
git remote -v  # Should show https://github.com/daveylongshaft/csc.git
git fetch      # Should succeed (requires auth)
```

### Initial Commit Details
- **Repository**: daveylongshaft/csc
- **Branch**: main (default)
- **Commit**: "Initial restructure: CSC migration from /c/csc to /c/csc_new"
- **Status**: ✅ Verified on GitHub (structure visible via API)

---


### 2. Fundamental Architecture Change Required

**Approach:**
- Workorders use dirs `workorders/ready/`, `workorders/wip/`, `workorders/done/` for basic queue/pooling
- Agents moving files between directories
- Queue-worker searching for workorders
- Only start workorders that are in ready.
- others dirs used for batches of related workorders to be run sequentialy 

- **Agents ONLY read and append** - wo file movement is automated
- **No searching** - agents know exact path
- **State tracking** - needs to be defined (metadata alongside file? status database?)

**This requires architectural redesign before continuing.**


### Lessons Learned from mistakes:
- Verify prerequisites before executing phases (don't reinstall to uninstall)
- Use batch execution only for well-defined, autonomous tasks
- Use direct bash for infrastructure work (faster, cheaper, verifiable)
- Always verify paths BEFORE installing packages

---

