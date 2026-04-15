import sys
import os
import time
import json
import threading
from pathlib import Path
from csc_platform import Platform

class PollingLoop:
    """Orchestrator polling loop for CSC infrastructure services."""

    def __init__(self, work_dir=None, poll_interval=60):
        self.plat = Platform()
        self.work_dir = Path(work_dir) if work_dir else self.plat.PROJECT_ROOT
        self.poll_interval = poll_interval
        self._running = True

    def _killswitch_sleep(self, seconds):
        """Sleep in 20s chunks — checks SHUTDOWN file at most every 20s."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if (self.work_dir / "SHUTDOWN").exists():
                return
            time.sleep(min(20, deadline - time.monotonic()))

    def run(self, config, srv=None):
        """Main execution loop for infrastructure services."""
        from csc_loop.infra import git_sync

        enable_test_runner = config.get("enable_test_runner", True)
        enable_queue_worker = config.get("enable_queue_worker", True)
        enable_pm = config.get("enable_pm", True)
        enable_pr_review = config.get("enable_pr_review", False)
        enable_jules = config.get("jules", {}).get("enabled", False)
        enable_codex = config.get("codex", {}).get("enabled", False)
        enable_pki = config.get("enable_pki", False)
        enable_ftpd = config.get("ftpd", {}).get("enabled", False)

        ts = lambda: time.strftime("%Y-%m-%d %H:%M:%S")
        idle_cycles = 0

        while self._running:
            if hasattr(self, "check_shutdown") and self.check_shutdown():
                if hasattr(self, "log_shutdown"): self.log_shutdown()
                break
            if (self.work_dir / "SHUTDOWN").exists():
                print(f"[{ts()}] [csc-loop] SHUTDOWN kill switch detected. Going dark.")
                if srv:
                    srv._running = False
                break

            git_sync.pull()
            had_work = False

            if enable_test_runner:
                try:
                    from csc_loop.infra import test_runner
                    if test_runner.run_cycle(self.work_dir):
                        had_work = True
                except Exception as e:
                    print(f"[{ts()}] [test-runner] ERROR: {e}")

            if enable_queue_worker:
                try:
                    from csc_loop.infra import queue_worker
                    if queue_worker.run_cycle(self.work_dir):
                        had_work = True
                except Exception as e:
                    print(f"[{ts()}] [queue-worker] ERROR: {e}")

            if enable_pm:
                try:
                    from csc_loop.infra import pm
                    pm.setup(self.work_dir)
                    if pm.run_cycle():
                        had_work = True
                        if enable_queue_worker:
                            from csc_loop.infra import queue_worker
                            if queue_worker.run_cycle(self.work_dir):
                                had_work = True
                except Exception as e:
                    print(f"[{ts()}] [pm] ERROR: {e}")

            if enable_pr_review:
                try:
                    from csc_loop.infra import pr_review
                    if pr_review.run_cycle(self.work_dir):
                        had_work = True
                except Exception as e:
                    print(f"[{ts()}] [pr-review] ERROR: {e}")

            if enable_jules:
                try:
                    from csc_loop.infra import jules_monitor
                    if jules_monitor.run_cycle(self.work_dir):
                        had_work = True
                except Exception as e:
                    print(f"[{ts()}] [jules] ERROR: {e}")

            if enable_codex:
                try:
                    from csc_loop.infra import codex_monitor
                    if codex_monitor.run_cycle(self.work_dir):
                        had_work = True
                except Exception as e:
                    print(f"[{ts()}] [codex] ERROR: {e}")

            if enable_pki:
                try:
                    from csc_loop.infra import pki_server
                    if pki_server.run_cycle(self.work_dir):
                        had_work = True
                except Exception as e:
                    print(f"[{ts()}] [pki] ERROR: {e}")

            if enable_ftpd:
                try:
                    from csc_loop.infra import ftpd
                    if ftpd.run_cycle(self.work_dir):
                        had_work = True
                except Exception as e:
                    print(f"[{ts()}] [ftpd] ERROR: {e}")

            git_sync.push_if_changed()

            if had_work:
                idle_cycles = 0
            else:
                idle_cycles += 1
                if idle_cycles >= 3:
                    self._killswitch_sleep(self.poll_interval)
                    idle_cycles = 0
