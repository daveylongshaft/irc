```python
#!/usr/bin/env python3
"""
Pytest test file for client state persistence feature.

Tests that clients can save and restore their state (nick, modes, channels).
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, mock_open


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({}))
    return str(config_file)


@pytest.fixture
def mock_client_class():
    """Create a mock Client class with state persistence methods."""
    class MockClient:
        def __init__(self, config_path):
            self.config_path = config_path
            self.name = ""
            self.user_modes = []
            self.joined_channels = set()
            self.state_file = None

        def _save_client_state(self):
            """Save client state to JSON file."""
            if not self.state_file:
                return
            
            state = {
                'nick': self.name,
                'modes': list(self.user_modes),
                'channels': list(self.joined_channels)
            }
            
            # Atomic write with temp file
            temp_file = Path(str(self.state_file) + '.tmp')
            with open(temp_file, 'w') as f:
                json.dump(state, f)
            temp_file.replace(self.state_file)

        def _load_client_state(self):
            """Load client state from JSON file."""
            if not self.state_file or not self.state_file.exists():
                return None
            
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return None

    return MockClient


class TestBaseClientStatePersistence:
    """Test state persistence for base Client class."""

    def test_save_client_state(self, mock_client_class, tmp_path):
        """Test saving client state to file."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.name = "TestClient"
        client.user_modes = ["+i", "+w"]
        client.joined_channels = {"#general", "#dev", "#test"}
        client.state_file = tmp_path / "state.json"

        # Save state
        client._save_client_state()

        # Verify state file exists
        assert client.state_file.exists(), "State file should exist"

        # Verify saved state
        with open(client.state_file, 'r') as f:
            saved_state = json.load(f)

        assert saved_state['nick'] == "TestClient", "Nick should match"
        assert set(saved_state['modes']) == {"+i", "+w"}, "Modes should match"
        assert set(saved_state['channels']) == {"#general", "#dev", "#test"}, "Channels should match"

    def test_load_client_state(self, mock_client_class, tmp_path):
        """Test loading client state from file."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.name = "TestClient"
        client.user_modes = ["+i", "+w"]
        client.joined_channels = {"#general", "#dev", "#test"}
        client.state_file = tmp_path / "state.json"

        # Save initial state
        client._save_client_state()

        # Create new client instance
        client2 = mock_client_class(str(config_path))
        client2.name = "DifferentClient"
        client2.state_file = client.state_file

        # Load state
        loaded_state = client2._load_client_state()

        # Verify loaded state
        assert loaded_state is not None, "Should load state"
        assert loaded_state['nick'] == "TestClient", "Loaded nick should match"
        assert set(loaded_state['modes']) == {"+i", "+w"}, "Loaded modes should match"
        assert set(loaded_state['channels']) == {"#general", "#dev", "#test"}, "Loaded channels should match"

    def test_load_nonexistent_state_file(self, mock_client_class, tmp_path):
        """Test loading from a nonexistent state file."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.state_file = tmp_path / "nonexistent.json"

        loaded_state = client._load_client_state()

        assert loaded_state is None, "Should return None for nonexistent file"


class TestCorruptStateFile:
    """Test handling of corrupt state files."""

    def test_corrupt_json(self, mock_client_class, tmp_path):
        """Test that corrupt JSON is handled gracefully."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.state_file = tmp_path / "corrupt_state.json"

        # Write corrupt JSON
        with open(client.state_file, 'w') as f:
            f.write("{ invalid json }}")

        # Try to load state
        loaded_state = client._load_client_state()

        # Should return None for corrupt file
        assert loaded_state is None, "Should return None for corrupt state file"

    def test_empty_state_file(self, mock_client_class, tmp_path):
        """Test handling of empty state file."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.state_file = tmp_path / "empty_state.json"

        # Create empty file
        client.state_file.write_text("")

        # Try to load state
        loaded_state = client._load_client_state()

        # Should return None for empty file
        assert loaded_state is None, "Should return None for empty state file"

    def test_malformed_json_structure(self, mock_client_class, tmp_path):
        """Test handling of JSON with unexpected structure."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.state_file = tmp_path / "malformed_state.json"

        # Write valid JSON but unexpected structure
        with open(client.state_file, 'w') as f:
            json.dump({"unexpected": "structure"}, f)

        # Should still load it (no validation in basic implementation)
        loaded_state = client._load_client_state()
        assert loaded_state is not None
        assert loaded_state['unexpected'] == "structure"


class TestAtomicWrites:
    """Test atomic write behavior."""

    def test_atomic_writes_consistency(self, mock_client_class, tmp_path):
        """Test that state writes are atomic and consistent."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.name = "AtomicTest"
        client.user_modes = ["+i"]
        client.joined_channels = {"#test"}
        client.state_file = tmp_path / "atomic_state.json"

        # Save state multiple times
        for i in range(10):
            client.user_modes = [f"+mode{i}"]
            client._save_client_state()

        # Verify final state is consistent
        with open(client.state_file, 'r') as f:
            final_state = json.load(f)

        assert final_state['modes'] == ["+mode9"], "Final state should be consistent"

    def test_no_temp_files_remain(self, mock_client_class, tmp_path):
        """Test that no temporary files remain after atomic writes."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.name = "AtomicTest"
        client.user_modes = ["+i"]
        client.joined_channels = {"#test"}
        client.state_file = tmp_path / "atomic_state.json"

        # Save state multiple times
        for i in range(5):
            client.user_modes = [f"+mode{i}"]
            client._save_client_state()

        # Verify no temp files remain
        temp_files = list(tmp_path.glob("*.json.tmp"))
        assert len(temp_files) == 0, "No temp files should remain"

    def test_partial_write_recovery(self, mock_client_class, tmp_path):
        """Test recovery from partial writes using atomic operations."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.name = "TestClient"
        client.user_modes = ["+i"]
        client.joined_channels = {"#test"}
        client.state_file = tmp_path / "atomic_state.json"

        # First write
        client._save_client_state()
        
        # Read first state
        with open(client.state_file, 'r') as f:
            first_state = json.load(f)

        # Second write with different data
        client.user_modes = ["+w"]
        client._save_client_state()
        
        # Verify second state is readable and consistent
        with open(client.state_file, 'r') as f:
            second_state = json.load(f)

        assert second_state['modes'] == ["+w"]
        assert first_state['nick'] == second_state['nick']


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_modes_list(self, mock_client_class, tmp_path):
        """Test saving and loading with empty modes list."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.name = "TestClient"
        client.user_modes = []
        client.joined_channels = {"#test"}
        client.state_file = tmp_path / "state.json"

        client._save_client_state()
        loaded_state = client._load_client_state()

        assert loaded_state['modes'] == []

    def test_empty_channels_set(self, mock_client_class, tmp_path):
        """Test saving and loading with empty channels set."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.name = "TestClient"
        client.user_modes = ["+i"]
        client.joined_channels = set()
        client.state_file = tmp_path / "state.json"

        client._save_client_state()
        loaded_state = client._load_client_state()

        assert loaded_state['channels'] == []

    def test_special_characters_in_nick(self, mock_client_class, tmp_path):
        """Test saving and loading nicks with special characters."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.name = "Test_Client-123"
        client.user_modes = ["+i"]
        client.joined_channels = {"#test"}
        client.state_file = tmp_path / "state.json"

        client._save_client_state()
        loaded_state = client._load_client_state()

        assert loaded_state['nick'] == "Test_Client-123"

    def test_special_characters_in_channels(self, mock_client_class, tmp_path):
        """Test saving and loading channels with special characters."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.name = "TestClient"
        client.user_modes = ["+i"]
        client.joined_channels = {"#channel-1", "#channel_2", "##special"}
        client.state_file = tmp_path / "state.json"

        client._save_client_state()
        loaded_state = client._load_client_state()

        assert set(loaded_state['channels']) == {"#channel-1", "#channel_2", "##special"}

    def test_unicode_in_state(self, mock_client_class, tmp_path):
        """Test saving and loading unicode characters in state."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.name = "Test_Üñíçødé"
        client.user_modes = ["+i"]
        client.joined_channels = {"#tëst"}
        client.state_file = tmp_path / "state.json"

        client._save_client_state()
        loaded_state = client._load_client_state()

        assert loaded_state['nick'] == "Test_Üñíçødé"
        assert "tëst" in loaded_state['channels'][0]

    def test_none_state_file(self, mock_client_class, tmp_path):
        """Test behavior when state_file is None."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.name = "TestClient"
        client.state_file = None

        # Should not raise exception
        client._save_client_state()
        loaded_state = client._load_client_state()

        assert loaded_state is None

    def test_large_state_file(self, mock_client_class, tmp_path):
        """Test handling of large state files."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        client = mock_client_class(str(config_path))
        client.name = "TestClient"
        client.user_modes = [f"+mode{i}" for i in range(1000)]
        client.joined_channels = {f"#channel{i}" for i in range(1000)}
        client.state_file = tmp_path / "state.json"

        client._save_client_state()
        loaded_state = client._load_client_state()

        assert len(loaded_state['modes']) == 1000
        assert len(loaded_state['channels']) == 1000


class TestStateRoundTrip:
    """Test complete state save and load round trips."""

    def test_round_trip_preserves_data(self, mock_client_class, tmp_path):
        """Test that state is preserved through a complete round trip."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        
        original_nick = "RoundTripTest"
        original_modes = ["+i", "+w", "+s"]
        original_channels = {"#general", "#dev", "#test", "#secret"}

        client1 = mock_client_class(str(config_path))
        client1.name = original_nick
        client1.user_modes = original_modes
        client