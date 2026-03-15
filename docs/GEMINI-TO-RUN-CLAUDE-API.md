# Running Claude API Batches When Anthropic Keys Are Exhausted

**Purpose**: When Anthropic API keys run out of credits, Gemini (or any agent) can submit work to the Claude Batch API and monitor completion. This allows work to continue seamlessly across API providers without manual intervention.

**TL;DR**: Use `bin/claude-batch/cbatch_queue_run.py` from any agent. It handles submission, polling, and cost tracking.

---

## Architecture

```
Queue-Worker (any agent: Gemini, ChatGPT, etc.)
    |
    v
Creates batch_config.json entries with workorder details
    |
    v
cbatch_queue_run.py submits JSONL to Claude Batch API
    |
    v
Polls job status every 30s (non-blocking, async)
    |
    v
Job completes -> Results downloaded
    |
    v
Workorder marked COMPLETE
    |
    v
Next workorder proceeds
```

**Key Insight**: Batches run **async** - Gemini doesn't wait. It submits and moves on.

---

## Prerequisites

### API Keys Required

**Claude Batch API**:
- `ANTHROPIC_API_KEY` - Must be set in environment (separate from claude-claude instances)
- Can use **different Anthropic accounts** for batch vs. interactive
- Recommended: Use a dedicated account for batch work

**Set in shell**:
```bash
export ANTHROPIC_API_KEY="sk-ant-v0-..."  # Batch API key (different account OK)
```

Or in `.env`:
```
ANTHROPIC_API_KEY=sk-ant-v0-...
```

### Verify Setup

```bash
python -c "from anthropic import Anthropic; c = Anthropic(); print('[OK] Batch API ready')"
```

---

## Workflow: Submit Workorders to Claude Batch API

### Step 1: Create Workorder Entry in batch_config.json

**Location**: `/c/csc/bin/claude-batch/batch_config.json`

**Add Entry**:
```bash
python /c/csc/bin/claude-batch/cbatch_add.py \
  /c/csc/workorders/ready/my-workorder.md \
  --model claude-opus-4-6 \
  --provider anthropic  # Explicit provider (optional, defaults to anthropic)
```

**Result**: Entry added to `batch_config.json`:
```json
{
  "entry_id": "1772345678-my-workorder",
  "filename": "my-workorder.md",
  "model": "claude-opus-4-6",
  "provider": "anthropic",
  "status": "pending",
  "submitted_at": null,
  "job_name": null
}
```

### Step 2: Submit Batch Job

**Command**:
```bash
python /c/csc/bin/claude-batch/cbatch_run.py run \
  /c/csc/bin/claude-batch/batch_config.json \
  --agent anthropic
```

**Process**:
1. Loads all pending entries from `batch_config.json`
2. Filters to `"provider": "anthropic"` only
3. Converts workorder `.md` files → JSONL format
4. Uploads JSONL to Anthropic Files API
5. Creates batch job via `client.messages.batch.create()`
6. Saves job metadata to `batch_state.json`
7. Starts polling (30s interval)

**Example Output**:
```
[2026-03-03 21:30:15] Submitting batch: 3 entries
[2026-03-03 21:30:15] Uploading JSONL to Anthropic Files API
[2026-03-03 21:30:20] File uploaded: file-ABC123xyz
[2026-03-03 21:30:25] Batch job created: batch_ABC123xyz
[2026-03-03 21:30:25] Polling status every 30s...
[2026-03-03 21:31:05] Status: PROCESSING (1/3 completed)
[2026-03-03 21:31:35] Status: PROCESSING (2/3 completed)
[2026-03-03 21:32:05] Status: COMPLETED
[2026-03-03 21:32:10] Downloaded results: batch_results_20260303_213210.jsonl
[2026-03-03 21:32:15] Estimated tokens: 45,123 input + 12,456 output
[2026-03-03 21:32:15] Estimated cost: $0.68 (at standard rates, no batch discount applied)
```

---

## Monitoring Batch Progress

### Check Job Status (Interactive)

```bash
# While job is running
python /c/csc/bin/claude-batch/cbatch_run.py status \
  --job-name batch_ABC123xyz
```

**Output**:
```
Job: batch_ABC123xyz
Status: PROCESSING
Progress: 2/3 completed
Submitted: 2026-03-03 21:30:25
Estimated completion: ~5 minutes
```

### Retrieve Results After Completion

```bash
python /c/csc/bin/claude-batch/cbatch_run.py retrieve \
  --job-name batch_ABC123xyz \
  --out /c/csc/batch_results_final.jsonl
```

**Process**:
1. Fetches final results from Anthropic
2. Saves to `batch_results_final.jsonl`
3. Extracts text from each result
4. Writes markdown summaries to workorder files

**Example Results File**:
```jsonl
{"id": "1772345678-my-workorder", "result": {"type": "text", "text": "Claude's response to workorder..."}}
{"id": "1772345679-another", "result": {"type": "text", "text": "Next workorder response..."}}
```

---

## Cost Estimation & Pricing

### Batch API Pricing (vs Interactive)

| Model | Interactive | Batch | Savings |
|-------|-----------|-------|---------|
| claude-opus-4-6 | $15/1M input, $75/1M output | $7.5/1M input, $37.5/1M output | **50% discount** |
| claude-sonnet-4-6 | $3/1M input, $15/1M output | $1.5/1M input, $7.5/1M output | **50% discount** |
| claude-haiku-3-5 | $0.80/1M input, $4/1M output | $0.40/1M input, $2/1M output | **50% discount** |

### Track Tokens & Cost

After batch completes:
```bash
# Results file shows token counts
cat /c/csc/batch_results_20260303_213210.jsonl | jq '.usage'

# Example output:
# {
#   "input_tokens": 45123,
#   "output_tokens": 12456
# }

# Manual cost calculation:
# Opus input: (45123 / 1000000) * $7.50 = $0.34
# Opus output: (12456 / 1000000) * $37.50 = $0.47
# Total: $0.81 (vs $2.72 interactive)
```

---

## Handling Batch Failures

### Common Issues

**Issue 1: Job Failed**
```
Status: FAILED
Error: "Request timed out"
```

**Fix**:
- Resubmit same batch: `cbatch_run.py run batch_config.json`
- System auto-deduplicates: same entries won't be reprocessed
- Job will continue from last successful state

**Issue 2: File Not Found**
```
Error: "file-ABC123xyz not found"
```

**Fix**:
- JSONL file was garbage-collected by Anthropic (>30 days old)
- Resubmit: `cbatch_run.py run batch_config.json`

**Issue 3: Batch Timeout (>72 hours)**
```
Status: EXPIRED
```

**Fix**:
- Batch jobs expire after 72 hours of inactivity
- Resubmit before expiry: `cbatch_run.py run batch_config.json`

---

## Queue Integration (Seamless Fallback)

When running queue-worker with Anthropic keys exhausted:

### Automatic Fallback

```bash
# Start queue worker normally
python /c/csc/bin/queue-worker --mode batch

# Queue worker detects Anthropic API limit
# Automatically switches to batch mode:
# 1. Creates JSONL from ready workorder
# 2. Submits to Claude Batch API
# 3. Moves workorder to "pending_batch"
# 4. Returns immediately (non-blocking)
# 5. Next cycle polls job status
# 6. When complete, workorder moves to done/
```

**No code changes needed** - batch submission is automatic when needed.

---

## Command Reference

### Add Entry to Batch Config

```bash
cbatch_add.py <workorder.md> [--model claude-opus-4-6] [--provider anthropic]
```

### List All Batch Entries

```bash
cbatch_list.py [--provider anthropic] [--status pending|submitted|completed]
```

### Run Batch Job

```bash
cbatch_run.py run batch_config.json [--agent anthropic] [--cache]
```

**Flags**:
- `--agent anthropic` - Filter to Anthropic entries only
- `--cache` - Use prompt caching (saves 90% input tokens on repeat queries)
- `--no-wait` - Submit and exit (don't poll)

### Check Job Status

```bash
cbatch_run.py status --job-name batch_ABC123xyz
```

### Retrieve Results

```bash
cbatch_run.py retrieve --job-name batch_ABC123xyz --out results.jsonl
```

### Edit Batch Entry

```bash
cbatch_edit.py <entry_id> --model claude-haiku-3-5
cbatch_edit.py <entry_id> --status pending  # Reset failed job
```

### Remove Entry

```bash
cbatch_remove.py <entry_id>
```

---

## Example: Full Workflow

```bash
#!/bin/bash

# 1. Create workorder (in workorders/ready/)
cat > workorders/ready/my-task.md << 'EOF'
---
urgency: P2
tags: batch,analysis
---

# Task: Analyze Customer Data

Please analyze the attached customer dataset and provide:
1. Summary statistics
2. Anomalies detected
3. Recommendations

EOF

# 2. Add to batch config
python bin/claude-batch/cbatch_add.py workorders/ready/my-task.md --model claude-opus-4-6

# 3. Submit batch (non-blocking)
python bin/claude-batch/cbatch_run.py run bin/claude-batch/batch_config.json --agent anthropic

# 4. Check status (returns immediately)
# Job is running async in background
echo "Batch submitted. Check status with:"
echo "  python bin/claude-batch/cbatch_run.py status --job-name batch_ABC123xyz"

# 5. In next cycle, queue-worker automatically polls and completes when done
```

---

## Cost Optimization Tips

### Use Prompt Caching for Repeated Queries

```bash
# Cache system context (CLAUDE.md, code maps, etc.)
cbatch_run.py run batch_config.json --cache
```

**Savings**:
- First request: Full input tokens billed
- Repeat requests: **90% input tokens cached** (only pay 10% of full cost)
- Good for: Same system context, many workorders

### Batch Large Tasks Together

**Instead of**:
```
Job 1: 1 entry (100k tokens, $0.75)
Job 2: 1 entry (100k tokens, $0.75)
Job 3: 1 entry (100k tokens, $0.75)
Total: $2.25 (with overhead)
```

**Do this**:
```
Batch 1: 3 entries (300k tokens, $2.25, no overhead)
Total: $2.25 (50% cheaper than interactive, same cost as separate batches but simpler)
```

### Model Selection

| Task | Model | Batch Cost |
|------|-------|-----------|
| Code review, analysis | Haiku | $0.01-0.05 per task |
| Implementation, refactoring | Sonnet | $0.10-0.30 per task |
| Complex reasoning, decisions | Opus | $0.20-0.50 per task |

---

## Troubleshooting

### "ANTHROPIC_API_KEY not set"

**Fix**:
```bash
export ANTHROPIC_API_KEY="sk-ant-v0-..."
python bin/claude-batch/cbatch_run.py run bin/claude-batch/batch_config.json
```

### "Rate limited: 429 Too Many Requests"

**Fix**:
- Wait 60s before resubmitting
- Reduce batch size (max 100 entries per job)
- Spread submissions across hours

### "Batch job timed out"

**Fix**:
- Resubmit same batch config
- System deduplicates: failed entries retry automatically

### "No results returned"

**Possible causes**:
1. Job still processing (check with `cbatch_run.py status`)
2. JSONL format error (check `batch_requests.jsonl`)
3. API token expired (refresh with `export ANTHROPIC_API_KEY=...`)

---

## Integration with CSC Service

When running csc-service:

```bash
# Start service with batch fallback enabled
csc-service --daemon --batch-fallback

# Service will:
# 1. Try interactive Claude API first
# 2. If rate limited or no credits → switch to batch
# 3. Submit workorders to Claude Batch API
# 4. Poll status automatically
# 5. Complete workorders when batch finishes
```

**Config**:
```json
{
  "batch_fallback_enabled": true,
  "batch_poll_interval": 30,
  "max_batch_entries_per_job": 100,
  "anthropic_api_key": "sk-ant-v0-..."
}
```

---

## FAQ

**Q: Can Gemini submit batches to Claude Batch API?**
A: Yes. Any agent with `ANTHROPIC_API_KEY` environment variable set can submit batches. Gemini calls `cbatch_run.py` just like any other agent.

**Q: What happens to work while batch is processing?**
A: Queue-worker continues with other workorders. Batch jobs run async. When batch completes, next cycle picks up results and completes the workorder.

**Q: Can I monitor batch from a different machine?**
A: Yes. Batch job name (`batch_ABC123xyz`) can be checked from anywhere with `cbatch_run.py status --job-name batch_ABC123xyz`.

**Q: How long do batch jobs take?**
A: Typically 5-30 minutes depending on queue. Max 72 hours before expiry.

**Q: Can I cancel a batch?**
A: No. Batches cannot be cancelled. They'll complete or expire. Work is idempotent.

**Q: Do I need separate Anthropic accounts for batch vs. interactive?**
A: No, but recommended. Batch jobs use same quota as interactive. Separate accounts avoid quota conflicts.

**Q: What if ANTHROPIC_API_KEY is wrong?**
A: Batch submission will fail immediately with auth error. Fix key and resubmit.

---

## Quick Start (Copy-Paste)

```bash
#!/bin/bash
# Run Claude batch from any agent (Gemini, ChatGPT, etc.)

export ANTHROPIC_API_KEY="sk-ant-v0-..."  # Your Anthropic key

cd /c/csc

# Add workorder to batch
python bin/claude-batch/cbatch_add.py workorders/ready/my-task.md

# Submit batch
python bin/claude-batch/cbatch_run.py run bin/claude-batch/batch_config.json

# Monitor
sleep 10
python bin/claude-batch/cbatch_run.py status --job-name batch_ABC123xyz

# Retrieve when done
python bin/claude-batch/cbatch_run.py retrieve --job-name batch_ABC123xyz
```

Done! Workorder results now in `batch_results_*.jsonl`.
