# Path-Based Git Protection System - Batch Processing Strategy

## Overview

The path-based git protection system has been split into **7 focused workorders** that can be processed efficiently using:
1. **Anthropic Batch API** - Process multiple prompts with cost reduction
2. **System Prompt Caching** - Cache codemap + operating instructions to save tokens
3. **Intelligent model selection** - Gemini-3-Pro/Flash for cheaper tasks, Opus for hardest

## Workorder Breakdown

| # | Workorder | Complexity | Recommended Model | Dependencies |
|---|-----------|-----------|-------------------|--------------|
| 1 | GitHub Actions Workflow | Medium | Haiku/Gemini-3-Flash | None |
| 2 | CODEOWNERS File | Easy | Haiku/Gemini-3-Flash | None |
| 3 | AI Reviewer Script | Hard | Sonnet/Opus | None (but needs WO4 context) |
| 4 | PR Creator Module | Medium | Sonnet/Gemini-3-Pro | Needs WO3 context |
| 5 | Queue Worker Modification | Hard | Opus | Needs WO3, WO4 context |
| 6 | Config & .gitignore Updates | Easy | Haiku/Gemini-3-Flash | Needs WO1, WO5 context |
| 7 | Testing & Validation | Medium | Haiku/Gemini-3-Flash | Needs WO1-WO6 complete |

## Batch Processing Instructions

### Phase 1: Prepare Batch Prompts (Do This ONCE)

Create a batch input file with all 7 workorders. Use **system prompt caching** for:
- Full CSC CLAUDE.md instructions
- Project codemap (from `tools/INDEX.txt`)
- Platform requirements
- Operating instructions from MEMORY.md

**Batch file structure:**
```
{
  "custom_batches": [
    {
      "custom_id": "wo-1-github-workflow",
      "params": {
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 2000,
        "system": [
          {
            "type": "text",
            "text": "# CLAUDE.md [FULL CSC INSTRUCTIONS - cached]"
          },
          {
            "type": "text",
            "text": "# Project Codemap [FROM tools/INDEX.txt - cached]"
          }
        ]
      },
      "messages": [
        {
          "role": "user",
          "content": "Read and implement WO #1: GitHub Actions Workflow\n\n[FULL WO CONTENT from workorders/ready/1_github_workflow...]"
        }
      ]
    },
    {
      "custom_id": "wo-2-codeowners",
      "params": {
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 1500,
        "system": [/* same cached system prompt */]
      },
      "messages": [/* WO #2 content */]
    },
    // ... WO #3-#7 similar structure
  ]
}
```

### Phase 2: Model Selection (Cost-Optimized)

**Gemini Phase (Try First - Cheaper):**
- WO #1 (GitHub Actions) → gemini-3-flash-preview
- WO #2 (CODEOWNERS) → gemini-3-flash-preview
- WO #6 (Config Updates) → gemini-3-flash-preview
- WO #7 (Testing) → gemini-3-flash-preview
- **Estimated cost:** ~$0.02

**Sonnet Phase (Medium Cost):**
- WO #3 (AI Reviewer) → claude-sonnet-4-5-20250929
- WO #4 (PR Creator) → claude-sonnet-4-5-20250929
- **Estimated cost:** ~$0.05

**Opus Phase (Hardest Tasks):**
- WO #5 (Queue Worker) → claude-opus-4-6 (most critical, most complex)
- **Estimated cost:** ~$0.15

**Total estimated cost:** ~$0.22 using batch API (vs ~$0.40+ for individual calls)

### Phase 3: Process in Order (Sequential)

**Reason for sequencing:** Later workorders need outputs from earlier ones as context.

**Execution order:**
1. **WO #1 & #2** (Gemini batch) - Pure file creation, no dependencies
2. **WO #3 & #4** (Sonnet batch) - PR creator needs AI reviewer context
3. **WO #5** (Opus batch) - Queue worker needs PR creator + AI reviewer context
4. **WO #6** (Gemini) - Config needs all previous workorders to know what tokens to add
5. **WO #7** (Haiku batch) - Testing comprehensive, after all code is done

### Phase 4: Batch Processing Commands

```bash
# 1. Create batch input file from workorders
cat > /tmp/path-protection-batch.json << 'EOF'
{
  "custom_batches": [
    {
      "custom_id": "wo-1",
      "params": {
        "model": "gemini-3-flash-preview",
        "max_tokens": 2000,
        "system": [/* cached system prompt */]
      },
      "messages": [{
        "role": "user",
        "content": "Read WO #1 from: workorders/ready/1772269761-1_github_workflow_ai_code_review_md.md\n\n$(cat workorders/ready/1772269761-1_github_workflow_ai_code_review_md.md)"
      }]
    },
    // ... repeat for WO #2, #3, etc.
  ]
}
EOF

# 2. Submit Gemini batch (WO #1, #2, #6, #7)
anthropic-batch-api submit /tmp/gemini-batch.json

# 3. Submit Sonnet batch (WO #3, #4)
anthropic-batch-api submit /tmp/sonnet-batch.json

# 4. Submit Opus batch (WO #5)
anthropic-batch-api submit /tmp/opus-batch.json

# 5. Monitor batch progress
anthropic-batch-api list
anthropic-batch-api status <batch-id>

# 6. Retrieve results
anthropic-batch-api retrieve <batch-id> > results.jsonl
```

### Phase 5: Process Batch Results

Results come back as JSONL (one result per line):

```bash
# Extract and process results
for wo_num in 1 2 3 4 5 6 7; do
  echo "=== Processing WO #$wo_num ==="

  # Extract the result for this workorder from the batch
  jq "select(.custom_id == \"wo-$wo_num\")" results.jsonl

  # The agent will have committed files and written completion summary
  # Check git status to see what was created
  git status
done
```

## Prompt Caching Configuration

When setting up batches, cache these system instructions (shared across all workorders):

```yaml
System Prompt (cached, ~2000 tokens):
- Full CLAUDE.md (CSC operating instructions)
- Project structure overview
- Cross-platform requirements
- Safety protocols (trash command, git workflow)
- Key architectural patterns

Code Context (cached, ~3000 tokens):
- tools/INDEX.txt (full code map)
- Key file paths and structure
- Queue worker architecture (since many WOs reference it)
- API key manager patterns

Volatile Prompt (per workorder, ~500-2000 tokens):
- The actual workorder content from ready/
- Any output from previous WOs (if sequential)
```

**Caching savings:**
- Total tokens per batch without caching: ~35,000
- Total tokens per batch with caching: ~8,000
- **Savings: 77% reduction in tokens (vs ~$0.25 saved)**

## Expected Timeline

**With Batch API:**
1. **Gemini Phase:** 5-10 min (parallel batch)
2. **Sonnet Phase:** 5-10 min (parallel batch)
3. **Opus Phase:** 3-5 min (single batch)
4. **Total:** ~15-25 min (all phases)
5. **Review & Validate:** ~30 min (manual review of outputs)

**Total time to completion:** ~1-2 hours (vs ~4-6 hours doing one-at-a-time)

## Integration Points

After batch processing completes:

1. **Verify all files were created:**
   ```bash
   git status  # Should show new files for WO #1-6
   ```

2. **Run tests:**
   ```bash
   # WO #7 provides detailed test plan
   # Follow testing and validation workorder
   ```

3. **Commit and move to done:**
   ```bash
   for wo in 1 2 3 4 5 6 7; do
     wo move "$(ls workorders/ready | grep "^[0-9]*-${wo}_")" done
   done
   git commit -m "feat: Implement path-based git protection system"
   git push
   ```

## Fallback Strategy

If Gemini API is exhausted:
- **Fall back to Sonnet** for Gemini-assigned workorders
- **Cost increase:** +$0.03 per WO (but still cheaper than Opus)
- **Quality:** Better (Sonnet is more capable than Gemini-Flash)

If Anthropic API issues:
- **Manual implementation:** Follow workorder specs directly
- **Use local Claude via ollama** if available
- **Fallback to haiku** for quick completion (cost-conscious)

## Monitoring & Troubleshooting

**Batch API monitoring:**
```bash
# Check batch status
anthropic-batch-api list --status=processing

# Cancel a batch if needed
anthropic-batch-api cancel <batch-id>

# Retrieve failed results
jq "select(.result.error != null)" results.jsonl
```

**If a workorder fails:**
1. Check error message in results.jsonl
2. Review workorder requirements
3. Re-assign to different model or human review
4. Continue with next workorder (don't block on single failure)

## Summary

✅ **7 workorders created** with detailed specifications
✅ **Batch API strategy** for cost & speed optimization
✅ **Prompt caching** configured for ~77% token savings
✅ **Model selection** tuned for quality vs cost tradeoff
✅ **Sequential ordering** ensures dependencies are satisfied

**Next steps:**
1. Generate batch input JSON from workorder files
2. Submit to Anthropic Batch API (Gemini phase first)
3. Monitor progress via `anthropic-batch-api list`
4. Process results and verify file creation
5. Run WO #7 testing & validation
6. Commit and merge to main

