# SUBPROCESS SPAWNING - CRITICAL RULES

## NEVER EVER USE THESE FLAGS

```python
subprocess.CREATE_NEW_PROCESS_GROUP      # BANNED
subprocess.DETACHED_PROCESS              # BANNED
subprocess.CREATE_NEW_WINDOW             # BANNED
subprocess.CREATE_NEW_CONSOLE            # BANNED
```

**These spawn visible terminal windows that cannot be closed and fill the desktop with uncontrollable windows.**

This caused the entire system to become unusable on 2026-03-12.

---

## CORRECT SUBPROCESS USAGE

### Background Process (Windows)
```python
# WRONG (spawns window):
subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)

# CORRECT (silent background):
subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW, stdout=log_file, stderr=log_file)
```

### Capture Output (all platforms)
```python
# CORRECT:
result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
```

### Silent Subprocess (no output visible)
```python
# CORRECT:
subprocess.run(cmd, capture_output=True, text=True,
               creationflags=subprocess.CREATE_NO_WINDOW)
```

---

## FILES THAT VIOLATED THIS RULE

1. `/c/csc/irc/packages/csc-service/csc_service/cli/commands/service_cmd.py` (line 99)
   - **STATUS**: FIX REQUIRED
   - Change to `CREATE_NO_WINDOW`

2. Any other file using the banned flags - SEARCH AND FIX IMMEDIATELY

---

## VERIFICATION CHECKLIST

Before committing any code:
```bash
# Search for banned flags:
grep -r "CREATE_NEW_PROCESS_GROUP" /c/csc/irc/packages/
grep -r "DETACHED_PROCESS" /c/csc/irc/packages/
grep -r "CREATE_NEW_WINDOW" /c/csc/irc/packages/
grep -r "CREATE_NEW_CONSOLE" /c/csc/irc/packages/
```

If any matches found → FIX BEFORE COMMITTING.

---

## WHY THIS MATTERS

The banned flags create processes in "detached" mode that spawn new visible terminal windows.
- Windows cannot be closed programmatically
- They pile up and make the desktop unusable
- There is no legitimate use case for them in CSC
- System becomes unresponsive and requires manual cleanup

**One mistake here breaks the entire system.**

---

## SERVICE RESTART RULE

**DO NOT START csc-service via `csc-ctl restart`**
**until all window-spawning subprocess calls are fixed.**

Check: `WINDOW_SPAWNING_FIX_REQUIRED.txt` before restarting.
