# Agent Launcher & Tracker Guide

## Overview

The **Agent Launcher** (`bin/agent-launcher.py`) manages the federation task execution and progress tracking for Opus and Haiku agents.

## Installation

No additional setup needed - the launcher uses the existing `claude` CLI that's already installed.

## Usage

### 1. Launch Opus Agent

```bash
python bin/agent-launcher.py opus
```

This starts Claude Opus on the server linking federation task:
- Reads: `prompts/wip/opus-server-linking-federation.md`
- Creates: `ServerLink` and `ServerNetwork` classes
- Implementation: S2S protocol for server-to-server communication
- Expected duration: 30-60 minutes

### 2. Launch Haiku Agents

```bash
python bin/agent-launcher.py haiku
```

This launches all three Haiku tasks sequentially:
1. **Configure Official Server** (haiku-configure-official-csc-server.md)
   - Updates all clients to read CSC_SERVER_HOSTNAME from .env
   - Updates documentation
   - Duration: 15-30 minutes

2. **Time Synchronization** (haiku-time-sync-for-server-merges.md)
   - Implements NTPClient class
   - Adds time tracking to servers
   - Duration: 20-30 minutes

3. **Nick Collision Resolution** (haiku-nick-collision-resolution.md)
   - Implements CollisionResolver class
   - Algorithm for handling nick conflicts on merge
   - Duration: 25-40 minutes

### 3. Check Status

```bash
python bin/agent-launcher.py status
```

Shows current progress for all tasks:
```
[OPUS] Server Linking & Federation System
  File: opus-server-linking-federation.md
  Model: opus
  Status: IN PROGRESS
  Lines: 245 | Journal entries: 12
  Last action: implementing ServerLink class connect() method

[HAIKU-CONFIG] Configure Official Server
  File: haiku-configure-official-csc-server.md
  Model: haiku
  Status: READY (not started)

[HAIKU-SYNC] Time Synchronization for Server Merges
  File: haiku-time-sync-for-server-merges.md
  Model: haiku
  Status: READY (not started)

[HAIKU-COLLISION] Nick Collision Resolution
  File: haiku-nick-collision-resolution.md
  Model: haiku
  Status: READY (not started)
```

### 4. Watch Progress Real-Time

```bash
python bin/agent-launcher.py track
```

Opens a real-time monitoring view that updates every 30 seconds:
- Shows journal entry counts for each task
- Displays latest action taken
- Indicates when tasks move to done/
- Auto-refreshes until all tasks complete or 1 hour passes

## How It Works

### Agent System Prompt

Each agent is given a mandatory system prompt that enforces:
1. **Journal every step** — Before doing anything, echo it to the WIP file
2. **No checkboxes** — Simple log format (one action per line)
3. **Don't delete WIP files** — Always move to done/ when complete
4. **Track progress** — Make journal entries frequent and detailed

Example journal entry:
```
reading server_s2s.py — understanding ServerLink class structure
adding ServerNetwork class to manage multiple S2S connections
implementing SLINK handshake with password authentication
testing 2-server link with localhost:9526
all tests passing, moving to done
```

### Progress Tracking

The launcher monitors progress by:
1. **Counting WIP file lines** — More lines = more work done
2. **Counting journal entries** — Action lines (reading, implementing, testing, etc.)
3. **Reading last action** — Latest journal entry shows current work
4. **Checking for completion** — File moved from wip/ to done/

## Output Files

- `logs/agent-opus.log` — Opus agent output
- `logs/agent-haiku-config.log` — Haiku config task output
- `logs/agent-haiku-sync.log` — Haiku time sync task output
- `logs/agent-haiku-collision.log` — Haiku collision task output
- `logs/agent-progress.log` — Tracker log

## Expected Workflow

### Ideal Scenario

```
1. Run: python bin/agent-launcher.py opus
   → Opus starts working on S2S protocol

2. While Opus works, start tracking:
   → python bin/agent-launcher.py track

3. Opus completes S2S basics (30 min)
   → opus-server-linking-federation.md moves to done/

4. Review Opus work, then start Haiku:
   → python bin/agent-launcher.py haiku

5. Haiku tasks run in sequence (60-100 min total)
   → Each task finishes and moves to done/

6. All done!
   → Run: git log --oneline -5
   → See all federation commits
```

### If Agent Stalls

If an agent doesn't show new journal entries for > 5 minutes:

1. **Check the log:**
   ```bash
   tail -50 logs/agent-opus.log
   ```

2. **Check the WIP file:**
   ```bash
   tail -20 prompts/wip/opus-server-linking-federation.md
   ```

3. **Kill the agent if stuck:**
   ```bash
   pkill -f "claude.*opus"
   ```

4. **Move WIP back to ready:**
   ```bash
   mv prompts/wip/opus-server-linking-federation.md prompts/ready/
   ```

5. **Try again:**
   ```bash
   python bin/agent-launcher.py opus
   ```

## Integration with Other Tools

### sm-run
The agents can use `sm-run` to test their service implementations:
```bash
sm-run platform info  # Test platform service
sm-run agent status   # Check agent queue
```

### dc-run
For Docker-based testing:
```bash
dc-run list  # List Docker prompts
```

### git workflow
Agents will make commits like:
```
[s2s-protocol] Implement ServerLink class for S2S connections
[s2s-network] Add ServerNetwork manager for linked servers
[s2s-handlers] Add S2S command handlers to server_message_handler
[s2s-tests] Add comprehensive S2S linking tests
```

View progress:
```bash
git log --oneline | grep s2s
git log --oneline | grep configure
git log --oneline | grep time-sync
git log --oneline | grep collision
```

## Verification Checklist

After all agents finish, verify:

- [ ] `prompts/done/opus-server-linking-federation.md` exists
- [ ] `prompts/done/haiku-configure-official-csc-server.md` exists
- [ ] `prompts/done/haiku-time-sync-for-server-merges.md` exists
- [ ] `prompts/done/haiku-nick-collision-resolution.md` exists
- [ ] All S2S classes created in `csc-server/server_s2s.py`
- [ ] All clients read CSC_SERVER_HOSTNAME from .env
- [ ] NTPClient implemented in `csc-shared/time_sync.py`
- [ ] CollisionResolver implemented in `csc-server/collision_resolver.py`
- [ ] All tests pass: `pytest tests/test_s2s_*.py`
- [ ] Git commits show all work: `git log --oneline | head -20`

## Troubleshooting

### "claude: command not found"
Install Claude Code:
```bash
pip install anthropic-sdk claude
```

### Agent produces empty log
The claude CLI might need different flags or the prompt file might be invalid. Check:
1. Prompt file is readable: `cat prompts/wip/opus-*.md | head`
2. File isn't corrupted (should start with `---`)
3. Try simpler prompt first to test

### Agent finishes too quickly (< 1 minute)
Likely hit an error. Check:
```bash
tail -20 logs/agent-*.log
tail -20 prompts/wip/opus-*.md
```

### All tasks marked as COMPLETED but code not there
Agents may have moved files to done/ without actually implementing. Check:
```bash
git log --oneline | grep s2s  # Should show commits
ls -la packages/csc-server/server_s2s.py  # Should exist
```

## Manual Agent Launch (Advanced)

If the launcher doesn't work, launch agents manually:

```bash
# Opus
claude -p --model opus \
  --append-system-prompt "Journal every step to prompts/wip/opus-server-linking-federation.md BEFORE doing it" \
  prompts/wip/opus-server-linking-federation.md

# Haiku
claude -p --model haiku \
  --append-system-prompt "Journal every step to prompts/wip/haiku-configure-official-csc-server.md BEFORE doing it" \
  prompts/wip/haiku-configure-official-csc-server.md
```

Then monitor progress manually:
```bash
watch -n 5 'wc -l prompts/wip/*.md && echo "---" && git log --oneline -3'
```

## See Also

- `FEDERATION_ROADMAP.md` — Detailed task descriptions
- `prompts/wip/*.md` — Individual task files
- `packages/csc-server/` — Where agents will write code
- `packages/csc-shared/` — Where shared utilities go
