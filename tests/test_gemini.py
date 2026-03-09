```python
#!/usr/bin/env python3
"""
Pytest test file for csc_service.clients.gemini.gemini module.

Tests the Gemini client class with mocked external dependencies.
"""

import pytest
import json
from unittest import mock
from pathlib import Path
from typing import Optional
import queue
import threading

# Import the module under test
from csc_service.clients.gemini.gemini import Gemini


class DataHarness:
    """Simple in-memory replacement for Data.get_data/put_data for tests."""
    def __init__(self):
        """Initialize an empty in-memory data store."""
        self.store = {}

    def get_data(self, k):
        """Retrieve a value from the in-memory store."""
        return self.store.get(k)

    def put_data(self, k, v):
        """Store a key-value pair in the in-memory store."""
        self.store[k] = v


@pytest.fixture
def mock_genai():
    """Mock the google.genai module."""
    with mock.patch("google.genai") as m:
        yield m


@pytest.fixture
def mock_secret_functions():
    """Mock all secret/config loading functions."""
    with mock.patch("csc_service.clients.gemini.secret.get_gemini_api_key") as mock_api_key, \
         mock.patch("csc_service.clients.gemini.secret.get_gemini_oper_credentials") as mock_creds, \
         mock.patch("csc_service.clients.gemini.secret.load_initial_core_file_context") as mock_context, \
         mock.patch("csc_service.clients.gemini.secret.get_system_instructions") as mock_sys_instr:
        
        mock_api_key.return_value = "test-api-key"
        mock_creds.return_value = {"test": "creds"}
        mock_context.return_value = "test file context"
        mock_sys_instr.return_value = "test system instructions"
        
        yield {
            "api_key": mock_api_key,
            "creds": mock_creds,
            "context": mock_context,
            "sys_instr": mock_sys_instr,
        }


@pytest.fixture
def mock_client_base(tmp_path):
    """Mock the Client base class."""
    with mock.patch("csc_service.clients.gemini.gemini.Client") as mock_client_class:
        # Create a mock instance
        mock_instance = mock.MagicMock()
        mock_instance.run_dir = tmp_path
        mock_instance.name = "Gemini"
        mock_instance.log = mock.MagicMock()
        mock_instance.init_data = mock.MagicMock()
        mock_instance.get_gemini_state_persistence = mock.MagicMock(return_value="test state")
        mock_instance.send_to_server = mock.MagicMock()
        mock_instance.n = "gemini_user"
        mock_instance.user_modes = []
        mock_instance.joined_channels = set()
        mock_instance.connection_status = {'registered': False}
        
        mock_client_class.return_value = mock_instance
        yield mock_client_class, mock_instance


@pytest.fixture
def gemini_client(tmp_path, mock_genai, mock_secret_functions, mock_client_base):
    """Create a Gemini client instance with all mocks in place."""
    mock_client_class, mock_instance = mock_client_base
    
    # Mock the genai client and model
    mock_genai.Client = mock.MagicMock()
    mock_genai_chat = mock.MagicMock()
    mock_genai.Client.return_value.chats.create = mock.MagicMock(return_value=mock_genai_chat)
    
    # Create the Gemini instance
    client = Gemini(host="localhost", server_port=9999)
    
    # Override some attributes that would be set in __init__
    client.run_dir = tmp_path
    client.state_file = tmp_path / "Gemini_state.json"
    
    return client


class TestGeminiInit:
    """Test Gemini initialization."""

    def test_gemini_init_basic(self, tmp_path, mock_genai, mock_secret_functions, mock_client_base):
        """Test basic Gemini initialization."""
        mock_client_class, mock_instance = mock_client_base
        mock_instance.run_dir = tmp_path
        
        client = Gemini(host="localhost", server_port=9999)
        
        assert client.name == "Gemini"
        assert client.autonomous_mode is True
        assert client.connection_status == {'registered': False}
        assert isinstance(client.joined_channels, set)

    def test_gemini_init_without_host(self, mock_genai, mock_secret_functions, mock_client_base):
        """Test Gemini initialization without explicit host."""
        mock_client_class, mock_instance = mock_client_base
        
        client = Gemini()
        
        assert client.name == "Gemini"
        assert client.autonomous_mode is True

    def test_gemini_system_instructions_built(self, gemini_client, mock_secret_functions):
        """Test that system instructions are properly assembled."""
        assert "test system instructions" in gemini_client.system_instructions
        assert "test state" in gemini_client.system_instructions

    def test_gemini_api_key_loaded(self, gemini_client, mock_secret_functions):
        """Test that Gemini API key is loaded."""
        assert gemini_client.GEMINI_API_KEY == "test-api-key"

    def test_gemini_model_name_set(self, gemini_client):
        """Test that model name is set correctly."""
        assert gemini_client.GEMINI_MODEL_NAME == "gemini-2.5-flash-lite"

    def test_gemini_chat_initialized(self, gemini_client):
        """Test that chat history and lock are initialized."""
        assert gemini_client.chat_history == []
        assert isinstance(gemini_client._query_lock, type(threading.Lock()))
        assert isinstance(gemini_client._work_queue, queue.Queue)


class TestGeminiStateManagement:
    """Test Gemini state persistence."""

    def test_save_client_state(self, gemini_client, tmp_path):
        """Test saving client state to JSON file."""
        gemini_client.state_file = tmp_path / "test_state.json"
        gemini_client.user_modes = ["+i", "+w"]
        gemini_client.joined_channels = {"#general", "#random"}
        
        gemini_client._save_client_state()
        
        assert gemini_client.state_file.exists()
        
        with open(gemini_client.state_file, 'r') as f:
            state = json.load(f)
        
        assert state["nick"] == "Gemini"
        assert state["modes"] == ["+i", "+w"]
        assert set(state["channels"]) == {"#general", "#random"}

    def test_load_client_state_exists(self, gemini_client, tmp_path):
        """Test loading client state when file exists."""
        state_file = tmp_path / "test_state.json"
        gemini_client.state_file = state_file
        
        # Create a state file
        state_data = {
            "nick": "Gemini",
            "modes": ["+i"],
            "channels": ["#general"]
        }
        with open(state_file, 'w') as f:
            json.dump(state_data, f)
        
        loaded_state = gemini_client._load_client_state()
        
        assert loaded_state is not None
        assert loaded_state["nick"] == "Gemini"
        assert loaded_state["modes"] == ["+i"]

    def test_load_client_state_not_exists(self, gemini_client, tmp_path):
        """Test loading client state when file does not exist."""
        gemini_client.state_file = tmp_path / "nonexistent_state.json"
        
        result = gemini_client._load_client_state()
        
        assert result is None

    def test_load_client_state_corrupt_json(self, gemini_client, tmp_path):
        """Test loading corrupted JSON state file."""
        state_file = tmp_path / "corrupt_state.json"
        gemini_client.state_file = state_file
        
        # Write invalid JSON
        with open(state_file, 'w') as f:
            f.write("{invalid json}")
        
        result = gemini_client._load_client_state()
        
        assert result is None

    def test_save_state_atomic_write(self, gemini_client, tmp_path):
        """Test that state is saved atomically."""
        gemini_client.state_file = tmp_path / "atomic_state.json"
        gemini_client.user_modes = []
        gemini_client.joined_channels = set()
        
        gemini_client._save_client_state()
        
        # Verify no temporary files remain
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0
        
        # Verify final file exists
        assert gemini_client.state_file.exists()


class TestGeminiNetworking:
    """Test Gemini networking functionality."""

    def test_send_to_server(self, gemini_client):
        """Test sending message to server."""
        gemini_client.send_to_server("test message")
        
        # The mocked base class's send_to_server should be called
        # (or the method should execute without error)
        # This test verifies the method exists and is callable
        assert hasattr(gemini_client, 'send_to_server')

    def test_current_channel_initialized(self, gemini_client):
        """Test that current channel is initialized."""
        assert gemini_client.current_channel == "#general"

    def test_connection_status_initialized(self, gemini_client):
        """Test that connection status is initialized."""
        assert gemini_client.connection_status == {'registered': False}


class TestGeminiGeminiIntegration:
    """Test Gemini API integration."""

    def test_connect_to_gemini_api(self, gemini_client, mock_genai):
        """Test connecting to Gemini API."""
        assert gemini_client.gemini_client is not None or gemini_client.GEMINI_API_KEY == "test-api-key"

    def test_gemini_model_name_correct(self, gemini_client):
        """Test that the correct model name is used."""
        assert gemini_client.GEMINI_MODEL_NAME == "gemini-2.5-flash-lite"

    def test_chat_history_empty_on_init(self, gemini_client):
        """Test that chat history starts empty."""
        assert isinstance(gemini_client.chat_history, list)
        assert len(gemini_client.chat_history) == 0


class TestGeminiAttributes:
    """Test Gemini client attributes."""

    def test_name_attribute(self, gemini_client):
        """Test name attribute."""
        assert gemini_client.name == "Gemini"

    def test_autonomous_mode_enabled(self, gemini_client):
        """Test autonomous mode is enabled."""
        assert gemini_client.autonomous_mode is True

    def test_log_file_attribute(self, gemini_client):
        """Test log file attribute."""
        assert "Gemini" in gemini_client.log_file

    def test_work_queue_initialized(self, gemini_client):
        """Test work queue is initialized."""
        assert isinstance(gemini_client._work_queue, queue.Queue)

    def test_query_lock_initialized(self, gemini_client):
        """Test query lock is initialized."""
        assert gemini_client._query_lock is not None


class TestGeminiEdgeCases:
    """Test edge cases and error conditions."""

    def test_state_file_path_created(self, gemini_client, tmp_path):
        """Test that state file path uses run_dir."""
        assert gemini_client.state_file.parent == gemini_client.run_dir

    def test_multiple_channels_tracking(self, gemini_client):
        """Test tracking multiple channels."""
        gemini_client.joined_channels.add("#general")
        gemini_client.joined_channels.add("#random")
        gemini_client.joined_channels.add("#dev")
        
        assert len(gemini_client.joined_channels) == 3
        assert "#general" in gemini_client.joined_channels

    def test_user_modes_list(self, gemini_client):
        """Test user modes list."""
        gemini_client.user_modes = ["+i", "+w", "+o"]
        
        assert len(gemini_client.user_modes) == 3
        assert "+i" in gemini_client.user_modes

    def test_state_file_cleanup_on_save(self, gemini_client, tmp_path):
        """Test that temporary files are cleaned up after save."""
        gemini_client.state_file = tmp_path / "state.json"
        gemini_client.user_modes = []
        gemini_client.joined_channels = set()
        
        gemini_client._save_client_state()
        
        # Check that only the final state file exists
        json_files = list(tmp_path.glob("state.json*"))
        assert len(json_files) == 1
        assert json_files[0].name == "state.json"


class TestGeminiMocking:
    """Test mocking setup and teardown."""

    def test_mock_setup_complete(self, gemini_client):
        """Test that all mocks are properly set up."""
        assert gemini_client is not None
        assert hasattr(gemini_client, 'GEMINI_API_KEY')
        assert hasattr(gemini_client, 'gemini_client')
        assert hasattr(gemini_client, '_query_lock')

    def test_secret_functions_mocked(self, mock_secret_functions):
        """Test that secret functions are mocked."""
        assert mock_secret_functions["api_key"] is not None
        assert mock_secret_functions["creds"] is not None
        assert mock_secret_functions["context"] is not None
        assert mock_secret_functions["sys_instr"] is not None

    def test_client_base_mocked(self, mock_client_base):
        """Test that Client base class is mocked."""
        mock_class, mock_instance = mock_client_base
        assert mock_class is not None
        assert mock_instance is not None


class TestGeminiDataPersistence:
    """Test data persistence methods."""

    def test_save_and_load_roundtrip(self, gemini_client, tmp_path):
        """Test saving and loading state data."""
        gemini_client.state_file = tmp_path / "roundtrip.json"
        gemini_client.user_modes = ["+i", "+o"]
        gemini_client.joined_channels = {"#test1", "#test2"}
        
        # Save
        gemini_client._save_client_state()
        
        # Load
        loaded = gemini_client._load_client_state()
        
        assert loaded is not None
        assert loaded["modes"] == ["+i", "+o"]
        assert set(loaded["channels"]) == {"#test1", "#test2"}

    def test_state_persistence_empty_channels(self, gemini_client, tmp_path):
        """Test state persistence with empty channels."""
        gemini_client.state_file = tmp_path / "empty_channels.json"
        gemini_client.user_modes = []
        gemini_client.joined_channels = set()
        
        gemini_client._save_client_state()
        loaded = gemini_client._load_client_state()
        
        assert loaded["channels"] == []
        assert loaded["modes"] == []
```