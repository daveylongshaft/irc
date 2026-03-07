# Benchmark: implement-feature

## Description
Add a small utility function with proper error handling — tests code generation quality and project conventions.

## Task
Add a `format_duration(seconds: float) -> str` function to `bin/claude-batch/common.py` that:

1. Takes a duration in seconds (float)
2. Returns a human-readable string:
   - Under 60s: `"42.5s"`
   - Under 3600s: `"5m 30s"`
   - 3600s+: `"2h 15m 30s"`
3. Handles edge cases: 0, negative (return "0s"), very large numbers
4. Add it after the existing `estimate_cost_usd` function
5. Write the function following the existing code style in the file (type hints, docstrings)

## Acceptance
- Function added to `bin/claude-batch/common.py`
- Handles all duration ranges correctly
- Follows existing code style (type hints, no excess)
- Edge cases handled (0, negative, large)
- No syntax errors

## Scoring Criteria
- **Correctness**: Does the function produce correct output for all ranges?
- **Style**: Does it match existing code conventions?
- **Robustness**: Edge case handling
- **Speed**: Total wall-clock time
- **Minimalism**: No over-engineering (simple function, not a class)
