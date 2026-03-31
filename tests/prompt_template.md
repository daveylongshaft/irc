# Task: Fix Failing Test — {{TEST_NAME}}

## What Failed

Test file: `tests/{{TEST_FILE}}`
Log file: `tests/logs/{{LOG_FILE}}`

### FAILED lines

```
{{FAILED_LINES}}
```

### Error details

```
{{ERROR_LINES}}
```

### Output (last 30 lines)

```
{{OUTPUT_TAIL}}
```

## Instructions

1. Read the full log at `tests/logs/{{LOG_FILE}}`
2. Read the test file at `tests/{{TEST_FILE}}` to understand what it expects
3. Identify root cause — common issues:
   - **ImportError**: Module was renamed/refactored. Fix the import in the test OR the module.
   - **AssertionError**: Code behavior changed. Fix the **code under test** (not the test) unless the test itself is wrong.
   - **AttributeError**: API changed. Check if the test or the code needs updating.
4. Fix the code. Prefer fixing source over tests, unless the test is clearly outdated.
5. `rm tests/logs/{{LOG_FILE}}` so the test runner re-runs it
6. Commit and push. **Do NOT run pytest yourself.**
