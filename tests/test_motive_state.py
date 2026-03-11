"""Tests for the daily motive-state alignment system.

Validates that all required files exist, have correct structure,
and that the alignment checker produces valid output.
"""

import json
import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTIVE_STATE_PATH = os.path.join(REPO_ROOT, "docs", "MOTIVE_STATE.md")
ALIGNMENT_SCRIPT = os.path.join(REPO_ROOT, "bin", "check_motive_alignment.py")
PROGRESS_FILE = os.path.join(REPO_ROOT, "logs", "motive_state_progress.json")
TEMPLATE_PATH = os.path.join(
    REPO_ROOT, "workorders", "recurring", "daily-motive-state-check.md.template"
)


# ---------------------------------------------------------------------------
# Part 1: MOTIVE_STATE.md
# ---------------------------------------------------------------------------


class TestMotiveStateMdExists(unittest.TestCase):
    """Verify docs/MOTIVE_STATE.md exists and is non-trivial."""

    def test_file_exists(self):
        self.assertTrue(
            os.path.isfile(MOTIVE_STATE_PATH),
            "docs/MOTIVE_STATE.md must exist",
        )

    def test_file_is_not_empty(self):
        size = os.path.getsize(MOTIVE_STATE_PATH)
        self.assertGreater(size, 1000, "MOTIVE_STATE.md should be substantial")


class TestMotiveStateMdStructure(unittest.TestCase):
    """Verify required sections in MOTIVE_STATE.md."""

    @classmethod
    def setUpClass(cls):
        with open(MOTIVE_STATE_PATH, "r", encoding="utf-8") as f:
            cls.content = f.read()
        cls.lines = cls.content.splitlines()

    def _has_heading_containing(self, text):
        text_lower = text.lower()
        return any(
            line.startswith("#") and text_lower in line.lower()
            for line in self.lines
        )

    def _mentions(self, text):
        return text.lower() in self.content.lower()

    def test_has_core_statement(self):
        self.assertTrue(
            self._mentions("Autonomous, Cross-Platform, Self-Orchestrating Multi-AI System"),
            "Must contain the core motive state statement",
        )

    def test_has_autonomy_pillar(self):
        self.assertTrue(self._has_heading_containing("AUTONOMOUS"))

    def test_has_cross_platform_pillar(self):
        self.assertTrue(self._has_heading_containing("CROSS-PLATFORM"))

    def test_has_self_orchestrating_pillar(self):
        self.assertTrue(self._has_heading_containing("SELF-ORCHESTRATING"))

    def test_has_multi_ai_pillar(self):
        self.assertTrue(self._has_heading_containing("MULTI-AI"))

    def test_has_daily_alignment_questions(self):
        self.assertTrue(
            self._has_heading_containing("Daily Alignment Questions"),
            "Must have daily alignment questions section",
        )

    def test_has_decision_rubric(self):
        self.assertTrue(
            self._has_heading_containing("Decision Rubric"),
            "Must have a decision rubric section",
        )

    def test_has_metrics_reference(self):
        self.assertTrue(
            self._mentions("motive_state_progress.json"),
            "Must reference the progress tracking file",
        )

    def test_has_90_day_plan(self):
        self.assertTrue(
            self._has_heading_containing("90 Days")
            or self._mentions("week 1")
            or self._mentions("week 1-2"),
            "Must have a forward-looking plan",
        )


# ---------------------------------------------------------------------------
# Part 2: check_motive_alignment.py
# ---------------------------------------------------------------------------


class TestAlignmentScriptExists(unittest.TestCase):
    """Verify the alignment script exists and is valid Python."""

    def test_script_exists(self):
        self.assertTrue(
            os.path.isfile(ALIGNMENT_SCRIPT),
            "bin/check_motive_alignment.py must exist",
        )

    def test_script_is_valid_python(self):
        with open(ALIGNMENT_SCRIPT, "r", encoding="utf-8") as f:
            source = f.read()
        # Should compile without syntax errors
        compile(source, ALIGNMENT_SCRIPT, "exec")

    def test_script_has_main_function(self):
        with open(ALIGNMENT_SCRIPT, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("def main()", content, "Must have a main() function")

    def test_script_has_checker_class(self):
        with open(ALIGNMENT_SCRIPT, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(
            "class MotiveStateChecker", content,
            "Must have MotiveStateChecker class",
        )


class TestMotiveStateChecker(unittest.TestCase):
    """Test the MotiveStateChecker class directly."""

    @classmethod
    def setUpClass(cls):
        # Import the module
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "check_motive_alignment", ALIGNMENT_SCRIPT
        )
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_checker_instantiates(self):
        checker = self.module.MotiveStateChecker()
        self.assertIsNotNone(checker)

    def test_check_alignment_returns_dict(self):
        checker = self.module.MotiveStateChecker()
        scores = checker.check_alignment()
        self.assertIsInstance(scores, dict)

    def test_scores_have_required_keys(self):
        checker = self.module.MotiveStateChecker()
        scores = checker.check_alignment()
        required_keys = [
            "autonomy", "cross_platform", "orchestration",
            "efficiency", "timestamp", "overall_alignment",
            "biggest_gap", "next_priority",
        ]
        for key in required_keys:
            self.assertIn(key, scores, f"Scores must contain '{key}'")

    def test_scores_are_numeric(self):
        checker = self.module.MotiveStateChecker()
        scores = checker.check_alignment()
        for key in ["autonomy", "cross_platform", "orchestration", "efficiency"]:
            self.assertIsInstance(scores[key], (int, float), f"{key} must be numeric")

    def test_scores_in_range(self):
        checker = self.module.MotiveStateChecker()
        scores = checker.check_alignment()
        for key in ["autonomy", "cross_platform", "orchestration", "efficiency"]:
            self.assertGreaterEqual(scores[key], 0, f"{key} must be >= 0")
            self.assertLessEqual(scores[key], 100, f"{key} must be <= 100")

    def test_overall_alignment_is_average(self):
        checker = self.module.MotiveStateChecker()
        scores = checker.check_alignment()
        expected = (
            scores["autonomy"]
            + scores["cross_platform"]
            + scores["orchestration"]
            + scores["efficiency"]
        ) / 4
        self.assertAlmostEqual(scores["overall_alignment"], expected, places=2)

    def test_save_progress_creates_file(self):
        checker = self.module.MotiveStateChecker()
        # Use a temp file so we don't pollute the real progress
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            tmp_path = tmp.name
        try:
            checker.PROGRESS_FILE = type(checker).REPO_ROOT.__class__(tmp_path)
            checker.progress = {"scores": [], "last_check": None}
            scores = checker.check_alignment()
            checker.save_progress(scores)

            self.assertTrue(os.path.exists(tmp_path))
            with open(tmp_path) as f:
                data = json.load(f)
            self.assertIn("scores", data)
            self.assertEqual(len(data["scores"]), 1)
            self.assertIn("last_check", data)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_biggest_gap_is_valid_pillar(self):
        checker = self.module.MotiveStateChecker()
        scores = checker.check_alignment()
        valid_pillars = {"autonomy", "cross_platform", "orchestration"}
        self.assertIn(
            scores["biggest_gap"], valid_pillars,
            "biggest_gap must be a valid pillar name",
        )

    def test_next_priority_is_nonempty_string(self):
        checker = self.module.MotiveStateChecker()
        scores = checker.check_alignment()
        self.assertIsInstance(scores["next_priority"], str)
        self.assertGreater(len(scores["next_priority"]), 0)


# ---------------------------------------------------------------------------
# Part 3: Daily workorder template
# ---------------------------------------------------------------------------


class TestDailyWorkorderTemplate(unittest.TestCase):
    """Verify the daily workorder template exists and has required content."""

    def test_template_exists(self):
        self.assertTrue(
            os.path.isfile(TEMPLATE_PATH),
            "workorders/recurring/daily-motive-state-check.md.template must exist",
        )

    def test_template_is_not_empty(self):
        size = os.path.getsize(TEMPLATE_PATH)
        self.assertGreater(size, 500, "Template should be substantial")

    def test_template_has_steps(self):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Step 1", content)
        self.assertIn("Step 2", content)
        self.assertIn("Step 3", content)
        self.assertIn("Step 4", content)

    def test_template_references_script(self):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(
            "check_motive_alignment.py", content,
            "Template must reference the alignment script",
        )

    def test_template_has_decision_table(self):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("ALIGNED", content)
        self.assertIn("DISTRACTION", content)

    def test_template_has_success_criteria(self):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Success Criteria", content)


# ---------------------------------------------------------------------------
# Part 4: Progress tracking file
# ---------------------------------------------------------------------------


class TestProgressFile(unittest.TestCase):
    """Verify logs/motive_state_progress.json exists and is valid."""

    def test_file_exists(self):
        self.assertTrue(
            os.path.isfile(PROGRESS_FILE),
            "logs/motive_state_progress.json must exist",
        )

    def test_file_is_valid_json(self):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)

    def test_has_motive_state_field(self):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("motive_state", data)
        self.assertIn("Autonomous", data["motive_state"])

    def test_has_scores_array(self):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("scores", data)
        self.assertIsInstance(data["scores"], list)
        self.assertGreater(len(data["scores"]), 0, "Must have at least one score entry")

    def test_has_targets(self):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("targets", data)
        targets = data["targets"]
        for key in ["autonomy", "cross_platform", "orchestration", "efficiency"]:
            self.assertIn(key, targets, f"targets must contain '{key}'")

    def test_score_entry_has_required_fields(self):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        entry = data["scores"][0]
        required_fields = [
            "timestamp", "autonomy", "cross_platform",
            "orchestration", "efficiency", "overall_alignment",
        ]
        for field in required_fields:
            self.assertIn(field, entry, f"Score entry must contain '{field}'")

    def test_score_values_are_numeric(self):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        entry = data["scores"][0]
        for key in ["autonomy", "cross_platform", "orchestration", "efficiency"]:
            self.assertIsInstance(
                entry[key], (int, float),
                f"Score '{key}' must be numeric",
            )


if __name__ == "__main__":
    unittest.main()
