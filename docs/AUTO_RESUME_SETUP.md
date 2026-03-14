# Claude CLI Auto-Resume Setup

**Purpose**: Claude CLI automatically resumes IRC proof test work on system startup (before login)

**Status**: Ready to deploy

---

## Quick Setup

### Step 1: Run Setup Script (As Administrator)
```powershell
powershell -ExecutionPolicy Bypass -File C:\csc\bin\setup-auto-resume-startup.ps1
```

This creates a Windows Task Scheduler job that:
- ✅ Runs on system startup
- ✅ Runs BEFORE user login
- ✅ Runs with SYSTEM privileges
- ✅ Executes in background
- ✅ Logs output to `C:\csc\logs\claude-auto-resume.log`

### Step 2: Reboot

On next reboot, Claude CLI will automatically:
1. Start in the background before you login
2. Read workorder: `/c/csc/ops/wo/ready/CLAUDE_AUTO_RESUME_PROOF_TEST.md`
3. Run with: `--dangerously-skip-permissions --model haiku`
4. Resume the proof test work autonomously

---

## What Gets Executed

The workorder (`CLAUDE_AUTO_RESUME_PROOF_TEST.md`) contains:
1. Kill old server process
2. Start fresh server with diagnostic logging
3. Run proof test
4. Analyze logs
5. Apply fixes
6. Iterate until test passes

All in the background while you log in.

---

## Monitoring

### Check if task is installed
```powershell
Get-ScheduledTask -TaskName "Claude-Auto-Resume-ProofTest" | Format-List
```

### View task logs
```bash
tail -f C:\csc\logs\claude-auto-resume.log
```

### Manually trigger the task
```powershell
Start-ScheduledTask -TaskName "Claude-Auto-Resume-ProofTest"
```

### Disable auto-resume
```powershell
Disable-ScheduledTask -TaskName "Claude-Auto-Resume-ProofTest"
```

### Re-enable auto-resume
```powershell
Enable-ScheduledTask -TaskName "Claude-Auto-Resume-ProofTest"
```

### Remove task completely
```powershell
Unregister-ScheduledTask -TaskName "Claude-Auto-Resume-ProofTest" -Confirm:$false
```

---

## Files Involved

- **Workorder** (what Claude will do): `/c/csc/ops/wo/ready/CLAUDE_AUTO_RESUME_PROOF_TEST.md`
- **Startup Script** (calls Claude): `/c/csc/bin/claude-auto-resume.bat`
- **Setup Script** (creates Task Scheduler): `/c/csc/bin/setup-auto-resume-startup.ps1`
- **Logs**: `/c/csc/logs/claude-auto-resume.log`

---

## How It Works

1. **On reboot**, Windows Task Scheduler runs `claude-auto-resume.bat` before login
2. **The batch file** executes: `claude cli run --dangerously-skip-permissions --model haiku -p "@/c/csc/ops/wo/ready/CLAUDE_AUTO_RESUME_PROOF_TEST.md"`
3. **Claude CLI** reads the workorder and executes all steps automatically
4. **Output** goes to the log file
5. **Work continues** until proof test passes or blocker is hit

---

## Expected Behavior After Reboot

- [ ] You login and see nothing unusual (work happening in background)
- [ ] Check `C:\csc\logs\claude-auto-resume.log` to see progress
- [ ] Claude CLI is working on proof test automatically
- [ ] When complete, workorder moved to `done/` folder
- [ ] Next task ready in `ready/` folder

---

## To Deploy Right Now

If you want auto-resume to start on NEXT reboot:

```powershell
# Open PowerShell as Administrator and run:
powershell -ExecutionPolicy Bypass -File C:\csc\bin\setup-auto-resume-startup.ps1
```

Then reboot. Claude will resume automatically.

---

## Notes

- Auto-resume uses `haiku` model to minimize cost
- Runs with `--dangerously-skip-permissions` as requested
- Workorder path: `@/c/csc/ops/wo/ready/CLAUDE_AUTO_RESUME_PROOF_TEST.md`
- Runs as SYSTEM user (before login)
- Safe to disable if you want manual control
