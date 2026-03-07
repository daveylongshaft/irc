# Benchmark: large-context-nav

## Description
Navigate a large codebase to answer specific questions — tests search efficiency and comprehension.

## Task
Answer these 5 questions about the CSC codebase. For each, cite the exact file and line number.

1. **What is the maximum number of attempts before PM flags a workorder for human review?** (Find the constant in pm.py)

2. **What system prompt does the agent service inject into every agent run?** (Find the WIP_SYSTEM_PROMPT in agent_service.py and quote the first sentence)

3. **How does the server ensure atomic writes to JSON storage?** (Find the pattern in storage.py — describe the temp-file → fsync → rename sequence)

4. **What UDP port does the IRC server listen on by default?** (Find the default in server config)

5. **What happens when a channel name is looked up — is it case-sensitive or case-insensitive?** (Find the normalization code and cite the exact method)

Write your answers with file:line citations to the WIP file.

## Acceptance
- All 5 questions answered correctly
- File and line number citations for each
- Answers are concise (1-3 sentences each)
- Written to WIP file

## Scoring Criteria
- **Accuracy**: All 5 correct? (binary per question)
- **Citations**: Exact file:line for each?
- **Efficiency**: How many files read to find answers?
- **Speed**: Total wall-clock time
