# PR Review & Auto-Merge Automation

## Overview

`bin/pr-review-agent.sh` performs automated PR triage and review, then either:

- approves + merges + deletes branch, or
- requests changes with explicit remediation steps and creates a fix workorder.

The script can run one cycle (service-driven) or daemon mode with adaptive polling.

## Implemented behavior

1. Discover open PRs from configured repository.
2. Gather PR metadata, changed files, and prior reviews.
3. Apply review checks:
   - blocking conflict state,
   - required testing section in PR body,
   - changed-file-sensitive validation (Python syntax, shell syntax).
4. Weigh human review state first:
   - unresolved human `CHANGES_REQUESTED` blocks auto-approval.
5. Post machine review:
   - `gh pr review --approve` when passing,
   - `gh pr review --request-changes` with actionable checklist when failing.
6. On approval, perform squash merge with branch cleanup.
7. On rejection, create a fix workorder in `workorders/ready/`.

## Polling modes

- **Single-cycle mode** (default): run once; scheduler/service invokes periodically.
- **Daemon mode** (`--daemon`): adaptive backoff with activity trigger.
  - Uses PR fingerprint (number + updatedAt + review decision footprint).
  - If PR state changes, next cycle runs fast (`fast_poll_interval`, default 10s).
  - If no changes, backs off to `poll_interval` (default 60s).

This reduces idle hammering while still responding quickly to active PR updates.

## Configuration

`pr-review-config.json` supports:

```json
{
  "repo": "owner/repo",
  "poll_interval": 60,
  "fast_poll_interval": 10,
  "max_attempts": 10,
  "timeout_hours": 72,
  "enabled": true
}
```

## Human-priority policy

The agent treats human feedback as authoritative:

- If a human reviewer requested changes and there is no newer human approval, the bot does not approve/merge.
- The rejection message includes a concrete "what to change" checklist.

## Rejection handling

When checks fail, the agent:

1. Requests changes on the PR with explicit actionable items.
2. Creates a `P0` workorder with issue list and re-test instructions.
3. Routes to:
   - **haiku** for test/syntax-centric fixes,
   - **opus** for queue-worker/PM/infrastructure-critical fixes.

## Real-time without hammering

Use adaptive daemon mode or service-triggered cycles:

- daemon mode: low-latency response during activity, low load when idle,
- service mode: event hooks (e.g., post-merge queue wakeup) + periodic fallback cycle.
