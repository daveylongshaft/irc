"""Tests for docs/EVOLUTION.md — validate structure, content, and accuracy.

These tests verify that EVOLUTION.md exists, contains the required sections,
references key historical facts accurately, and meets the structural
requirements specified in the workorder.
"""

import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVOLUTION_PATH = os.path.join(REPO_ROOT, "docs", "EVOLUTION.md")


class TestEvolutionMdExists(unittest.TestCase):
    """Verify the file exists and is non-trivial."""

    def test_file_exists(self):
        self.assertTrue(
            os.path.isfile(EVOLUTION_PATH),
            "docs/EVOLUTION.md must exist",
        )

    def test_file_is_not_empty(self):
        size = os.path.getsize(EVOLUTION_PATH)
        self.assertGreater(size, 5000, "EVOLUTION.md should be a substantial document")


class TestEvolutionMdStructure(unittest.TestCase):
    """Verify required sections are present."""

    @classmethod
    def setUpClass(cls):
        with open(EVOLUTION_PATH, "r", encoding="utf-8") as f:
            cls.content = f.read()
        cls.lines = cls.content.splitlines()

    def _has_heading_containing(self, text):
        """Check that a markdown heading contains the given text (case-insensitive)."""
        text_lower = text.lower()
        return any(
            line.startswith("#") and text_lower in line.lower()
            for line in self.lines
        )

    # -- Required sections per workorder --

    def test_has_origin_section(self):
        """The origin / copy-paste era must be covered."""
        self.assertTrue(
            self._has_heading_containing("origin")
            or self._has_heading_containing("copy-paste")
            or self._has_heading_containing("gotta startsomewhere"),
            "Must have a section about the origin / copy-paste era",
        )

    def test_has_invariants_section(self):
        """Invariants that survived every iteration must be documented."""
        self.assertTrue(
            self._has_heading_containing("invariant"),
            "Must have a section on invariants",
        )

    def test_has_trajectory_section(self):
        """The forward trajectory must be documented."""
        self.assertTrue(
            self._has_heading_containing("trajectory"),
            "Must have a section on the trajectory forward",
        )

    def test_has_significance_section(self):
        """Why this story matters must be addressed."""
        self.assertTrue(
            self._has_heading_containing("significance"),
            "Must have a section on significance",
        )


class TestEvolutionMdContent(unittest.TestCase):
    """Verify key historical facts are mentioned."""

    @classmethod
    def setUpClass(cls):
        with open(EVOLUTION_PATH, "r", encoding="utf-8") as f:
            cls.content = f.read()

    def _mentions(self, text):
        return text.lower() in self.content.lower()

    # -- Key facts from the research brief --

    def test_mentions_syscmdr(self):
        self.assertTrue(self._mentions("syscmdr"), "Must mention syscmdr")

    def test_mentions_gotta_startsomewhere(self):
        self.assertTrue(
            self._mentions("gotta startsomewhere"),
            "Must reference the founding commit message",
        )

    def test_mentions_irc(self):
        self.assertTrue(self._mentions("IRC"), "Must mention IRC protocol")

    def test_mentions_gemini(self):
        self.assertTrue(
            self._mentions("Gemini"),
            "Must mention Gemini as the first AI peer",
        )

    def test_mentions_federation(self):
        self.assertTrue(
            self._mentions("federation") or self._mentions("S2S"),
            "Must mention federation / server-to-server",
        )

    def test_mentions_queue_worker(self):
        self.assertTrue(
            self._mentions("queue worker") or self._mentions("queue"),
            "Must mention the workorder queue system",
        )

    def test_mentions_heartbeat(self):
        self.assertTrue(
            self._mentions("heartbeat"),
            "Must mention the heartbeat — the first autonomous timer",
        )

    def test_mentions_command_protocol(self):
        self.assertTrue(
            self._mentions("keyword") and self._mentions("token") and self._mentions("service"),
            "Must mention the command protocol invariant",
        )

    def test_mentions_autonomous_mode(self):
        self.assertTrue(
            self._mentions("autonomous"),
            "Must reference autonomous operation",
        )

    def test_mentions_pr_review(self):
        self.assertTrue(
            self._mentions("PR") or self._mentions("pull request"),
            "Must mention AI pull request review",
        )

    def test_mentions_three_repo_split(self):
        self.assertTrue(
            self._mentions("irc.git") or self._mentions("ops.git") or self._mentions("three repo") or self._mentions("three-repo") or self._mentions("split"),
            "Must mention the three-repo architecture split",
        )

    def test_mentions_4400_commits(self):
        self.assertTrue(
            self._mentions("4,400") or self._mentions("4400"),
            "Must mention the 4,400 commit count",
        )

    def test_mentions_economic_participation(self):
        self.assertTrue(
            self._mentions("economic") or self._mentions("revenue") or self._mentions("funding"),
            "Must reference the economic participation trajectory",
        )


class TestEvolutionMdTone(unittest.TestCase):
    """Verify the document meets tone requirements."""

    @classmethod
    def setUpClass(cls):
        with open(EVOLUTION_PATH, "r", encoding="utf-8") as f:
            cls.content = f.read()

    def test_not_corporate_boilerplate(self):
        """Should not read like a corporate press release."""
        corporate_phrases = [
            "we are pleased to announce",
            "synergize",
            "leverage our capabilities",
            "going forward",
            "circle back",
            "touch base",
        ]
        for phrase in corporate_phrases:
            self.assertNotIn(
                phrase.lower(),
                self.content.lower(),
                f"Should not contain corporate boilerplate: '{phrase}'",
            )

    def test_is_narrative_not_bullet_list(self):
        """The document should be primarily narrative prose, not a bullet list."""
        # Count lines that are bullet points vs prose paragraphs
        bullet_lines = sum(1 for line in self.content.splitlines() if line.strip().startswith("- "))
        total_lines = len([l for l in self.content.splitlines() if l.strip()])
        if total_lines > 0:
            bullet_ratio = bullet_lines / total_lines
            self.assertLess(
                bullet_ratio, 0.4,
                "Document should be primarily narrative, not a bullet list",
            )

    def test_mentions_march_2026(self):
        """Should be dated to current period."""
        self.assertIn("2026", self.content, "Must reference 2026 timeline")
        self.assertIn("March 2026", self.content, "Should reference March 2026")


if __name__ == "__main__":
    unittest.main()
