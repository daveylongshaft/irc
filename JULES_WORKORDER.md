---
model: claude-opus-4-6
max_rounds: 25
requires: [git, python3.10]
---

# Task: Eliminate csc-service Dependency — Complete Migration to Modular Packages

## Problem

**csc-service was dismantled in commit bd2ba070a (Mar 23)** into 14 standalone modular packages following strict one-class-per-file architecture.

**But it still exists.** The "dismantle" was incomplete:
- 233 imports from `csc_service` remain across the codebase
- csc-server-core still imports from deprecated csc-service for core handlers
- Dead queue federation code was added back to csc-service in commit 670d1a2b7

**This is architectural debt that blocks progress.**

## Dependencies to Migrate (233 imports)

Key imports that must be moved to proper packages:
- `from csc_service.server.server_message_handler import MessageHandler` → find canonical location
- `from csc_service.server.server_file_handler import FileHandler` → find canonical location
- `from csc_service.shared.channel import ChannelManager` → find canonical location
- `from csc_service.shared.chat_buffer import ChatBuffer` → find canonical location
- `from csc_service.shared.irc import SERVER_NAME` → find canonical location
- `from csc_service.shared.crypto import is_encrypted, decrypt, encrypt` → find canonical location
- (228 more scattered across packages/)

## Tasks

### 1. Map Imports (Reconnaissance)
```bash
# Find all imports from csc_service
grep -r "from csc_service" --include="*.py" packages/ | tee /tmp/csc_service_imports.txt
grep -r "import csc_service" --include="*.py" packages/ >> /tmp/csc_service_imports.txt

# Count by importer
grep "from csc_service" /tmp/csc_service_imports.txt | cut -d: -f1 | sort | uniq -c | sort -rn
```

Output tells us:
- Which packages import from csc_service
- What they need (MessageHandler, FileHandler, ChannelManager, etc.)
- Where those classes actually live NOW (14 modular packages)

### 2. Verify Canonical Locations

For each heavily-imported class (MessageHandler, FileHandler, ChannelManager, ChatBuffer, etc.):
- [ ] Find where it's currently defined (should be in one of the 14 packages)
- [ ] Verify it's properly exported from that package's `__init__.py`
- [ ] Test import: `python -c "from <new_package> import ClassName"`

**If a class can't be found in the 14 packages**, it's a zombie in csc-service — create it in the proper package or extract it.

### 3. Rewrite Imports (Bulk Migration)

For each file with csc_service imports:
1. Replace old imports with new ones
2. Test the file imports without errors
3. Run any local tests if they exist

**Use sed or Python script for bulk replacement** (don't do this manually).

Example:
```python
# OLD
from csc_service.server.server_message_handler import MessageHandler

# NEW (find canonical location from step 2)
from csc_server_core.server_message_handler import MessageHandler
# OR
from csc_message_handlers import MessageHandler
# (Whatever the actual new location is)
```

### 4. Delete csc-service Package
```bash
# Once all imports migrated:
rm -rf packages/csc-service/
git add -A
git commit -m "refactor: Remove deprecated csc-service package after import migration"
```

### 5. Verification
```bash
# Confirm no remaining imports
grep -r "from csc_service\|import csc_service" --include="*.py" packages/
# Should return: (no matches)

# Run tests to verify nothing broke
pytest tests/ -v
```

## Expected Outcome

- [ ] All 233 imports rewritten to point to proper modular packages
- [ ] `packages/csc-service/` directory deleted
- [ ] All tests pass
- [ ] No dead code left behind
- [ ] Clear git history showing what moved where

## Blockers

- **What are the 14 packages?** Check CLAUDE.md / docs
- **Where do MessageHandler, FileHandler, etc. actually live NOW?** Find them in the 14 packages
- **Are all classes properly exported from their packages' `__init__.py`?** Verify before rewriting imports

Answer these first, then bulk-rewrite imports.

## Notes

- This is NOT a refactor — just connect existing code to its real home
- The 14 packages already exist; csc-service is the zombie
- Use Python scripts for bulk import rewriting (faster, fewer typos)
- Test aggressively: old imports break silently if missed

## Files to Modify

(Will be discovered in step 1, but expect ~50-100 Python files)

## Acceptance Criteria

- [ ] csc-service directory deleted
- [ ] 0 remaining `from csc_service` imports in codebase
- [ ] All tests pass
- [ ] No import errors on fresh checkout + pip install
- [ ] Clear commit showing what moved where
