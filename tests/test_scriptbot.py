"""Tests for ScriptBot in irc repo."""

import unittest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock

# Adjust sys.path to find csc_service
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "packages" / "csc-service"))

# ScriptBot is nested in csc_scriptbot
sys.path.insert(0, str(project_root / "packages" / "csc-service" / "csc_service" / "clients" / "scriptbot" / "csc_scriptbot"))

from scriptbot import ScriptBot

class TestScriptBot(unittest.TestCase):
    def test_scriptbot_init(self):
        # We need to mock Client's __init__ or ensure it doesn't try to connect
        with unittest.mock.patch('csc_service.clients.client.client.Client.__init__', return_value=None):
            with unittest.mock.patch('csc_service.clients.client.client.Client.log'):
                bot = ScriptBot(config_path="fake.json")
                self.assertIsNotNone(bot)

if __name__ == "__main__":
    unittest.main()
