"""Julius client — queue/check Jules plans for autonomous plan-review.

Provides helpers for submitting Jules plans to the plan-review agent queue
and polling for the resulting approval decision.

Used by pm.py and jules_monitor.py to integrate plan review into the
Jules feedback loop.
"""

import json
import time
from pathlib import Path

from csc_service.shared.data import Data


class Julius(Data):
    """Client for queuing and checking Jules plan review decisions."""

    def __init__(self, csc_root: str = None) -> None:
        """Initialize Julius client with paths.

        Args:
            csc_root: Path to CSC project root. Auto-detected if None.
        """
        super().__init__()
        self.name = "julius"
        self._initialize_paths(csc_root)
        self.init_data("julius_data.json")

    def _initialize_paths(self, csc_root: str = None) -> None:
        """Resolve CSC root and plan-review queue directories.

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
        self.review_in = agent_dir / "queue" / "in"
        self.review_out = agent_dir / "queue" / "out"

    def submit_plan_for_review(self, session_id: str, plan_content: str) -> bool:
        """Queue a Jules plan for review by the plan-review agent.

        Writes a JSON file to agents/plan-review/queue/in/ so the
        PlanReviewer service can pick it up on the next poll cycle.

        Args:
            session_id: Jules session identifier (used as filename stem).
            plan_content: Raw plan text to review.

        Returns:
            True if the plan was queued successfully.
        """
        self.review_in.mkdir(parents=True, exist_ok=True)

        plan_file = self.review_in / f"{session_id}_plan.json"
        payload = {
            "session_id": session_id,
            "content": plan_content,
            "submitted_at": time.time(),
        }

        try:
            plan_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self.log(f"Plan queued for review: {session_id}")
            return True
        except OSError as e:
            self.log(f"Failed to queue plan {session_id}: {e}")
            return False

    def check_plan_approval(self, session_id: str) -> dict | None:
        """Check if a plan has been reviewed and return the decision.

        Reads the decision file from agents/plan-review/queue/out/ if it
        exists. Returns None while the review is still pending.

        Args:
            session_id: Jules session identifier to look up.

        Returns:
            Decision dict (with 'decision', 'reason', 'confidence') if
            reviewed, or None if still pending.
        """
        decision_file = self.review_out / f"{session_id}_decision.json"

        if not decision_file.exists():
            return None

        try:
            return json.loads(decision_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            self.log(f"Failed to read decision for {session_id}: {e}")
            return None
