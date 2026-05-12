---
slug: csc-chain-integration
name: CSC chain integration required
description: New CSC classes must integrate into the inheritance chain via server reference, not float as standalone objects.
type: feedback
status: reference
tags: [feedback, csc, architecture, python]
related: [oo-containerization]
updated: 2026-04-15T00:00:00Z
---

New classes in the CSC codebase must be fully integrated into the chain (Root->Log->Data->Version->Platform->Network->Crypto->Service->Server), not standalone objects layered over the existing system.

**Why:** The chain provides log(), data_dir, platform methods, network primitives, etc. Standalone objects can't use these and create a parallel system.

**How to apply:** Classes that need chain access take `server` as first arg and access the chain through `self.server.log()`, etc. Place new classes in the correct chain level package (e.g. crypto-level classes in csc-crypto, not csc-server). Use composition (sub-objects), not standalone data classes.
