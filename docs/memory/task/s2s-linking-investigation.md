---
slug: s2s-linking-investigation
name: S2S Linking Investigation
description: Stashed work to restore haven-4346 <-> haven-ef6e server linking and synchronized #general membership.
type: task
status: stashed
tags: [networking, s2s, unfinished, resume]
related: [server-topology, temp-clone-git-workflow]
updated: 2026-04-06T17:52:03Z
---

Goal: get haven-4346 linked cleanly to haven-ef6e with #general showing the same members on both sides.

Findings before pause:
- haven-4346 did receive SYNCUSER traffic from haven-ef6e, so reachability and cert-auth handshake were at least partially working.
- Hub log showed remote channels from haven-4346 being removed during disk restore because they were not on disk locally.
- Runtime/status paths were inconsistent; live link state was not being written to a dedicated links file.
- Config lookup behavior differs between root and etc locations; needs normalizing before deployment.

Next steps:
- Preserve or rebuild remote channel membership after restore_channels runs.
- Persist links.json from ServerNetwork for status tooling.
- Normalize S2S config discovery so etc/root mismatches do not silently split operator intent from runtime behavior.
- Re-verify bidirectional membership sync in #general after patching; deploy from temp clone branch.
