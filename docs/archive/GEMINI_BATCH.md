# Gemini Batch API Tools

Location: `bin/gemini-batch/`
Merged: PR #3 (Jules, 2026-03-06)
Tests: `irc/tests/test_gbatch_tools.py`
Requirement: `pip install google-genai` (GOOGLE_API_KEY env var)

---

## Overview

`bin/gemini-batch/` provides Gemini's equivalent of the Claude batch executor: a synchronous
tool loop and a batch API runner that lets Gemini agents execute workorders via the Google
GenAI Batch API, with full local tool execution (read/write files, run commands, search code).

Two execution modes:

| Mode | Script | Use when |
|------|--------|----------|
| **Tool loop** (synchronous, real-time) | `gbatch_tool_run.py` | Small workorders, immediate feedback |
| **Batch API loop** (async, cost-effective) | `gbatch_executor.py` | Long workorders, overnight runs |

---

## Files

| File | Purpose |
|------|---------|
| `gbatch_tools.py` | Tool implementations + `ToolExecutor` dispatcher |
| `gbatch_convert.py` | Workorder `.md` → Gemini JSONL converter + frontmatter parser |
| `gbatch_run.py` | Batch API job creation, polling, result retrieval |
| `gbatch_executor.py` | Continuous batch API tool loop (create → poll → execute → resubmit) |
| `gbatch_tool_run.py` | Synchronous (non-batch) tool loop via `generate_content` |

---

## Quick Start

### Synchronous Tool Loop (recommended for development)

```bash
export GOOGLE_API_KEY=your_key
python bin/gemini-batch/gbatch_tool_run.py ops/wo/ready/your-workorder.md
```

### Batch API Loop (cost-effective for production)

```bash
export GOOGLE_API_KEY=your_key
python bin/gemini-batch/gbatch_executor.py ops/wo/ready/your-workorder.md
python bin/gemini-batch/gbatch_executor.py ops/wo/ready/your-workorder.md --model gemini-2.5-pro --max-rounds 20
```

### Convert Workorder to JSONL (for manual batch submission)

```bash
# Single workorder
python bin/gemini-batch/gbatch_convert.py to-jsonl ops/wo/ready/myworkorder.md --out batch.jsonl

# Directory of workorders
python bin/gemini-batch/gbatch_convert.py batch to-jsonl ops/wo/ready/ --out batch.jsonl

# Parse batch results back to Markdown
python bin/gemini-batch/gbatch_convert.py from-results results.jsonl --out summary.md
```

---

## Workorder Frontmatter

Workorders can include YAML frontmatter to override model and set metadata:

```markdown
---
model: gemini-2.5-pro
priority: P1
agent: gemini
---

Your workorder instructions here.
```

Supported frontmatter keys:
- `model` — override default model (`gemini-2.5-flash`)
- `priority` — metadata only, not used by executor
- `agent` — metadata only

---

## Available Tools

`ToolExecutor` exposes these tools to the model:

| Tool | Description | Key safety constraint |
|------|-------------|----------------------|
| `read_file(path)` | Read file contents | Path must resolve under CSC_ROOT |
| `write_file(path, content)` | Write/overwrite file | Creates parent dirs; path must resolve under CSC_ROOT |
| `list_directory(path)` | List directory entries | Path must resolve under CSC_ROOT |
| `run_command(command, cwd)` | Execute shell command | Blocks: `rm -rf /`, `git push --force`, `git reset --hard`, `git rebase`, writes to `/etc|/sys|/dev` |
| `glob_files(pattern, base)` | Find files by glob | Returns relative paths |
| `search_files(pattern, path, file_glob)` | Grep files by regex | Returns `file:line:content` format |

### Path Resolution

All paths are resolved against `CSC_ROOT` (the project root, detected as the directory three
levels above `bin/gemini-batch/`). This prevents path traversal:

```python
_resolve_path("../../etc/passwd")  # raises ValueError: Path traversal detected
_resolve_path("/etc/passwd")       # rerooted to CSC_ROOT/etc/passwd (still safe)
```

---

## Batch API Loop Architecture

`gbatch_executor.py` implements the loop:

```
1. Parse workorder (frontmatter + body)
2. For each round (up to max_rounds):
   a. Serialize conversation + tools to JSONL
   b. Upload JSONL file to Gemini Files API
   c. Submit batch job → get job_name
   d. Poll until COMPLETED (every 15s)
   e. Download results
   f. If response has no function_calls → DONE (save result file)
   g. If response has function_calls → execute locally, append responses, go to step a
```

Results are saved as `<workorder_stem>_result.md` alongside the input file.

---

## Synchronous Tool Loop Architecture

`gbatch_tools.py:ToolExecutor.run_tool_loop()` runs the same logic using
`client.models.generate_content()` directly (no batch submission). Faster for
interactive/debug use.

---

## Relation to Claude Batch Tools

The Gemini tools mirror the Claude batch tools in `bin/claude-batch/`. Key differences:

| Aspect | Claude (`bin/claude-batch/`) | Gemini (`bin/gemini-batch/`) |
|--------|-------------------------------|-------------------------------|
| API | Anthropic Messages Batch API | Google GenAI Batch API |
| Auth | `ANTHROPIC_API_KEY` | `GOOGLE_API_KEY` |
| Tool format | `tool_use` / `tool_result` | `functionCall` / `functionResponse` |
| Batch state file | `batch_state.json` | `batch_state.json` |
| Common converter | `common.py` | `gbatch_convert.py` (standalone) |

---

## Tests

```bash
cd irc
python -m pytest tests/test_gbatch_tools.py -v
```

Tests cover (34 cases, no google-genai required):
- Path traversal prevention (`_resolve_path`)
- `read_file`, `write_file`, `list_directory` — happy path + error cases
- `run_command` — safety blocks (rm -rf, force push, hard reset)
- `glob_files`, `search_files`
- `ToolExecutor.execute` dict-dispatch (all 6 tools + unknown)
- `parse_frontmatter` — valid, no-frontmatter, unclosed, empty block
- `load_system_context` — graceful missing file handling
