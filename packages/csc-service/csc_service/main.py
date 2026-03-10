"""csc-service: unified service manager for CSC.

Usage:
    csc-service --daemon              # run all subsystems
    csc-service --daemon --local      # run on cwd (no clone)
    csc-service --daemon --dir /path  # run in specific directory
"""
import sys
import os
import time
import json
import threading
import subprocess
from pathlib import Path

def main():
    args = sys.argv[1:]
    
    # Walk up to find project root: prefer csc-service.json (config), fall back to CLAUDE.md
    csc_root = Path(__file__).resolve().parent
    claude_md_stop = None
    for _ in range(10):
        if (csc_root / "csc-service.json").exists():
            break
        if (csc_root / "CLAUDE.md").exists() and claude_md_stop is None:
            claude_md_stop = csc_root  # remember but keep looking for csc-service.json
        if csc_root == csc_root.parent:
            csc_root = claude_md_stop or csc_root
            break
        csc_root = csc_root.parent
    work_dir = csc_root
    poll_interval = 60

    # Initialize Platform layer first - this sets up global Log paths
    from csc_service.shared.platform import Platform
    plat = Platform()
    
    config_file = csc_root / "csc-service.json"
    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding='utf-8'))
        except Exception: pass

    poll_interval = config.get("poll_interval", 60)
    enable_test_runner = config.get("enable_test_runner", True)
    enable_queue_worker = config.get("enable_queue_worker", True)
    enable_pm = config.get("enable_pm", True)
    enable_pr_review = config.get("enable_pr_review", False)
    enable_jules = config.get("jules", {}).get("enabled", False)

    from csc_service.infra import git_sync
    git_sync.setup(work_dir)

    if "--daemon" in args:
        os.environ["CSC_HEADLESS"] = "true"
        ts = lambda: time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts()}] [csc-service] Starting (poll every {poll_interval}s)")
        
        # Start core threaded components (IRC server, Bridge, Clients)
        server_thread = None
        if config.get("enable_server", True):
            from csc_server.server import Server
            srv = Server()
            server_thread = threading.Thread(target=srv.run, daemon=True)
            server_thread.start()
            print(f"[{ts()}] [csc-service] Started IRC server")

        # Daemon main loop for infra services
        try:
            while True:
                git_sync.pull()

                if enable_test_runner:
                    from csc_service.infra import test_runner
                    test_runner.run_cycle(work_dir)

                if enable_queue_worker:
                    from csc_service.infra import queue_worker
                    queue_worker.run_cycle(work_dir)

                if enable_pm:
                    from csc_service.infra import pm
                    pm.setup(work_dir)
                    pm.run_cycle()

                if enable_pr_review:
                    from csc_service.infra import pr_review
                    pr_review.run_cycle(work_dir)

                if enable_jules:
                    from csc_service.infra import jules_monitor
                    jules_monitor.run_cycle(work_dir)

                git_sync.push_if_changed()
                time.sleep(poll_interval)

        except KeyboardInterrupt:
            print(f"\n[{ts()}] [csc-service] Stopped")
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
