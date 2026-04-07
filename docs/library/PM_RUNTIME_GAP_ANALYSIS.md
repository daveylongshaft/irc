# PM Runtime Gap Analysis (Docs vs Current Repository)

## Scope

This note compares PM documentation claims to currently available checked-in runtime scripts.

## Inconsistencies found

The following PM functions are documented in archived PM summary docs but are **not present** in current executable PM runtime files in this repository snapshot:

- `find_batch_candidates`
- `spawn_opus_self_fix`
- `spawn_haiku_debug`
- `run_cycle_safe`

Related PM docs are still available under `docs/tools/pm/`, but active runtime implementation for those specific helpers is not present in the currently tracked scripts.

## What can be implemented now

- PR-review improvements were implemented in `bin/pr-review-agent.sh` (human-priority rejection weighting, explicit remediation checklist, adaptive daemon polling).
- PM helper implementation should be done only after identifying/restoring the active PM runtime module location (e.g., a real `pm.py` service module).

## Recommended next steps for PM

1. Identify canonical PM runtime file.
2. Implement the four helper methods there.
3. Wire `run_cycle_safe()` into service loop.
4. Reconcile `docs/tools/pm/*` with actual method signatures.
5. Move this analysis to archive once PM runtime is fully aligned.
