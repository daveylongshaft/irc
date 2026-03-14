# CSC Background Service Setup

Unified background service for CSC that runs continuously without popup windows.

- **Polls filesystem**: Once per minute (not every 2 minutes)
- **No popups**: Runs as true Windows Service
- **Logging**: All activity logged to `logs/csc-service.log`
- **Cross-platform**: Works on Windows (Service), Linux/macOS (systemd/launchd), Android (manual)

## Windows Setup (NSSM - Recommended)

### Step 1: Install NSSM (Non-Sucking Service Manager)

Using Scoop (recommended):
```powershell
scoop install nssm
```

Using Chocolatey:
```powershell
choco install nssm
```

Using direct download:
- Download from: https://nssm.cc/download
- Extract to `C:\Program Files\nssm\`
- Add to PATH or use full path

### Step 2: Install CSC Service

Open PowerShell as Administrator and run:
```powershell
cd C:\csc
python bin\csc-service.py install
```

This will:
- Create a Windows Service named "CSC Background Service"
- Set it to run `csc-service.py` with log output to `logs/csc-service.log`
- Configure auto-start on Windows startup

### Step 3: Start the Service

```powershell
# Start service
python bin\csc-service.py start

# Or use native Windows commands:
net start "CSC Background Service"
```

### Verify It's Running

```powershell
# Check service status
Get-Service | grep "CSC"

# View logs
Get-Content C:\csc\logs\csc-service.log -Tail 20

# Or use tail
tail -f C:\csc\logs\csc-service.log
```

### Managing the Service

```powershell
# Start service
net start "CSC Background Service"
python bin\csc-service.py start

# Stop service
net stop "CSC Background Service"
python bin\csc-service.py stop

# Remove service
python bin\csc-service.py remove

# View service properties
Get-WmiObject win32_service | Where-Object {$_.Name -eq "CSCBackgroundService"}

# Enable auto-start on boot
net config "CSC Background Service" /auto
```

## Linux/macOS Setup (systemd/launchd)

### Linux (systemd)

Create service file at `/etc/systemd/system/csc-background.service`:
```ini
[Unit]
Description=CSC Background Service
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/opt/csc
ExecStart=/usr/bin/python3 /opt/csc/bin/csc-service.py run
Restart=always
RestartSec=10

StandardOutput=append:/opt/csc/logs/csc-service.log
StandardError=append:/opt/csc/logs/csc-service.log

[Install]
WantedBy=multi-user.target
```

Install and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable csc-background
sudo systemctl start csc-background
```

Monitor:
```bash
sudo systemctl status csc-background
journalctl -u csc-background -f
tail -f /opt/csc/logs/csc-service.log
```

### macOS (launchd)

Create plist at `~/Library/LaunchAgents/com.csc.background.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.csc.background</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/opt/csc/bin/csc-service.py</string>
        <string>run</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/opt/csc</string>
    <key>StandardOutPath</key>
    <string>/opt/csc/logs/csc-service.log</string>
    <key>StandardErrorPath</key>
    <string>/opt/csc/logs/csc-service.log</string>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
```

Install and start:
```bash
launchctl load ~/Library/LaunchAgents/com.csc.background.plist
```

Monitor:
```bash
tail -f /opt/csc/logs/csc-service.log
launchctl list | grep csc
```

## Android/Termux Setup

Run the service in a persistent terminal session or screen:

```bash
# Install screen or tmux if needed
pkg install screen

# Run service in detachable session
screen -d -m -S csc-service python /opt/csc/bin/csc-service.py run

# View logs
tail -f /opt/csc/logs/csc-service.log

# Reconnect to session
screen -r csc-service

# Detach (Ctrl+A, then D)
```

## What the Service Does

Every minute:
- **Queue Worker**: Scans `agents/*/queue/in/` for new prompts
  - Moves to `queue/work/`
  - Spawns wrappers
  - Monitors for completion
  - Cleans up

Every 5 minutes (on 5-minute boundaries):
- **Test Runner**: Runs test suite
  - Generates fix prompts on failure
  - Routes to appropriate agents

## Logging

Service logs everything to `logs/csc-service.log`:

```bash
# View real-time
tail -f C:\csc\logs\csc-service.log

# View last 50 lines
tail -50 C:\csc\logs\csc-service.log

# View specific time range
Get-Content C:\csc\logs\csc-service.log | Select-String "2026-02-20 23:"
```

## Troubleshooting

### Service won't install
- Ensure NSSM is installed and in PATH: `nssm -v`
- Run PowerShell as Administrator
- Check logs: `C:\csc\logs\csc-service.log`

### Service not running
- Check status: `Get-Service | grep CSC`
- Check Windows Event Viewer for service errors
- Try running in foreground: `python C:\csc\bin\csc-service.py run`

### Logs not appearing
- Ensure `C:\csc\logs\` directory exists
- Check file permissions
- Run service process manually to see errors

### Too many log entries
- Service polls once per minute (300 entries/hour)
- Rotate logs: Rename and compress old logs files

## Performance Notes

- **Poll interval**: 60 seconds (once per minute)
- **Queue worker**: Runs within 60-second window
- **Test runner**: Runs every 5 minutes (within same window)
- **CPU impact**: Minimal (I/O bound, not CPU bound)
- **Memory**: ~50-100 MB Python process
- **No popups**: Service runs as background process without console

## Current Status

Service infrastructure:
- ✅ `bin/csc-service.py` - Unified service for all platforms
- ✅ `logs/csc-service.log` - Auto-created on first run
- ✅ One-minute polling (not every 2 minutes)
- ✅ No popup windows
- ✅ Proper Windows Service integration

Next: Install NSSM, then run `python bin\csc-service.py install`
