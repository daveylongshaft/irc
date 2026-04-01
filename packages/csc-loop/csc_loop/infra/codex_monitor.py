"""Codex Monitor — submit workorders to OpenAI Codex Cloud and track results.

Uses the Codex CLI (`codex cloud exec --env csc`) to submit coding tasks,
polls `codex cloud list --json` to track progress, and applies completed diffs.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from csc_data.data import Data

class CodexMonitor(Data):
    """Monitor Codex tasks, submit workorders, and apply diffs."""

    def __init__(self, csc_root=None):
        super().__init__()
        self.name = "codex-monitor"
        self._initialize_paths(csc_root)
        self.init_data("codex_monitor_data.json")
        self._codex_env = "csc"
        self._load_config()

    def _initialize_paths(self, csc_root=None):
        if csc_root:
            self.csc_root = Path(csc_root).resolve()
        elif os.environ.get("CSC_ROOT"):
            self.csc_root = Path(os.environ["CSC_ROOT"])
        else:
            p = Path(__file__).resolve().parents[4]
            self.csc_root = p

        self.wo_dir = self.csc_root / "ops" / "wo"
        self.tracking_file = self.csc_root / "tmp" / "codex_tasks.json"

    def _load_config(self):
        for cfg_path in [self.csc_root / "csc-service.json", self.csc_root / "etc" / "csc-service.json"]:
            if cfg_path.exists():
                try:
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                    self._codex_env = cfg.get("codex", {}).get("environment", "csc")
                except Exception:
                    pass
                break

    def _runtime(self, msg):
        try:
            ts = time.strftime("%H:%M:%S")
            log_dir = self.csc_root / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "runtime.log", "a", encoding="utf-8") as f:
                f.write(f"[{ts}] [codex] {msg}\n")
        except Exception:
            pass

    def _find_codex_bin(self):
        codex_path = shutil.which("codex")
        if codex_path:
            return [codex_path]
        if sys.platform == "win32":
            npm_prefix = os.environ.get("APPDATA", "")
            if npm_prefix:
                cmd_path = Path(npm_prefix) / "npm" / "codex.cmd"
                if cmd_path.exists():
                    return [str(cmd_path)]
        npx_path = shutil.which("npx")
        if npx_path:
            return [npx_path, "codex"]
        return ["codex"]

    def _run_codex_cmd(self, args, timeout=60):
        cmd = self._find_codex_bin() + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.csc_root),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                shell=(sys.platform == "win32"),
            )
            return result.stdout.strip(), result.stderr.strip(), result.returncode
        except subprocess.TimeoutExpired:
            self.log(f"Codex command timed out: {' '.join(args)}", "WARN")
            return "", "", 1
        except Exception as e:
            self.log(f"Codex command failed: {e}", "ERROR")
            return "", str(e), 1

    def submit_workorder(self, workorder_filename):
        wip_path = self.wo_dir / "wip" / workorder_filename
        if not wip_path.exists():
            self.log(f"Workorder not found: {wip_path}", "ERROR")
            return None

        content = wip_path.read_text(encoding="utf-8", errors="replace")
        prompt = (
            f"Task: {workorder_filename}\n\n"
            f"{content}\n\n"
            f"Rules: one class per file (snake_case names), write tests, "
            f"do NOT run tests, use Platform for paths, ASCII only in .md files."
        )

        self.log(f"Submitting to Codex Cloud: {workorder_filename}")
        stdout, stderr, rc = self._run_codex_cmd(["cloud", "exec", "--env", self._codex_env, prompt], timeout=120)

        if rc != 0:
            self.log(f"Codex cloud exec failed (rc={rc}): {stderr[:300]}", "ERROR")
            return None

        task_id = self._parse_task_id(stdout)
        if not task_id:
            self.log(f"Could not parse task ID from: {stdout[:200]}", "ERROR")
            return None

        tracking = self.get_data("tasks") or {}
        tracking[task_id] = {
            "workorder": workorder_filename,
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "submitted",
        }
        self.put_data("tasks", tracking)
        self.log(f"Submitted: {workorder_filename} -> {task_id}")
        return task_id

    def _parse_task_id(self, output):
        match = re.search(r'(task_e_[a-f0-9]+)', output)
        if match:
            return match.group(1)
        for line in output.splitlines():
            line = line.strip()
            if not line: continue
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    tid = data.get("id") or data.get("task_id") or data.get("taskId")
                    if tid: return tid
            except json.JSONDecodeError: continue
        return None

    def poll_tasks(self):
        stdout, stderr, rc = self._run_codex_cmd(["cloud", "list", "--json"], timeout=30)
        if rc != 0:
            self.log(f"Codex cloud list failed (rc={rc}): {stderr[:200]}", "WARN")
            return []

        try:
            data = json.loads(stdout)
            cloud_tasks = data.get("tasks", [])
        except json.JSONDecodeError:
            self.log("Failed to parse cloud list output", "WARN")
            return []

        tracking = self.get_data("tasks") or {}
        changes = []

        for task in cloud_tasks:
            task_id = task.get("id", "")
            cloud_status = task.get("status", "")
            if task_id not in tracking: continue

            tracked = tracking[task_id]
            old_status = tracked.get("status", "")
            if cloud_status != old_status:
                tracked["status"] = cloud_status
                tracked["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                if task.get("summary"): tracked["summary"] = task["summary"]
                changes.append((task_id, tracked["workorder"], cloud_status))
                self.log(f"Task {task_id}: {old_status} -> {cloud_status} ({tracked['workorder']})")
                self._runtime(f"task {task_id[-12:]}: {old_status} -> {cloud_status}")

        if changes:
            self.put_data("tasks", tracking)
        return changes

    def handle_completed_task(self, task_id):
        tracking = self.get_data("tasks") or {}
        if task_id not in tracking: return False
        tracked = tracking[task_id]
        workorder_filename = tracked["workorder"]

        self.log(f"Applying diffs for task {task_id} ({workorder_filename})")
        stdout, stderr, rc = self._run_codex_cmd(["cloud", "apply", task_id], timeout=120)
        if rc != 0:
            self.log(f"Failed to apply diffs for {task_id}: {stderr[:200]}", "ERROR")
            tracked["status"] = "apply_failed"
            self.put_data("tasks", tracking)
            return False

        wip_path = self.wo_dir / "wip" / workorder_filename
        if wip_path.exists():
            with open(wip_path, "a", encoding="utf-8") as f:
                f.write(f"\n\n[codex] Applied task {task_id} at {time.strftime('%Y-%m-%dT%H:%M:%S')}\nCOMPLETE\n")
            done_dir = self.wo_dir / "done"
            done_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(wip_path), str(done_dir / workorder_filename))

        tracked["status"] = "applied"
        tracked["applied_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.put_data("tasks", tracking)
        return True

    def handle_failed_task(self, task_id):
        tracking = self.get_data("tasks") or {}
        if task_id not in tracking: return
        tracked = tracking[task_id]
        workorder_filename = tracked["workorder"]

        wip_path = self.wo_dir / "wip" / workorder_filename
        if wip_path.exists():
            with open(wip_path, "a", encoding="utf-8") as f:
                f.write(f"\n\n[codex] Task {task_id} failed at {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
            ready_dir = self.wo_dir / "ready"
            ready_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(wip_path), str(ready_dir / workorder_filename))

        tracked["status"] = "failed"
        self.put_data("tasks", tracking)

    def run_cycle(self):
        tracking = self.get_data("tasks") or {}
        active_tasks = {tid: t for tid, t in tracking.items() if t.get("status") not in ("applied", "failed", "apply_failed")}
        if not active_tasks: return False

        changes = self.poll_tasks()
        had_work = False
        for task_id, workorder_filename, new_status in changes:
            had_work = True
            if new_status == "ready":
                self.handle_completed_task(task_id)
            elif new_status in ("failed", "error", "cancelled"):
                self.handle_failed_task(task_id)
        return had_work

def run_cycle(work_dir=None):
    monitor = CodexMonitor(work_dir)
    return monitor.run_cycle()
