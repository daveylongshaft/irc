# CSC Restructure Phase 7: Final Verification

**Agent**: Haiku
**Priority**: P0
**Duration**: 10 minutes
**Goal**: Run final verification tests to confirm the restructure is complete and correct

---

## PHASE 7: Final Verification

All services are started. Run final verification tests to ensure the restructure is complete and the system works correctly.

### 7.1 Test Server Connectivity

The csc-server should be listening on UDP port 9525. Test:

```
python -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.sendto(b'test', ('localhost', 9525)); print('Server OK')"
```

Should print "Server OK". If it fails, server isn't listening. Report the error.

### 7.2 Test Queue Worker Finds Tasks

Queue-worker should be able to find workorders. Check:

```
ls /c/csc/ops/wo/ready/ | head -3
```

Should list some workorders (at least the restructure plan itself). If empty or error, queue-worker can't find ops/wo/. Report what you see.

### 7.3 Test Agent Status

Agent service should now use correct paths:

```
python -c "from csc_service.shared.services.agent_service import AgentService; from pathlib import Path; a = AgentService(Path('/c/csc')); print(a.status())"
```

Should print agent status (running, idle, etc.) without errors. If it fails, paths weren't updated correctly. Report the error.

### 7.4 Test File Access

The system should be able to read/write to new paths:

```
touch /c/csc/ops/wo/ready/test.txt && rm /c/csc/ops/wo/ready/test.txt && echo "File access OK"
```

Should print "File access OK" without permission errors. Report the result.

### 7.5 Spot-Check Data Integrity

Check that the restructure didn't lose data:

```
ls /c/csc_old/workorders/ | wc -l
```

Count the old location.

```
ls /c/csc/ops/wo/ | wc -l
```

Count the new location. Both counts should be approximately equal (may differ if one includes hidden files). If the new count is much lower, data was lost. Report both counts.

Similarly for agents:

```
ls /c/csc_old/agents/ | wc -l
```

```
ls /c/csc/ops/agents/ | wc -l
```

Again, counts should be similar. Report both counts.

### 7.6 Import Test

Verify that Python imports work correctly from new paths:

```
cd /c/csc/irc/
python -c "from csc_shared.irc import IRCMessage, build_irc_message; m = build_irc_message('PRIVMSG', ['#channel', 'hello']); print('Import and build OK')"
```

Should print "Import and build OK". If it fails, package structure is broken. Report the error.

### 7.7 Completion Checklist

Report the status of each verification:

- [ ] All services stopped and uninstalled (Phase 1–2) (Y/N)
- [ ] Restructure completed, files in /c/new_csc/ → /c/csc/ (Phase 3) (Y/N)
- [ ] Packages reinstalled under new paths (Phase 4) (Y/N)
- [ ] Path constants updated in all 6 files (Phase 5.2) (Y/N)
- [ ] Config files (csc-service.json, platform.json) reachable (Phase 5.3) (Y/N)
- [ ] Git submodules linked correctly (Phase 5.4) (Y/N)
- [ ] Workorders and agents accessible at new paths (Phase 5.5) (Y/N)
- [ ] All services started and running (Phase 6) (Y/N)
- [ ] Server listening on UDP 9525 (Phase 7.1) (Y/N)
- [ ] Queue-worker can find tasks (Phase 7.2) (Y/N)
- [ ] Agent status works without errors (Phase 7.3) (Y/N)
- [ ] File access works at new paths (Phase 7.4) (Y/N)
- [ ] Data counts match (no data loss) (Phase 7.5) (Y/N)
- [ ] Python imports work (Phase 7.6) (Y/N)

**If all checkmarks pass, the restructure is complete and verified.**

**If any fails, report which check failed and the error details. Do not ignore failures.**

### 7.8 Final Summary

Summarize the overall result:
- COMPLETE: All verification checks passed, system is fully restructured and operational
- PARTIAL: Some checks passed, some failed - report which ones
- FAILED: Critical checks failed - system not fully operational

Provide details of any failures or issues encountered.
