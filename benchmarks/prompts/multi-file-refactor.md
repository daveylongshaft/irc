# Benchmark: multi-file-refactor

## Description
Rename a function across multiple files — tests code navigation, search, and coordinated edits.

## Task
Refactor the function `estimate_tokens_for_text` in `bin/claude-batch/common.py` to `estimate_input_tokens`.

1. Find all files that import or call `estimate_tokens_for_text`
2. Rename the function definition in `common.py`
3. Update all call sites and imports across the codebase
4. Verify no references to the old name remain (grep for it)
5. Write a summary of all files changed and why

## Acceptance
- Function renamed in definition and all call sites
- No grep hits for the old name `estimate_tokens_for_text`
- No syntax errors introduced
- Summary of changes written to WIP file

## Scoring Criteria
- **Correctness**: Did it find ALL references? (not just the obvious ones)
- **Safety**: Did it verify with grep after renaming?
- **Speed**: Total wall-clock time
- **Completeness**: Summary includes every file touched
