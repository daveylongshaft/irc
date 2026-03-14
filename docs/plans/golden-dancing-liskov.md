# Plan: Windows Test Runner Service

## Context

The CSC test system currently uses `tests/run_tests.sh` (bash) to poll for tests missing logs and run them. On Windows, this is invoked via `setup-tasks.bat` as `bash tests/run_tests.sh` through Task Scheduler every 5 minutes. The user wants:

1. A native Python test runner script (no bash dependency) at `bin/test-runner`
2. A `--daemon` mode that polls every 60 seconds
3. A `.bat` wrapper at `bin/test-runner.bat`
4. An installer that registers it as a Windows scheduled task
5. Documentation in README

## Files to Create

### 1. `bin/test-runner` (Python script)

Reimplements `tests/run_tests.sh` in pure Python:

- **Scan** `tests/test_*.py` and `tests/live_*.py`
- **Skip** any test with an existing `tests/logs/<basename>.log`
- **Run** missing tests via `python -m pytest <file> -v`, capture output to log
- **PLATFORM_SKIP**: If log contains `PLATFORM_SKIP:` lines, keep log (lock), generate routing prompt from `tests/platform_skip_template.md`
- **FAILED**: If log contains `FAILED` lines, generate fix prompt from `tests/prompt_template.md`
- **`--daemon` flag**: Loop with 60-second sleep between cycles
- **`--install` flag**: Print/run schtasks command to register as scheduled task (every 1 minute)
- **`--uninstall` flag**: Remove the scheduled task
- **Logging**: Append to `logs/test-runner.log`

Structure follows `bin/queue-worker` patterns:
- Same path constants (CSC_ROOT, SCRIPT_DIR, etc.)
- Same `log()` function pattern
- Same `--daemon` / `--setup-scheduler` CLI pattern

### 2. `bin/test-runner.bat` (Batch wrapper)

Follow existing pattern from `bin/queue-worker.bat`:
```batch
@echo off
REM Test Runner Batch Wrapper for Windows Task Scheduler
cd /d "%~dp0..\"
python "%~dp0test-runner" %*
```

### 3. Update `bin/setup-tasks.bat`

Change the "CSC Test Runner" task from:
```
bash tests\run_tests.sh
```
to:
```
python bin\test-runner
```
And change interval from 5 minutes to 1 minute.

### 4. Update `CLAUDE.md`

Add test-runner documentation to the Common Commands / Testing section.

## Key Design Decisions

- **Pure Python** - no bash dependency on Windows
- **Template substitution** done with `str.replace()` (matching the simple `{{VAR}}` pattern in templates)
- **Same idempotent semantics** as `run_tests.sh`: log exists = skip, no log = run
- **schtasks** for installer (consistent with existing setup-tasks.bat pattern)
- **1-minute polling** as requested

## Files Modified

| File | Action |
|------|--------|
| `bin/test-runner` | Create - Python test runner |
| `bin/test-runner.bat` | Create - Batch wrapper |
| `bin/setup-tasks.bat` | Edit - Update test runner task to use Python script, 1-min interval |
| `CLAUDE.md` | Edit - Add test-runner docs to Testing section |

## Verification

1. Run `python bin/test-runner` once manually - should find `test_queue_worker` (no log) and run it
2. Check `tests/logs/test_queue_worker.log` is created
3. Run again - should skip all tests (all have logs)
4. Delete a log, run again - should re-run that test
5. Run `bin/test-runner --install` as admin to register scheduled task
6. `schtasks /query /tn "CSC Test Runner"` to verify
