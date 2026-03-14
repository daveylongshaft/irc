# CSC Restructure Phase 1: Pre-Restructure Shutdown

**Agent**: Haiku
**Priority**: P0
**Duration**: 10 minutes
**Goal**: Stop all services gracefully and capture system state

---

## PHASE 1: Pre-Restructure Shutdown

Before any restructuring begins, all services must be stopped gracefully and the current system state must be captured for recovery if needed.

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

**When complete**, report:
- All services successfully stopped (Y/N)
- Config backup created at /tmp/csc-config-backup.json (Y/N)
- Queue state captured in /tmp/agent-queue-state.txt (Y/N)
- Workorder state captured in /tmp/workorder-state.txt (Y/N)
