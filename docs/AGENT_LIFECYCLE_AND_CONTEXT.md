Agent Lifecycle: Assignment, Spawning, and Context Loading
===========================================================

Complete explanation of how workorders flow through agent.assign, queue-worker, and PM,
and how context is constructed for Anthropic (and other) agents. This clarifies a commonly
misunderstood part of the system.

OVERVIEW: THE THREE PHASES
==========================

Phase 1: ASSIGNMENT (agent.assign)
  Interactive command: User selects agent and assigns workorder
  Result: Queued in agents/<agent>/queue/in/ for background processing

Phase 2: SPAWNING (queue-worker.process_inbox)
  Background daemon: Polls queue/in/, assembles context, spawns agent
  Result: Agent process running in isolated temp repo clone

Phase 3: VERIFICATION (PM)
  Background daemon: Monitors WIP file, tracks completion
  Result: Moves to done/, commits, logs completion

---

PHASE 1: ASSIGNMENT (agent.assign) — INTERACTIVE
=================================================

Where: irc/packages/csc-service/csc_service/shared/services/agent_service.py:467
Who: User or automated system (calls agent assign <workorder> <agent>)
Timing: Synchronous, immediate

What Happens:

  1. Find workorder in ready/ or wip/
     path = ready/<name>.md  or  wip/<name>.md

  2. Check platform capabilities
     - Verify system can satisfy workorder requirements
     - Check for required tools (docker, git, etc.)
     - If missing: leave in ready/ for capable system

  3. Get selected agent
     agent_name = get_data("selected_agent") or "haiku"

  4. Move workorder to WIP (mark as in-progress)
     ready/<name>.md  -->  wip/<name>.md

  5. Create metadata JSON
     {
       "agent": "haiku",
       "workorder": "fix_server_privmsg.md",
       "timestamp": "2026-03-14T13:45:22",
       "original_path": "ready/fix_server_privmsg.md",
       "platform_tags": ["requires_git"]
     }

  6. Write metadata to agent queue
     agents/haiku/queue/in/fix_server_privmsg.json

  7. Generate orders.md
     agents/haiku/queue/in/orders.md (template with placeholders)

  8. Return success message
     "Queued 'fix_server_privmsg.md' for agent 'haiku'"

At this point:
  - Workorder is in wip/ (user sees it as "in progress")
  - Metadata + orders.md are in queue/in/ (waiting for queue-worker to pick up)
  - Agent service is done; background daemon takes over

---

PHASE 2: SPAWNING (queue-worker.process_inbox) — BACKGROUND
============================================================

Where: irc/packages/csc-service/csc_service/infra/queue_worker.py:1166
Who: Background daemon (runs every cycle, ~1-5 seconds)
Timing: Asynchronous, background processing

Prerequisite: agent.assign has queued work in agents/<name>/queue/in/

Flow:

  1. SCAN & LOAD PENDING WORK
     Load agents/<agent>/queue/in/orders.md (queue entry)
     Extract: agent_name, workorder_filename
     Mark item as "processing" internally

  2. MOVE ORDERS.MD TO WORK (prevent re-processing)
     agents/haiku/queue/in/orders.md  -->  agents/haiku/queue/work/orders.md
     (If process crashes, work is in queue/work/, not queue/in/)

  3. CLONE TEMP REPO (isolation)
     Create isolated copy of entire CSC repo:
       tmp/clones/haiku/fix_server_privmsg-<timestamp>/
     Reasoning: Agent can modify code, run tests, create branches
               without affecting main repo or other agents
     CSC_AGENT_REPO env var = path to clone

  4. BUILD FULL PROMPT (context assembly) <- KEY PART
     This is where context from roles/ + agents/*/context/ is assembled
     See "CONTEXT ASSEMBLY" section below for details

  5. INJECT TEMPLATE VARIABLES into orders.md
     Replace placeholders in orders.md:
       <clone_rel_path>  -->  tmp/clones/haiku/fix_server_privmsg-<ts>/
       <wip_path>        -->  ops/wo/wip/fix_server_privmsg.md
       <agent_name>      -->  haiku

  6. BUILD AGENT COMMAND
     Depends on agent type (claude, gemini, local model, etc.)
     For Anthropic Claude agents:
       cmd = [
         "python", "-m", "cagent.exec",
         "ops/agents/claude/cagent.yaml",
         "<full_prompt_text>",
         "--working-dir", str(temp_clone),
         "--env-from-file", ".env"
       ]

  7. SPAWN SUBPROCESS
     proc = subprocess.Popen(
       cmd,
       cwd=temp_clone,
       env={...env vars...},
       stdout=log_file,
       stderr=subprocess.STDOUT,
       creationflags=subprocess.CREATE_NO_WINDOW  # No visible window
     )
     Save PID for tracking
     Log start time

  8. WAIT FOR AGENT TO FINISH
     Monitor WIP file for updates
     Check for COMPLETE marker
     Track elapsed time, detect stalls (>5 min without update)
     Agent process runs until exit code received

---

CONTEXT ASSEMBLY: The Critical Part
====================================

Location: queue_worker.py:836 function build_full_prompt()

The full prompt sent to the agent is assembled in this order:

  1. ROLE CONTEXT (from ops/roles/<role>/)
     Extract role from WIP file:
       agent: architect  # or worker, debugger, etc.
     Load:
       ops/roles/architect/README.md       (primary role docs)
       ops/roles/architect/*.md            (all other .md files)
     Purpose: Defines what the role is, what they're responsible for,
              how to approach tasks, system knowledge

  2. AGENT-SPECIFIC CONTEXT (from agents/<agent>/context/)
     agents/claude/context/*.md
     agents/haiku/context/*.md
     agents/gemini/context/*.md
     Purpose: Agent-specific instructions (API keys, model quirks,
              tool usage, Claude-specific prompt caching setup, etc.)

  3. SYSTEM RULE (journaling requirement)
     "SYSTEM RULE: Journal every step to <wip_path> BEFORE doing it.
      Use: echo '<step>' >> <wip_path>.
      Do NOT touch git. Do NOT move files. Do NOT run tests.
      When done, echo 'COMPLETE' >> <wip_path> and exit."

  4. WIP CONTENT (the actual task)
     ops/wo/wip/fix_server_privmsg.md (the workorder)

Assembled result (pseudocode):
  """
  === ops/roles/architect/README.md ===
  [Role documentation - 2000+ lines]

  === GUIDELINES.md ===
  [Role guidelines]

  === agents/claude/context/PROMPT_CACHING.md ===
  [Claude-specific prompt caching setup]

  === agents/claude/context/TOOL_USE.md ===
  [How to use Claude's tool-use API]

  === SYSTEM RULE: Journal every step... ===
  [Journaling requirement]

  === TASK: fix_server_privmsg.md ===
  [The actual workorder - what needs to be done]
  """

Total context size: ~50KB - 200KB depending on role + task complexity

Important: This full text is passed to the agent. The agent receives it as
a single string prompt, NOT as separate files. The agent's model will see
all of this context at once.

---

WHY THIS MATTERS FOR ANTHROPIC AGENTS (PROMPT CACHING)
======================================================

Anthropic's prompt caching feature allows agents to cache large context blocks
that don't change frequently (e.g., system prompts, role definitions, tool docs).

Scenario 1: OLD APPROACH (No Caching)
  Agent 1: Run with full 150KB prompt (role + context + task)
  Agent 2: Run with same 150KB prompt (role + context + task)
  Agent 3: Run with same 150KB prompt
  Result: 450KB of redundant API calls

Scenario 2: NEW APPROACH (With Prompt Caching)
  Agent 1: Run with full 150KB prompt
    - First 100KB: role + context (gets cached by Anthropic)
    - Last 50KB: task (unique per workorder)
  Agent 2: Run with same role + context
    - Anthropic returns cached 100KB instantly
    - Only pay for 50KB new task content
    - Cost reduced by 67%
  Agent 3: Same pattern
    - 50KB charged per agent instead of 150KB

Implementation: Anthropic SDK marks cache breakpoints
  "cache_control": {"type": "ephemeral"}

Current Status:
  - agents/claude/context/ can include PROMPT_CACHING.md
  - roles/ should be standardized for cache efficiency
  - The same role context gets reused across many workorders
  - Caching is transparent to agents (SDK handles it)

Future: Make roles/ the ONLY context source (no agents/*/context/)
  Why: Agents don't need agent-specific context; roles define everything
  Benefit: 100% cache hit for role context across all agents/workorders
  Plan: Migrate agents/<name>/context/ knowledge into roles/

---

PHASE 3: VERIFICATION (PM) — MONITORING & COMPLETION
=====================================================

Location: irc/packages/csc-service/csc_service/infra/pm.py
Who: Project Manager daemon
Timing: Runs every cycle while agent is active, then post-process

While Agent is Running:

  1. Monitor WIP file updates
     stat(ops/wo/wip/<workorder>.md) -> check mtime
     Detect: stale (no updates for >300 seconds) or complete

  2. Track progress
     Count lines in WIP to estimate % complete
     Check for error patterns in agent log

  3. On stall detection (>5 min without update)
     Log warning: "Agent stalled, no updates"
     Don't kill automatically (let agent continue)
     User can manually: agent kill <agent>

After Agent Exits (exit code received):

  1. process_finished_work() is called
     return_code = process exit code
     agent_log = path to agent's output log

  2. Determine success/failure
     exit_code == 0?  -->  SUCCESS
     exit_code != 0?  -->  FAILURE (mark for retry)

  3. On SUCCESS:
     a. Move WIP to done/
        ops/wo/wip/<name>.md  -->  ops/wo/done/<name>.md

     b. Commit to git (in temp clone, then push main)
        git add -A
        git commit -m "fix(server): fix privmsg routing"
        git push origin main

     c. Log completion
        Log: "Completed: fix_server_privmsg.md (haiku, 345 seconds)"
        Record in pm_data.json

     d. Clean up
        Delete temp clone (can be re-cloned if needed)
        Remove from queue/work/

  4. On FAILURE:
     a. Leave in wip/ or move back to ready/
     b. Log error
     c. Generate new workorder for next agent
        "PROMPT_fix_fix_server_privmsg_retry.md"

  5. Cycle continues
     Look for next queued workorder in queue/in/
     Go back to PHASE 2

---

FULL LIFECYCLE EXAMPLE
======================

T=0:00  User: agent select sonnet && agent assign fix_server.md
        [Phase 1: ASSIGNMENT]
        - fix_server.md moves to wip/
        - metadata + orders.md placed in agents/sonnet/queue/in/

T=0:01  Queue-worker cycle triggers
        [Phase 2: SPAWNING]
        - Picks up orders.md from queue/in/
        - Clones temp repo: tmp/clones/sonnet/fix_server-<ts>/
        - Assembles context (role + agent + system + task)
        - Builds command with full prompt text
        - Spawns: python -m cagent.exec ... <full_prompt>
        - Agent process starts running

T=0:15  Agent writes to WIP file
        "Step 1: read server.py line 100"
        PM detects update, logs progress

T=0:45  Agent writes to WIP file again
        "Step 2: identified bug in privmsg routing"
        PM logs

T=1:30  Agent process exits with code 0 (success)
        [Phase 3: VERIFICATION]
        - PM receives exit code
        - Moves wip/fix_server.md to done/
        - Commits to git: "fix(server): handle malformed privmsg"
        - Pushes to remote
        - Cleans up temp clone
        - Logs completion

T=1:31  Next workorder queued automatically (if any)
        System loops back to PHASE 2

---

KEY DESIGN PATTERNS
===================

ISOLATION (Temp Clones)
  Why: Agents modify code, run tests, create branches
  How: Queue-worker clones entire repo per agent per task
  Cleanup: Temp clone deleted after completion (safe cleanup)
  Recovery: If clone creation fails, agent works in main repo (fallback)

CONTEXT IMMUTABILITY
  Why: Agent receives context once at startup
  How: Full prompt assembled before subprocess.Popen()
  Implication: Agent can't request more context mid-task
  Solution: Context must be complete upfront (roles/ is the right place)

JOURNALING (WIP file)
  Why: Track agent progress, prevent re-running, verify completion
  How: Agent appends text to ops/wo/wip/<name>.md before each step
  Not monitored by: git (git ignores wip/)
  Monitored by: PM daemon (watches mtime for staleness detection)
  Completion marker: Agent writes "COMPLETE" as final line

QUEUE ORDERING (FIFO)
  Why: First queued, first processed
  How: agents/<agent>/queue/in/ is processed in order
  Fairness: No agent dominates; all agents take turns
  Scaling: queue-worker processes one workorder per cycle

---

COMMON MISCONCEPTIONS (CLEARED UP)
==================================

"Context is files on disk the agent reads"
  WRONG: Context is text assembled and passed as a string to the agent
  RIGHT: Full prompt is built before agent starts, given as one large text

"Agent can request more context from roles/"
  WRONG: Agent receives context once at startup
  RIGHT: All needed context must be in roles/ beforehand

"agents/<agent>/context/ is the primary context"
  WRONG: It's supplementary
  RIGHT: roles/ is primary (used by all agents), agents/*/context/ is agent-specific

"PM monitors agent's git commits"
  WRONG: Agent runs in temp clone, PM commits afterward
  RIGHT: PM does final commit to main after agent exits, PM pushes

"Multiple agents can work simultaneously"
  PARTIALLY: Each agent has own queue (can run same time), but share same WIP dirs
  CORRECT: ops/wo/wip/ is shared; PM de-duplicates completed work

"Workorder is complete when agent writes COMPLETE"
  WRONG: Agent writes COMPLETE, PM verifies exit code, then moves file
  RIGHT: PM is authority; agent signals, PM verifies and finalizes

---

ARCHITECTURAL IMPLICATIONS
==========================

For Unified Context (roles/ as Single Source of Truth):

Current state:
  Role context: ops/roles/architect/README.md (active, primary)
  Agent context: agents/claude/context/*.md (supplementary)

Future state:
  Role context: ops/roles/architect/README.md (everything)
  Agent context: (deprecated, merge into roles/)

Benefit: 100% prompt cache hits across agents
  Why: All agents using same role get same cached context
  Cost savings: 3-4x reduction in API calls for repeated roles

Implementation plan:
  1. Move agents/*/context/ knowledge into ops/roles/*/
  2. Deprecate agents/*/context/ (keep for backwards compat)
  3. Update build_full_prompt() to warn on missing content
  4. Enable Anthropic prompt caching in claude agent config

---

DEBUGGING AGENT ISSUES
======================

"Agent stuck in queue/in/"
  Check: agents/<agent>/queue/in/orders.md exists?
  Check: queue-worker is running? (csc-ctl status queue-worker)
  Fix: queue-worker cycle not triggering (restart service)

"Agent spawned but not doing anything (WIP empty)"
  Check: Agent log file (logs/agent_<ts>_<name>.log)
  Common: Missing context files, bad permission on temp clone
  Fix: Check role/<role> exists and readable

"Agent exit code != 0 (failure)"
  Check: Agent log for error message
  Common: Missing tool (docker, git), bad working directory
  Fix: Verify platform capabilities match workorder requirements

"WIP file shows old progress, agent died?"
  Check: Agent process PID (ps aux | grep cagent)
  Check: mtime of WIP (ls -la ops/wo/wip/<name>)
  If >5 min old: agent likely crashed
  Fix: agent kill <agent> (move WIP back to ready)

"orders.md template variables not injected?"
  Check: Queue-worker log for injection errors
  Common: Bad relative path calculation, clone creation failed
  Fix: Delete agents/<agent>/queue/work/orders.md, re-queue

---

REFERENCES
==========

Code locations:
  Agent Service: irc/packages/csc-service/csc_service/shared/services/agent_service.py:467
  Queue Worker: irc/packages/csc-service/csc_service/infra/queue_worker.py:1166
  Context Assembly: queue_worker.py:836 (build_full_prompt)
  PM Completion: queue_worker.py:1061 (process_finished_work)

Documentation:
  GIT_WORKFLOW.md - How agents use git
  HOUSEKEEPING.md - Monitoring and troubleshooting
  irc/docs/tools/agents.txt - Code map for agent service
  irc/docs/tools/workorders.txt - Code map for workorders
