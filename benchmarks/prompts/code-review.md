# Benchmark: code-review

## Description
Review a code file for bugs, style issues, and improvements — tests analytical depth and code comprehension.

## Task
Review `packages/csc-service/csc_service/shared/services/benchmark_service.py` and produce a structured code review covering:

1. **Bugs**: Any actual bugs or logic errors
2. **Security**: Path traversal, injection, or unsafe operations
3. **Error handling**: Missing or inadequate error handling
4. **Style**: Inconsistencies with Python conventions
5. **Performance**: Inefficiencies or unnecessary operations
6. **Architecture**: Design issues or improvement opportunities

Format your review as:
```
## Code Review: benchmark_service.py

### Bugs Found
- [file:line] Description

### Security Issues
- [file:line] Description

### Error Handling
- [file:line] Description

### Style Issues
- [file:line] Description

### Performance
- [file:line] Description

### Architecture Notes
- Description

### Summary
Overall assessment and priority recommendations.
```

Write the review to the WIP file.

## Acceptance
- All 6 categories addressed
- Specific line numbers referenced where applicable
- At least 3 real findings (not padding)
- Summary with actionable recommendations
- Written to WIP file

## Scoring Criteria
- **Depth**: How many real issues found?
- **Accuracy**: Are findings legitimate (not false positives)?
- **Specificity**: Line numbers, concrete suggestions
- **Actionability**: Can someone fix these from the review alone?
- **Speed**: Total wall-clock time
