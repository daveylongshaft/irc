# CSC Restructure Phase 2: Uninstall All Packages

**Agent**: Haiku
**Priority**: P0
**Duration**: 5 minutes
**Goal**: Clean pip environment by uninstalling all CSC packages

---

## PHASE 2: Uninstall All Packages

With all services stopped, the system is in a stable state for package uninstallation. This phase removes all CSC-related pip packages so they can be reinstalled under the new paths.

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

Uninstall all in one command:

```
pip uninstall -y csc-shared csc-server csc-client csc-service csc-claude csc-gemini csc-chatgpt csc-bridge coding-agent
```

Or uninstall one at a time for clarity:

```
pip uninstall -y csc-shared
pip uninstall -y csc-server
pip uninstall -y csc-client
pip uninstall -y csc-service
pip uninstall -y csc-claude
pip uninstall -y csc-gemini
pip uninstall -y csc-chatgpt
pip uninstall -y csc-bridge
pip uninstall -y coding-agent
```

**Wait for each to complete fully.**

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

**When complete**, report:
- All CSC packages successfully uninstalled (Y/N)
- pip list shows no remaining csc-* packages (Y/N)
- Import test confirms csc_shared not available (Y/N)
