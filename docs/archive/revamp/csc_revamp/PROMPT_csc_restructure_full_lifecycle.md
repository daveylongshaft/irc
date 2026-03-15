# CSC Major Restructure: Full Lifecycle Orchestration

**Agent**: Haiku
**Priority**: P0
**Scope**: Services stop → uninstall packages → restructure → reinstall → start → verify
**Duration**: 5–8 hours (mostly waiting for network I/O)
**Output**: /c/csc/ fully restructured, all services running, all data accessible

---

## Overview

This is a complete system lifecycle for the CSC restructure:

1. **Phase 1: Pre-Restructure Shutdown** — Stop all services, capture state
2. **Phase 2: Uninstall All Packages** — Clean pip environment
3. **Phase 3: Execute Restructure** — Run the detailed restructure plan (folder copy, path updates, git setup)
4. **Phase 4: Reinstall Packages** — Fresh install under new paths
5. **Phase 5: Verify Filesystem** — Check all data files and configs exist
6. **Phase 6: Start Services** — Boot all services in new locations
7. **Phase 7: Final Verification** — Test all paths, verify data integrity

---

## PHASE 1: Pre-Restructure Shutdown

### 1.1 Identify Running Services

Before stopping anything, identify what's running. Execute:

```
csc-ctl status
```

This shows all services (server, queue-worker, test-runner, PM, AI clients, bridge, etc.) and their status (running/stopped/disabled).

**Record the output.** You'll need to restart the same services later.

### 1.2 Graceful Service Shutdown

For each running service, run:

```
csc-ctl stop <service>
```

Services to stop (in order):
1. queue-worker
2. test-runner
3. pm
4. server
5. bridge
6. gemini (AI client, if enabled)

After each stop command, verify with `csc-ctl status` that the service shows "stopped". Do not rely on timing—check actual status before proceeding to next stop.

### 1.3 Verify All Stopped

After stopping, run:

```
csc-ctl status
```

All services should show "stopped" or "disabled". If any still show "running", force-kill:

```
csc-ctl kill <service>
```

### 1.4 Capture Current State

Before uninstalling, document what's currently configured:

```
csc-ctl dump > /tmp/csc-config-backup.json
```

This exports all service configurations. Keep this safe — you may need to reference it later.

Also capture the agent queue state:

```
ls -la /c/csc/agents/*/queue/in/ > /tmp/agent-queue-state.txt
ls -la /c/csc/agents/*/queue/work/ >> /tmp/agent-queue-state.txt
ls -la /c/csc/workorders/ready/ >> /tmp/workorder-state.txt
```

---

## PHASE 2: Uninstall All Packages

### 2.1 List Installed CSC Packages

Run:

```
pip list | grep -E "(csc|coding-agent)"
```

This shows all installed csc-* packages. You'll uninstall each one.

**Record the list.** Expected packages:
- csc-shared
- csc-server
- csc-client
- csc-service
- csc-claude
- csc-gemini
- csc-chatgpt
- csc-bridge
- coding-agent

### 2.2 Uninstall All CSC Packages

For each package from the list above:

```
pip uninstall -y csc-shared csc-server csc-client csc-service csc-claude csc-gemini csc-chatgpt csc-bridge coding-agent
```

Or uninstall one at a time for clarity:

```
pip uninstall -y csc-shared
pip uninstall -y csc-server
pip uninstall -y csc-client
... (repeat for all)
```

### 2.3 Verify Clean

After uninstalling, run:

```
pip list | grep csc
```

Should return empty (no csc-* packages). If any remain, uninstall again.

Also verify no import errors:

```
python -c "import csc_shared" 2>&1
```

Should return an error (module not found). If it succeeds, something didn't uninstall.

---

## PHASE 3: Execute Restructure

At this point, all services are stopped and packages are uninstalled. The system is in a clean state.

### 3.1 Read and Follow the Detailed Restructure Plan

**Reference file**: `/c/csc/workorders/ready/PROMPT_csc_major_restructure_all_steps.md`

This is a 2,200-line plain-English plan with 10 sections:

1. Current state review (read-only)
2. GitHub repo operations (backup old, delete old, create new)
3. Folder migration (copy packages, bin, tests, etc. from /c/csc/ to /c/new_csc/irc/ and ops/)
4. Path constants updates (6 files, line-by-line edits)
5. Git and submodule setup
6. Agent status bug fix
7. cagent_run.py architecture (design, no code yet)
8. Testing & verification
9. Final swap (csc → csc_old; new_csc → csc)
10. Post-swap tasks

**Execute sections 1–9 fully.** Do NOT proceed to section 10 (post-swap) yet; we'll do that in Phase 5.

As you work through the plan:
- **Read every file** before editing (confirm line numbers)
- **Test each major section** (folder copy, git init, path update)
- **Use git commands** to verify submodule setup
- **Take screenshots or notes** if anything fails — include in your report

### 3.2 After Section 9 Complete: Verify Structure

When section 9 completes (folder swap), verify:

```
ls -la /c/csc/
# Should show: irc/, ops/, .git/, .gitmodules, csc-service.json, platform.json

ls -la /c/csc/irc/packages/
# Should show all packages: csc-shared/, csc-server/, csc-service/, ...

ls -la /c/csc/ops/wo/
# Should show: ready/, wip/, done/, hold/, archive/, results/, batch/

ls -la /c/csc/ops/agents/
# Should show: haiku/, sonnet/, opus/, claude-api/, gemini/
```

If all directories exist and are not empty, structure is correct. If anything is missing, **STOP and report what's missing.**

---

## PHASE 4: Reinstall Packages

### 4.1 Navigate to New Location

```
cd /c/csc/irc/
```

All packages are now under irc/packages/.

### 4.2 Reinstall in Dependency Order

Install packages in this order (dependencies first):

```
pip install -e /c/csc/irc/packages/csc-shared
pip install -e /c/csc/irc/packages/csc-server
pip install -e /c/csc/irc/packages/csc-service
pip install -e /c/csc/irc/packages/csc-claude
pip install -e /c/csc/irc/packages/csc-gemini
pip install -e /c/csc/irc/packages/csc-chatgpt
pip install -e /c/csc/irc/packages/csc-bridge
pip install -e /c/csc/irc/packages/coding-agent
```

**Wait for each to complete.** If any fails, stop and report the error.

### 4.3 Verify Imports

Test that imports work:

```
python -c "from csc_shared.irc import IRCMessage; print('csc-shared OK')"
python -c "from csc_server.server import Server; print('csc-server OK')"
python -c "from csc_service.infra.queue_worker import QueueWorker; print('csc-service OK')"
```

All three should print "OK". If any fails, the package didn't install correctly.

### 4.4 Refresh Project Maps

```
cd /c/csc/
refresh-maps
```

This updates tools/, tree.txt, p-files.list for the new folder structure. **Wait for it to complete.**

---

## PHASE 5: Verify Filesystem & Data Files

### 5.1 Check Config Files Exist

```
ls -la /c/csc/csc-service.json
ls -la /c/csc/platform.json
```

Both should exist and be readable. If missing, the restructure failed.

### 5.2 Verify Path Constants in Code

For each file listed below, **read the specified lines and confirm the paths are correct**:

**File: /c/csc/irc/packages/csc-service/csc_service/shared/services/agent_service.py**
- Line 33: Should say `PROJECT_ROOT / "ops" / "wo"` (not "workorders")
- Line 662: Should say `PROJECT_ROOT / "ops" / "agents"`
- Confirm PROJECT_ROOT resolves to /c/csc/ (umbrella root)

**File: /c/csc/irc/packages/csc-service/csc_service/infra/queue_worker.py**
- Lines 54–58: Should reference "ops/wo" and "ops/agents" (not old paths)
- Verify no references to `/c/csc/workorders` (old path)

**File: /c/csc/irc/bin/agent**
- Line 46: Path resolution should go up 3 levels (irc/bin → irc → umbrella root)

**File: /c/csc/irc/CLAUDE.md**
- Search for "workorders/": All examples should say "ops/wo/"
- Search for "/c/csc/": All examples should reference correct paths
- Spot-check 5–10 examples to confirm

### 5.3 Check Data Files Reachable

Test that the system can find data files:

```
python -c "from pathlib import Path; print(Path('/c/csc/csc-service.json').exists())"
# Should print: True

python -c "from pathlib import Path; print(Path('/c/csc/ops/wo/ready/').exists())"
# Should print: True
```

Both should print True. If either prints False, data files are in wrong location.

### 5.4 Verify Git Structure

```
cd /c/csc/
git submodule status
```

Should show both submodules linked:
```
+<hash> irc (HEAD detached at <hash>)
+<hash> ops (HEAD detached at <hash>)
```

If you see errors about submodules not found, the restructure failed.

### 5.5 Verify Workorders & Agents Accessible

```
ls /c/csc/ops/wo/ready/ | wc -l
# Should show a count > 0 (number of ready workorders)

ls /c/csc/ops/agents/haiku/queue/in/ | wc -l
# Should show a count >= 0 (may be empty)
```

If you get "directory not found" errors, the ops/ folder structure is wrong.

---

## PHASE 6: Start Services

### 6.1 Start Core Server First

```
csc-ctl start server
```

Verify immediately (do not wait, check status):

```
csc-ctl status server
```

Should show "running" or "enabled". If it shows "failed", check the logs:

```
csc-ctl show server
```

Read the error and report what went wrong.

### 6.2 Start Infrastructure Services

In this order, verifying after each:

```
csc-ctl start queue-worker
csc-ctl status queue-worker  # Verify started, then continue
csc-ctl start test-runner
csc-ctl status test-runner   # Verify started, then continue
csc-ctl start pm
csc-ctl status pm            # Verify started, then continue
```

### 6.3 Start AI Clients

In this order (if enabled in csc-service.json):

```
csc-ctl start gemini
csc-ctl start claude-api
```

Verify all clients are ready:

```
csc-ctl status
```

All enabled clients should show under "Clients:" section. If any show "failed" or "error", check logs before proceeding.

Should show all enabled clients under "Clients:".

### 6.4 Start Optional Services

If they were running before:

```
csc-ctl start bridge    # Optional IRC bridge
```

### 6.5 Final Service Status

```
csc-ctl status
```

Should show all services running. Record this output.

---

## PHASE 7: Final Verification

### 7.1 Test Server Connectivity

The csc-server should be listening on UDP port 9525. Test:

```
python -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.sendto(b'test', ('localhost', 9525)); print('Server OK')"
```

Should print "Server OK". If it fails, server isn't listening.

### 7.2 Test Queue Worker Finds Tasks

Queue-worker should be able to find workorders. Check:

```
ls /c/csc/ops/wo/ready/ | head -3
```

Should list some workorders (at least the restructure plan itself). If empty or error, queue-worker can't find ops/wo/.

### 7.3 Test Agent Status

Agent service should now use correct paths:

```
python -c "from csc_service.shared.services.agent_service import AgentService; a = AgentService(Path('/c/csc')); print(a.status())"
```

Should print agent status (running, idle, etc.) without errors. If it fails, paths weren't updated correctly.

### 7.4 Test File Access

The system should be able to read/write to new paths:

```
touch /c/csc/ops/wo/ready/test.txt && rm /c/csc/ops/wo/ready/test.txt && echo "File access OK"
```

Should print "File access OK" without permission errors.

### 7.5 Spot-Check Data Integrity

Check that the restructure didn't lose data:

```
# Count workorders before and after
ls /c/csc_old/workorders/ | wc -l    # Old location
ls /c/csc/ops/wo/ | wc -l            # New location
```

Both counts should be approximately equal (may differ if one includes hidden files). If the new count is much lower, data was lost.

Similarly for agents:

```
ls /c/csc_old/agents/ | wc -l        # Old location
ls /c/csc/ops/agents/ | wc -l        # New location
```

Again, counts should be similar.

### 7.6 Import Test

Verify that Python imports work correctly from new paths:

```
cd /c/csc/irc/
python -c "from csc_shared.irc import IRCMessage, build_irc_message; m = build_irc_message('PRIVMSG', ['#channel', 'hello']); print('Import and build OK')"
```

Should print "Import and build OK". If it fails, package structure is broken.

---

## Completion Checklist

- [ ] All services stopped and uninstalled (Phase 1–2)
- [ ] Restructure completed, files in /c/new_csc/ → /c/csc/ (Phase 3)
- [ ] Packages reinstalled under new paths (Phase 4)
- [ ] Path constants updated in all 6 files (Phase 5.2)
- [ ] Config files (csc-service.json, platform.json) reachable (Phase 5.3)
- [ ] Git submodules linked correctly (Phase 5.4)
- [ ] Workorders and agents accessible at new paths (Phase 5.5)
- [ ] All services started and running (Phase 6)
- [ ] Server listening on UDP 9525 (Phase 7.1)
- [ ] Queue-worker can find tasks (Phase 7.2)
- [ ] Agent status works without errors (Phase 7.3)
- [ ] File access works at new paths (Phase 7.4)
- [ ] Data counts match (no data loss) (Phase 7.5)
- [ ] Python imports work (Phase 7.6)

If all checkmarks pass, the restructure is complete and verified.

---

## Failure Recovery

If anything fails at any phase:

1. **Stop immediately** — don't continue to next phase
2. **Capture the error** — include full error message and context
3. **Report findings** — what failed, where, what did you try
4. **Do not attempt fixes** — wait for guidance

The old repo is backed up at /c/csc_old/, so no data is lost. Recovery is possible.

---

## Notes

- **Patient waiting**: Network operations and pip installs may take 10–15 minutes. Don't interrupt.
- **Read before edit**: Every file edit should be preceded by reading the file.
- **Test after each phase**: Verify what you just did before moving on.
- **Record outputs**: Screenshot or log important outputs (status, errors, file listings).
- **Ask if stuck**: If any step is unclear, ask before proceeding.

Good luck! This is a major lifecycle event. Take it slow and verify everything.

