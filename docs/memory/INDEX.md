# Memory Index

Read this file first. Each entry is one line -- enough to decide if you need to open the file.
For cross-topic relationships see XREF.md. For status overview see STATUS.md.
Machine-readable version: index.json (same data; YAML frontmatter in each file is source of truth).

## user
- `davey-profile` [reference] -- Who Davey is: background, expertise, core values, work style. Primary context for tailoring all responses.
- `davey-collaboration-preferences` [reference] -- Preserve interrupted work, track finished vs unfinished tasks, keep implementation off main checkouts.

## feedback
- `ascii-only` [reference] -- Never use non-ASCII characters in any file output -- no emoji, no Unicode dashes or arrows.
- `right-over-immediate` [reference] -- Always choose the architecturally correct approach; never build scaffolding then offer to upgrade it.
- `attention-to-detail` [reference] -- Read requirements carefully, verify configurations exactly, announce each action before doing it.
- `verbose-script-logging` [reference] -- Long-running scripts must emit timestamped progress to stdout AND a log file.
- `no-find-grep-cat` [reference] -- Always use dedicated tools (Glob/Grep/Read/Edit); never reach for find/grep/cat/head/tail/sed/awk in Bash.
- `oo-containerization` [reference] -- Domain entities own their data AND the methods that operate on it; no parallel dicts keyed by identity tuples.
- `snake-case` [reference] -- All identifiers including class names use snake_case; overrides Python PEP8 PascalCase convention.
- `no-ssh` [reference] -- Do not initiate SSH or remote commands by default; a direct instruction overrides this for that task only.
- `git-no-claude` [reference] -- Omit Co-Authored-By Claude footer from all commit messages.
- `tool-permissions` [reference] -- All tool use is pre-approved; call tools directly without asking for permission first.
- `csc-chain-integration` [reference] -- New CSC classes must integrate into the inheritance chain via server reference, not float as standalone objects.
- `es-for-search` [reference] -- Prefer the es command (Everything CLI) for locating files by name; install CLI tools to ~/.local/bin/ exactly as directed.
- `proactive-tool-usage` [reference] -- Check memory at session start, use code maps as source of truth, save learnings immediately.
- `news-scholarly-sources` [reference] -- For current events and tracked topics, cite news, scholarly/think-tank work, and official briefings -- not Wikipedia or Britannica.
- `margaret-weak-reviewer` [reference] -- ENGL 1302 peer reviewer Margaret Bridges provides inaccurate feedback; weight below Prof. Royall's.
- `speak-up-before-acting` [reference] -- If an instruction will break something obvious, say so before executing and propose the fix.

## environment
- `server-topology` [reference] -- Local is haven-4346 (davey-hp-ai laptop); remotes are haven-ef6e (hub/FTP/VPN/PKI), beacon-83eb, well-b7ea.
- `sudo-server` [reference] -- TCP server on 127.0.0.1:7329 running as SYSTEM at boot; accepts JSON commands and runs them elevated.
- `haven-vpn` [reference] -- OpenVPN auto-connects to haven at 107.173.223.138 TCP/443 split-mode; tunnel IP 10.10.10.10.
- `rucky-admin` [reference] -- Local admin on haven-4346 with blank password, console-only logon, for recovering from a broken davey config.

## workflow
- `temp-clone-git-workflow` [reference] -- Implementation work goes in C:/csc/tmp/irc on a feature branch; main checkouts are disposable and reset to origin/main periodically.
- `ops-roles-shared-entrypoint` [reference] -- Shared role guidance lives in ops/roles/_shared/ -- load on demand, not by default.
- `csc-stub-logging` [reference] -- Unimplemented CSC methods must call log_stubbed_call(); output goes to stdout AND stubs.log for workorder reconciliation.

## reference
- `csc-github` [reference] -- Central CSC repo at github.com/daveylongshaft/csc.git; clone with --recurse-submodules.
- `elevenlabs-key` [reference] -- Pro-tier ElevenLabs key for the english/ animation framework lives at C:\Users\davey\.api_keys (outside any repo).
- `code-maps` [reference] -- /irc/docs/tools/ has auto-generated authoritative code maps for all CSC services and methods; use instead of reading source.
- `haven-script-server` [reference] -- Pre-built eggdrop binaries, python.so, and deployment scripts at /var/www/script-server/ on haven.
- `pm-queue-worker` [reference] -- Orchestration layer: PM.classify/pick_agent/run_cycle and queue_worker.process_inbox/monitor_active_tasks.

## task
- `s2s-linking-investigation` [stashed] -- Restore haven-4346 <-> haven-ef6e server linking and synchronized #general membership.
- `phase1-dispatcher` [done] -- Eggdrop dispatcher with dual access (DCC + IRC channel), event-driven monitoring, mircryption. COMPLETE 2026-05-05.
- `csc-bot-package` [done] -- Deployable bot bundle at C:\csc\tmp\bot.tgz -- eggdrop 1.10.1 + python.so + dispatcher scripts + setup.sh. Deploy-tested in WSL.
- `account-manager` [stashed] -- 8-account Google Drive/email management system; awaiting user input on recovery emails, 2FA, and ruckypup.tab@ purpose.
- `bridge-dual-server` [stashed] -- Bridge designed for single outbound; stashed work to support routing to two test servers (19525 and 29525).
- `testing-servers` [reference] -- Two IRC test servers at /c/csc/tmp/s2s-test/; server1 on 19525, server2 on 29525.

## project
- `acc-spring-2026` [reference] -- Davey is enrolled at Austin Community College Spring 2026 in Ethics, ENGL 1302, Phys-Anth, and College Algebra.
- `distributed-workforce-arch` [reference] -- Eggdrop bot + background services + shared ops/ filesystem; no root required, everything in user home dirs.

## topic
- `iran-war-overview` [reference] -- 2026 US/Israel-Iran war status snapshot -- belligerents, casus belli, current status, peace blockers, economic impact. Refresh before discussing.
- `iran-war-timeline` [reference] -- Append-only dated event log for the 2026 US/Israel-Iran war from June 2025 onward.
