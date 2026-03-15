# Plan: Give cagent agents full tool access + revert WIP append

## Context
cagent exec agents currently have no tools — they can only generate text to stdout. The system rule tells agents to `echo >> prompts/wip/...` but without shell/file tools, they can't. A hack was added to queue-worker to append stdout to WIP, but that bloats WIP files with raw model output. Instead, give cagent the tools so agents can journal to WIP themselves.

## Changes

### 1. Update all 11 `agents/<name>/cagent.yaml` files
Add `tools` section with file and shell access:
```yaml
    tools:
      - name: read_file
      - name: write_file
      - name: run_terminal_cmd
```

Files: `claude`, `haiku`, `opus`, `gemini`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-3-flash`, `gemini-3-pro`, `qwen`, `deepseek`, `codellama`

### 2. Revert queue-worker WIP append logic
Remove the block in `process_work()` that appends agent log output to WIP (lines added in previous edit). The agent will write COMPLETE to WIP itself via tools.

File: `bin/queue-worker` — remove the `_find_agent_log` helper and the "Append cagent output" block in `process_work()`.

### 3. Stop benchmark poller, clean stale WIP
Clean up `prompts/wip/benchmark-hello-world-1771686848.md` and queue files from the failed run.

## Verification
- Run `benchmark run hello-world codellama`
- Trigger `queue-worker`
- Agent should use `run_terminal_cmd` to echo steps to WIP and write COMPLETE
- Benchmark poller detects COMPLETE, archives result
