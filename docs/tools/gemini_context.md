# Gemini Agent Context — Performance Reviews & Guidance

This file is included in every Gemini launch. Read it. Learn from past runs.

## Platform Layer (2026-02-19)

CSC now has a cross-platform detection layer (`packages/csc_shared/platform.py`). Key facts:
- Detects hardware, OS, virtualization, software, Docker, AI agents
- Persists to `platform.json` on every startup
- Prompts can have YAML front-matter: `requires:`, `platform:`, `min_ram:`
- Tests for specific platforms use `tests/platform_gate.py` — prints `PLATFORM_SKIP:` on wrong platform
- Cron keeps the log on wrong platform (locks it), generates a `PROMPT_run_test_<name>.md` routing prompt
- Right-platform AI picks up the prompt, deletes the log, lets cron run the test there
- Prompt filenames now use agent recommendation prefixes (e.g., `gemini-2.5-flash-`, `haiku-`)
- See `docs/platform.md` for full documentation

---

## Run Review: PROMPT_fix_test_integration.md (2026-02-17)

**Task:** Fix 1 failing test (test_private_message race condition)
**Result:** Fixed. 5 lines changed, 2 commits. ~12 minutes.

### What went well
- Correct root cause diagnosis: race condition between persist/restore and client access
- Clean, minimal fix: added `clients_lock` around persist_all() and restore_all()
- Good commit message: "Fix race condition in server persistence by locking during multi-file writes"
- Journaled every step to the WIP file (after instructions were corrected)
- Properly moved task to done/ with a separate housekeeping commit

### What needs improvement

1. **DID NOT PUSH.** The commits are local only (`origin/main: ahead 2`). The workflow is fix → commit → push → move to done. You skipped push. Always run `git push` after committing.

2. **Wrong turn wasted time.** You added debug logging to storage.py, then reverted it. On a 1-failure task, the test log + source code should be enough to diagnose. Read the error traceback carefully before reaching for printf debugging.

3. **Journal entries lack detail.** "found: client dropped due to storage sync issue" is vague. Better: "found: test_private_message AssertionError — PRIVMSG not received because persist_all() modifies clients dict while message handler iterates it, causing KeyError that drops the client." The WIP log is the owner's receipt — make it informative enough that someone reading it understands the problem without re-reading the code.

4. **Read too many files.** You read server.py, csc_server/server.py, storage.py, csc_server/storage.py, server_message_handler.py — some of these are the same file at different paths. Check `tools/INDEX.txt` and `tools/csc-server.txt` first to find exactly which file and method you need. The code maps exist to save you from reading everything.

5. **12 minutes for a 5-line fix is slow.** The diagnosis was correct but the path was wandering. For single-failure tasks: read log → read traceback → find the failing line → read that function → fix. Should be 3-5 minutes.

### Rules to internalize

- **Always `git push` after committing.** Check with `git log origin/main..HEAD` — if it shows commits, you haven't pushed.
- **Never run tests.** Cron handles testing. Delete the log file to trigger retest: `rm tests/logs/test_<name>.log`
- **Use code maps first.** Read `tools/INDEX.txt` then `tools/csc-server.txt` before opening .py files.
- **Journal with detail.** Each echo should tell a reader what you found or what you're changing and why. Not just "reading X" but "reading X to check Y because Z."
- **Stay scoped.** Only modify files related to your task. Don't touch bridge, topic_command, or other packages unless your task requires it.

---

## Run Review: PROMPT_fix_dh_encryption.md (2026-02-17)

**Task:** Fix broken DH key exchange between bridge and server (2 bugs: wrong params + encrypted reply)
**Result:** Fixed. 3 files changed (crypto.py, server_message_handler.py, config.json). 2 commits. ~3 minutes.

### What went well — significant improvement
- **PUSHED this time.** `git log origin/main..HEAD` is clean. The Run 1 feedback was applied.
- **Fast execution.** ~3 minutes for a multi-file fix across shared lib + server + config. Major improvement from 12 min on Run 1.
- **Clean, correct fix.** Modified DHExchange to accept optional p,g params, reordered send-before-store in handler. Both bugs fixed precisely as described.
- **Journaled 11 steps.** Every action logged before doing it.
- **Stayed scoped.** Only touched the 3 files needed. No wandering into unrelated code.
- **No wrong turns.** No debug logging detours. Read the code, understood it, fixed it.
- **Re-enabled encryption in config.** Followed all instructions including cleanup.

### What still needs improvement

1. **Journal detail is better but still generic.** "Modifying crypto.py to allow custom DH parameters" is clearer than Run 1, but still doesn't say WHY (server was generating new p,g instead of using client's). Ideal: "Modifying crypto.py DHExchange.__init__ to accept p,g args — server must use client's params for shared secret to match."

2. **Tried `cat` instead of proper file reading.** Journal says "Reading code maps using cat since read_file was blocked" — use the Read/file tool, not cat via shell. Shell commands for file reading waste time and can hit permission issues.

3. **Did not delete test logs for retest.** The prompt said "Do NOT run tests — cron handles that" but didn't explicitly mention deleting logs. However, the standard workflow includes `rm tests/logs/test_<name>.log` to trigger cron retest. Always delete relevant test logs after a fix.

### Trend: Run 1 → Run 2
| Metric | Run 1 | Run 2 |
|--------|-------|-------|
| Time | ~12 min | ~3 min |
| Pushed | No | Yes |
| Wrong turns | 1 (debug logging) | 0 |
| Journal entries | 10 (vague) | 11 (better) |
| Files touched outside scope | Yes | No |
| Overall | C+ | A- |

---

## Run Review: PROMPT_test_quit_cleanup.md (2026-02-17)

**Task:** Ghost nick cleanup — 3 parts: server prune cycle via last_seen, startup prune, test QUIT teardown
**Result:** Partially fixed. 2 files changed (server.py +30, test_integration.py +11). 1 commit. ~17 minutes (09:24 launch → 09:28 commit).

### What went well
- **Pushed.** Commit `47b834d` reached remote. Good habit retained from Run 2 feedback.
- **Core fix is correct.** Added second pass to `_run_cleanup_once()` that prunes persisted channel members with no live connection when `last_seen > timeout`. Correct algorithm, clean implementation.
- **Startup prune works.** Added `self._run_cleanup_once()` call after `storage.restore_all()` in `__init__`. Correct placement.
- **Test cleanup pattern is right.** Changed `test_integration.py:make_client()` to send QUIT before close via `addCleanup()`. Good pattern.

### What needs improvement

1. **Incomplete scope — missed 2 of 3 test files.** The prompt explicitly listed `test_server_irc.py`, `test_integration.py`, `test_topic_command.py`, `test_persistence.py` for teardown QUIT. Only `test_integration.py` was updated. The other test files still create ghosts. This is a partial fix — should have been caught before committing.

2. **Only 6 journal entries for a 3-part task.** A task with 3 distinct implementation parts should have ~15+ entries: what you read, what you found, what you changed in each part, and what you verified. "Modifying packages/csc-server/server.py to add ghost nick cleanup logic" is one line for 30 lines of code. Break it down: what function, what the algorithm does, what edge cases you considered.

3. **Did not delete test logs.** After fixing server.py and test_integration.py, should have `rm tests/logs/test_integration.log` and `rm tests/logs/test_server_irc.log` etc. to trigger cron retest. Same feedback as Run 2.

4. **17 minutes is reasonable for the server.py changes but not for a partial result.** If you had done all 3 test files it would be a solid B+. Shipping incomplete work is worse than taking longer to finish.

### Trend: Run 1 → Run 2 → Run 3 (quit cleanup)
| Metric | Run 1 | Run 2 | Run 3 |
|--------|-------|-------|-------|
| Time | ~12 min | ~3 min | ~17 min |
| Pushed | No | Yes | Yes |
| Wrong turns | 1 | 0 | 0 |
| Journal entries | 10 (vague) | 11 (better) | 6 (sparse) |
| Files touched outside scope | Yes | No | No |
| Completed full task scope | Yes | Yes | **No — missed test files** |
| Overall | C+ | A- | B- |

### Key lesson
**Read the full task spec before committing.** The prompt listed 4+ test files. Check each one off. Don't commit until all parts are done.
