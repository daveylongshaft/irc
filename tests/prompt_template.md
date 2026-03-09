# Task: Fix Failing Test — {{TEST_NAME}}

## What Failed

Test file: `tests/{{TEST_FILE}}`
Log file: `tests/logs/{{LOG_FILE}}`

### FAILED lines

```
{{FAILED_LINES}}
```

## Instructions

1. Read the full log at `tests/logs/{{LOG_FILE}}`
2. Identify root cause of each failure
3. Fix the **code under test**, not the test (unless the test itself is wrong)
4. `rm tests/logs/{{LOG_FILE}}` (so cron re-runs the test)
5. Commit, push, move this prompt to done. **Do NOT run pytest yourself.**
