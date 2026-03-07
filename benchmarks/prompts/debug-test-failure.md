# Benchmark: debug-test-failure

## Description
Diagnose and fix a test failure from a log file — tests debugging, root cause analysis, and targeted fixes.

## Task
A test is failing. The test log is at `tests/logs/test_benchmark_debug.log` with this content:

```
FAILED tests/test_server_irc.py::test_privmsg_to_channel
  AssertionError: Expected message to contain 'PRIVMSG #general :hello'
  but got 'PRIVMSG #General :hello'

  The server is not normalizing channel names to lowercase before routing.
```

This is a SIMULATED failure for benchmarking purposes. Your task:

1. Read the test log above (it's embedded in this prompt, not a real file)
2. Identify the root cause: channel name case normalization
3. Find where channel name normalization happens in the server code
4. Read `packages/csc-server/csc_server/server_message_handler.py` to find the PRIVMSG handler
5. Explain what the fix would be (do NOT actually modify server code — this is a benchmark)
6. Write your diagnosis and proposed fix to the WIP file

## Acceptance
- Root cause correctly identified (case normalization in channel routing)
- Correct file and function identified for the fix
- Proposed fix is technically sound
- Written to WIP file

## Scoring Criteria
- **Accuracy**: Did it identify the correct root cause?
- **Navigation**: Did it find the right files efficiently?
- **Reasoning**: Is the proposed fix correct and complete?
- **Speed**: Total wall-clock time
