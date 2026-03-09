"""Tests for AI clients in irc repo."""

import unittest
import sys
from pathlib import Path

# Adjust sys.path to find csc_service
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "packages" / "csc-service"))

class TestClientImports(unittest.TestCase):
    def test_gemini_import(self):
        from csc_service.clients.gemini.gemini import Gemini
        self.assertIsNotNone(Gemini)

    def test_claude_import(self):
        from csc_service.clients.claude.claude import Claude
        self.assertIsNotNone(Claude)

    def test_chatgpt_import(self):
        from csc_service.clients.chatgpt.chatgpt import ChatGPT
        self.assertIsNotNone(ChatGPT)

    def test_dmrbot_import(self):
        from csc_service.clients.dmrbot.dmrbot import DMRBot
        self.assertIsNotNone(DMRBot)

if __name__ == "__main__":
    unittest.main()
