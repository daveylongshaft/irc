# CSC Restructure Phase 4: Reinstall Packages

**Agent**: Haiku
**Priority**: P0
**Duration**: 15-20 minutes
**Goal**: Reinstall all packages under new paths and verify imports work

---

## PHASE 4: Reinstall Packages

The restructure is complete and the new folder structure is in place. Now reinstall all packages in their new locations.

### 4.1 Navigate to New Location

```
cd /c/csc/irc/
```

All packages are now under irc/packages/.

### 4.2 Reinstall in Dependency Order

Install packages in this order (dependencies first). Wait for each to complete fully before starting the next:

```
pip install -e /c/csc/irc/packages/csc-shared
```

**Wait for completion, verify success (exit code 0), then continue:**

```
pip install -e /c/csc/irc/packages/csc-server
pip install -e /c/csc/irc/packages/csc-service
pip install -e /c/csc/irc/packages/csc-claude
pip install -e /c/csc/irc/packages/csc-gemini
pip install -e /c/csc/irc/packages/csc-chatgpt
pip install -e /c/csc/irc/packages/csc-bridge
pip install -e /c/csc/irc/packages/coding-agent
```

**If any installation fails, STOP immediately and report the error message and which package failed.**

### 4.3 Verify Imports

Test that imports work:

```
python -c "from csc_shared.irc import IRCMessage; print('csc-shared OK')"
python -c "from csc_server.server import Server; print('csc-server OK')"
python -c "from csc_service.infra.queue_worker import QueueWorker; print('csc-service OK')"
```

All three should print "OK". If any fails, the package didn't install correctly. Report which package failed and the error.

### 4.4 Refresh Project Maps

```
cd /c/csc/
refresh-maps
```

This updates tools/, tree.txt, p-files.list for the new folder structure. **Wait for it to complete fully.**

### 4.5 Completion Report

When complete, report:
- csc-shared installed successfully (Y/N)
- csc-server installed successfully (Y/N)
- csc-service installed successfully (Y/N)
- All other packages installed (Y/N)
- All import tests passed (Y/N)
- refresh-maps completed (Y/N)
