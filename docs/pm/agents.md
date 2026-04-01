# Agent Roster & Assignment Policy

## Active Agent Policy

| Agent | Role | Used For |
|-------|------|----------|
| gemini-3-pro | Code | Features, refactors, bug fixes, implementation |
| gemini-2.5-flash | Docs & Tests | Documentation, test fixes, validation |
| haiku | Audit | Code audits, reviews, validation checks |
| opus | Debug | Debugging, investigation, complex problem analysis |

**No local agents** (ollama, qwen, deepseek, codellama) are used for PM assignments.

## Assignment Rules

### By Workorder Type

| Workorder Pattern | Agent | Rationale |
|-------------------|-------|-----------|
| PROMPT_fix_test_* | gemini-2.5-flash | Test fixes are straightforward |
| PROMPT_run_test_* | gemini-2.5-flash | Platform-routed test execution |
| PROMPT_docs_* | gemini-2.5-flash | Documentation tasks |
| PROMPT_docstring* | gemini-2.5-flash | Docstring generation |
| *audit*, *review*, *validate* | haiku | Audit and review tasks |
| *debug*, *investigate* | opus | Debugging requires deep reasoning |
| *refactor*, *rename*, *migrate* | gemini-3-pro | Code restructuring |
| *fix_* (non-test) | gemini-3-pro | Bug fixes need code understanding |
| Everything else | gemini-3-pro | Default: treat as code task |

### By Filename Prefix (Human Override)
If a workorder filename starts with an agent name, that's a human hint:
- `haiku-*` → assign to haiku
- `opus-*` → assign to opus
- `gemini-3-pro-*` → assign to gemini-3-pro
- etc.

These hints override the default assignment.

### Escalation Path
```
Task fails → retry same agent once
  → fails again → escalate:
    gemini-2.5-flash → gemini-3-pro
    gemini-3-pro → opus
    haiku → gemini-3-pro
    opus → flag for human review
```

## Agent Execution

Each agent has its own `run_agent.sh` (or `.bat`) in `agents/<name>/bin/`.

**Claude agents** (haiku, sonnet, opus):
```bash
claude --dangerously-skip-permissions --model <model> -p - < orders.md
```

**Gemini agents** (gemini-3-pro, gemini-2.5-flash, etc.):
```bash
npx @google/gemini-cli -y -m <model> -p " " < orders.md
```

Each agent also has an `orders.md-template` that gets combined with the workorder
content during assignment. The template provides project context and mandatory
WIP journaling instructions.
