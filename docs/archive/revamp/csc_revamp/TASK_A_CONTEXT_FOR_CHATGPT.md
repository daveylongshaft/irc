# TASK A: Path Resolution - Context for ChatGPT

## Quick Start

**Repository**: https://github.com/daveylongshaft/csc.git (private)

**Clone**:
```bash
git clone --recursive https://github.com/daveylongshaft/csc.git
cd csc
```

**GitHub Authentication** (if prompted):
```
Username: daveylongshaft
Password: REDACTED
```

---

## Your Task

**See**: `TASK_A_PATH_RESOLUTION_AUDIT_AND_REPLACEMENT.md`

**In Summary**:
1. Find all hardcoded paths in `irc/packages/` (e.g., `/c/csc/workorders`, `/c/csc/agents`)
2. Replace with Platform-resolved paths using `Platform().PROJECT_ROOT`
3. Use `Path()` and `/` operator, not string concatenation
4. Update CLAUDE.md path examples
5. Verify no hardcoded paths remain

**Key Files to Check**:
- `irc/packages/csc-service/csc_service/shared/services/agent_service.py`
- `irc/packages/csc-service/csc_service/infra/queue_worker.py`
- `irc/packages/csc-service/csc_service/shared/common.py`
- `irc/bin/agent` script
- `irc/CLAUDE.md` (examples)

**When Done**:
- Commit changes to main branch
- Push to repository
- Include verification report in commit message
