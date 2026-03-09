#!/usr/bin/env python3
"""
Test Runner: Polls for tests missing logs and runs them automatically.

Scans irc/tests/test_*.py and live_*.py, runs any without a matching log
in irc/tests/logs/. Generates fix prompts (ops/wo/ready/) for failures and
routing prompts for platform-gated tests.

Usage (embedded, called from main.py loop):
    test_runner.run_cycle()

Usage (standalone):
    python test_runner.py          # one cycle
    python test_runner.py --daemon # poll every 60s
"""

import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Root detection
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent

# Walk up to find .irc_root marker -> IRC_ROOT
_p = SCRIPT_DIR
for _i in range(10):
    if (_p / ".irc_root").exists():
        break
    if _p == _p.parent:
        break
    _p = _p.parent
IRC_ROOT = _p

# CSC_ROOT is one level above irc/ (has .irc_root)
CSC_ROOT = IRC_ROOT.parent

POLL_INTERVAL = 60

# ---------------------------------------------------------------------------
# Paths (updated by _setup_work_root for isolated clones)
# ---------------------------------------------------------------------------
TEST_DIR         = IRC_ROOT / "tests"
LOG_DIR          = TEST_DIR / "logs"
TEMPLATE         = TEST_DIR / "prompt_template.md"
PLATFORM_TEMPLATE = TEST_DIR / "platform_skip_template.md"
PROMPT_DIR       = CSC_ROOT / "ops" / "wo" / "ready"
LOGS_DIR         = CSC_ROOT / "ops" / "logs"
RUNNER_LOG       = LOGS_DIR / "test-runner.log"


def _setup_work_root(irc_root):
    """Redirect all paths to an isolated irc clone."""
    global IRC_ROOT, CSC_ROOT, TEST_DIR, LOG_DIR, TEMPLATE
    global PLATFORM_TEMPLATE, PROMPT_DIR, LOGS_DIR, RUNNER_LOG
    IRC_ROOT          = Path(irc_root)
    CSC_ROOT          = IRC_ROOT.parent
    TEST_DIR          = IRC_ROOT / "tests"
    LOG_DIR           = TEST_DIR / "logs"
    TEMPLATE          = TEST_DIR / "prompt_template.md"
    PLATFORM_TEMPLATE = TEST_DIR / "platform_skip_template.md"
    PROMPT_DIR        = CSC_ROOT / "ops" / "wo" / "ready"
    LOGS_DIR          = CSC_ROOT / "ops" / "logs"
    RUNNER_LOG        = LOGS_DIR / "test-runner.log"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [test-runner] [{level}] {msg}"
    print(line, file=sys.stderr)
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(RUNNER_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

def _fill_template(template_path, replacements):
    try:
        content = template_path.read_text(encoding="utf-8")
        for key, value in replacements.items():
            content = content.replace(f"{{{{{key}}}}}", value)
        return content
    except Exception as e:
        log(f"Template error {template_path}: {e}", "ERROR")
        return None


# ---------------------------------------------------------------------------
# Core cycle
# ---------------------------------------------------------------------------

def find_test_files():
    files = []
    for pattern in ["test_*.py", "live_*.py"]:
        files.extend(sorted(TEST_DIR.glob(pattern)))
    return files


def run_one_test(test_file):
    """Run a single test. Returns: skipped | passed | failed | platform_skip | error"""
    basename = test_file.stem
    log_file = LOG_DIR / f"{basename}.log"

    if log_file.exists():
        return "skipped"

    log(f"Running: {test_file.name}")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-v"],
            capture_output=True, text=True, timeout=300,
            cwd=str(IRC_ROOT),
        )
        output = result.stdout + "\n" + result.stderr
    except subprocess.TimeoutExpired:
        output = "FAILED: Test timed out after 300 seconds\n"
        log(f"TIMEOUT: {test_file.name}", "WARN")
    except Exception as e:
        output = f"FAILED: Could not run test: {e}\n"
        log(f"ERROR running {test_file.name}: {e}", "ERROR")
        return "error"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file.write_text(output, encoding="utf-8")
    os.chmod(log_file, 0o664)

    platform_skip_lines = [l for l in output.splitlines() if "PLATFORM_SKIP:" in l]
    if platform_skip_lines:
        log(f"PLATFORM_SKIP: {test_file.name}")
        _generate_platform_prompt(basename, "\n".join(platform_skip_lines))
        return "platform_skip"

    failed_lines = [l for l in output.splitlines() if "FAILED" in l]
    if failed_lines or (hasattr(result, 'returncode') and result.returncode != 0):
        log(f"FAILED: {test_file.name} ({len(failed_lines)} failures)", "WARN")
        _generate_fix_prompt(basename, "\n".join(failed_lines))
        return "failed"

    log(f"PASSED: {test_file.name}")
    return "passed"


def run_cycle(work_dir_arg=None):
    """Run one polling cycle. Called from main.py loop."""
    if work_dir_arg:
        _setup_work_root(work_dir_arg)

    test_files = find_test_files()
    if not test_files:
        log("No test files found")
        return 0

    stats = {"skipped": 0, "passed": 0, "failed": 0, "platform_skip": 0, "error": 0}
    for test_file in test_files:
        result = run_one_test(test_file)
        stats[result] = stats.get(result, 0) + 1

    ran = stats["passed"] + stats["failed"] + stats["platform_skip"] + stats["error"]
    if ran > 0:
        log(f"Cycle done: {ran} ran — passed={stats['passed']} failed={stats['failed']} "
            f"platform_skip={stats['platform_skip']} skipped={stats['skipped']}")
    return ran


# ---------------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------------

def _generate_fix_prompt(basename, failed_lines):
    prompt_file = PROMPT_DIR / f"PROMPT_fix_{basename}.md"
    if prompt_file.exists():
        return
    if not TEMPLATE.exists():
        log(f"Template missing: {TEMPLATE}", "WARN")
        return
    test_name = basename[5:] if basename.startswith("test_") else basename
    content = _fill_template(TEMPLATE, {
        "TEST_NAME": test_name,
        "TEST_FILE": f"{basename}.py",
        "LOG_FILE": f"{basename}.log",
        "FAILED_LINES": failed_lines,
    })
    if content:
        PROMPT_DIR.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(content, encoding="utf-8")
        os.chmod(prompt_file, 0o664)
        log(f"Created fix prompt: {prompt_file.name}")


def _generate_platform_prompt(basename, skip_lines):
    prompt_file = PROMPT_DIR / f"PROMPT_run_{basename}.md"
    if prompt_file.exists():
        return
    if not PLATFORM_TEMPLATE.exists():
        log(f"Platform template missing: {PLATFORM_TEMPLATE}", "WARN")
        return
    test_name = basename[5:] if basename.startswith("test_") else basename
    content = _fill_template(PLATFORM_TEMPLATE, {
        "TEST_NAME": test_name,
        "TEST_FILE": f"{basename}.py",
        "LOG_FILE": f"{basename}.log",
        "PLATFORM_SKIP_LINES": skip_lines,
    })
    if content:
        PROMPT_DIR.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(content, encoding="utf-8")
        os.chmod(prompt_file, 0o664)
        log(f"Created platform prompt: {prompt_file.name}")


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def main():
    if "--daemon" in sys.argv or "-d" in sys.argv:
        log(f"Daemon mode (poll every {POLL_INTERVAL}s, tests: {TEST_DIR})")
        try:
            while True:
                run_cycle()
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            log("Stopped")
    else:
        run_cycle()


if __name__ == "__main__":
    main()
