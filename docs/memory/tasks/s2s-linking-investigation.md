# S2S Linking Investigation

- Slug: `s2s-linking-investigation`
- Category: `tasks`
- Status: `stashed`
- Tags: networking, resume, s2s, unfinished
- Related: server-topology, temp-clone-git-workflow
- Created: 2026-04-06T17:51:18Z
- Updated: 2026-04-06T17:52:03Z

## Summary
Unfinished work to restore haven.4346 <-> haven.ef6e server linking and synchronized #general membership.

## Details
Goal: get haven.4346 linked cleanly to haven.ef6e and ensure #general shows the same members on both sides.

Known findings before pause:
- haven.4346 did receive SYNCUSER traffic from haven.ef6e earlier, so raw reachability and cert-auth handshake were at least partially working.
- The hub log showed remote channels from haven.4346 being removed during disk restore because they were not on disk locally.
- Local status visibility was misleading because runtime/status paths were inconsistent and live link state was not being written to a dedicated links file.
- Config lookup behavior differs between root and etc locations, so config discovery needs to be normalized before deployment.

Likely next implementation areas:
- Preserve or rebuild remote channel membership after restore_channels runs.
- Persist links.json from ServerNetwork for status tooling.
- Normalize S2S config discovery so etc/root mismatches do not silently split operator intent from runtime behavior.
- Re-verify bidirectional membership sync in #general after patching and deploy from the temp clone branch.

## Updates
- 2026-04-06T17:52:03Z: Preserved concrete findings: remote channel eviction during restore, runtime status path mismatch, and config discovery mismatch.
