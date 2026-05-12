---
slug: bridge-dual-server
name: Bridge dual-server architecture issue
description: Bridge designed for single outbound; stashed work to support routing to two test servers (19525 and 29525).
type: task
status: stashed
tags: [csc, bridge, networking, s2s]
related: [testing-servers, s2s-linking-investigation]
updated: 2026-04-11T00:00:00Z
---

Bridge (csc-bridge) was designed with one outbound transport. Two inbound listeners (TCP 9666 and 9665) both forward to the same server because Bridge takes only one outbound_transport param.

Root cause: main.py line ~288-294 creates one UDPOutbound pointing to server_port; Bridge.start() only uses that one.

Solutions:
1. Two separate Bridge instances (simplest) -- run bridge twice with different CSC_ROOT env, one for 9666->19525, one for 9665->29525.
2. Modify Bridge to support routing (better) -- add inbound_to_outbound mapping dict, Bridge.__init__ accepts dict of outbounds, route session based on which inbound listener accepted it.
3. TCP-relay layer -- bridge routes all to TCP relay on localhost:9525 which re-multiplexes.

Next step: implement Solution 2 OR use Solution 1 (two bridge instances) for faster testing.
