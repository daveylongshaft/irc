"""Tests for collision_resolver in irc repo."""

import unittest
import sys
from pathlib import Path

# Adjust sys.path to find csc_service
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "packages" / "csc-service"))

from csc_service.server.collision_resolver import detect_collision, resolve_collision, generate_collision_nick

class TestCollisionResolver(unittest.TestCase):
    def test_detect_collision(self):
        local_users = {"alice": {"info": "..."}}
        remote_nicks = ["Alice", "Bob"]
        
        self.assertTrue(detect_collision("Alice", "serv1", "serv2", local_users, remote_nicks))
        self.assertFalse(detect_collision("Charlie", "serv1", "serv2", local_users, remote_nicks))

    def test_resolve_collision_older_wins(self):
        # Alice on serv1 connected at 100, Alice on serv2 connected at 200
        winner, loser_new_nick = resolve_collision("Alice", "serv1", "serv2", 100, 200)
        self.assertEqual(winner, "serv1")
        self.assertTrue(loser_new_nick.startswith("Alice_"))

    def test_generate_collision_nick(self):
        nick = "VeryLongNickname"
        new_nick = generate_collision_nick(nick)
        self.assertLessEqual(len(new_nick), 15)
        self.assertNotEqual(nick, new_nick)

if __name__ == "__main__":
    unittest.main()
