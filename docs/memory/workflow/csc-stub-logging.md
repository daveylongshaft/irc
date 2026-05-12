---
slug: csc-stub-logging
name: CSC stub logging convention
description: Unimplemented CSC methods must call log_stubbed_call(); output goes to stdout AND stubs.log for workorder reconciliation.
type: workflow
status: reference
tags: [workflow, csc, stubs, logging]
related: [code-maps]
updated: 2026-04-12T00:00:00Z
---

Every stubbed or partially-implemented method in csc_server/exec/dispatcher.py MUST call log_stubbed_call(class_name, method_name, **extra) on each invocation.

Output goes to:
1. Loud "[!!! STUB-HIT !!!]" line via the normal _logger (shows up in journalctl/stdout)
2. Tab-separated record appended to stubs.log under the server's data_dir (fallback: $CSC_ROOT/stubs.log, then cwd). Format: <iso-ts> TAB <server> TAB <class> TAB <method> TAB <extra-json>

SyncMesh stubs use self._log_stub(method_name, **extra) which forwards to dispatcher.log_stubbed_call("SyncMesh", ...).

Why: grep source for log_stubbed_call to see what remains stubbed; grep stubs.log to see what has been hit by real clients. The two views together drive the workorder that says which stubs to promote next.

How to apply: when adding any new IRC command handler, info query, oper command, or S2S hook that is not fully implemented, call self.log_stubbed_call("CommandDispatcher", "_handle_xxx") as the first thing after permission checks. Still emit the RFC-mandated closing numeric so clients do not hang.
