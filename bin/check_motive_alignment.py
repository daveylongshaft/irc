#!/usr/bin/env python3
"""
Check daily alignment with Central Motive State.

Compares current system state to MOTIVE_STATE.md and generates report.
Run daily as part of CI/CD or manual check.
"""

import json
from pathlib import Path
from datetime import datetime


class MotiveStateChecker:
    """Check alignment with Central Motive State."""

    REPO_ROOT = Path(__file__).resolve().parent.parent
    MOTIVE_STATE_FILE = REPO_ROOT / "docs" / "MOTIVE_STATE.md"
    PROGRESS_FILE = REPO_ROOT / "logs" / "motive_state_progress.json"

    TARGETS = {
        "autonomy": 95,
        "cross_platform": 100,
        "orchestration": 90,
        "efficiency": 40,  # percent of naive cost (lower is better)
    }

    def __init__(self):
        self.progress = self._load_progress()

    def _load_progress(self) -> dict:
        """Load progress history."""
        if not self.PROGRESS_FILE.exists():
            return {"scores": [], "last_check": None}

        with open(self.PROGRESS_FILE) as f:
            return json.load(f)

    def check_alignment(self) -> dict:
        """Check current state vs motive state."""
        scores = {
            "autonomy": self._measure_autonomy(),
            "cross_platform": self._measure_cross_platform(),
            "orchestration": self._measure_orchestration(),
            "efficiency": self._measure_efficiency(),
            "timestamp": datetime.now().isoformat(),
            "overall_alignment": 0,  # calculated below
        }

        scores["overall_alignment"] = (
            scores["autonomy"]
            + scores["cross_platform"]
            + scores["orchestration"]
            + scores["efficiency"]
        ) / 4

        # Determine biggest gap and next priority
        pillar_gaps = {
            "autonomy": self.TARGETS["autonomy"] - scores["autonomy"],
            "cross_platform": self.TARGETS["cross_platform"] - scores["cross_platform"],
            "orchestration": self.TARGETS["orchestration"] - scores["orchestration"],
        }
        scores["biggest_gap"] = max(pillar_gaps, key=pillar_gaps.get)
        scores["next_priority"] = self._suggest_priority(scores["biggest_gap"])

        return scores

    def _measure_autonomy(self) -> float:
        """Measure autonomy (0-100).

        Checks whether key system components can operate without
        manual intervention.
        """
        score = 0

        # Check: queue-worker config exists (can run autonomously)
        qw_data = self.REPO_ROOT / "queue_worker_data.json"
        if qw_data.exists():
            score += 25

        # Check: PM data exists (makes decisions independently)
        pm_data = self.REPO_ROOT / "pm_data.json"
        if pm_data.exists():
            score += 25

        # Check: test-runner exists (self-healing tests)
        test_runner = self.REPO_ROOT / "bin" / "test-runner"
        test_runner_py = self.REPO_ROOT / "bin" / "test-runner.py"
        if test_runner.exists() or test_runner_py.exists():
            score += 25

        # Check: agent_data.json exists (agents configured)
        agent_data = self.REPO_ROOT / "agent_data.json"
        if agent_data.exists():
            score += 25

        return float(score)

    def _measure_cross_platform(self) -> float:
        """Measure cross-platform capability (0-100).

        Checks whether the system has platform-aware infrastructure.
        """
        score = 0

        # Check: platform detection module exists
        platform_module = (
            self.REPO_ROOT
            / "packages"
            / "csc-service"
            / "csc_service"
            / "shared"
            / "platform.py"
        )
        if platform_module.exists():
            score += 25

        # Check: platform.json generated (detection ran)
        platform_json = self.REPO_ROOT / "platform.json"
        if platform_json.exists():
            score += 25

        # Check: platform gate for tests exists
        platform_gate = self.REPO_ROOT / "tests" / "platform_gate.py"
        if platform_gate.exists():
            score += 25

        # Check: docs cover platform support
        platform_docs = self.REPO_ROOT / "docs" / "services.md"
        if platform_docs.exists():
            score += 25

        return float(score)

    def _measure_orchestration(self) -> float:
        """Measure self-orchestration (0-100).

        Checks whether the system manages its own workqueue and routing.
        """
        score = 0

        # Check: queue-worker infrastructure exists
        qw_module = (
            self.REPO_ROOT
            / "packages"
            / "csc-service"
            / "csc_service"
            / "infra"
        )
        if qw_module.exists() and (qw_module / "queue_worker.py").exists():
            score += 25

        # Check: PM module exists (priority management)
        if qw_module.exists() and (qw_module / "pm.py").exists():
            score += 25

        # Check: workorder lifecycle directories
        # (system uses wip/done/ready pattern)
        wo_patterns = ["ready", "wip", "done"]
        wo_found = 0
        for pattern in wo_patterns:
            if list(self.REPO_ROOT.glob(f"**/{pattern}")):
                wo_found += 1
        if wo_found >= 2:
            score += 25

        # Check: agent configuration supports multiple models
        agent_data = self.REPO_ROOT / "agent_data.json"
        if agent_data.exists():
            try:
                with open(agent_data) as f:
                    data = json.load(f)
                if isinstance(data, dict) and len(data) >= 2:
                    score += 25
            except (json.JSONDecodeError, OSError):
                pass

        return float(score)

    def _measure_efficiency(self) -> float:
        """Measure multi-AI efficiency (0-100).

        Checks whether the system uses multiple models and cost optimization.
        """
        score = 0

        # Check: multiple AI client packages exist
        ai_packages = ["csc-claude", "csc-gemini", "csc-chatgpt"]
        ai_found = sum(
            1
            for pkg in ai_packages
            if (self.REPO_ROOT / "packages" / pkg).exists()
        )
        if ai_found >= 2:
            score += 25

        # Check: batch executor exists
        batch_exec = self.REPO_ROOT / "docs" / "batch_executor.py"
        if batch_exec.exists():
            score += 25

        # Check: agent_data has model cost/routing info
        agent_data = self.REPO_ROOT / "agent_data.json"
        if agent_data.exists():
            try:
                with open(agent_data) as f:
                    data = json.load(f)
                # If agents are configured with different models
                if isinstance(data, dict) and len(data) >= 3:
                    score += 25
            except (json.JSONDecodeError, OSError):
                pass

        # Check: csc-service unified package exists (consolidation)
        unified = self.REPO_ROOT / "packages" / "csc-service"
        if unified.exists():
            score += 25

        return float(score)

    def _suggest_priority(self, biggest_gap: str) -> str:
        """Suggest next priority based on the biggest gap."""
        suggestions = {
            "autonomy": "Implement self-healing infrastructure and auto-start for all services",
            "cross_platform": "Extend platform detection to cover all deployment targets",
            "orchestration": "Implement intelligent model routing in PM based on task complexity",
        }
        return suggestions.get(biggest_gap, "Review motive state alignment")

    def save_progress(self, scores: dict):
        """Save scores to progress file."""
        self.progress["scores"].append(scores)
        self.progress["last_check"] = datetime.now().isoformat()

        self.PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self.PROGRESS_FILE, "w") as f:
            json.dump(self.progress, f, indent=2)

    def print_report(self, scores: dict):
        """Print alignment report."""
        print()
        print("=" * 60)
        print("CENTRAL MOTIVE STATE - DAILY ALIGNMENT REPORT")
        print("=" * 60)
        print(f"Date: {scores['timestamp']}")
        print()

        pillars = {
            "autonomy": ("AUTONOMY", scores["autonomy"], self.TARGETS["autonomy"]),
            "cross_platform": ("CROSS-PLATFORM", scores["cross_platform"], self.TARGETS["cross_platform"]),
            "orchestration": ("SELF-ORCHESTRATING", scores["orchestration"], self.TARGETS["orchestration"]),
            "efficiency": ("MULTI-AI EFFICIENCY", scores["efficiency"], self.TARGETS["efficiency"]),
        }

        for key, (name, score, target) in pillars.items():
            filled = int(score / 5)
            bar = "#" * filled + "." * (20 - filled)
            status = "OK" if score >= 80 else "WARN" if score >= 60 else "LOW"
            print(f"[{status:4}] {name:20} [{bar}] {score:3.0f}/100 (target: {target})")

        print()
        print(f"OVERALL ALIGNMENT: {scores['overall_alignment']:.0f}/100")
        print(f"BIGGEST GAP:       {scores.get('biggest_gap', 'N/A')}")
        print(f"NEXT PRIORITY:     {scores.get('next_priority', 'N/A')}")
        print("=" * 60)
        print()

        # Recommendations
        print("ALIGNMENT GUIDANCE:")
        if scores["autonomy"] < 80:
            print("  -> Autonomy needs work. Prioritize self-healing infrastructure.")
        if scores["cross_platform"] < 80:
            print("  -> Cross-platform support incomplete. Extend platform detection.")
        if scores["orchestration"] < 80:
            print("  -> Self-orchestration needs improvement. Enhance PM decision-making.")
        if scores["efficiency"] < 80:
            print("  -> Efficiency can be improved. Implement batch API + caching.")

        if scores["overall_alignment"] >= 80:
            print("  -> System is well-aligned. Focus on maintaining and refining.")

        print()


def main():
    checker = MotiveStateChecker()
    scores = checker.check_alignment()
    checker.save_progress(scores)
    checker.print_report(scores)


if __name__ == "__main__":
    main()
