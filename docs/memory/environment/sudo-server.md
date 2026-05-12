---
slug: sudo-server
name: Sudo Server (Windows elevated execution)
description: TCP server on 127.0.0.1:7329 running as SYSTEM at boot; accepts JSON commands and runs them elevated.
type: environment
status: reference
tags: [environment, windows, elevated, sudo]
related: [server-topology]
updated: 2026-05-09T00:00:00Z
---

sudo_server.py listens on 127.0.0.1:7329. Request: `{"cmd": "...", "cwd": "...", "shell": true, "timeout": 120}` + newline. Response: `{"stdout": "...", "stderr": "...", "exitcode": 0}`. Max message 1MB. Logs every call to C:\csc\bin\sudo.log.

Runs as SYSTEM at boot via scheduled task named "SudoServer" (AtStartup, SYSTEM principal, RunLevel Highest, Hidden, no timeout, restart 3x/1m). Action: `C:\Windows\py.exe C:\csc\bin\sudo_server.py`.

Two ways to call from Claude Code:

1. Python client (preferred):
   ```python
   import sys; sys.path.insert(0, r"C:\claude")
   from sudo_call import run, sudo
   sudo("net session", timeout=15)
   run("sc query OpenVPNService", "label")
   ```
   Helper at C:\claude\sudo_call.py.

2. CLI client: `python C:\csc\bin\sudo.py "<command>"`. Env vars: SUDO_PORT, SUDO_CWD, SUDO_TIMEOUT.

Caveat: SYSTEM has no user profile. Commands depending on %USERPROFILE%, davey's PATH, or per-user env behave differently. Pass full paths and explicit working directories.

Manual restart: run C:\claude\swap_sudo.ps1 as admin, or kill SYSTEM py.exe and run `Start-ScheduledTask -TaskName SudoServer` as admin.

Startup companion: C:\Users\davey\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\View Sudo Log.lnk opens sudo.log at login. Remove together with the scheduled task if ever uninstalled.
