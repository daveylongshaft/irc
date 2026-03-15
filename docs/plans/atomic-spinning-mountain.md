# Universal Agent Wrapper Implementation Plan

## Context

The current `dc-agent-wrapper` was originally designed for docker-coder but is now used for all agents. We need to:
1. Rename it to `agent-wrapper` to reflect its universal purpose
2. Add template-based queue integration so agents receive standardized task files
3. Ensure the wrapper works consistently for all agent types (cloud, local, docker tools)

The wrapper already handles most required functionality:
- Git operations (pull before, commit/push after)
- Prompt movement (ready → wip → done/ready)
- COMPLETE marker detection
- Map refresh before commits

**What's new:** Template system that copies standardized task files to `agents/<agent>/queue/in/` with references to `prompts/wip/prompt.md` and `README.1shot`.

---

## Implementation Steps

### 1. Create Template System

**New directory:** `C:\csc\agents\templates\`

**Files to create:**

**`agents/templates/default.md`:**
```markdown
# Agent Task: {prompt_name}

## Assignment
- Agent: {agent_name}
- Model: {model}
- Started: {timestamp}

## Task Context

**Prompt File:** `prompts/wip/{prompt_filename}`
**Project Guide:** `README.1shot`

Read both files above for full context and guidelines.

## Task Description

{prompt_content}

## Work Log

PID: {pid}
Agent: {agent_name}
Model: {model}
Started: {timestamp}

---
### Agent work log (append steps below):

```

**`agents/templates/README.md`:**
```markdown
# Agent Task Templates

Templates in this directory are used by the agent-wrapper to create standardized task files in agent queue directories.

## Variables

Templates support these placeholders:
- `{prompt_name}` - Human-readable task name
- `{agent_name}` - Agent identifier (e.g., "ollama-qwen")
- `{timestamp}` - ISO 8601 timestamp
- `{prompt_filename}` - Actual WIP filename
- `{prompt_content}` - Full prompt text
- `{model}` - Model being used
- `{pid}` - Process ID (filled after spawn)

## Usage

When `agent assign <prompt> <agent>` is called, the wrapper:
1. Reads `default.md`
2. Substitutes variables
3. Copies to `agents/<agent>/queue/in/<prompt>.md`
4. Queue worker picks up and processes
```

---

### 2. Rename and Update Wrapper

**A. Copy wrapper files:**
```bash
cp bin/dc-agent-wrapper bin/agent-wrapper
cp bin/dc-agent-wrapper.bat bin/agent-wrapper.bat
```

**B. Update `bin/agent-wrapper.bat` (line 2):**
```batch
@echo off
python "%~dp0agent-wrapper" %*
```

**C. Add template copying function to `bin/agent-wrapper` (insert after line 102):**

```python
def copy_template_to_queue(agent_name, prompt_filename, template_vars):
    """Copy template to agent's queue/in/ directory with variable substitution."""
    template_file = CSC_ROOT / "agents" / "templates" / "default.md"
    if not template_file.exists():
        log_message(f"WARNING: Template not found at {template_file}, skipping queue copy")
        return False

    # Read template
    template_content = template_file.read_text(encoding='utf-8')

    # Substitute variables
    for key, value in template_vars.items():
        template_content = template_content.replace(f"{{{key}}}", str(value))

    # Write to queue/in/
    queue_in_dir = CSC_ROOT / "agents" / agent_name / "queue" / "in"
    queue_in_dir.mkdir(parents=True, exist_ok=True)

    queue_file = queue_in_dir / prompt_filename
    queue_file.write_text(template_content, encoding='utf-8')
    log_message(f"Copied template to {agent_name}/queue/in/{prompt_filename}")
    return True
```

**D. Update main() function (around line 236-302):**

Add `--queue-mode` flag support and call template copy:

```python
# After line 238, update usage:
if len(sys.argv) < 6:
    log_message("Usage: agent-wrapper <prompt_filename> <agent_name> <model> <log_file> <wip_file> [--use-file <prompt_file>] [--queue-mode]")
    sys.exit(1)

# After line 251, check for queue mode:
queue_mode = "--queue-mode" in sys.argv

# After line 284 (after reading prompt_file), add queue copy:
if queue_mode:
    prompt_content = prompt_file.read_text(encoding='utf-8')
    template_vars = {
        'prompt_name': prompt_filename.replace('.md', '').replace('_', ' ').title(),
        'agent_name': agent_name,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'prompt_filename': prompt_filename,
        'prompt_content': prompt_content,
        'model': model,
        'pid': 'pending'
    }
    copy_template_to_queue(agent_name, prompt_filename, template_vars)
```

**E. Update header docstring (lines 1-26):**
- Change script name from `dc-agent-wrapper` to `agent-wrapper`
- Add `[--queue-mode]` to usage examples

---

### 3. Update Agent Service

**File:** `packages/csc-shared/services/agent_service.py`

**A. Update wrapper path (line 438):**
```python
wrapper_script = self.PROJECT_ROOT / "bin" / "agent-wrapper"
```

**B. Add queue mode flag (line 469, add after `str(prompt_file)`):**
```python
wrapper_cmd = [
    sys.executable if sys.executable else "python3",
    str( wrapper_script ),
    wip_path.name,
    agent_binary,
    model,
    str( log_file ),
    str( wip_path ),
    "--use-file",
    str( prompt_file ),
    "--queue-mode"  # NEW: Enable queue template copying
]
```

---

### 4. Update Queue Worker (Backward Compatibility)

**File:** `packages/csc-shared/services/queue_worker_service.py`

**Update `find_wrapper()` method (around line 66-82):**

```python
def find_wrapper(self):
    """Find the wrapper script (agent-wrapper with fallback to dc-agent-wrapper)."""
    wrapper_candidates = [
        self.BIN_DIR / "agent-wrapper",
        self.BIN_DIR / "agent-wrapper.py",
    ]

    if self.IS_WINDOWS:
        wrapper_candidates.extend([
            self.BIN_DIR / "agent-wrapper.bat",
            self.BIN_DIR / "agent-wrapper.exe",
        ])

    # Fallback to old name for backward compatibility
    wrapper_candidates.extend([
        self.BIN_DIR / "dc-agent-wrapper",
        self.BIN_DIR / "dc-agent-wrapper.py",
    ])

    for wrapper in wrapper_candidates:
        if wrapper.exists():
            return str(wrapper)

    return None
```

---

### 5. Update Documentation

**File:** `CLAUDE.md`

Find and replace all references to `dc-agent-wrapper` with `agent-wrapper`.

Key sections to update:
- Git workflow section
- Background services section
- Any command examples

---

## Critical Files

| File | Changes | Lines |
|------|---------|-------|
| `bin/agent-wrapper` | Rename from dc-agent-wrapper, add template copy | 103-120, 236-302 |
| `bin/agent-wrapper.bat` | Rename, update reference | 2 |
| `packages/csc-shared/services/agent_service.py` | Update wrapper path, add queue flag | 438, 469 |
| `packages/csc-shared/services/queue_worker_service.py` | Add backward compatibility | 66-82 |
| `agents/templates/default.md` | NEW - Template definition | - |
| `agents/templates/README.md` | NEW - Template docs | - |
| `CLAUDE.md` | Update wrapper references | Multiple |

---

## Testing Plan

### Manual Tests

**1. Template Creation Test:**
```bash
# Verify template exists
cat agents/templates/default.md
```

**2. Queue Integration Test:**
```bash
# Create test prompt
echo "# Test task" > prompts/ready/test-wrapper.md

# Assign to agent
agent assign test-wrapper.md ollama-qwen

# Verify template appeared in queue
ls -la agents/ollama-qwen/queue/in/
cat agents/ollama-qwen/queue/in/test-wrapper.md
```

**3. Full Integration Test:**
```bash
# Create benchmark
benchmark add hello-wrapper "echo hello"

# Run with agent
benchmark run hello-wrapper haiku

# Monitor
tail -f logs/agent_*.log
```

**4. Backward Compatibility Test:**
```bash
# Verify old wrapper still exists temporarily
ls -la bin/dc-agent-wrapper

# Verify queue worker finds new wrapper
queue-worker cycle
```

---

## Verification Checklist

After implementation:

- [ ] `agents/templates/default.md` created with all placeholders
- [ ] `bin/agent-wrapper` renamed and includes `copy_template_to_queue()`
- [ ] `bin/agent-wrapper.bat` calls correct script
- [ ] Agent service uses new wrapper path and passes `--queue-mode`
- [ ] Queue worker finds new wrapper (with fallback)
- [ ] Template appears in `agents/<agent>/queue/in/` after assignment
- [ ] Template contains correct variable substitutions
- [ ] Prompts still move through ready → wip → done flow
- [ ] Git operations still work (pull, refresh-maps, commit, push)
- [ ] COMPLETE marker detection still works
- [ ] All agent types work (cloud, local, docker tools)
- [ ] Documentation updated in CLAUDE.md

---

## Rollback Plan

If issues arise:
1. Revert agent_service.py to use `dc-agent-wrapper`
2. Keep both wrappers until stable
3. Test with single agent type before enabling for all

The old `dc-agent-wrapper` remains functional during transition.
