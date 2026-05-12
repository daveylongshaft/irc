---
slug: oo-containerization
name: OO containerization -- entities own data AND behavior
description: Domain entities own their data AND the methods that operate on it; no parallel dicts keyed by identity tuples.
type: feedback
status: reference
tags: [feedback, architecture, oo, csc]
related: [right-over-immediate, csc-chain-integration]
updated: 2026-04-12T00:00:00Z
---

When modeling domain entities (Link, User, Channel, Session), put the data AND the methods that operate on that data in the same object. Never use parallel dicts keyed by identity tuples or id strings as a substitute for an object.

Concrete form: a Link object owns its transport (sendto/matches), its stats (sent/recv msgs/bytes, opened_at, last_seen), its known-via state (users/channels/opers on the other side), and its lifecycle (state UP/DOWN, resolve, close).

**Why:** Davey rewrote the entire csc-server package because the prior shape did not respect this. Parallel-state patterns compound errors and make partial-failure modes (netsplit, link loss, desync) impossible to reason about. With proper containerization, losing a link immediately tells you exactly which users/channels desynced.

**How to apply:** When adding new cross-cutting state, add fields and methods to the owning domain object. If you find yourself writing `d[key]["field"] += 1` from outside the entity, the entity is wrong. Prefer composition via mixins so cross-cutting capabilities attach cleanly rather than bloating a god-class.
