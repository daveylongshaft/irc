Agent Configuration & Management
=================================

CSC supports 8 core AI models configured for automated workorder assignment,
with flexible escalation paths and easy customization for adding new models.

CORE MODELS (8)
---------------

| # | Name | Provider | Role | Capabilities | Best For |
|---|------|----------|------|--------------|----------|
| 1 | **haiku** | Claude | docs-and-tests | Fast, cheap, API tools | Quick validation, docs, tests |
| 2 | **sonnet** | Claude | code | Balanced, capable, API tools | General coding, features |
| 3 | **opus** | Claude | debug | Smartest, API tools | Complex debugging, architecture |
| 4 | **gemini-flash** | Gemini | docs-and-tests | Fast, cheap, SDK | PR reviews, quick tasks |
| 5 | **gemini-pro** | Gemini | code | Smartest, SDK | Complex code analysis |
| 6 | **chatgpt** | OpenAI | code | Capable, tools | Audits, code review, features |
| 7 | **codex** | Outsourced | code-gen | Code generation | Boilerplate, template generation |
| 8 | **jules** | Outsourced | git-automation | Git workflows | Commits, PR automation |

USING AGENTS
------------

Select an agent for interactive work:
  agent select haiku              Select haiku as active agent
  agent select sonnet
  ai do agent select opus         Use IRC command

List available agents:
  agent list                      Show all 8 core models
  ai do agent list                Via IRC

Check agent status:
  agent status                    Current active agent
  ai do agent status

Assign specific agent to workorder:
  wo assign my_task.md sonnet     Assign to Sonnet
  wo assign bug_fix.md opus       Force heavyweight analysis

Queue-worker auto-assignment:
  (Leave agent blank in workorder - PM assigns automatically)
  - Picks cheapest capable agent for the task
  - Escalates on failure (see ESCALATION PATH below)

ESCALATION PATH
---------------

When a workorder fails with the current agent, PM automatically escalates
in this order:

haiku -> gemini-flash -> gemini-pro -> chatgpt -> sonnet -> opus -> codex -> jules

Example:
- Task assigned to haiku (cheap, fast)
- If haiku fails: retry with gemini-flash
- If gemini-flash fails: try gemini-pro
- Continue up the chain to opus
- If opus fails: try outsourced (codex/jules)
- If all fail: flag for human review

WORKORDER ROLES & ASSIGNMENT
-----------------------------

Workorder roles are matched to agent "good_for" capabilities:

good_for categories:
  docs              - Documentation, READMEs, guides
  test-fix          - Test failures, debugging tests
  validation        - Config validation, checks
  feature           - New features, additions
  refactor          - Code improvements, cleanup
  simple-fix        - Small bug fixes
  complex-fix       - Multi-file fixes, deep changes
  debug             - Troubleshooting, root cause analysis
  architecture      - System design, large refactors
  audit             - Code review, security audit
  pr-review         - Pull request review & approval
  pr-reviewer       - PR reviewer assignment
  code-gen          - Template generation, boilerplate
  git-commits       - Automated commit creation
  pr-automation     - GitHub PR automation

Example role assignments:
  good_for: ["feature", "refactor", "complex-fix"]
    -> Can handle new features, code cleanup, multi-file changes

  good_for: ["docs", "test-fix", "validation"]
    -> Specialized in documentation, test debugging, config validation

CONFIGURATION
--------------

Three files control agent availability and behavior:

1. csc_service/infra/pm.py
   ========================
   Defines which agents are available and what work they handle.

   AGENTS list:
     {
       "name": "haiku",
       "role": "docs-and-tests",
       "good_for": ["docs", "test-fix", "validation", "quick-analysis"]
     }

   ESCALATION path:
     "haiku": "gemini-flash",
     "gemini-flash": "gemini-pro",
     ...
     "opus": "codex",
     "codex": "jules",
     "jules": None  # -> human review

   To add a new agent:
     a) Add entry to AGENTS list with name, role, good_for categories
     b) Add to ESCALATION path (where should it escalate to?)
     c) Update VALID_AGENTS set (auto-generated from AGENTS)

2. csc_service/shared/services/agent_service.py
   ============================================
   CLI interface (agent list, agent select, etc.)

   KNOWN_AGENTS dict maps agent names to display labels:
     "haiku": {"label": "Claude Haiku 4.5 (fast, cheap)"},
     "gemini-flash": {"label": "Gemini Flash (fast, cheap)"},

   To add a new agent:
     a) Add to KNOWN_AGENTS dict
     b) Add to LOCAL_AGENTS set if local/offline model
     c) Ensure agents/<name>/cagent.yaml exists (defines provider/model)

3. agents/ directory
   =================
   Each agent has a config file:
     agents/haiku/cagent.yaml
     agents/sonnet/cagent.yaml
     agents/codex/cagent.yaml
     etc.

   cagent.yaml format (example for Anthropic):
     provider: anthropic
     model: claude-3-5-haiku-20241022
     api_key_env: ANTHROPIC_API_KEY

   cagent.yaml format (example for Gemini):
     provider: google
     model: gemini-2.5-flash
     api_key_env: GOOGLE_API_KEY

ADDING A CUSTOM AGENT
---------------------

Steps to add a new AI model to CSC:

1. Create agent config file:
     mkdir -p agents/<my-agent>
     cat > agents/<my-agent>/cagent.yaml <<EOF
     provider: anthropic  # or google, openai, etc
     model: claude-3-sonnet-20250319
     api_key_env: ANTHROPIC_API_KEY
     EOF

2. Update csc_service/infra/pm.py - AGENTS list:
     {
       "name": "my-agent",
       "role": "code",
       "good_for": ["feature", "debug", "refactor"]
     },

3. Update csc_service/infra/pm.py - ESCALATION path:
     Add where it fits in the escalation order:
     "my-agent": "next-agent-on-failure",

4. Update csc_service/shared/services/agent_service.py - KNOWN_AGENTS:
     "my-agent": {"label": "My Custom Agent (description)"},

5. Set API key in .env:
     MY_AGENT_API_KEY=sk-...
     (if using different env var name, update cagent.yaml)

6. Test it:
     agent list                    # Should show my-agent
     agent select my-agent         # Should work
     wo assign my_task.md my-agent # Should assign

REPLACING OUTDATED MODELS
--------------------------

When a model is deprecated and needs replacement:

Example: Replace gemini-2.5-flash with gemini-3-flash

1. Update agents/gemini-flash/cagent.yaml:
     provider: google
     model: gemini-3-flash          # <-- Change model name

2. Optional: Update pm.py if role changed:
     (Only if the new model has different capabilities)

3. Optional: Update label in agent_service.py:
     "gemini-flash": {"label": "Gemini 3 Flash (newer, faster)"},

4. Test:
     agent select gemini-flash      # Should use new model
     wo assign task.md gemini-flash # Should use gemini-3-flash

Note: No changes to ESCALATION path needed if swapping same-role models.

PR REVIEW CONFIGURATION
-----------------------

PR review is handled by csc_service/infra/pr_review.py, which creates
workorders marked with role: "pr-review" and assigns them via PM.

To change which agent reviews PRs:

1. In csc-service.json:
     "enable_pr_review": true,
     "pr_review_agent": "gemini-flash"  # or "sonnet", "opus", etc

2. Update pm.py - add "pr-review" to agent's good_for:
     {
       "name": "my-agent",
       "role": "code",
       "good_for": ["feature", "pr-review", "pr-reviewer"]
     }

Current config (as of 2026-03-17):
  - PR reviews enabled with gemini-flash (cost-effective, capable)
  - Falls back to sonnet, then opus if flash fails
  - Uses PR_REVIEW_POLICY.md for approval/merge rules

ROLE ALIASING
-------------

You can create aliases for long model names:

In agent_service.py KNOWN_AGENTS:
  "gemini-flash": {"label": "Gemini Flash (fast, cheap) - alias for 2.5-flash"},
  "gemini-2.5-flash": {"label": "Gemini 2.5 Flash (fast, cheap)"},

Both refer to the same model but allow shorter names in commands:
  agent select gemini-flash        # Short alias
  agent select gemini-2.5-flash    # Full name

MONITORING & DEBUGGING
---------------------

Check agent assignments:
  logs/log.log                      # Service logs include assignment decisions
  wo list wip                       # See what agent is working on what
  wo read <file>                    # Check assigned agent

Check escalation in action:
  tail -f logs/log.log | grep -i "escalat"  # Watch escalations
  tail -f logs/pm.log                       # PM decisions

Check available agents at runtime:
  python3 -c "from csc_service.infra import pm; print(pm.AGENTS)"
  python3 -c "from csc_service.shared.services.agent_service import Agent; print(Agent.KNOWN_AGENTS.keys())"

API KEY SETUP
-------------

Required environment variables in .env or csc-service.json:

Anthropic (Claude):
  ANTHROPIC_API_KEY=sk-ant-...

Google (Gemini):
  GOOGLE_API_KEY=AIz...

OpenAI (ChatGPT):
  OPENAI_API_KEY=sk-...

Outsourced workers (codex, jules):
  CODEX_API_KEY=...                # If external API
  JULES_GITHUB_TOKEN=ghp_...        # GitHub token for commits

Set in ~/.env for development, or pass via environment for production:
  export ANTHROPIC_API_KEY="sk-..."
  csc-service --daemon

TROUBLESHOOTING
---------------

Agent not showing in list:
  - Check KNOWN_AGENTS in agent_service.py has the entry
  - Check agents/<name>/cagent.yaml exists
  - Restart service: csc-ctl restart csc-service

Agent assignment fails:
  - Check all agents in ESCALATION path are valid
  - Check API keys are set in .env
  - Check pm.py AGENTS list has the agent with good_for categories
  - See logs/log.log for assignment decisions

Wrong agent being assigned:
  - Check workorder has correct role in frontmatter
  - Check agent's good_for list includes that role
  - Check escalation order (cheaper agents assigned first)
  - Force assignment: wo assign task.md <agent-name>

API key errors:
  - Check ANTHROPIC_API_KEY, GOOGLE_API_KEY etc are set
  - Check keys have required permissions
  - Check cagent.yaml points to correct env var name
  - Test manually: curl -H "Authorization: Bearer $ANTHROPIC_API_KEY" ...

PERFORMANCE TUNING
------------------

Cheap tier for cost control:
  Prefer haiku for docs, tests, quick validation
  Use gemini-flash for PR reviews instead of opus
  Fall back to paid only when necessary

Fast tier for speed:
  haiku: Fastest Anthropic model
  gemini-flash: Fastest Gemini model
  Both good for time-sensitive tasks

Capable tier for complex work:
  opus: Most capable Claude model
  gemini-pro: Most capable Gemini model
  chatgpt: Alternative capable model
  Use for architecture, deep debugging, audits

REFERENCES
----------

See also:
  - csc_service/infra/pm.py - Agent roster and PM assignment logic
  - csc_service/shared/services/agent_service.py - CLI interface
  - csc_service/infra/pr_review.py - PR review automation
  - bin/agent - Shell wrapper for agent commands
  - CLAUDE.md - Agent instruction file (what agents are told to do)
  - PR_REVIEW_POLICY.md - PR approval and merge policies
