"""Tests for stats_service in irc repo."""

import unittest
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

# Adjust sys.path to find csc_service
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "packages" / "csc-service"))

from csc_service.shared.services.stats_service.stats_service import StatsService

class TestStatsService(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.mock_server = MagicMock()
        self.stats = StatsService(self.mock_server)

    def test_stats_init(self):
        self.assertEqual(self.stats.name, "stats")

if __name__ == "__main__":
    unittest.main()
