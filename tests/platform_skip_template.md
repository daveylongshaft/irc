# Task: Run Test on Correct Platform — {{TEST_NAME}}

## What Happened

Test file `tests/{{TEST_FILE}}` was skipped on the current machine because it requires a different platform.

### PLATFORM_SKIP reason

```
{{PLATFORM_SKIP_LINES}}
```

## Instructions

This test needs to run on the platform listed above. If you are on that platform:

1. Delete the log so the test can run: `rm tests/logs/{{LOG_FILE}}`
2. Let cron re-run the test (do NOT run pytest yourself)
3. If the test passes: commit the log, push, move this prompt to done
4. If the test fails with a real error (not PLATFORM_SKIP): fix the code, delete the log, commit, push

If you are NOT on the required platform, leave this prompt in ready/ for the next machine.
