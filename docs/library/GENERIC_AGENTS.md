# Generic Agents - Simple Task Execution

Generic agents are simple, focused workers that execute specific tasks without needing to understand the orchestration system.

**Key difference from code-fixer:**
- ✅ Code-fixer: Finds and fixes bugs (specialized)
- ✅ Generic agents: Any focused task (analysis, review, generation, etc.)

## Quick Start

### 1. Create a Prompt File

File: `workorders/wip/generic-code-review.md`

```markdown
---
agent: generic-agent
model: qwen:7b
---

# Code Review: ChannelManager

## Task
Review packages/csc-server/csc_server/channel.py

## Requirements
- Check for bugs
- Find design issues
- Suggest improvements

## Acceptance
- Review complete and documented
- Issues listed with severity
- Suggestions provided

## Work Log

(Agent journals here)
```

### 2. Agent Starts Service

```bash
agent-control start generic-agent
```

### 3. Agent Processes Prompt

Agent reads prompt file and:
1. Understands the task
2. Uses code maps to find target files
3. Reads and analyzes code
4. Journals findings
5. Journals COMPLETE

```markdown
## Work Log

Found ChannelManager via tools/INDEX.txt at packages/csc-server/csc_server/channel.py
Read channel.py - analyzed add_channel(), validate_channel_name(), get_channel()
Found issue: Line 42 missing validation on empty channel names
Created detailed review in REVIEW.md
COMPLETE
```

### 4. Wrapper Processes

Wrapper script:
- Sees COMPLETE marker
- Runs refresh-maps
- Commits changes
- Pushes to remote

## How It Works

### Code Maps Available

Generic agents have read-only access to:

**tools/INDEX.txt** - API map
```
csc-server:
  ChannelManager
    - add_channel(name)
    - get_channel(name)
    - validate_channel_name(name)
```

**tree.txt** - Directory structure
```
packages/csc-server/
├── csc_server/
│   ├── channel.py
│   ├── server.py
│   └── storage.py
└── tests/
```

**p-files.list** - All files
```
./packages/csc-server/csc_server/channel.py
./packages/csc-server/tests/test_channel.py
```

**tests.txt** - Test infrastructure
```
Test Location: tests/ and packages/*/tests/
Test Pattern: test_*.py
Framework: pytest
```

### Agent Workflow

```
Read prompt (task description)
    ↓
Use code maps to locate code
    ↓
Read source files
    ↓
Do analysis/generation/review/etc
    ↓
Journal each step in prompt file
    ↓
Print COMPLETE
    ↓
Wrapper handles git operations
```

### Journaling

Agent appends to Work Log section of prompt file:

```bash
echo "Found ChannelManager in INDEX.txt" >> workorders/wip/task.md
echo "Read implementation at packages/csc-server/csc_server/channel.py" >> workorders/wip/task.md
echo "Identified issue: missing validation on line 42" >> workorders/wip/task.md
echo "Created detailed review" >> workorders/wip/task.md
echo "COMPLETE" >> workorders/wip/task.md
```

## Prompt Format

### YAML Front-Matter

```yaml
---
agent: generic-agent
model: qwen:7b
timeout: 10
stall_timeout: 120
---
```

**Fields:**
- `agent`: "generic-agent"
- `model`: Which local model to use (qwen:7b, deepseek-coder:6.7b, etc.)
- `timeout`: Max time in minutes
- `stall_timeout`: Kill if no output for N seconds

### Sections

```markdown
# Task Title

## Task
What needs to be done

## Requirements
Acceptance criteria

## Acceptance
How to know it's done

## Work Log
(Agent journals here)
```

## Example Generic Agents

### Code Reviewer

```markdown
# Code Review: Server.py

## Task
Review packages/csc-server/csc_server/server.py

## Requirements
- Check for correctness
- Find performance issues
- Identify security concerns
- Suggest improvements

## Acceptance
- Detailed review created
- Issues documented with severity
- Suggestions provided

## Work Log
```

### Documentation Generator

```markdown
# Generate API Docs for Storage

## Task
Create API documentation for packages/csc-server/csc_server/storage.py

## Requirements
- Document all public classes and methods
- Include parameters and return types
- Add usage examples
- Explain the atomic write pattern

## Acceptance
- docs/storage_api.md created
- Complete API documentation
- Examples and explanations included

## Work Log
```

### Dependency Analyzer

```markdown
# Analyze Dependencies in csc-server

## Task
Find unused imports and potential circular dependencies

## Requirements
- Check all .py files in csc-server package
- List unused imports
- Find circular dependency chains
- Identify suspicious patterns

## Acceptance
- dependencies.md report created
- All issues documented
- Suggestions for fixes provided

## Work Log
```

### Test Coverage Analyzer

```markdown
# Analyze Test Coverage for Channel Module

## Task
Assess test coverage and find gaps

## Requirements
- Check what's tested in test_channel.py
- Find untested code paths
- Identify critical gaps
- Suggest test additions

## Acceptance
- Coverage analysis created
- Gap analysis complete
- Test suggestions provided

## Work Log
```

## Monitoring Progress

### While Running

```bash
# Watch agent process
tail -f workorders/wip/task.md
```

### After Completion

```bash
# View completed work
cat workorders/done/task.md

# View git commit
git log -1 --stat

# View changes
git show HEAD
```

## What Agents CAN Do

✅ Read code files
✅ Navigate using code maps
✅ Analyze code patterns
✅ Generate documentation
✅ Create new files
✅ Modify existing files
✅ Write tests
✅ Create reports
✅ Review and critique code
✅ Journal findings

## What Agents DON'T Need to Know

❌ Git workflows
❌ How to refresh maps
❌ Commit/push operations
❌ Orchestration system details
❌ How other agents work
❌ CI/CD pipelines
❌ Test runners

## Creating Custom Generic Agents

To create a new specialized generic agent (e.g., code-style-fixer, api-endpoint-documenter):

1. **Create new agent directory:**
   ```bash
   mkdir -p agents/my-agent/context
   ```

2. **Create context/system.md:**
   - Explain the task focus
   - Show how to use code maps
   - Give examples

3. **Create state.json:**
   - Agent name and description
   - Capabilities
   - Example tasks

4. **Create example prompts:**
   - In workorders/ready/ with agent prefix
   - Show what kind of tasks it handles

5. **Usage:**
   ```bash
   agent-control start my-agent
   ```

## Integration with Existing System

### Fits Into Prompt Queue

Generic agents work with the existing `workorders/ready/` → `wip/` → `done/` system:

1. Create prompt in `workorders/ready/`
2. Agent moves to `workorders/wip/`
3. Agent processes and journals
4. Wrapper moves to `workorders/done/` and commits

### Uses Code Maps

Generic agents can read:
- `tools/INDEX.txt` for API structure
- `tree.txt` for directory layout
- `p-files.list` for file discovery
- `tests.txt` for test setup

### Wrapper Handles Post-Work

After agent exits with COMPLETE:
- `refresh-maps --quick` updates tools/
- `git add -A` stages changes
- `git commit` with auto-generated message
- `git push` to remote

## Examples of Generic Agent Tasks

- Code quality review
- Security audit
- Documentation generation
- Test coverage analysis
- Platform compatibility check
- Dependency audit
- Performance analysis
- Architecture review
- Code duplication finding
- Error handling audit
- API documentation
- Configuration documentation
- Design pattern identification
- Refactoring suggestions
- Migration planning

Each is a focused, single-purpose agent that:
- Understands its domain
- Uses code maps to navigate
- Does its job
- Journals what it did
- Exits cleanly

The wrapper takes it from there.

## Summary

Generic agents are simple, focused workers that:
- ✅ Receive a clear task in a prompt file
- ✅ Use code maps to understand the codebase
- ✅ Do their work
- ✅ Journal their steps
- ✅ Exit with COMPLETE
- ❌ Don't need orchestration knowledge
- ❌ Don't commit, push, or refresh maps
- ❌ Don't coordinate with the system

They're focused, effective, and reusable for any analysis/generation task.
