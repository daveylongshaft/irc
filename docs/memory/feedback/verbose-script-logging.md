---
slug: verbose-script-logging
name: Verbose script logging
description: Long-running scripts must emit timestamped progress to stdout AND a log file.
type: feedback
status: reference
tags: [feedback, scripting, logging]
related: []
updated: 2026-04-29T00:00:00Z
---

When writing scripts that run more than a few seconds, emit verbose timestamped progress to both stdout and a log file.

**Why:** Silent scripts are debugging hell -- Davey cannot tell if a script is stalled, looping, or errored.

**How to apply:**
- Start every step with a timestamped banner: `Write-Output "[$(Get-Date -Format 'HH:mm:ss.fff')] step N: doing X"`
- Log to file: `Start-Transcript -Path C:\Users\davey\setup_logs\<name>_$ts.log` (PowerShell) or `exec > >(tee -a $LOG) 2>&1` (bash)
- Inside loops, log iteration count + key state every N iterations.
- Wrap risky calls so failures print a clear error + the failing command.
- Print elapsed time at the end and after each major phase.
- Emit [OK] / [FAIL] markers per step.
- For PowerShell: set `$VerbosePreference = 'Continue'`.

Applies to: setup scripts, install/upgrade scripts, anything backgrounded via sudo, anything that could run > 5 seconds without output.
