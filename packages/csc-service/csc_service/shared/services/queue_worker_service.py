"""
Queue Worker Service: Background service for processing agent prompt queues.

Workflow:
1. Scan agents/*/queue/in/ for queued workorders
2. Move from queue/in/ -> queue/work/
3. Start agent using agents/<agent>/bin/run_agent.sh
4. Track agent PID
5. When PID dies, check for COMPLETE in WIP file
6. If complete:
   - Move queue/work/ -> queue/out/
   - Move wip/ -> done/
   - Run refresh-maps
   - Git commit+push
7. If incomplete:
   - Log as FAILED
   - Move wip/ -> ready/ for retry

Can run:
- Via periodic scripts (cron, Task Scheduler) - use bin/queue-worker
- Embedded in csc-service daemon - use QueueWorkerService
- Via csc-ctl queue-worker cycle command
"""

import os
import sys
import json
import time
import shutil
import signal
import subprocess
from pathlib import Path
from datetime import datetime
from csc_service.server.service import Service
from csc_service.shared.services import PROJECT_ROOT as _PROJECT_ROOT
from csc_service.shared.platform import Platform


class QueueWorkerService(Service):
    """Background service for processing agent prompt queues.

    Monitors agents/*/queue/in/ and manages prompt execution lifecycle.
    """

    PROJECT_ROOT = _PROJECT_ROOT
    AGENTS_DIR = _PROJECT_ROOT / "agents"
    PROMPTS_BASE = _PROJECT_ROOT / "workorders"
    WIP_DIR = PROMPTS_BASE / "wip"
    DONE_DIR = PROMPTS_BASE / "done"
    READY_DIR = PROMPTS_BASE / "ready"
    LOGS_DIR = _PROJECT_ROOT / "logs"
    BIN_DIR = _PROJECT_ROOT / "bin"

    # PID file extension
    PID_SUFFIX = ".pid"

    # Platform detection
    IS_WINDOWS = os.name == 'nt'

    # Real agents (not docker tool chains)
    REAL_AGENTS = {
        # Cloud agents
        "haiku", "sonnet", "opus",
        "gemini", "gemini-2.5-flash", "gemini-2.5-flash-lite",
        "gemini-3-flash", "gemini-3-pro", "gemini-2.5-pro",
        # Local agents
        "ollama-codellama", "ollama-deepseek", "ollama-qwen",
        # Test
        "test-agent"
    }

    def __init__(self, server_instance):
        super().__init__(server_instance)
        self.name = "queue_worker"
        self.init_data()
        self.platform = None
        self._load_platform()
        # Auto-create temp/runtime directories
        self._ensure_temp_dirs()
        self.log("Queue Worker Service initialized")

    def _load_platform(self):
        """Load platform data with dual-notation paths."""
        try:
            platform_file = self.PROJECT_ROOT / "platform.json"
            if platform_file.exists():
                with open(platform_file, 'r') as f:
                    self.platform = json.load(f)
        except Exception as e:
            self.log(f"WARN: Could not load platform.json: {e}")
            self.platform = None

    def _ensure_agent_dirs(self, agent_name):
        """Auto-create agent directories from template if they don't exist."""
        agent_dir = self.AGENTS_DIR / agent_name
        if agent_dir.exists():
            return  # Already exists

        # Create basic structure
        (agent_dir / "bin").mkdir(parents=True, exist_ok=True)
        (agent_dir / "queue" / "in").mkdir(parents=True, exist_ok=True)
        (agent_dir / "queue" / "work").mkdir(parents=True, exist_ok=True)
        (agent_dir / "queue" / "out").mkdir(parents=True, exist_ok=True)

        # Copy run_agent scripts from template (if it exists)
        template_dir = self.AGENTS_DIR / "templates"
        if template_dir.exists():
            for script in ["run_agent.py", "run_agent.bat", "run_agent.sh"]:
                template_script = template_dir / script
                if template_script.exists():
                    try:
                        dest_script = agent_dir / "bin" / script
                        shutil.copy2(str(template_script), str(dest_script))
                        # Make .sh executable on Unix-like systems
                        if script.endswith('.sh') and os.name != 'nt':
                            os.chmod(str(dest_script), 0o755)
                        self.log(f"Created {agent_dir.name}/{script} from template")
                    except Exception as e:
                        self.log(f"WARN: Could not copy {script}: {e}")
        else:
            # If no template, at least create empty bin dir
            self.log(f"Created agent directory: {agent_dir.name}")

    def _ensure_temp_dirs(self):
        """Auto-create temp/runtime directories if they don't exist."""
        dirs_to_create = [
            self.WIP_DIR,
            self.DONE_DIR,
            self.READY_DIR,
            self.LOGS_DIR,
        ]
        for directory in dirs_to_create:
            directory.mkdir(parents=True, exist_ok=True)

    def _get_path_for_shell(self, windows_path, use_linux=False):
        """Convert path to appropriate notation for shell (bash uses Linux notation)."""
        if not self.platform:
            return str(windows_path)

        windows_path_str = str(windows_path)

        if use_linux and self.platform.get('runtime', {}).get('proj_dir_linux'):
            # Replace Windows proj_dir with Linux proj_dir
            proj_dir_win = self.platform.get('runtime', {}).get('proj_dir_windows', str(self.PROJECT_ROOT))
            proj_dir_linux = self.platform.get('runtime', {}).get('proj_dir_linux')
            if windows_path_str.startswith(proj_dir_win):
                return windows_path_str.replace(proj_dir_win, proj_dir_linux).replace('\\', '/')

        return windows_path_str

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def is_process_alive(self, pid):
        """Check if a process with given PID is still running."""
        try:
            if self.IS_WINDOWS:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True, text=True
                )
                return str(pid) in result.stdout
            else:
                os.kill(pid, 0)
                return True
        except (OSError, ProcessLookupError, subprocess.CalledProcessError):
            return False

    def append_agent_log_to_wip(self, agent_name, prompt_filename):
        """Append agent log file to WIP file for audit trail."""
        wip_file = self.WIP_DIR / prompt_filename

        # Find agent log file
        log_stem = Path(prompt_filename).stem
        for log_file in self.LOGS_DIR.glob(f"agent_*_{log_stem}.log"):
            if log_file.exists():
                try:
                    log_content = log_file.read_text(encoding='utf-8', errors='ignore')
                    if log_content.strip():
                        if wip_file.exists():
                            with open(wip_file, 'a', encoding='utf-8') as f:
                                f.write(f"\n\n--- Agent Log ---\n{log_content}")
                        else:
                            wip_file.write_text(log_content, encoding='utf-8')
                        self.log(f"Appended agent log to {prompt_filename}")
                except Exception as e:
                    self.log(f"WARN: Could not append agent log: {e}")
                break

    def check_wip_complete(self, prompt_filename):
        """Check if WIP file has COMPLETE as the last non-empty line."""
        wip_file = self.WIP_DIR / prompt_filename
        if not wip_file.exists():
            return False

        try:
            content = wip_file.read_text(encoding='utf-8', errors='ignore')
            lines = [l.strip() for l in content.splitlines() if l.strip()]
            if not lines:
                return False
            return lines[-1] == "COMPLETE"
        except Exception:
            return False

    def add_verification_message(self, prompt_filename):
        """Add verification message to incomplete workorder."""
        wip_file = self.WIP_DIR / prompt_filename
        if wip_file.exists():
            try:
                with open(wip_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n\n--- Verify/Complete or Finish ---\nPlease verify this workorder is complete or finish the work and add COMPLETE as the last line.\n")
            except Exception as e:
                self.log(f"WARN: Could not add verification message: {e}")

    def find_run_agent(self, agent_name):
        """Find the run_agent script for an agent.

        Checks:
        1. agents/<agent>/bin/run_agent.sh (Unix)
        2. agents/<agent>/bin/run_agent.bat (Windows)
        """
        agent_dir = self.AGENTS_DIR / agent_name / "bin"

        if self.IS_WINDOWS:
            bat = agent_dir / "run_agent.bat"
            if bat.exists():
                return str(bat)

        sh = agent_dir / "run_agent.sh"
        if sh.exists():
            return str(sh)

        return None

    def run_refresh_maps(self):
        """Run refresh-maps to update code maps."""
        refresh = self.BIN_DIR / "refresh-maps"
        if not refresh.exists():
            self.log("WARN: refresh-maps not found, skipping")
            return

        try:
            result = subprocess.run(
                [sys.executable, str(refresh), "--quick"],
                cwd=str(self.PROJECT_ROOT),
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                self.log("refresh-maps completed")
            else:
                self.log(f"refresh-maps failed: {result.stderr[:200]}")
        except Exception as e:
            self.log(f"refresh-maps error: {e}")

    def git_commit_push(self, message):
        """Git add, commit, pull --rebase, and push changes."""
        cwd = str(self.PROJECT_ROOT)
        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=cwd, capture_output=True, text=True, timeout=30
            )
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=cwd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                self.log(f"Git commit: {message[:80]}")
                # Retry loop: pull --rebase then push, up to 3 attempts
                for attempt in range(3):
                    pull_result = subprocess.run(
                        ["git", "pull", "--rebase", "--autostash"],
                        cwd=cwd, capture_output=True, text=True, timeout=60
                    )
                    if pull_result.returncode != 0:
                        self.log(f"Git pull --rebase failed: {pull_result.stderr[:200]}")
                        break
                    push_result = subprocess.run(
                        ["git", "push"],
                        cwd=cwd, capture_output=True, text=True, timeout=60
                    )
                    if push_result.returncode == 0:
                        self.log("Git push OK")
                        break
                    self.log(f"Git push attempt {attempt+1} failed, retrying...")
                    time.sleep(2)
                else:
                    self.log("Git push failed after 3 attempts")
            else:
                self.log(f"Git commit skipped (nothing to commit or error)")
        except Exception as e:
            self.log(f"Git error: {e}")

    # ------------------------------------------------------------------
    # Queue Processing
    # ------------------------------------------------------------------

    def spawn_agent(self, agent_name, prompt_filename):
        """Start an agent using its run_agent script. Returns PID or None."""
        run_script = self.find_run_agent(agent_name)
        if not run_script:
            self.log(f"ERROR: No run_agent script for {agent_name}")
            return None

        try:
            # The queue/work/ file IS the orders.md for the agent
            queue_work = self.AGENTS_DIR / agent_name / "queue" / "work"
            workorder_path = queue_work / prompt_filename

            # Create log file
            self.LOGS_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime('%Y%m%d-%H%M%S')
            log_file = self.LOGS_DIR / f"{agent_name}_{ts}_{prompt_filename}.log"

            # Build command with appropriate path notation for the shell
            if run_script.endswith('.bat'):
                # Windows batch file - use Windows paths
                cmd = [run_script, str(workorder_path)]
            else:
                # Bash script - use Linux notation paths from platform.json
                workorder_path_linux = self._get_path_for_shell(workorder_path, use_linux=True)
                run_script_linux = self._get_path_for_shell(run_script, use_linux=True)
                cmd = ["bash", run_script_linux, workorder_path_linux]

            self.log(f"Starting agent: {' '.join(cmd)}")

            # Open log file for agent output
            log_fh = open(str(log_file), 'w', buffering=1)

            # Spawn agent in background
            if self.IS_WINDOWS:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.PROJECT_ROOT),
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.PROJECT_ROOT),
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    start_new_session=True
                )

            pid = proc.pid
            self.log(f"Agent {agent_name} started with PID {pid}")
            self.log(f"Log: {log_file}")
            return pid

        except Exception as e:
            self.log(f"ERROR spawning agent {agent_name}: {e}")
            return None

    def _any_agent_running(self):
        """Check if any agent is currently running (has a .pid in queue/work/)."""
        for agent_dir in self.AGENTS_DIR.glob("*/queue/work"):
            if not agent_dir.exists():
                continue
            for pid_file in agent_dir.glob(f"*{self.PID_SUFFIX}"):
                try:
                    pid = int(pid_file.read_text(encoding='utf-8').strip())
                    if self.is_process_alive(pid):
                        return True
                except Exception:
                    pass
        return False

    def process_queue_in(self):
        """Check agents/*/queue/in/ for new prompts and start agents.

        Only starts ONE agent at a time. If any agent is already running,
        skip this cycle.

        For each queued file:
        1. Move from queue/in/ -> queue/work/
        2. Start agent using run_agent.sh
        3. Save PID file in queue/work/
        """
        try:
            # One agent at a time
            if self._any_agent_running():
                self.log("Agent already running, skipping queue/in/ processing")
                return

            for agent_name in sorted(self.REAL_AGENTS):
                # Auto-create agent dirs from template if needed
                self._ensure_agent_dirs(agent_name)

                queue_in = self.AGENTS_DIR / agent_name / "queue" / "in"
                if not queue_in.exists():
                    continue

                for prompt_file in sorted(queue_in.glob("*.md")):
                    prompt_filename = prompt_file.name
                    self.log(f"Found queued prompt: {agent_name}/{prompt_filename}")

                    # Move to queue/work/
                    queue_work = self.AGENTS_DIR / agent_name / "queue" / "work"
                    queue_work.mkdir(parents=True, exist_ok=True)
                    work_path = queue_work / prompt_filename

                    try:
                        shutil.move(str(prompt_file), str(work_path))
                        self.log(f"Moved to queue/work/: {agent_name}/{prompt_filename}")
                    except Exception as e:
                        self.log(f"ERROR moving to queue/work/: {e}")
                        continue

                    # Start agent
                    pid = self.spawn_agent(agent_name, prompt_filename)
                    if pid:
                        # Save PID file
                        pid_file = queue_work / f"{prompt_filename}{self.PID_SUFFIX}"
                        try:
                            pid_file.write_text(str(pid), encoding='utf-8')
                            self.log(f"Saved PID {pid} for {agent_name}/{prompt_filename}")
                        except Exception as e:
                            self.log(f"ERROR saving PID: {e}")
                        # One at a time - stop after first successful spawn
                        return
                    else:
                        # Spawn failed, move back to queue/in/
                        try:
                            shutil.move(str(work_path), str(prompt_file))
                            self.log(f"Moved back to queue/in/ (spawn failed)")
                        except Exception:
                            pass

        except Exception as e:
            self.log(f"ERROR processing queue/in/: {e}")

    def process_queue_work(self):
        """Check agents/*/queue/work/ for completed agents.

        For each PID file in queue/work/:
        1. Check if PID is still alive
        2. If dead, check COMPLETE in WIP file
        3. If complete: queue/work/ -> queue/out/, wip/ -> done/
        4. If incomplete: log FAILED, wip/ -> ready/
        5. Run refresh-maps and git commit
        """
        try:
            needs_commit = False

            for agent_dir in self.AGENTS_DIR.glob("*/queue/work"):
                if not agent_dir.exists():
                    continue

                agent_name = agent_dir.parent.parent.name
                if agent_name not in self.REAL_AGENTS:
                    continue

                for pid_file in sorted(agent_dir.glob(f"*{self.PID_SUFFIX}")):
                    prompt_filename = pid_file.name[:-len(self.PID_SUFFIX)]

                    try:
                        pid = int(pid_file.read_text(encoding='utf-8').strip())
                    except Exception as e:
                        self.log(f"ERROR reading PID file {pid_file}: {e}")
                        continue

                    # Check if still running
                    if self.is_process_alive(pid):
                        continue

                    self.log(f"Agent PID {pid} finished for {agent_name}/{prompt_filename}")

                    # Append agent log to WIP for audit trail
                    self.append_agent_log_to_wip(agent_name, prompt_filename)

                    # Check for COMPLETE in WIP
                    is_complete = self.check_wip_complete(prompt_filename)
                    self.log(f"WIP status: {'COMPLETE' if is_complete else 'INCOMPLETE'}")

                    # Move queue/work/ -> queue/out/
                    work_prompt = agent_dir / prompt_filename
                    queue_out = agent_dir.parent / "out"
                    queue_out.mkdir(parents=True, exist_ok=True)

                    if work_prompt.exists():
                        try:
                            # Rename with unix timestamp suffix to avoid collisions
                            stem = Path(prompt_filename).stem
                            suffix = Path(prompt_filename).suffix
                            out_name = f"{stem}-{int(time.time())}{suffix}"
                            shutil.move(str(work_prompt), str(queue_out / out_name))
                            self.log(f"Moved {prompt_filename} to queue/out/{out_name}")
                        except Exception as e:
                            self.log(f"ERROR moving to queue/out/: {e}")

                    # Clean up PID file
                    try:
                        pid_file.unlink()
                    except Exception:
                        pass

                    # Move WIP file based on completion status
                    wip_file = self.WIP_DIR / prompt_filename
                    if wip_file.exists():
                        if is_complete:
                            # Success: wip/ -> done/
                            self.DONE_DIR.mkdir(parents=True, exist_ok=True)
                            dest = self.DONE_DIR / prompt_filename
                            try:
                                shutil.move(str(wip_file), str(dest))
                                self.log(f"SUCCESS: {prompt_filename} -> done/")
                                needs_commit = True
                            except Exception as e:
                                self.log(f"ERROR moving to done/: {e}")
                        else:
                            # Failed: add verification message and move wip/ -> ready/ for retry
                            self.add_verification_message(prompt_filename)
                            self.READY_DIR.mkdir(parents=True, exist_ok=True)
                            dest = self.READY_DIR / prompt_filename
                            try:
                                shutil.move(str(wip_file), str(dest))
                                self.log(f"INCOMPLETE: {prompt_filename} -> ready/ for retry")
                                needs_commit = True
                            except Exception as e:
                                self.log(f"ERROR moving to ready/: {e}")

            # Post-completion: refresh maps and git commit
            if needs_commit:
                self.run_refresh_maps()
                self.git_commit_push(
                    f"csc-service: auto-sync {time.strftime('%Y%m%d-%H%M%S')}"
                )

        except Exception as e:
            self.log(f"ERROR processing queue/work/: {e}")

    def run_cycle(self):
        """Run one complete queue processing cycle.

        1. Process queue/in/ - start new agents
        2. Process queue/work/ - handle completed agents
        """
        self.log("=" * 50)
        self.log("Cycle start")

        # Git pull to get latest changes
        try:
            self.log("git pull")
            pull_result = subprocess.run(
                ["git", "pull", "--rebase", "--autostash"],
                cwd=str(self.PROJECT_ROOT),
                capture_output=True, text=True, timeout=30
            )
            if pull_result.returncode != 0:
                self.log(f"git pull failed: {pull_result.stderr[:200]}")
        except Exception as e:
            self.log(f"git pull error: {e}")

        self.process_queue_in()
        self.process_queue_work()
        self.log("Cycle end")

    # ------------------------------------------------------------------
    # IRC service interface
    # ------------------------------------------------------------------

    def default(self, *args) -> str:
        """Show available commands."""
        return (
            "Queue Worker Service:\n"
            "  cycle  - Run one processing cycle\n"
            "  status - Show queue status\n"
        )

    def cycle(self) -> str:
        """Run one queue processing cycle."""
        self.run_cycle()
        return "Queue cycle complete"

    def status(self) -> str:
        """Show queue status."""
        lines = ["Queue Worker Status:\n"]

        queued_count = 0
        processing_count = 0
        completed_count = 0

        for agent_name in sorted(self.REAL_AGENTS):
            agent_base = self.AGENTS_DIR / agent_name / "queue"

            in_dir = agent_base / "in"
            work_dir = agent_base / "work"
            out_dir = agent_base / "out"

            in_count = len(list(in_dir.glob("*.md"))) if in_dir.exists() else 0
            work_count = len(list(work_dir.glob("*.pid"))) if work_dir.exists() else 0
            out_count = len(list(out_dir.glob("*.md"))) if out_dir.exists() else 0

            if in_count or work_count or out_count:
                lines.append(f"  {agent_name}: in={in_count} work={work_count} out={out_count}")
                queued_count += in_count
                processing_count += work_count
                completed_count += out_count

        lines.append(f"\n  Total: queued={queued_count} running={processing_count} done={completed_count}")
        return "\n".join(lines)
