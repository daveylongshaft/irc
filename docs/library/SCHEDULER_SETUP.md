# CSC Background Services Setup

This guide shows how to set up the queue-worker and test-runner to run automatically in the background.

**Do NOT use Windows Task Scheduler** - it opens popup terminal windows every cycle.

## Windows Setup (Docker Services)

### Test Runner
```bash
bin/install-test-runner.bat     # Build image and start container
bin/uninstall-test-runner.bat   # Stop and remove container
docker logs csc-test-runner --tail 20   # View recent logs
```

### Queue Worker
```bash
queue-worker --daemon           # Run continuously (polls every 60s)
```

## Linux/macOS Setup

### Option 1: Daemon Mode (Recommended)
```bash
# Run in background
nohup queue-worker --daemon >> logs/queue-worker.log 2>&1 &

# Test runner (Docker)
bin/install-test-runner.bat
```

### Option 2: Cron
```bash
crontab -e
# Add:
*/2 * * * * /opt/csc/bin/queue-worker >> /opt/csc/logs/queue-worker.log 2>&1
```

### Option 3: systemd
```ini
# /etc/systemd/system/csc-queue-worker.service
[Unit]
Description=CSC Queue Worker
After=network.target

[Service]
ExecStart=/opt/csc/bin/queue-worker --daemon
WorkingDirectory=/opt/csc
Restart=always
User=csc

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable csc-queue-worker
sudo systemctl start csc-queue-worker
```

## What These Services Do

### Queue Worker
- Polls `workorders/ready/` for new prompts every 60 seconds
- Moves prompts to `workorders/wip/`
- Spawns agent processes in background
- Monitors for completion based on WIP file COMPLETE tag
- Cleans up finished work, commits and pushes

### Test Runner (Docker)
- Runs in its own Docker container with a git clone of the repo
- Checks for missing test logs (indicates test hasn't run)
- Runs tests and generates new logs
- If a test fails, auto-generates a fix prompt in `workorders/ready/`
- Only pushes when there are actual changes

## Monitoring

```bash
# Queue status
ls workorders/{ready,wip}/

# Test status
ls tests/logs/
docker logs csc-test-runner --tail 20

# Queue worker log
tail -f logs/queue-worker.log
```

## Troubleshooting

**Queue worker not processing:**
- Check log: `tail logs/queue-worker.log`
- Verify workorders directory exists: `ls workorders/ready/`

**Tests not running:**
- Check container: `docker ps --filter name=csc-test-runner`
- Delete a log to force rerun: `rm tests/logs/test_foo.log`
- Check container logs: `docker logs csc-test-runner --tail 50`

**Test runner pushing empty commits:**
- Should not happen with current fix (only stages test logs and workorders)
- Restart container: `docker restart csc-test-runner`
