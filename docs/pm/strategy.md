# PM Strategy: Agent Assignment Under Usage Constraints

## The Problem
We have limited paid AI usage that can run out at any time.
Every API call costs money and burns through our allocation.

## Agent Policy

| Agent | Role | When to Use |
|-------|------|-------------|
| gemini-2.5-flash | Docs & Tests | Documentation, test fixes, validation - cheap and fast |
| gemini-3-pro | Code | Features, refactors, bug fixes - capable code agent |
| haiku | Audit | Code audits, reviews - good at analysis |
| opus | Debug | Debugging, investigation - deep reasoning for hard problems |

**No local agents** are used for PM assignments.

## Priority Tiers

### P0 - Do Now (blocks everything)
- Failing tests (`fix_test_*`)
- Broken infrastructure (queue-worker, test-runner)
- Security issues
- Agent: gemini-2.5-flash for test fixes, gemini-3-pro for infra fixes

### P1 - Do Soon (force multipliers)
- PM improvements
- Queue-worker enhancements
- Agent tooling improvements
- Agent: gemini-3-pro

### P2 - Do When Capacity Allows
- New features
- Bug fixes that don't block other work
- Platform enhancements
- Agent: gemini-3-pro

### P3 - Do With Cheapest Agent
- Documentation (`docs_*`, `docstring*`)
- Simple validation tasks
- Agent: gemini-2.5-flash

## Failure Escalation

```
Task arrives → assign per policy
  → COMPLETE? done
  → INCOMPLETE (attempt 1)? retry same agent
  → INCOMPLETE (attempt 2)? escalate:
      gemini-2.5-flash → gemini-3-pro
      gemini-3-pro → opus
      haiku → gemini-3-pro
      opus → flag for human review
  → INCOMPLETE (attempt 3+)? flag for human review
```

## Budget Awareness

- Track assignments by agent in pm_state.json
- When API errors occur, queue-worker detects and logs
- PM should not re-assign to an agent whose API key is exhausted
