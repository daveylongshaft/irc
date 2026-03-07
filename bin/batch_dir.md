# batch_dir.py - Batch Directory Executor

Execute all workorders in a directory sequentially via Anthropic Batch API with full tool loop support.

## Overview

Scans a directory for workorder files (.md), submits each as a Batch API request, executes them sequentially with full tool support, and reports results.

Perfect for:
- Running all workorders in a queue directory
- Automated batch processing
- Sequential multi-step tasks
- Workorder pipeline execution

## Usage

```bash
# Execute all workorders in directory
python3 /c/csc/bin/batch_dir.py /c/csc/ops/wo/ready/

# With custom retry count
python3 /c/csc/bin/batch_dir.py /path/to/wo/ --max-retries 5

# Continue even if some fail
python3 /c/csc/bin/batch_dir.py /path/to/wo/ --skip-failed

# Dry run (preview without executing)
python3 /c/csc/bin/batch_dir.py /path/to/wo/ --dry-run

# Custom file pattern
python3 /c/csc/bin/batch_dir.py /path/to/wo/ --pattern "phase_*.md"
```

## Command Line Options

### Required
- `directory` - Directory containing .md workorder files

### Optional
- `--max-retries N` - Max retries per workorder (default: 2)
- `--pattern GLOB` - File pattern to match (default: *.md)
- `--dry-run` - Show what would run without executing
- `--skip-failed` - Continue even if a workorder fails

## Workorder Format

Workorder files (.md) are simple text files:

```markdown
# Phase 1: Restructure and Backup

Stop all services, backup current repo, prepare for restructuring.

1. Disable services with csc-ctl
2. Uninstall packages
3. Backup /c/csc to /c/csc_old
4. Create new structure
```

First line is system prompt (what Claude should do).
Rest is the user instruction (detailed steps).

## Execution Flow

1. **Discover**: Find all .md files in directory, sort alphabetically
2. **Submit**: For each file:
   - Read workorder content
   - Create Batch API request
   - Submit to Anthropic API
3. **Execute**:
   - Run batch_executor.py for each batch ID
   - Implement full tool loop with retries
   - Track success/failure
4. **Report**: Save results JSON with status for each workorder

## Example Output

```
================================================================================
BATCH DIRECTORY EXECUTOR
================================================================================
Directory: /c/csc/ops/wo/ready
Workorders: 3
Max retries: 2

 1. phase_1_backup.md
 2. phase_2_restructure.md
 3. phase_3_reinstall.md

================================================================================

[1/3] phase_1_backup
--------------------------------------------------------------------------------
Submitting batch...
Batch ID: msgbatch_01JoDGSYgfqHBQqMXh9jnUaK
Executing batch (max retries: 2)...
[10:04:16] [+] API key loaded
...
[10:07:44] [+] Reached end_turn - loop complete
SUCCESS: Workorder phase_1_backup completed

[2/3] phase_2_restructure
...

================================================================================
SUMMARY
================================================================================
Total: 3
Success: 3
Failed: 0

Results saved to: /c/csc/ops/wo/ready/batch_results_20260305_101200.json
```

## Results File

JSON file saved after execution:

```json
{
  "phase_1_backup": {
    "status": "SUCCESS",
    "batch_id": "msgbatch_01JoDGSYgfqHBQqMXh9jnUaK",
    "timestamp": "2026-03-05T10:07:44.000000"
  },
  "phase_2_restructure": {
    "status": "SUCCESS",
    "batch_id": "msgbatch_01MEAQxvNL69HAbPDYsuaeR3",
    "timestamp": "2026-03-05T10:15:00.000000"
  },
  "phase_3_reinstall": {
    "status": "FAILED",
    "batch_id": "msgbatch_01YENeceG7qXCu6WaVu9VxXs",
    "error": "Tool execution timeout",
    "timestamp": "2026-03-05T10:20:15.000000"
  }
}
```

## Tool Loop Features

Each workorder execution includes:
- Full tool loop (run_command, read_file, write_file, list_directory)
- Automatic retry on tool failures
- Model escalation (haiku → sonnet → opus)
- Verbose execution logging
- Path normalization (Cygwin/Windows)

## Common Patterns

### Execute CSC restructure phases
```bash
# Create workorder directory
mkdir -p /c/csc/ops/wo/phases

# Copy/create phase workorders
cp phase_1.md phase_2.md phase_3.md /c/csc/ops/wo/phases/

# Execute all phases sequentially
python3 batch_dir.py /c/csc/ops/wo/phases/ --max-retries 3
```

### Process workorder queue
```bash
# Execute all ready workorders
python3 batch_dir.py /c/csc/ops/wo/ready/

# Move completed to done
mv /c/csc/ops/wo/ready/* /c/csc/ops/wo/done/
```

### Handle failures gracefully
```bash
# Skip failed workorders and continue
python3 batch_dir.py /c/csc/ops/wo/ready/ --skip-failed

# Check results
cat /c/csc/ops/wo/ready/batch_results_*.json | jq '.[] | select(.status=="FAILED")'
```

## Integration with Scripts

Use in CI/CD or deployment scripts:

```bash
#!/bin/bash
set -e

export ANTHROPIC_API_KEY="sk-ant-api03-..."

# Execute workorder directory
python3 /c/csc/bin/batch_dir.py /c/csc/ops/wo/ready/ --max-retries 3

# Check results
if grep -q "FAILED" /c/csc/ops/wo/ready/batch_results_*.json; then
    echo "Some workorders failed"
    exit 1
fi

echo "All workorders completed successfully"
```

## Return Codes

- `0` - All workorders completed successfully
- `1` - One or more workorders failed (unless --skip-failed used)

## Environment

Requires:
- `ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY_3` in .env
- Python 3.8+
- batch_executor.py available at /c/csc/bin/

## Notes

- Workorders executed in alphabetical order
- Each workorder waits for previous to complete
- Batch API may take 2-5 minutes per workorder
- Failed workorders can be rerun individually
- Results JSON preserves batch IDs for reference
- Tool errors are automatically retried with escalation
