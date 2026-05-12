---
slug: testing-servers
name: S2S test server setup
description: Two IRC test servers at /c/csc/tmp/s2s-test/; server1 on 19525, server2 on 29525.
type: task
status: reference
tags: [csc, testing, s2s, servers]
related: [bridge-dual-server, s2s-linking-investigation]
updated: 2026-04-11T00:00:00Z
---

Server 1: /c/csc/tmp/s2s-test/server1-root (haven.19525, UDP 19525)
Server 2: /c/csc/tmp/s2s-test/server2-root (haven.29525, UDP 29525)

Bridge: /c/csc/tmp/clones/csc/irc/packages/csc-bridge. Config: /c/csc/etc/csc-service.json.
TCP 9666 -> UDP 19525 (Server 1). TCP 9665 -> UDP 29525 (Server 2). See bridge-dual-server for routing limitation.

Startup order: server1, server2, then bridge.
- Server 1: cd /c/csc/tmp/s2s-test/server1-root && python -m csc_server
- Server 2: cd /c/csc/tmp/s2s-test/server2-root && python -m csc_server
- Bridge: cd /c/csc/tmp/clones/csc/irc/packages/csc-bridge && python main.py
