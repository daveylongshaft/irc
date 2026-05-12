---
slug: csc-bot-package
name: CSC Bot Package (bot.tgz)
description: Deployable bot bundle at C:\csc\tmp\bot.tgz -- eggdrop 1.10.1 + python.so + dispatcher scripts + setup.sh. Deploy-tested in WSL.
type: task
status: done
tags: [csc, eggdrop, deployment, artifact]
related: [phase1-dispatcher, haven-script-server, distributed-workforce-arch]
updated: 2026-05-05T00:00:00Z
---

Artifact: C:\csc\tmp\bot.tgz (1.3M, 277 entries). Deploy-tested end-to-end in WSL: extract -> setup.sh -> launch bot -> connects to libera. All modules load clean.

Contents:
- bot/eggdrop-1.10.1 -- main binary (dynamic; libtcl8.6, libssl, libcrypto, libc)
- bot/eggdrop -- symlink to versioned binary
- bot/modules-1.10.1/*.so -- 14 modules including python.so (95K)
- bot/scripts/csc_auth.tcl, csc_dispatcher.tcl, csc_lin.tcl
- bot/setup.sh -- generates eggdrop.conf, builds ops/ tree, stages scripts

Key build decisions:
- eggdrop git HEAD (1.10.1+arbchan+extban), NOT 1.9.5 -- python.mod from git uses HOOK_POST_SELECT missing in 1.9.5
- Dropped -static LDFLAGS -- fully static + dlopen(loadmodule) is incompatible with glibc; binary segfaults
- DNS module incompatible with threaded DNS core -- do NOT loadmodule dns

Eggdrop 1.10.x gotchas:
- `set servers { ... }` not `servers { ... }`
- set userfile/chanfile/pidfile MUST come before module loads
- loadmodule channels MUST come before any `channel add`
- bind type dccdiscon does NOT exist in 1.10; use chof or disc
- Top-level proc calls in sourced scripts need namespace qualification

setup.sh env vars (all have defaults): BOT_HOME, CSC_HOME, OPS_HOME, BOT_NICK, BOT_USER, BOT_REALNAME, IRC_SERVER (irc.libera.chat), IRC_PORT (6667), IRC_CHANNEL (#csc), BOT_TGZ, REPO_URL.
