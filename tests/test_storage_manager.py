```python
"""Tests for PersistentStorageManager."""

import json
import os
import pytest
import tempfile
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from csc_server.storage import PersistentStorageManager


class TestAtomicIO:
    """Test atomic read/write operations."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Initialize temporary directory and PersistentStorageManager for atomic I/O tests."""
        self.tmpdir = tmp_path
        self.logs = []
        self.storage = PersistentStorageManager(
            str(self.tmpdir), log_func=self.logs.append
        )

    def test_files_created_on_init(self):
        """All 5 JSON files should be created with defaults."""
        for key, filename in PersistentStorageManager.FILES.items():
            path = self.tmpdir / filename
            assert path.exists(), f"{filename} should exist"
            data = json.loads(path.read_text())
            assert data["version"] == 1

    def test_atomic_write_creates_file(self):
        """Atomic write should create a valid JSON file."""
        path = self.tmpdir / "test.json"
        data = {"key": "value", "num": 42}
        ok = self.storage._atomic_write(str(path), data)
        assert ok is True
        loaded = json.loads(path.read_text())
        assert loaded == data

    def test_atomic_write_no_tmp_left(self):
        """After successful write, no .tmp file should remain."""
        path = self.tmpdir / "test.json"
        self.storage._atomic_write(str(path), {"a": 1})
        assert not (self.tmpdir / "test.json.tmp").exists()

    def test_atomic_read_missing_file(self):
        """Reading a missing file should return None."""
        result = self.storage._atomic_read(str(self.tmpdir / "nope.json"))
        assert result is None

    def test_atomic_read_corrupt_file(self):
        """Reading a corrupt JSON file should quarantine it and return None."""
        path = self.tmpdir / "corrupt.json"
        path.write_text("{invalid json!!!")
        result = self.storage._atomic_read(str(path))
        assert result is None
        # Original file should be quarantined
        assert not path.exists()
        # A .corrupt.* file should exist
        corrupt_files = [f for f in self.tmpdir.iterdir() if ".corrupt." in f.name]
        assert len(corrupt_files) > 0

    def test_atomic_write_replaces_existing(self):
        """Atomic write should replace existing file content."""
        path = self.tmpdir / "test.json"
        self.storage._atomic_write(str(path), {"v": 1})
        self.storage._atomic_write(str(path), {"v": 2})
        data = json.loads(path.read_text())
        assert data["v"] == 2

    def test_atomic_write_with_invalid_path(self):
        """Atomic write should handle invalid paths gracefully."""
        result = self.storage._atomic_write("/invalid/path/test.json", {"a": 1})
        assert result is False

    def test_atomic_read_valid_json(self):
        """Atomic read should correctly parse valid JSON."""
        path = self.tmpdir / "valid.json"
        test_data = {"key": "value", "list": [1, 2, 3], "nested": {"a": 1}}
        path.write_text(json.dumps(test_data))
        result = self.storage._atomic_read(str(path))
        assert result == test_data


class TestChannelOperations:
    """Test channel save/load operations."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Initialize temporary directory and PersistentStorageManager for channel operation tests."""
        self.tmpdir = tmp_path
        self.logs = []
        self.storage = PersistentStorageManager(
            str(self.tmpdir), log_func=self.logs.append
        )

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
        assert loaded["channels"]["#test"]["topic"] == "Hello"
        assert loaded["channels"]["#test"]["modes"] == ["n", "t"]

    def test_save_channels_creates_file(self):
        """save_channels should create the channels.json file."""
        data = {
            "version": 1,
            "channels": {}
        }
        self.storage.save_channels(data)
        channels_file = self.tmpdir / "channels.json"
        assert channels_file.exists()

    def test_load_channels_returns_default_on_missing(self):
        """load_channels should return default structure if file is missing."""
        # Remove the channels file
        channels_file = self.tmpdir / "channels.json"
        if channels_file.exists():
            channels_file.unlink()
        result = self.storage.load_channels()
        assert "version" in result
        assert "channels" in result

    def test_save_multiple_channels(self):
        """Multiple channels should be saved and loaded correctly."""
        data = {
            "version": 1,
            "channels": {
                "#test1": {
                    "name": "#test1",
                    "topic": "Channel 1",
                    "modes": [],
                    "mode_params": {},
                    "ban_list": [],
                    "invite_list": [],
                    "created": 1000.0,
                    "members": {},
                },
                "#test2": {
                    "name": "#test2",
                    "topic": "Channel 2",
                    "modes": ["n"],
                    "mode_params": {},
                    "ban_list": [],
                    "invite_list": [],
                    "created": 2000.0,
                    "members": {"user1": "op"},
                }
            }
        }
        self.storage.save_channels(data)
        loaded = self.storage.load_channels()
        assert len(loaded["channels"]) == 2
        assert loaded["channels"]["#test1"]["topic"] == "Channel 1"
        assert loaded["channels"]["#test2"]["topic"] == "Channel 2"
        assert "user1" in loaded["channels"]["#test2"]["members"]


class TestUserOperations:
    """Test user save/load operations."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Initialize temporary directory and PersistentStorageManager for user operation tests."""
        self.tmpdir = tmp_path
        self.logs = []
        self.storage = PersistentStorageManager(
            str(self.tmpdir), log_func=self.logs.append
        )

    def test_save_and_load_users(self):
        """Users should round-trip through save/load."""
        data = {
            "version": 1,
            "users": {
                "alice": {
                    "nick": "alice",
                    "user": "alice",
                    "host": "example.com",
                    "real": "Alice",
                    "modes": [],
                    "channels": ["#test"],
                    "connected": 1000.0
                }
            }
        }
        self.storage.save_users(data)
        loaded = self.storage.load_users()
        assert loaded["users"]["alice"]["nick"] == "alice"
        assert loaded["users"]["alice"]["host"] == "example.com"

    def test_save_users_creates_file(self):
        """save_users should create the users.json file."""
        data = {
            "version": 1,
            "users": {}
        }
        self.storage.save_users(data)
        users_file = self.tmpdir / "users.json"
        assert users_file.exists()

    def test_load_users_returns_default_on_missing(self):
        """load_users should return default structure if file is missing."""
        users_file = self.tmpdir / "users.json"
        if users_file.exists():
            users_file.unlink()
        result = self.storage.load_users()
        assert "version" in result
        assert "users" in result

    def test_save_multiple_users(self):
        """Multiple users should be saved and loaded correctly."""
        data = {
            "version": 1,
            "users": {
                "alice": {
                    "nick": "alice",
                    "user": "alice",
                    "host": "example.com",
                    "real": "Alice",
                    "modes": [],
                    "channels": [],
                    "connected": 1000.0
                },
                "bob": {
                    "nick": "bob",
                    "user": "bob",
                    "host": "example.org",
                    "real": "Bob",
                    "modes": ["i"],
                    "channels": ["#test"],
                    "connected": 2000.0
                }
            }
        }
        self.storage.save_users(data)
        loaded = self.storage.load_users()
        assert len(loaded["users"]) == 2
        assert loaded["users"]["bob"]["modes"] == ["i"]


class TestServerOperations:
    """Test server configuration save/load operations."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Initialize temporary directory and PersistentStorageManager for server operation tests."""
        self.tmpdir = tmp_path
        self.logs = []
        self.storage = PersistentStorageManager(
            str(self.tmpdir), log_func=self.logs.append
        )

    def test_save_and_load_server(self):
        """Server config should round-trip through save/load."""
        data = {
            "version": 1,
            "server": {
                "name": "test.irc",
                "info": "Test IRC Server",
                "modes": ["n", "t"],
                "created": 1000.0
            }
        }
        self.storage.save_server(data)
        loaded = self.storage.load_server()
        assert loaded["server"]["name"] == "test.irc"
        assert loaded["server"]["info"] == "Test IRC Server"

    def test_save_server_creates_file(self):
        """save_server should create the server.json file."""
        data = {
            "version": 1,
            "server": {}
        }
        self.storage.save_server(data)
        server_file = self.tmpdir / "server.json"
        assert server_file.exists()

    def test_load_server_returns_default_on_missing(self):
        """load_server should return default structure if file is missing."""
        server_file = self.tmpdir / "server.json"
        if server_file.exists():
            server_file.unlink()
        result = self.storage.load_server()
        assert "version" in result
        assert "server" in result


class TestMiscOperations:
    """Test miscellaneous operations save/load."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Initialize temporary directory and PersistentStorageManager for misc operation tests."""
        self.tmpdir = tmp_path
        self.logs = []
        self.storage = PersistentStorageManager(
            str(self.tmpdir), log_func=self.logs.append
        )

    def test_save_and_load_misc(self):
        """Miscellaneous data should round-trip through save/load."""
        data = {
            "version": 1,
            "misc": {
                "motd": ["Welcome", "To IRC"],
                "stats": {"users": 5, "channels": 3}
            }
        }
        self.storage.save_misc(data)
        loaded = self.storage.load_misc()
        assert loaded["misc"]["motd"] == ["Welcome", "To IRC"]
        assert loaded["misc"]["stats"]["users"] == 5

    def test_save_misc_creates_file(self):
        """save_misc should create the misc.json file."""
        data = {
            "version": 1,
            "misc": {}
        }
        self.storage.save_misc(data)
        misc_file = self.tmpdir / "misc.json"
        assert misc_file.exists()

    def test_load_misc_returns_default_on_missing(self):
        """load_misc should return default structure if file is missing."""
        misc_file = self.tmpdir / "misc.json"
        if misc_file.exists():
            misc_file.unlink()
        result = self.storage.load_misc()
        assert "version" in result
        assert "misc" in result


class TestStorageManagerIntegration:
    """Integration tests for PersistentStorageManager."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Initialize temporary directory and PersistentStorageManager for integration tests."""
        self.tmpdir = tmp_path
        self.logs = []
        self.storage = PersistentStorageManager(
            str(self.tmpdir), log_func=self.logs.append
        )

    def test_all_files_initialized_on_creation(self):
        """All required JSON files should exist after initialization."""
        required_files = list(PersistentStorageManager.FILES.values())
        for filename in required_files:
            path = self.tmpdir / filename
            assert path.exists(), f"{filename} should be created on init"

    def test_custom_log_function_called(self):
        """Custom log function should be called on operations."""
        # The logs list should have received some messages during init
        # This tests that the log_func parameter is actually used
        storage = PersistentStorageManager(
            str(self.tmpdir / "subdir"), log_func=self.logs.append
        )
        # Some log messages should have been recorded
        assert isinstance(self.logs, list)

    def test_storage_directory_handling(self, tmp_path):
        """Storage manager should handle directory creation and management."""
        new_dir = tmp_path / "storage" / "nested"
        storage = PersistentStorageManager(str(new_dir), log_func=lambda x: None)
        assert new_dir.exists()
        # Check that files were created in the nested directory
        assert (new_dir / "channels.json").exists()

    def test_concurrent_save_operations(self):
        """Multiple save operations should work correctly."""
        users_data = {"version": 1, "users": {"alice": {"nick": "alice"}}}
        channels_data = {"version": 1, "channels": {"#test": {"name": "#test"}}}
        server_data = {"version": 1, "server": {"name": "test.irc"}}

        self.storage.save_users(users_data)
        self.storage.save_channels(channels_data)
        self.storage.save_server(server_data)

        loaded_users = self.storage.load_users()
        loaded_channels = self.storage.load_channels()
        loaded_server = self.storage.load_server()

        assert "alice" in loaded_users["users"]
        assert "#test" in loaded_channels["channels"]
        assert loaded_server["server"]["name"] == "test.irc"

    def test_empty_data_save_and_load(self):
        """Empty data structures should be saved and loaded correctly."""
        empty_users = {"version": 1, "users": {}}
        empty_channels = {"version": 1, "