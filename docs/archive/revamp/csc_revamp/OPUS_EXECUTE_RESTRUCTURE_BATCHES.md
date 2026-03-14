# Execute CSC Restructure - Batch API Tool Loop

**Agent**: Opus
**Test Case**: CSC restructure (safe - existing system is backup if fails)
**Batch IDs**:
- msgbatch_01JoDGSYgfqHBQqMXh9jnUaK (Phase 1)
- msgbatch_01MEAQxvNL69HAbPDYsuaeR3 (Phase 2)
- msgbatch_01YENeceG7qXCu6WaVu9VxXs (Phase 3)
- msgbatch_01VR2ZAWYhvXFtgovqYmy88H (Phase 4)
- msgbatch_01HTVWVLazaYVfL7Lg8BeiAu (Phase 5)

## Task

Implement batch API tool loop executor that:

1. Retrieves batch results from Anthropic API
2. Parses tool_use blocks (run_command, read_file, write_file, list_directory)
3. Executes tools locally on /c/csc/
4. Creates tool_result blocks with tool_use_id
5. Submits follow-up batches with results
6. Loops until stop_reason = "end_turn"

## Output

Write `/c/csc/bin/batch_executor.py` that can be run as:
```bash
python /c/csc/bin/batch_executor.py msgbatch_01JoDGSYgfqHBQqMXh9jnUaK msgbatch_01MEAQxvNL69HAbPDYsuaeR3 ...
```

Or:
```bash
python /c/csc/bin/batch_executor.py --all-restructure-phases
```

## Result

After execution:
- `/c/csc/irc/` exists with packages/, bin/, tests/
- `/c/csc/ops/` exists with wo/ and agents/
- `/c/csc_old/` contains backup
- All 5 phases complete

That's it. Build it, test it, execute it.
