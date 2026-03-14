# CSC Restructure Phase 6: Start Services

**Agent**: Haiku
**Priority**: P0
**Duration**: 10 minutes
**Goal**: Boot all CSC services in their new locations

---

## PHASE 6: Start Services

Filesystem is verified and all packages are installed. Now start all services to bring the system online.

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

Read the error and report what went wrong. Do not proceed to next step if server failed.

### 6.2 Start Infrastructure Services

In this order, verifying after each:

```
csc-ctl start queue-worker
csc-ctl status queue-worker
```

Verify it shows "running", then continue:

```
csc-ctl start test-runner
csc-ctl status test-runner
```

Verify it shows "running", then continue:

```
csc-ctl start pm
csc-ctl status pm
```

Verify it shows "running". If any of these fail, report which service and what error.

### 6.3 Start AI Clients

In this order (if enabled in csc-service.json):

```
csc-ctl start gemini
csc-ctl status gemini
```

Then:

```
csc-ctl start claude-api
csc-ctl status claude-api
```

### 6.4 Start Optional Services

If they were running before (check /tmp/csc-config-backup.json from Phase 1):

```
csc-ctl start bridge
csc-ctl status bridge
```

### 6.5 Final Service Status

Run:

```
csc-ctl status
```

Record the complete output. All enabled services should show as "running". If any show "failed" or "error", report which service and what the error is.

### 6.6 Completion Report

When complete, provide:
- csc-ctl status server output (is it running?)
- csc-ctl status queue-worker output (is it running?)
- csc-ctl status test-runner output (is it running?)
- csc-ctl status pm output (is it running?)
- All other enabled services running (Y/N)
- Full csc-ctl status output (paste complete output)
