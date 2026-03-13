"""PR Review & Auto-Merge Agent - integrated into service polling loop.

This module calls the autonomous pr-review-agent.sh bash script which:
- Polls for open PRs
- Runs automated review checklist
- Approves/rejects PRs autonomously
- Merges approved PRs
- Logs all decisions

Zero manual intervention required.
"""
import subprocess
from pathlib import Path
from csc_service.shared.data import Data


class PRReviewer(Data):
    def __init__(self, csc_root=None):
        super().__init__()
        self.name = "pr-review"
        self._initialize_paths(csc_root)
        self.init_data("pr-review_runtime.json")

    def _initialize_paths(self, csc_root=None):
        if csc_root:
            self.csc_root = Path(csc_root).resolve()
        else:
            p = Path(__file__).resolve().parent
            for _ in range(10):
                if (p / "CLAUDE.md").exists() or (p / "csc-service.json").exists():
                    break
                if p == p.parent:
                    break
                p = p.parent
            self.csc_root = p

    def run_cycle(self):
        """Run PR review cycle by calling autonomous bash script."""
        self.log("Starting PR review cycle")

        # Call the autonomous pr-review-agent.sh script
        script_path = self.csc_root / "bin" / "pr-review-agent.sh"

        if not script_path.exists():
            self.log(f"PR review script not found: {script_path}", "WARN")
            return

        try:
            import sys
            kwargs = {
                "cwd": str(self.csc_root),
                "capture_output": True,
                "text": True,
                "timeout": 300,
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(
                ["bash", str(script_path)],
                **kwargs
            )

            # Log output
            if result.stdout:
                self.log(f"Script output: {result.stdout[:200]}")
            if result.returncode != 0 and result.stderr:
                self.log(f"Script error: {result.stderr[:200]}", "WARN")

            self.log(f"PR review cycle completed (exit code: {result.returncode})")

        except subprocess.TimeoutExpired:
            self.log("PR review script timed out", "ERROR")
        except Exception as e:
            self.log(f"PR review cycle failed: {e}", "ERROR")


def run_cycle(csc_root=None):
    """Entry point called by service main loop."""
    reviewer = PRReviewer(csc_root)
    reviewer.run_cycle()
