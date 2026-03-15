# Plan: Docker Agent Wrapper Enhancement

## Context

`dc-run` and `dc-agent-wrapper` already exist and handle prompt lifecycle (git pull, move ready→wip, launch agent, wait, move to done/ready, commit/push). But they're missing:

1. **File growth monitoring** — wrapper just does `proc.wait(timeout=1800)`, no liveliness check
2. **STATUS: COMPLETE checking** — uses exit code only, doesn't read WIP content
3. **Test verification** — no check that tests were written before marking done
4. **Single-agent enforcement** — no PID check on existing wip/ files
5. **dc-sh variant** — no bash runtime shortcut (only dc-run with ollama default)

## Existing Files (DO NOT recreate)

- `bin/dc-run` (201 lines) — CLI frontend, lists prompts, calls dc-agent-wrapper
- `bin/dc-agent-wrapper` (324 lines) — lifecycle manager, git/prompt/agent orchestration
- `packages/csc-shared/services/agent_service.py` (771 lines) — agent assign engine
- `bin/agent` — CLI wrapper for agent_service methods
- `bin/sm-run` — CLI for service methods

## Prompt Files to Create

### 1. `sonnet-enhance-dc-agent-wrapper.md`
**Agent: sonnet** (moderate complexity, core logic changes)
**What:** Enhance `bin/dc-agent-wrapper` with:
- Replace `proc.wait(timeout=1800)` with polling loop (30s interval)
- Track WIP file size; if no growth for 3 minutes, kill agent, move to ready/
- After process exits: read last non-empty line of WIP
  - If "STATUS: COMPLETE" → proceed to test verification
  - Else → move to ready/ (for resumption)
- Test verification: check if `tests/test_*.py` files were modified (via `git diff --name-only`)
  - If no tests: append "Tests required" to WIP, restart agent
  - If tests: move to done/
- Single-agent enforcement: scan wip/*.md for AGENT_PID lines, refuse if another is alive
**Files:** `bin/dc-agent-wrapper`

### 2. `haiku-create-dc-sh-and-update-dc-run.md`
**Agent: haiku** (simple scripting, copy/modify)
**What:**
- Create `bin/dc-sh` — copy of dc-run but defaults to `--agent coding-agent --model bash`
- Create `bin/dc-sh.bat` — Windows batch wrapper
- Update `bin/dc-run` to support `--agent coding-agent --model python3` as a recognized shorthand
- Both should support: `list`, `menu`, `#N`, `filename.md`
**Files:** `bin/dc-sh`, `bin/dc-sh.bat`, `bin/dc-run`

### 3. `haiku-create-docker-prompt-templates.md`
**Agent: haiku** (documentation/template writing)
**What:** Create two reusable prompt templates:
- `prompts/TEMPLATE_docker_python3.md` — Python3 task structure with:
  - Objective, Requirements, Code Context, Implementation Steps, Testing, Work Log, Success Criteria
  - Instructions: read tools/INDEX.txt, use p-files.list, write tests (don't run), journal with echo >>
  - Must end with "STATUS: COMPLETE" when done
- `prompts/TEMPLATE_docker_bash.md` — Same structure for bash tasks
**Files:** `prompts/TEMPLATE_docker_python3.md`, `prompts/TEMPLATE_docker_bash.md`

### 4. `haiku-update-docs-for-docker-agents.md`
**Agent: haiku** (documentation)
**What:** Update CLAUDE.md and README.1st with:
- Docker agent usage: `dc-run list`, `dc-run task.md`, `dc-sh task.md`
- How monitoring works (file growth check, STATUS: COMPLETE, test verification)
- Template reference
- agent assign integration: `agent assign docker-python task.md`
**Files:** `CLAUDE.md`, `README.1st`

## Verification

After all prompts complete:
1. `dc-run list` shows ready/ prompts
2. `dc-run test-task.md` launches coding-agent, monitors file growth, checks completion
3. `dc-sh test-task.md` works for bash tasks
4. Hung agent (no file growth for 3 min) gets killed and moved to ready/
5. Agent that exits without STATUS: COMPLETE → moved to ready/
6. Agent that completes but skips tests → restarted with "write tests" instruction
7. Agent that completes with tests → moved to done/, committed, pushed
