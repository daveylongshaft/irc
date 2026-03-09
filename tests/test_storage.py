"""Tests for PersistentStorageManager in irc repo."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Adjust sys.path to find csc_service
# Assuming we are in /opt/audit/irc/tests
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "packages" / "csc-service"))

from csc_service.server.storage import PersistentStorageManager
from csc_service.shared.channel import ChannelManager


class TestAtomicIO(unittest.TestCase):
    """Test atomic read/write operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.logs = []
        self.storage = PersistentStorageManager(
            self.tmpdir, log_func=self.logs.append
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_files_created_on_init(self):
        """All JSON files should be created with defaults."""
        for key, filename in PersistentStorageManager.FILES.items():
            path = os.path.join(self.tmpdir, filename)
            self.assertTrue(os.path.exists(path), f"{filename} should exist")
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["version"], 1)

    def test_atomic_write_creates_file(self):
        """Atomic write should create a valid JSON file."""
        path = os.path.join(self.tmpdir, "test.json")
        data = {"key": "value", "num": 42}
        ok = self.storage._atomic_write(path, data)
        self.assertTrue(ok)
        with open(path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

class TestChannelOperations(unittest.TestCase):
    """Test channel save/load operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.logs = []
        self.storage = PersistentStorageManager(
            self.tmpdir, log_func=self.logs.append
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load_channels(self):
        """Channels should round-trip through save/load."""
        data = {
            "version": 1,
            "channels": {
                "#test": {
                    "name": "#test",
                    "topic": "Hello",
                    "modes": ["n", "t"],
                    "mode_params": {},
                    "ban_list": [],
                    "invite_list": [],
                    "created": 1000.0,
                    "members": {},
                }
            }
        }
        self.storage.save_channels(data)
        loaded = self.storage.load_channels()
        self.assertEqual(loaded["channels"]["#test"]["topic"], "Hello")

    def test_save_channels_from_manager(self):
        """Should serialize ChannelManager state correctly."""
        cm = ChannelManager()
        ch = cm.ensure_channel("#test")
        ch.topic = "Testing"
        ch.add_member("User1", ("127.0.0.1", 5000), {"o"})

        ok = self.storage.save_channels_from_manager(cm)
        self.assertTrue(ok)

        loaded = self.storage.load_channels()
        ch_data = loaded["channels"]["#test"]
        self.assertEqual(ch_data["topic"], "Testing")
        # ChannelManager normalizes nicks to lowercase
        self.assertIn("user1", ch_data["members"])

if __name__ == "__main__":
    unittest.main()
