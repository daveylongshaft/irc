r"""
RunAgentExecutor: Pure Python executor for running AI agents without bash/batch scripts.

Replaces bin/run_agent.sh and bin/run_agent.bat with a cross-platform Python class
that handles:
- Loading queue metadata from agents/{agent}/queue/in/{orders}.json
- Preparing environment variables (unset nesting detection, load .env)
- Building the claude command with proper prompt injection
- Running the agent via subprocess.Popen()
- Journaling START/COMPLETE to WIP file
- Error handling for missing binaries, timeouts, subprocess failures

Cross-platform:
- Windows: Uses shell=True for cmd.exe, handles path notation
- Linux/macOS: Uses start_new_session=True for process groups
- Path handling via pathlib.Path (automatically handles / vs \)
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Tuple


class RunAgentExecutor:
    """Execute an AI agent for a queued workorder.

    Loads queue metadata, prepares environment, and spawns the agent
    using subprocess.Popen(). Handles cross-platform differences (Windows
    vs Unix, shell requirements, path notation).

    Usage:
        executor = RunAgentExecutor(
            agent_name="haiku",
            queue_entry_path=Path("agents/haiku/queue/in/orders.md")
            # project_root auto-detected; override only if needed
        )
        return_code = executor.execute()
        sys.exit(return_code)
    """

    def __init__(self, agent_name: str, queue_entry_path: Path, project_root: Optional[Path] = None):
        """Initialize executor with queue entry metadata.

        Args:
            agent_name: Name of the agent (e.g., 'haiku', 'sonnet')
            queue_entry_path: Path to the queue/in/orders.md file
            project_root: Project root directory (auto-detected if None)
        """
        self.agent_name = agent_name
        self.queue_entry_path = Path(queue_entry_path)
        self.project_root = project_root or self._find_project_root()

        # Standard directories
        self.workorders_base = self.project_root / "workorders"
        self.wip_dir = self.workorders_base / "wip"
        self.ready_dir = self.workorders_base / "ready"
        self.logs_dir = self.project_root / "logs"

        # Metadata loaded from queue/in/orders.json
        self.metadata: Dict = {}
        self.wip_filename: str = ""
        self.wip_path: Optional[Path] = None

        # Platform detection
        self.is_windows = os.name == 'nt'

    @staticmethod
    def _find_project_root() -> Path:
        """Find project root by looking for CLAUDE.md or csc-service.json."""
        current = Path(__file__).resolve().parent
        for _ in range(10):
            if (current / "CLAUDE.md").exists() or (current / "csc-service.json").exists():
                return current
            if current == current.parent:
                break
            current = current.parent
        # Fallback: return cwd
        return Path.cwd()

    def _load_queue_entry(self) -> bool:
        """Load queue metadata from orders.json in same directory as orders.md.

        Queue entry contains:
            - timestamp: ISO timestamp of queue assignment
            - agent_name: Selected agent name
            - workorder_name: Original workorder filename
            - wip_path_windows: WIP path in Windows notation
            - wip_path_linux: WIP path in Unix notation

        Returns:
            True if loaded successfully, False if metadata missing/invalid
        """
        # Metadata file is orders.json in same directory as orders.md
        metadata_path = self.queue_entry_path.parent / "orders.json"

        if not metadata_path.exists():
            self._journal_error(f"Metadata file not found: {metadata_path}")
            return False

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                self.metadata = json.load(f)
        except Exception as e:
            self._journal_error(f"Failed to load metadata: {e}")
            return False

        # Extract WIP filename from metadata
        self.wip_filename = self.metadata.get("workorder_name", "")
        if not self.wip_filename:
            self._journal_error("Metadata missing 'workorder_name' field")
            return False

        # Determine WIP path (use Windows notation on Windows, otherwise use Linux)
        if self.is_windows:
            wip_path_str = self.metadata.get("wip_path_windows")
        else:
            wip_path_str = self.metadata.get("wip_path_linux")

        if not wip_path_str:
            # Fallback: construct from project root
            wip_path_str = str(self.wip_dir / self.wip_filename)

        self.wip_path = Path(wip_path_str)
        return True

    def _prepare_environment(self) -> Dict[str, str]:
        """Prepare environment variables for agent execution.

        - Unset Claude Code nesting detection variables
        - Load .env file if present
        - Set CSC_* environment variables (project root, WIP paths)

        Returns:
            Environment dict for subprocess.Popen()
        """
        env = os.environ.copy()

        # Unset Claude Code nesting detection
        # These prevent nested claude invocations from being detected
        for var in ["CLAUDE_CODE_SESSION_ID", "CLAUDE_INVOCATION_ID", "CLAUDE_CODE_TASK_ID"]:
            env.pop(var, None)

        # Load .env file if present
        env_file = self.project_root / ".env"
        if env_file.exists():
            try:
                with open(env_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if '=' in line:
                            key, value = line.split('=', 1)
                            env[key.strip()] = value.strip()
            except Exception as e:
                # Log but don't fail on .env read errors
                pass

        # Set CSC_* environment variables
        env["CSC_PROJECT_ROOT"] = str(self.project_root)
        if self.wip_path:
            env["CSC_WIP_FILE"] = str(self.wip_path)
        env["CSC_AGENT"] = self.agent_name

        return env

    def _build_command(self) -> Optional[Tuple[list, str]]:
        """Build the claude command for executing the agent.

        Reads queue/in/orders.md and builds command:
            claude --append-system-prompt "system rules..." \
                   --output workorders/wip/{wip_file} \
                   "< full prompt with system rules + orders content >"

        Returns:
            Tuple of (cmd_list, prompt_text) or None if build failed
        """
        # Read orders.md from queue
        if not self.queue_entry_path.exists():
            self._journal_error(f"Queue entry not found: {self.queue_entry_path}")
            return None

        try:
            orders_content = self.queue_entry_path.read_text(encoding='utf-8')
        except Exception as e:
            self._journal_error(f"Failed to read queue entry: {e}")
            return None

        if not self.wip_path:
            self._journal_error("WIP path not set (metadata load failed?)")
            return None

        # System prompt - same as agent_service.py WIP_SYSTEM_PROMPT
        wip_filename_only = self.wip_path.name
        system_prompt = (
            "MANDATORY: Journal every step to the WIP file BEFORE doing it. "
            "Run: echo '<what you are about to do>' >> workorders/wip/{wip_file} "
            "BEFORE each action. No checkboxes. No Edit tool. Just echo one line per step. "
            "Example: echo 'read version_service.py' >> workorders/wip/{wip_file} "
            "NEVER run tests — cron handles that within 1 minute for free. "
            "NEVER DELETE WIP FILES. The wrapper handles moving them to done/. "
            "NEVER run git commands. The wrapper handles git operations. "
            "When done, write COMPLETE to the WIP file and exit. "
            "If you do not update the WIP file, your work cannot be monitored or recovered. "
            "This is NON-NEGOTIABLE."
        ).format(wip_file=wip_filename_only)

        full_prompt = f"SYSTEM RULE: {system_prompt}\n\n{orders_content}"

        # Check if claude binary exists
        claude_bin = shutil.which("claude")
        if not claude_bin:
            self._journal_error("claude command not found in PATH")
            return None

        # Build command for subprocess
        cmd = [
            claude_bin,
            "--append-system-prompt", system_prompt,
            "--output", str(self.wip_path),
            full_prompt
        ]

        return cmd, full_prompt

    def _journal_start(self) -> bool:
        """Write START marker to WIP file with timestamp.

        Format:
            START 2026-02-26 14:30:45 - Agent: haiku

        Returns:
            True if successful, False if WIP directory doesn't exist
        """
        if not self.wip_path:
            return False

        # Ensure WIP directory exists
        self.wip_dir.mkdir(parents=True, exist_ok=True)

        try:
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            marker = f"START {timestamp} - Agent: {self.agent_name}\n"

            # Create WIP file if it doesn't exist, or append
            if self.wip_path.exists():
                with open(self.wip_path, 'a', encoding='utf-8') as f:
                    f.write(marker)
            else:
                self.wip_path.write_text(marker, encoding='utf-8')

            return True
        except Exception:
            return False

    def _journal_complete(self) -> bool:
        """Write COMPLETE marker to WIP file.

        Returns:
            True if successful
        """
        if not self.wip_path or not self.wip_path.exists():
            return False

        try:
            with open(self.wip_path, 'a', encoding='utf-8') as f:
                f.write("\nCOMPLETE\n")
            return True
        except Exception:
            return False

    def _journal_error(self, message: str):
        """Write error message to WIP file (and stderr).

        Args:
            message: Error message to log
        """
        print(f"ERROR: {message}", file=sys.stderr)

        # Also write to WIP if it exists and we have a WIP path
        if self.wip_path:
            try:
                self.wip_dir.mkdir(parents=True, exist_ok=True)
                with open(self.wip_path, 'a', encoding='utf-8') as f:
                    f.write(f"\nERROR: {message}\n")
            except Exception:
                pass

    def execute(self) -> int:
        """Main execution flow: load, prepare, build, run, journal.

        Returns:
            0 on success (subprocess exited 0)
            1 on failure (metadata load, binary not found, subprocess error, etc.)
        """
        # Step 1: Load queue metadata
        if not self._load_queue_entry():
            return 1

        # Step 2: Journal START
        if not self._journal_start():
            self._journal_error("Failed to write START marker to WIP")
            return 1

        # Step 3: Prepare environment
        env = self._prepare_environment()

        # Step 4: Build command
        cmd_result = self._build_command()
        if cmd_result is None:
            return 1
        cmd, full_prompt = cmd_result

        # Step 5: Spawn agent via subprocess.Popen()
        try:
            if self.is_windows:
                # Windows: Use CREATE_NO_WINDOW for silent background execution
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.project_root),
                    env=env,
                    shell=False,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                # Unix/Linux/macOS: Use start_new_session for process groups
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.project_root),
                    env=env,
                    shell=False,
                    start_new_session=True
                )

            # Wait for subprocess to complete
            return_code = proc.wait()

            # Success: journal COMPLETE if subprocess succeeded
            if return_code == 0:
                self._journal_complete()
            else:
                self._journal_error(f"Claude subprocess exited with code {return_code}")

            return return_code

        except Exception as e:
            self._journal_error(f"Failed to spawn subprocess: {e}")
            return 1


def main():
    """Entry point when run as: python run_agent_executor.py <agent> <queue_entry>"""
    if len(sys.argv) < 3:
        print("Usage: python run_agent_executor.py <agent_name> <queue_entry_path>")
        print("  agent_name: haiku, sonnet, opus, etc.")
        print("  queue_entry_path: agents/{agent}/queue/in/orders.md")
        sys.exit(1)

    agent_name = sys.argv[1]
    queue_entry_path = Path(sys.argv[2])

    executor = RunAgentExecutor(agent_name, queue_entry_path)
    return_code = executor.execute()
    sys.exit(return_code)


if __name__ == "__main__":
    main()
