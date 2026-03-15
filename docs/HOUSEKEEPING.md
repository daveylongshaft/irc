Housekeeping & Maintenance Guide
=================================

Regular maintenance tasks to keep the CSC system healthy, organized, and performant.

DAILY CHECKS
============

Queue Status
  wo status              Check how many queued/wip/done workorders exist
  agent status           Verify agents are running and responsive
  tail logs/log.log      Watch for errors or stale activity

Logs Review
  tail -50 logs/log.log  Check recent activity
  grep ERROR logs/*.log  Search for errors (check multiple logs)
  grep WARN logs/*.log   Check for warnings indicating system stress

System Health
  df -h                  Verify disk space (watch /c/csc/ size)
  ps aux | grep python   Check if services are running

WEEKLY TASKS
============

Code Maps
  refresh-maps           Regenerate tools/, tree.txt, p-files.list
  (Run after significant code changes)

Documentation
  Check irc/docs/       Verify no stale docs accumulating
  Check ops/wo/archive/ Verify completed workorders properly archived

Git Status
  git status             Working tree should be clean
  git log -5             Verify recent commits are meaningful

Agent Context Audit
  ls -la ops/agents/*/context/   Check all agents have context
  ls -la ops/roles/*/README.md    Verify all roles defined

MONTHLY TASKS
=============

Trash Cleanup
  trash --list           Review .trash/ contents
  trash --empty          Empty if safe (nothing needed for recovery)

Archive Old Workorders
  find ops/wo/archive -name "*.md" | wc -l    Count archived tasks
  (Move old done/ workorders to archive/ per ops/INDEX.md)

Documentation Refresh
  irc/docs/              Update stale docs, move to archive/
  Check README.md        Verify links are accurate

Performance Check
  python -c "import json; json.load(open('etc/channels.json'))"  Validate JSON
  (Check other JSON files: opers.json, platform.json, etc.)

Backup Verification
  ls -la etc/backup/     Verify corrupt backup files collected

TEST CACHE CLEARING
===================

When to Clear
  - After major structural changes
  - If tests are mysteriously failing
  - If .pytest_cache is >100MB

Procedure
  rm -rf .pytest_cache
  rm -rf tests/logs/*.log   (Forces test-runner to re-run all tests)

GIT MAINTENANCE
===============

Log Cleanup (if log.log grows >100MB)
  tail -100000 logs/log.log > logs/log.log.new
  mv logs/log.log.new logs/log.log

Object Repack (if .git/objects grows large)
  git gc                 Repack and compress objects
  git gc --aggressive    More aggressive compression (slower)

Prune Dangling Objects
  git fsck               Check repository integrity
  git gc --prune=now     Remove dangling commits and objects

WORKORDER MANAGEMENT
====================

Archive Completed Work
  wo status                          Check queue status
  wo list done                       List recently completed
  wo archive <filename>              Move to archive/ (marks as verified)

Old Archives Cleanup (annually)
  find ops/wo/archive -mtime +365 -name "*.md"
  (Review and delete if truly no longer needed)

Queue Overflow (>500 workorders)
  wo list ready | wc -l             Check ready queue size
  Investigate: Why are so many queued?
  Create P1 workorder: "Analyze why ready queue is >500"

AGENT MANAGEMENT
================

Context Verification
  For each agent in ops/agents/:
    - Verify agent/context/ or agent/bin/cagent.yaml exists
    - Check agent/README.md (if interactive) matches ops/roles/*/README.md

Agent Queue Cleanup
  ops/agents/*/queue/in/              Should be empty (processed)
  ops/agents/*/queue/out/             Should be empty (moved to results/)
  (Queue-worker handles this, but verify monthly)

Agent Status
  agent list                          List all available agents
  agent status                        Check running agents
  For stalled agents: agent kill <agent> && agent assign <wo> <agent>

DOCUMENTATION MAINTENANCE
==========================

Stale Doc Detection
  irc/docs/SYSTEM_STATUS.txt         Update if >1 day old
  (Check modification times: ls -lt irc/docs/)

Archive Historical Docs
  irc/docs/ files >3 months old → irc/docs/archive/
  Keep tools/, plans/, archive/ subdirs current

Broken Link Check
  In README.md and INDEX files, verify all links exist
  Tools: grep "\[.*\](.*\.md)" README.md | check paths

Dead Code References
  Search docs for deleted files/functions
  Update docs to match current codebase

ETC/ DIRECTORY CLEANUP
======================

Config File Validation
  python -c "import json; json.load(open('etc/opers.json'))"
  python -c "import json; json.load(open('etc/channels.json'))"
  (Check all *.json files for corruption)

Backup Files
  ls -la etc/backup/                 Review crash backups
  Delete if older than 2 weeks (unless recovering)

Large File Check
  du -sh etc/*                       Check if any file >10MB
  (history.json can grow large; consider archiving)

TMP/ DIRECTORY CLEANUP
======================

Old Agent Clones
  find tmp/ -type d -mtime +7        Find clones >1 week old
  rm -rf tmp/clones/old-name/        Remove stale clones

PID Files
  find tmp/ -name "*.pid"            Should exist only for running agents
  (Clean up orphaned PID files)

Orphaned Workorder Files
  find tmp/ -name "orders-*.md"      Should be empty
  (Queue-worker should clean these up, but verify)

PERFORMANCE OPTIMIZATION
========================

Code Map Regeneration
  refresh-maps                       After major code changes
  (Regenerates tools/, tree.txt, p-files.list)

Cache Clearing (if tools/ is stale)
  rm -rf .pytest_cache/
  refresh-maps --quick               Refresh just tools/

Log Archival (if log.log >500MB)
  Create logs/log.log.archive.<date>
  Truncate logs/log.log to recent 10k lines
  (Keep for recovery, don't delete)

DATABASE VALIDATION
===================

Channel State Integrity
  cat etc/channels.json | python -m json.tool > /dev/null
  (Validates JSON syntax)

User Database
  cat etc/opers.json | python -m json.tool > /dev/null
  cat etc/users.json | python -m json.tool > /dev/null

History Database
  cat etc/history.json | python -m json.tool > /dev/null
  (Can be huge; truncate if >100MB)

DEPLOYMENT VERIFICATION
=======================

Service Status
  csc-ctl status                     All services should show "running"
  csc-ctl status queue-worker        Queue processor should be active

Port Availability
  lsof -i :9525                      IRC server should own UDP 9525
  (Fail if something else is listening)

API Key Validation
  test -f .env && echo "OK" || echo "Missing .env"
  grep "ANTHROPIC_API_KEY" .env      Claude API key present?
  grep "GOOGLE_API_KEY" .env         Gemini API key present?

EMERGENCY RECOVERY
==================

Corrupted JSON File
  Restore from backup:
    cp etc/backup/<file>.json.corrupt.<timestamp> etc/<file>.json
  Or revert from git:
    git checkout etc/<file>.json

Server Crash / Power Loss
  Server starts and recovers from persistent JSON automatically
  Verify:
    cat etc/channels.json | python -m json.tool | head -20
    (Check that data is intact)

Stalled Agent
  agent kill <agent>                 Force-kill the agent
  Move WIP back to ready:
    wo move wip/<filename> ready
  Restart:
    agent assign ready/<filename> <agent>

Lost Workorder Files
  Check .trash/ first:
    trash --list | grep <name>
  Or recover from git:
    git checkout ops/wo/archive/<filename>.md

CHECKLIST (print and post)
==========================

Daily:
  [ ] wo status                Check queue
  [ ] tail logs/log.log        Review activity
  [ ] agent status             Verify agents running
  [ ] Disk space OK            df -h

Weekly:
  [ ] refresh-maps             Update code maps
  [ ] git status               Clean working tree
  [ ] Review irc/docs/         No stale docs
  [ ] Archive workorders       Move done/ to archive/

Monthly:
  [ ] JSON validation          Check etc/*.json
  [ ] trash --list             Review deleted files
  [ ] Large files              Any >100MB?
  [ ] Backup verification      etc/backup/ reviewed
  [ ] Agent contexts           All agents have context

Quarterly:
  [ ] Log archival             Truncate log.log if >500MB
  [ ] Cache clearing           rm .pytest_cache
  [ ] Old archives review      ops/wo/archive/ cleanup
  [ ] Documentation audit      Stale docs to archive/
  [ ] git gc                   Repack repository

MONITORING ALERTS
=================

Watch for These Conditions:

Ready Queue >500
  Indicates workorder generation > processing rate
  Investigate and create P1 analysis workorder

Stale WIP Files (>4 hours in wip/)
  Agent likely crashed or hung
  Kill agent and move back to ready/

Log Files Growing Fast
  >100MB in 24h = excessive activity or loops
  Review logs for errors

Missing Oper Context
  If agent can't read ops/roles/*/README.md
  Verify symlinks created (run setup-role-links.sh)

Failed Git Operations
  Any agent report "git operation failed"
  Check git configuration and permissions

High Memory Usage
  Watch for runaway processes
  Use: ps aux | sort -k4 -n | tail -10

TOOL-SPECIFIC MAINTENANCE
==========================

refresh-maps
  Always run before committing code changes
  Regenerates: tools/, tree.txt, p-files.list
  (Enables agents to find code by searching maps)

trash
  Alternative to rm (safe deletion to .trash/)
  Review: trash --list
  Empty: trash --empty

wo (workorder command)
  wo status       Queue statistics
  wo list ready   Available workorders
  wo move <f> <d> Move between queue dirs
  wo archive <f>  Mark as verified complete

csc-ctl
  csc-ctl status  All services
  csc-ctl restart <service>  Restart component
  csc-ctl config <s> <k>     Get setting value

DOCUMENTATION REFERENCES
=========================

irc/docs/INDEX.md           All IRC documentation
ops/INDEX.md                Operations and workorder system
bin/TOOLS_MANIFEST.md       CLI tool inventory
README.md                   Project overview
SETUP_ROLE_LINKS.md         Role symlink/junction setup
