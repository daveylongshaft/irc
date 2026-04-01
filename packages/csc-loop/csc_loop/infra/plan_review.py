"""Autonomous plan review agent service.

Polls agents/plan-review/queue/in/ for Jules-generated plans, reviews each
one via AI, and writes approval decisions to agents/plan-review/queue/out/.

Zero manual intervention required. Called from the service main loop every
60 seconds alongside queue-worker, test-runner, pm, and pr-review.
"""

import json
import re
import subprocess
import time
from pathlib import Path

from csc_data.data import Data


class PlanReviewer(Data):
    """Review Jules plans autonomously using an AI subprocess."""

    def __init__(self, csc_root: str = None) -> None:
        """Initialize PlanReviewer with paths.

        Args:
            csc_root: Path to CSC project root. Auto-detected if None.
        """
        super().__init__()
        self.name = "plan-review"
        self._initialize_paths(csc_root)
        self.init_data("plan_review_data.json")

    def _initialize_paths(self, csc_root: str = None) -> None:
        """Resolve CSC root and queue directories.

        Args:
            csc_root: Explicit root path, or None to auto-detect.
        """
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

        agent_dir = self.csc_root / "agents" / "plan-review"
        self.queue_in = agent_dir / "queue" / "in"
        self.queue_out = agent_dir / "queue" / "out"
        self.state_file = agent_dir / "state.json"

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def _ensure_dirs(self) -> None:
        """Create queue directories if they do not exist."""
        self.queue_in.mkdir(parents=True, exist_ok=True)
        self.queue_out.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> dict:
        """Load agent metrics from state.json.

        Returns:
            Dict with total_reviewed, total_approved, total_denied, errors.
        """
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "total_reviewed": 0,
            "total_approved": 0,
            "total_denied": 0,
            "last_review_at": None,
            "errors": 0,
        }

    def _save_state(self, state: dict) -> None:
        """Persist agent metrics to state.json.

        Args:
            state: Metrics dict to persist.
        """
        try:
            self.state_file.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except OSError as e:
            self.log(f"Failed to save plan-review state: {e}")

    # ------------------------------------------------------------------
    # AI decision parsing
    # ------------------------------------------------------------------

    def _parse_decision(self, ai_output: str) -> dict:
        """Extract approval decision JSON from AI output.

        Looks for a JSON object containing a 'decision' key in the output.
        Falls back to a DENY decision if parsing fails.

        Args:
            ai_output: Raw text output from the review AI.

        Returns:
            Dict with 'decision', 'reason', 'confidence', and optional 'notes'.
        """
        try:
            match = re.search(r'\{[^{}]*"decision"[^{}]*\}', ai_output, re.DOTALL)
            if match:
                candidate = json.loads(match.group())
                if candidate.get("decision") in ("APPROVE", "DENY"):
                    return candidate
        except (json.JSONDecodeError, AttributeError):
            pass

        return {
            "decision": "DENY",
            "reason": "Could not parse AI decision from output",
            "confidence": 0.0,
        }

    # ------------------------------------------------------------------
    # Single-plan review
    # ------------------------------------------------------------------

    def _review_plan(self, plan_file: Path) -> None:
        """Review a single plan file and write decision to queue/out/.

        Spawns an AI subprocess to review the plan text, parses the JSON
        decision, writes it to queue/out/{session_id}_decision.json, and
        removes the input file.

        Args:
            plan_file: Path to the plan JSON file in queue/in/.
        """
        try:
            plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            self.log(f"Failed to read plan file {plan_file.name}: {e}")
            plan_file.unlink(missing_ok=True)
            return

        session_id = plan_data.get("session_id", plan_file.stem)
        plan_content = plan_data.get("content", "")

        review_prompt = (
            f"Review this Jules plan:\n\nSession: {session_id}\n\n{plan_content}"
        )

        try:
            import sys
            kwargs = {
                "capture_output": True,
                "text": True,
                "timeout": 120,
                "cwd": str(self.csc_root),
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "csc_cli.csc_clients.claude.main",
                    "--system",
                    "Plan Reviewer",
                    "--prompt",
                    review_prompt,
                ],
                **kwargs
            )
            ai_output = result.stdout
        except subprocess.TimeoutExpired:
            self.log(f"AI review timed out for session {session_id}", )
            ai_output = ""
        except Exception as e:
            self.log(f"AI subprocess error for session {session_id}: {e}")
            ai_output = ""

        decision = self._parse_decision(ai_output)

        result_path = self.queue_out / f"{session_id}_decision.json"
        try:
            result_path.write_text(
                json.dumps(decision, indent=2), encoding="utf-8"
            )
        except OSError as e:
            self.log(f"Failed to write decision for {session_id}: {e}")
            return

        self.log(
            f"Plan reviewed: {session_id} -> {decision['decision']} "
            f"(confidence: {decision.get('confidence', '?')})"
        )
        plan_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    def run_cycle(self) -> None:
        """Poll queue/in/ for pending plans and review each one.

        Called by the service main loop every 60 seconds.
        """
        self._ensure_dirs()

        pending = list(self.queue_in.glob("*.json"))
        if not pending:
            return

        self.log(f"Plan Review: found {len(pending)} plan(s) to review")

        state = self._load_state()

        for plan_file in pending:
            try:
                decision_path = self.queue_out / f"{plan_file.stem.replace('_plan', '')}_decision.json"
                # Derive expected decision filename
                stem = plan_file.stem  # e.g. "abc123_plan"
                session_id = plan_file.stem
                if stem.endswith("_plan"):
                    session_id = stem[: -len("_plan")]

                self._review_plan(plan_file)

                # Update metrics
                state["total_reviewed"] += 1
                state["last_review_at"] = time.time()

                # Read decision to update approve/deny counters
                out_path = self.queue_out / f"{session_id}_decision.json"
                if out_path.exists():
                    try:
                        d = json.loads(out_path.read_text(encoding="utf-8"))
                        if d.get("decision") == "APPROVE":
                            state["total_approved"] += 1
                        else:
                            state["total_denied"] += 1
                    except (json.JSONDecodeError, OSError):
                        pass

            except Exception as e:
                self.log(f"Error reviewing {plan_file.name}: {e}")
                state["errors"] = state.get("errors", 0) + 1

        self._save_state(state)


def run_cycle(csc_root: str = None) -> None:
    """Entry point called by service main loop.

    Args:
        csc_root: Path to CSC project root.
    """
    reviewer = PlanReviewer(csc_root)
    reviewer.run_cycle()
