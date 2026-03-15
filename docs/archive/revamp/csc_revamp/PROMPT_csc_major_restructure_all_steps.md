# CSC Major Restructure: Complete Implementation Plan (Plain English, No Code)

**Agent**: Haiku
**Priority**: P0
**Scope**: Repos, folders, API runner, bug fix
**Estimated Duration**: 4–6 hours (manual steps + testing)
**Outcome**: /c/new_csc/ fully staged, ready for renaming

---

## Context

You are restructuring CSC into:
- **Repo layer**: Three private repos (csc, csc-irc, csc-ops) replacing five old ones
- **Folder layer**: Code under irc/, AI instructions under ops/
- **API runner**: New streaming executor with prompt caching
- **Bug fix**: Correct agent status display

This plan is detailed and plain-English. Execute each step as written; at the end, you'll have a fully staged /c/new_csc/ ready to swap with /c/csc.

---

## PART 1: Understand Current State (Read-Only)

### 1.1 Current Repo Layout
Read the following to understand what exists:

- GitHub contains five CSC-related repos:
  - syscmdr (to delete)
  - syscmdr-II (to delete)
  - systemcommander (to delete)
  - client-server-commander (leave untouched)
  - csc (current, will become csc-irc)

- Your local /c/csc/ contains:
  - packages/ (Python code)
  - bin/ (executables: claude-batch/, run_agent.py, csc-ctl, agent, workorders, refresh-maps, trash)
  - tests/ (test suite)
  - workorders/ (AI instruction queue)
  - agents/ (haiku/, sonnet/, opus/ queue dirs)
  - benchmarks/, docs/, tools/
  - CLAUDE.md, README.md, docker/, deploy/

### 1.2 Current Path Constants (Reference)

These need to be updated later. Note their locations:

| File | Current Path | Current Line | Current Value |
|------|-------------|-------------|---------------|
| packages/csc-service/csc_service/shared/services/agent_service.py | Line 33 | PROJECT_ROOT / "workorders" | (read to confirm) |
| agent_service.py | Line 662 | PROJECT_ROOT / "agents" | (read to confirm) |
| packages/csc-service/csc_service/infra/queue_worker.py | Lines 54–58 | csc_root / "agents" and csc_root / "workorders" | (read to confirm) |
| packages/csc-service/csc_service/shared/services/agent_service.py | Line 46 | Path(__file__).parent.parent (from irc/ to csc/) | (will need update) |
| bin/agent | Line 46 | Path(__file__).parent.parent (root) | (will need update) |
| bin/claude-batch/common.py | Lines 90–91 | BASE_DIR.parent.parent | (read and confirm) |

Before modifying, read each file to understand the context and exact line. Write down what you see.

---

## PART 2: GitHub Repo Operations (Using Existing Credentials)

**Note**: GitHub credentials are already configured in /c/csc/. All git commands will use these credentials automatically. Username: daveylongshaft. If needed, API key is in /c/csc/.env.

### 2.1 Backup Old Repos

For each of these repos (syscmdr, syscmdr-II, systemcommander):

1. Clone the repo to a temporary directory (e.g., /tmp/backup/REPO):
   ```
   git clone https://github.com/daveylongshaft/REPO /tmp/backup/REPO
   ```
   **Wait for clone to complete** (check exit code: if 0, success; non-zero, report error and stop)

2. Create a tarball:
   ```
   tar -czf /tmp/backups/REPO-20260305.tar.gz -C /tmp/backup REPO
   ```

3. Verify the tarball is created and > 0 bytes (use: `ls -lh /tmp/backups/REPO-20260305.tar.gz`)

4. Copy the tarball to a safe location (optional: /c/csc-backups/ or cloud storage)

5. Delete the temporary clone directory: `rm -rf /tmp/backup/REPO`

Record the tarball paths and sizes as you go.

### 2.2 Delete Old Repos from GitHub

Using GitHub CLI (gh repo delete), delete these three repos:
- syscmdr
- syscmdr-II
- systemcommander

For each repo, run:
```
gh repo delete daveylongshaft/REPO --yes
```

**After each deletion**, verify by attempting to view the repo:
```
gh repo view daveylongshaft/REPO
```

Should return "repository not found" (404).

### 2.3 Create Three New Private Repos

Using GitHub CLI, create these three **private** repos:

1. **github.com/daveylongshaft/csc** (umbrella repo, fresh history, no initial content)
   - Description: "CSC Multi-AI IRC Orchestration System"
   - Private: Yes
   - Initialize: None (no README, no .gitignore)

2. **github.com/daveylongshaft/csc-irc** (code repo)
   - Description: "CSC IRC Protocol Implementation and Code"
   - Private: Yes
   - Initialize: None

3. **github.com/daveylongshaft/csc-ops** (operations/instructions repo)
   - Description: "CSC AI Operations and Workorder Instructions"
   - Private: Yes
   - Initialize: None

Verify all three are created and marked private by running:
```
gh repo view daveylongshaft/csc --json visibility
```

Should output: `PRIVATE`

---

## PART 3: Folder Structure Migration in /c/new_csc/

### 3.1 Create New Folder Layout

Starting from /c/csc/, you will build /c/new_csc/ with this structure:

```
/c/new_csc/
  irc/                           # <- All code and executables
    packages/                    # (from /c/csc/packages/)
      csc-service/
      csc-server/
      csc-claude/
      csc-gemini/
      csc-chatgpt/
      csc-bridge/
      csc-shared/
      coding-agent/
    bin/                         # (from /c/csc/bin/)
      claude-batch/
      run_agent.py
      csc-ctl
      agent
      workorders
      refresh-maps
      trash
      setup-trash-aliases.sh
      install-test-runner.bat
      (all other bin scripts)
    tests/                       # (from /c/csc/tests/)
    tools/                       # (from /c/csc/tools/)
    benchmarks/                  # (from /c/csc/benchmarks/)
    docs/                        # (from /c/csc/docs/)
    docker/                      # (from /c/csc/docker/)
    deploy/                      # (from /c/csc/deploy/)
    CLAUDE.md                    # (from /c/csc/CLAUDE.md)
    README.md                    # (from /c/csc/README.md)
    .gitignore
    .github/                     # (from /c/csc/.github/ if exists)

  ops/                           # <- All AI instruction files
    wo/                          # (from /c/csc/workorders/)
      ready/
      wip/
      done/
      hold/
      archive/
      results/
      batch/
    agents/                      # (from /c/csc/agents/)
      haiku/
        queue/
          in/
          work/
      sonnet/
        queue/
          in/
          work/
      opus/
        queue/
          in/
          work/
      claude-api/                # NEW agent dir
        queue/
          in/
          work/
      gemini/
        queue/
          in/
          work/
    templates/                   # (from /c/csc/agents/templates/ if exists)

  csc-service.json               # (from /c/csc/csc-service.json)
  platform.json                  # (from /c/csc/platform.json)
  .gitmodules                    # (to be created)
  .gitignore                     # (updated, see below)
  .git/                          # (fresh git init for umbrella repo)
```

### 3.2 Execute Folder Copy

Copy the existing folders from /c/csc/ into /c/new_csc/ with this sequence:

1. Create the top-level /c/new_csc/ directory (already done)
2. Create /c/new_csc/irc/ and copy:
   - /c/csc/packages/ → /c/new_csc/irc/packages/
   - /c/csc/bin/ → /c/new_csc/irc/bin/
   - /c/csc/tests/ → /c/new_csc/irc/tests/
   - /c/csc/tools/ → /c/new_csc/irc/tools/
   - /c/csc/benchmarks/ → /c/new_csc/irc/benchmarks/
   - /c/csc/docs/ → /c/new_csc/irc/docs/
   - /c/csc/docker/ → /c/new_csc/irc/docker/
   - /c/csc/deploy/ → /c/new_csc/irc/deploy/
   - /c/csc/CLAUDE.md → /c/new_csc/irc/CLAUDE.md
   - /c/csc/README.md → /c/new_csc/irc/README.md
   - /c/csc/.github/ → /c/new_csc/irc/.github/ (if exists)

3. Create /c/new_csc/ops/ and copy:
   - /c/csc/workorders/ → /c/new_csc/ops/wo/
   - /c/csc/agents/ → /c/new_csc/ops/agents/ (queue dirs only; delete any template/ or non-queue content)

4. Copy to root:
   - /c/csc/csc-service.json → /c/new_csc/csc-service.json
   - /c/csc/platform.json → /c/new_csc/platform.json

5. Do NOT copy:
   - .git/ (will be created fresh)
   - .venv/, venv/ (pip will reinstall)
   - __pycache__/, .pytest_cache/ (regenerated on run)
   - memory/ (user auto-memory, stays in home dir)

---

## PART 4: Path Constants Updates

After the folder copy, you must update path constants in code. These are HIGH-IMPACT changes that affect multiple files. Read each file first to confirm exact line numbers and context, then make updates.

### 4.1 File: packages/csc-service/csc_service/shared/services/agent_service.py

**Read this file** to understand the context around lines 33, 662, and 46.

**Update 1: Line 33**
- Current: PROJECT_ROOT / "workorders"
- New: PROJECT_ROOT / "ops" / "wo"
- Reason: workorders/ moved to ops/wo/

**Update 2: Line 662**
- Current: PROJECT_ROOT / "agents"
- New: PROJECT_ROOT / "ops" / "agents"
- Reason: agents/ moved to ops/agents/

**Update 3: Line 46** (bin/agent path resolution)
- Current: Path(__file__).parent.parent (resolves to csc/ root)
- New: Path(__file__).parent.parent.parent (resolves to umbrella csc/, then to irc/ parent)
- Reason: agent is in irc/bin/, needs to find irc/ root first, then navigate up

Read the full context of each path resolution before making the change. Ensure you understand the directory structure that results.

### 4.2 File: packages/csc-service/csc_service/infra/queue_worker.py

**Read this file** to understand the context around lines 54–58.

**Update 1: Lines 54–58**
- Current: csc_root / "agents" and csc_root / "workorders"
- New: csc_root / "ops" / "agents" and csc_root / "ops" / "wo"
- Reason: Both moved under ops/

Find every reference to "agents" and "workorders" directories in this file. Update all of them.

### 4.3 File: bin/agent

**Read this file** to understand the path resolution around line 46.

**Update: Line 46**
- Current: Path(__file__).parent.parent (from bin/ to csc/ root)
- New: Path(__file__).parent.parent.parent (from irc/bin/ to irc/, then to umbrella root)
- Reason: agent is now in irc/bin/, needs to navigate through irc/ before reaching umbrella root

Verify the path resolution by tracing it mentally: irc/bin/agent → irc/bin → irc → umbrella root.

### 4.4 File: packages/csc-service/csc_service/shared/services/agent_service.py (line 46 - duplicate check)

**Read this file** to verify if there are other path resolutions that need updating.

Check if line 46 is also a path.parent.parent call. If so, it may need the same update as bin/agent.

### 4.5 File: irc/bin/claude-batch/common.py

**CRITICAL UPDATE**: This file needs absolute paths instead of relative path resolution.

**Read lines 1–95** to understand current structure.

**Update**: Rewrite the `repo_root()` function and path initialization to use absolute paths:

1. **At the top of the file** (after imports, around line 12), add:

```python
# Absolute path to umbrella repo root (/c/csc/)
UMBRELLA_ROOT = Path("/c/csc")  # Will be refactored to use platform.json later
PROJECT_ROOT = UMBRELLA_ROOT
```

2. **Replace the current repo_root() function** (around line 90–91):

Old:
```python
def repo_root() -> Path:
    return BASE_DIR.parent.parent
```

New:
```python
def repo_root() -> Path:
    return UMBRELLA_ROOT  # Return absolute path, no relative resolution
```

3. **After restructure is complete** (Phase 10), refactor this to read from platform.json or platform layer:

```python
def repo_root() -> Path:
    # TODO: Replace with platform.get_csc_root() or similar after restructure
    from csc_shared.platform import Platform
    return Platform().csc_root
```

**Reason**: Using absolute paths avoids runtime path.parent resolution bugs. After restructure, we'll refactor to use the Platform layer (which reads from platform.json).

### 4.6 File: irc/CLAUDE.md (formerly /c/csc/CLAUDE.md)

**Read this file** to find all path examples and references.

**Update all path examples in documentation**:
- /opt/csc/ → /c/csc/ (windows) or /opt/csc/ (Linux, if applicable)
- Workorders examples: workorders/ → ops/wo/
- Agents examples: agents/ → ops/agents/
- Code examples: packages/... → irc/packages/...
- Bin examples: bin/... → irc/bin/...

Update section headers, code blocks, and inline path references. Ensure consistency throughout.

---

## PART 5: Git and Submodule Setup

### 5.1 Initialize Git in /c/new_csc/ (umbrella repo)

1. cd /c/new_csc/
2. git init (fresh repo, clean history)
3. Create .gitignore file with contents that include:
   - *.pyc, __pycache__/, .pytest_cache/
   - .venv/, venv/
   - *.pid, *.log
   - csc-logs/, temp/, tmp/
   - memory.db*, (all credential files)
   - (copy relevant patterns from /c/csc/.gitignore)

4. Create .gitmodules file with contents:

```
[submodule "irc"]
    path = irc
    url = https://github.com/daveylongshaft/csc-irc
[submodule "ops"]
    path = ops
    url = https://github.com/daveylongshaft/csc-ops
```

5. Verify .gitmodules exists and is readable

### 5.2 Initialize Git in /c/new_csc/irc/ (code repo)

1. cd /c/new_csc/irc/
2. git init (fresh repo, clean history)
3. Copy .gitignore from existing csc/.gitignore (or create new one)
4. Add all files: git add .
5. Create first commit: git commit -m "Initial commit: CSC IRC protocol and code"
6. Add remote and push to GitHub:
   ```
   git remote add origin https://github.com/daveylongshaft/csc-irc
   git push -u origin main
   ```
   **After git push, check exit code**:
   - If exit code is 0: push succeeded, continue
   - If non-zero: push failed, report error and stop

   **Do NOT use sleep.** The git push command will block until complete.

### 5.3 Initialize Git in /c/new_csc/ops/ (operations repo)

1. cd /c/new_csc/ops/
2. git init (fresh repo, clean history)
3. Create .gitignore (empty or minimal — ops/ stores markdown, not code)
4. Add all files: git add .
5. Create first commit: git commit -m "Initial commit: CSC AI operations and workorders"
6. Add remote and push to GitHub:
   ```
   git remote add origin https://github.com/daveylongshaft/csc-ops
   git push -u origin main
   ```
   **After git push, check exit code**:
   - If exit code is 0: push succeeded, continue
   - If non-zero: push failed, report error and stop

   **Do NOT use sleep.** The git push command will block until complete.

### 5.4 Link Submodules in Umbrella Repo

1. cd /c/new_csc/
2. git submodule add https://github.com/daveylongshaft/csc-irc irc
   - **After git submodule add, check exit code** (if non-zero, stop and report error)
3. git submodule add https://github.com/daveylongshaft/csc-ops ops
   - **After git submodule add, check exit code** (if non-zero, stop and report error)
4. git add .gitmodules irc/ ops/
5. git commit -m "Add irc and ops submodules"
6. Verify: git submodule status (should show both submodules with correct URLs)

---

## PART 6: Agent Status Display Bug Fix

### 6.1 Read the File

File: /c/new_csc/irc/packages/csc-service/csc_service/shared/services/agent_service.py

**Read lines 664–741** (the status() method) carefully. Understand:
- How temp_wips is currently computed (currently at line 708)
- Where it's used in the "Running (from queue)" block (around line 700)
- How it's used in the "WIP files" block (around line 730)

### 6.2 Understand the Bug

The problem:
- Line 700 reads WIP size from MAIN REPO: self.WIP_DIR / prompt (stale)
- Line 708 computes temp_wips (live temp-repo WIP, not used in running block)
- Result: "Running from queue" shows stale size; "WIP files" shows live size

### 6.3 Apply the Fix

**Move the temp_wips computation UP**: Cut lines around 708 (temp_wips = self._find_temp_repo_wips()) and paste them BEFORE the running tasks loop (before line 700).

After the move:
- The running tasks block can now USE temp_wips.get() to prefer the live temp-repo WIP size
- The WIP files block still uses the same temp_wips variable
- Both blocks now show the SAME live size

**Expected change**: ~5 lines moved (no logic changes).

### 6.4 Verify the Fix

After moving, read the status() method again. Trace through:
1. temp_wips computed first? (Yes)
2. Running tasks block uses temp_wips? (Should show live size now)
3. WIP files block uses temp_wips? (Should still show live size)
4. Both blocks now read the same source? (Yes)

---

## PART 7: New API Runner (`irc/bin/cagent_run.py`)

### 7.1 Understand the Purpose

You're building a **streaming, synchronous API runner** that:
- Loads workorder markdown files
- Calls the Anthropic API with tool definitions (read_file, write_file, run_command, list_directory)
- Executes tool calls locally in real-time (not batch fire-and-forget)
- Uses prompt caching to save 90% on repeated context reads
- Writes progress to WIP files

This replaces the existing "batch API" approach with a streaming, cacheable runner.

### 7.2 Reusable Components (Already Exist)

Before writing anything new, review these existing files:

1. **irc/bin/claude-batch/common.py**
   - Contains: pricing tables, cost estimation, repo_root(), config loading
   - Reuse: all pricing and config functions

2. **irc/bin/claude-batch/cbatch_run.py**
   - Contains: workorder → Batch API format conversion
   - Reuse: the workorder parsing logic (how to extract title, content, etc.)

3. **irc/bin/batch-opus-impl-with-tools.py**
   - Contains: tool definitions (read_file, write_file, list_directory, run_command)
   - Reuse: all four tool definitions verbatim

4. **irc/bin/batch-execute-tools.py**
   - Contains: tool execution loop pattern
   - Reuse: how to parse tool_use blocks, execute locally, return tool_result

### 7.3 High-Level Structure of cagent_run.py

When you build this file, structure it as:

**Section 1: Imports and Setup**
- Import Anthropic client, pathlib, json, sys, argparse
- Set up logging

**Section 2: Load Reusable Components**
- Import tool definitions from batch-opus-impl-with-tools.py (or copy them)
- Import config loading from common.py
- Import pricing functions from common.py

**Section 3: File I/O and Tool Execution**
- read_file(path): read file content (8000 char limit)
- write_file(path, content): write file
- list_directory(path): list files
- run_command(cmd): execute bash, capture stdout/stderr (30s timeout)
- search_files(pattern): glob matching (NEW tool)
- execute_tool(tool_name, *args): dispatch to tool functions

**Section 4: Main Streaming Loop**
- Load workorder markdown
- Extract title and content
- Load CLAUDE.md + tools/INDEX.txt as CACHED system context (cache_control: ephemeral)
- Call client.messages.create() with streaming=True
- Loop: while stop_reason != "end_turn":
  - Read content blocks from response
  - If tool_use block: execute locally, collect tool_result
  - If text block: echo to stdout and WIP file
  - Send tool_result back, continue
- End loop when stop_reason == "end_turn"

**Section 5: CLI Interface**
- Argument parsing: --workorder, --agent, --model, --dry-run
- If --workorder: run single workorder
- If --agent: process all workorders in ops/agents/AGENT/queue/in/
- If --dry-run: print API payload with cache_control blocks (don't execute)

**Section 6: Async Handling** (if needed)
- Handle long-running tool calls without timeouts
- Retry logic for transient API errors
- Cost tracking and reporting

### 7.4 Prompt Caching Strategy

The key to 90% cost savings is caching the system context:

**System context (cached):**
- Block 1: Full CLAUDE.md file (~10KB)
  - cache_control: {"type": "ephemeral"}
- Block 2: tools/INDEX.txt + tree.txt (~8KB)
  - cache_control: {"type": "ephemeral"}

**User message (NOT cached, unique per workorder):**
- The workorder markdown content

This way:
- First call: write cost is 1.25x (includes cache write)
- 2nd call onward: input cost drops to 0.10x (cache hits)
- Break-even: call #2; 90% savings from call #3 onward

### 7.5 CLI Examples (Document These)

When built, the CLI should support:

```
# Run a single workorder
python irc/bin/cagent_run.py --workorder ops/wo/ready/my-task.md --model haiku

# Dry-run (print API payload, don't execute)
python irc/bin/cagent_run.py --workorder ops/wo/ready/my-task.md --dry-run

# Batch process all workorders for an agent
python irc/bin/cagent_run.py --agent haiku --model haiku

# Show cost estimate
python irc/bin/cagent_run.py --workorder ops/wo/ready/my-task.md --estimate
```

### 7.6 Integration with Queue System

After cagent_run.py is built:

1. Update packages/csc-service/csc_service/infra/queue_worker.py:
   - Add "claude-api" to KNOWN_AGENTS list
   - When agent == "claude-api", invoke cagent_run.py instead of subprocess.run(["csc-claude", ...])

2. Update packages/csc-service/csc_service/shared/services/agent_service.py:
   - Ensure agent status displays correctly for "claude-api" agent
   - Verify icon/color display for new agent type

---

## PART 8: Testing and Verification

### 8.1 Verify Folder Structure

After all moves, verify /c/new_csc/ layout:

```bash
ls -la /c/new_csc/
# Should see: irc/, ops/, csc-service.json, platform.json, .gitmodules, .gitignore, .git/

ls -la /c/new_csc/irc/
# Should see: packages/, bin/, tests/, tools/, benchmarks/, docs/, CLAUDE.md, README.md

ls -la /c/new_csc/ops/
# Should see: wo/, agents/, templates/ (if exists)

ls -la /c/new_csc/ops/agents/
# Should see: haiku/, sonnet/, opus/, claude-api/, gemini/ (all with queue/in and queue/work subdirs)
```

### 8.2 Verify Path Constants

For each updated file, trace the path resolution:

**agent_service.py, line 33:**
- Read the line and confirm it now says: PROJECT_ROOT / "ops" / "wo"
- Verify PROJECT_ROOT is set correctly (should be umbrella root /c/csc/)

**agent_service.py, line 662:**
- Read the line and confirm it now says: PROJECT_ROOT / "ops" / "agents"

**queue_worker.py, lines 54–58:**
- Read the lines and confirm all "workorders" → "ops/wo" and "agents" → "ops/agents"

**bin/agent, line 46:**
- Read the line and trace the path: __file__ = irc/bin/agent → .parent = irc/bin/ → .parent.parent = irc/ → .parent.parent.parent = umbrella root
- Confirm it resolves to /c/csc/ (umbrella root)

**CLAUDE.md:**
- Read section on "File Locations & What's Where" and verify all path examples updated
- Read "Common Commands" and verify workorder examples use ops/wo/ and ops/agents/

### 8.3 Verify Git Repos

1. Verify GitHub repos exist and are private:
   ```bash
   gh repo view daveylongshaft/csc --json visibility        # Should return "PRIVATE"
   gh repo view daveylongshaft/csc-irc --json visibility    # Should return "PRIVATE"
   gh repo view daveylongshaft/csc-ops --json visibility    # Should return "PRIVATE"
   ```

2. Verify submodules are linked:
   ```bash
   cd /c/new_csc/
   git submodule status                           # Should show both irc and ops
   ```

3. Verify irc/ and ops/ have their own git histories:
   ```bash
   cd /c/new_csc/irc/
   git log --oneline | head -3                    # Should show fresh history
   cd /c/new_csc/ops/
   git log --oneline | head -3                    # Should show fresh history
   ```

### 8.4 Verify cagent_run.py (After Built)

1. Test with --dry-run:
   ```bash
   python /c/new_csc/irc/bin/cagent_run.py --workorder /c/new_csc/ops/wo/ready/test-task.md --dry-run
   # Should print API payload with cache_control blocks (no API call)
   ```

2. Verify cache_control blocks are present:
   - Look for "cache_control": {"type": "ephemeral"} in the output
   - Should appear for CLAUDE.md and tools/INDEX.txt blocks
   - Should NOT appear for the workorder content

3. Test with a simple workorder:
   ```bash
   python /c/new_csc/irc/bin/cagent_run.py --workorder /c/new_csc/ops/wo/ready/test-task.md --model haiku
   # Should execute the workorder and write WIP progress
   ```

### 8.5 Verify agent status Display

After the bug fix, test agent status:

```bash
cd /c/new_csc/irc/
python -m csc_service.shared.services.agent_service   # Or however you invoke status

# Verify output shows:
# - "Running (from queue)" displays LIVE WIP size (from temp repo)
# - "WIP files" displays SAME size (both reading from temp_wips)
# - No size mismatch between the two sections
```

---

## PART 9: Final Verification and Swap

### 9.1 Summary Checklist

Before proceeding to the final swap, verify:

- [ ] /c/new_csc/irc/ contains all code (packages/, bin/, tests/, etc.)
- [ ] /c/new_csc/ops/ contains all AI instructions (wo/, agents/)
- [ ] All path constants updated (6 files, confirmed by reading)
- [ ] All GitHub repos created (csc, csc-irc, csc-ops are private)
- [ ] All GitHub repos deleted (syscmdr, syscmdr-II, systemcommander are gone; 404 on view)
- [ ] Git submodules linked (git submodule status shows both)
- [ ] CLAUDE.md updated with new paths
- [ ] agent_service.py: temp_wips computed before running tasks block
- [ ] cagent_run.py built and --dry-run works
- [ ] cagent_run.py shows cache_control blocks

### 9.2 Final Swap

Once all verification passes:

1. Rename old repo (backup):
   ```bash
   cd /c/
   mv csc csc_old
   # /c/csc -> /c/csc_old (backup, can be deleted later)
   ```

2. Rename new staging repo (activate):
   ```bash
   mv new_csc csc
   # /c/new_csc -> /c/csc (new structure, active)
   ```

3. Verify the swap:
   ```bash
   ls -la /c/ | grep csc
   # Should see: csc/ (the new one), csc_old/ (backup), csc-test-runner/ (unaffected)

   ls -la /c/csc/
   # Should see: irc/, ops/, .gitmodules, .git/ (umbrella)
   ```

4. Test critical paths:
   ```bash
   cd /c/csc/
   ls irc/bin/
   # Should list: csc-ctl, agent, workorders, claude-batch/, cagent_run.py, etc.

   ls ops/wo/
   # Should list: ready/, wip/, done/, hold/, archive/, results/, batch/

   ls ops/agents/
   # Should list: haiku/, sonnet/, opus/, claude-api/, gemini/
   ```

---

## PART 10: Post-Swap Tasks (After Swap Complete)

These happen AFTER the folder swap, not before:

### 10.1 Reinstall Packages

```bash
cd /c/csc/irc/
pip install -e packages/csc-shared
pip install -e packages/csc-server
pip install -e packages/csc-service
# (install others as needed)
```

### 10.2 Refresh Project Maps

```bash
cd /c/csc/
refresh-maps  # Updates tools/, tree.txt, p-files.list for new folder structure
```

### 10.3 Verify Test Runner Still Works

```bash
cd /c/csc/
python bin/test-runner --help   # Should work
# Or wherever test-runner is located in new bin/
```

### 10.4 Update Instruction History

Add this line to /c/csc/instruction_history.log:
```
2026-03-05T HH:MM | COMPLETED: CSC Major Restructure — repos split, folders reorganized, agent status fixed, cagent_run.py built with prompt caching
```

### 10.5 Clean Up Backup (Optional)

After verifying the swap works:
```bash
rm -rf /c/csc_old/                   # Delete old backup (or keep for safety)
rm -rf /tmp/backups/                 # Delete GitHub repo tarballs (or keep for archival)
rm -rf /c/new_csc/                   # Should not exist (renamed to csc)
```

---

## Expected Outcome

After all steps complete:

1. **Repos**: Five old repos archived and deleted; three new private repos created and linked
2. **Folders**: All code under irc/; all instructions under ops/
3. **Paths**: All constants updated and verified
4. **Bug Fixed**: agent status display shows correct (live) WIP sizes
5. **New Tool**: cagent_run.py ready to stream API calls with prompt caching
6. **Integration**: claude-api agent added to known agents; queue-worker ready to use cagent_run.py
7. **Staged**: /c/csc/ fully restructured and ready for use

---

## Notes for Execution

- **Read before modifying**: Always read a file to confirm line numbers and context before making edits
- **Test as you go**: After each major section, verify the change took effect
- **Paths are critical**: Small path errors cascade to all tools. Triple-check path constants
- **Git history**: Fresh histories on all new repos (no merge conflicts with old branches)
- **Backup tarballs**: Keep GitHub repo tarballs for 30+ days before deletion
- **Ask for clarification**: If any step is ambiguous, ask the user before proceeding

---

## Questions for User (Before Starting)

Before you start work, confirm:

1. What is USER (your GitHub username)? Used in all repo URLs.
2. Should csc_old/ backup be deleted after swap verification, or kept long-term?
3. Is there any critical state in /c/csc/agents/ (active WIP files) that must be preserved? If yes, ensure ops/agents/ has full copies.

Good luck! This is a major restructure. Go slow, verify everything, and you'll have a clean, scalable architecture.

