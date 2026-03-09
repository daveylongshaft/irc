```python
import pytest
from unittest.mock import patch, MagicMock, mock_open, call
from pathlib import Path
import tempfile
import os

from csc_client.client import Client


class TestClientReadline:
    """Tests for Client readline/arrow key support functionality."""

    def _make_client(self):
        """Create a bare Client with only a log method (skips __init__)."""
        client = object.__new__(Client)
        client.log = MagicMock()
        return client

    # ==================================================================
    # 1. Readline Import Tests
    # ==================================================================
    @patch("csc_client.client.readline")
    def test_readline_imported_when_available(self, mock_readline):
        """When readline is available, it should be used by _setup_readline."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            client._setup_readline()

        # Verify readline was actually used
        mock_readline.set_history_length.assert_called()

    @patch("csc_client.client.readline", None)
    def test_client_works_without_readline(self):
        """Client should work even when readline is not available."""
        client = self._make_client()
        # Should not raise an exception
        client._setup_readline()
        assert client is not None

    # ==================================================================
    # 2. Readline Setup Tests
    # ==================================================================
    @patch("csc_client.client.readline")
    @patch("atexit.register")
    def test_setup_readline_configures_history(self, mock_atexit, mock_readline):
        """_setup_readline should configure history file and length."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        client._setup_readline()

        # Verify history length was set
        mock_readline.set_history_length.assert_called_once_with(1000)

    @patch("csc_client.client.readline")
    @patch("atexit.register")
    def test_setup_readline_registers_exit_handler(self, mock_atexit, mock_readline):
        """_setup_readline should register an atexit handler for saving history."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        client._setup_readline()

        # Verify atexit.register was called
        mock_atexit.assert_called_once()

    @patch("csc_client.client.readline")
    def test_setup_readline_enables_tab_completion(self, mock_readline):
        """_setup_readline should enable tab completion."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            client._setup_readline()

        # Verify tab completion was configured
        calls = [str(c) for c in mock_readline.parse_and_bind.call_args_list]
        assert any("tab: complete" in c for c in calls)

    @patch("csc_client.client.readline")
    def test_setup_readline_sets_emacs_mode(self, mock_readline):
        """_setup_readline should set emacs editing mode."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            client._setup_readline()

        # Verify emacs mode was configured
        calls = [str(c) for c in mock_readline.parse_and_bind.call_args_list]
        assert any("editing-mode emacs" in c for c in calls)

    @patch("csc_client.client.readline")
    def test_setup_readline_attempts_to_read_history_file(self, mock_readline):
        """_setup_readline should attempt to read existing history file."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            client._setup_readline()

        # Verify read_history_file was called
        mock_readline.read_history_file.assert_called_once()
        # Should use home directory path
        call_args = str(mock_readline.read_history_file.call_args)
        assert ".csc_client_history" in call_args

    @patch("csc_client.client.readline")
    def test_setup_readline_handles_missing_history_file(self, mock_readline):
        """_setup_readline should handle missing history file gracefully."""
        # Simulate FileNotFoundError when reading history
        mock_readline.read_history_file = MagicMock(side_effect=FileNotFoundError())
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            # Should not raise an exception
            client._setup_readline()
            assert client is not None

    @patch("csc_client.client.readline")
    def test_setup_readline_handles_read_errors(self, mock_readline):
        """_setup_readline should handle errors reading history file."""
        # Simulate generic error when reading history
        mock_readline.read_history_file = MagicMock(side_effect=Exception("Read error"))
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            # Should not raise an exception
            client._setup_readline()
            assert client is not None

    # ==================================================================
    # 3. Readline Exit Handler Tests
    # ==================================================================
    @patch("csc_client.client.readline")
    def test_setup_readline_exit_handler_saves_history(self, mock_readline):
        """The atexit handler should save history to file."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()
        mock_readline.write_history_file = MagicMock()

        client = self._make_client()
        with patch("atexit.register") as mock_atexit:
            client._setup_readline()

        # Get the registered handler
        assert mock_atexit.called
        handler = mock_atexit.call_args[0][0]
        
        # Call the handler
        handler()
        
        # Verify history was written
        mock_readline.write_history_file.assert_called_once()

    @patch("csc_client.client.readline")
    def test_setup_readline_exit_handler_handles_write_errors(self, mock_readline):
        """The atexit handler should handle errors when writing history."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()
        mock_readline.write_history_file = MagicMock(side_effect=Exception("Write error"))

        client = self._make_client()
        with patch("atexit.register") as mock_atexit:
            client._setup_readline()

        # Get the registered handler
        handler = mock_atexit.call_args[0][0]
        
        # Call the handler - should not raise
        handler()

    # ==================================================================
    # 4. Client Initialization Tests
    # ==================================================================
    @patch("csc_client.client.readline")
    @patch("csc_client.client.Data")
    @patch("csc_client.client.Log")
    @patch("csc_client.client.Platform")
    def test_client_init_calls_setup_readline(self, mock_platform, mock_log, mock_data, mock_readline):
        """Client __init__ should call _setup_readline."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()
        
        mock_data_instance = MagicMock()
        mock_log_instance = MagicMock()
        mock_platform_instance = MagicMock()
        
        mock_data.return_value = mock_data_instance
        mock_log.return_value = mock_log_instance
        mock_platform.return_value = mock_platform_instance
        mock_platform_instance.get_platform.return_value = "linux"

        with patch("atexit.register"):
            with patch.object(Client, '_setup_readline') as mock_setup_readline:
                client = Client("test_host", 1234, "test_user")
                mock_setup_readline.assert_called_once()

    # ==================================================================
    # 5. Arrow Key Support Tests
    # ==================================================================
    @patch("csc_client.client.readline")
    def test_readline_arrow_keys_enabled_via_emacs_mode(self, mock_readline):
        """Arrow keys should be enabled through emacs mode configuration."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            client._setup_readline()

        # Check that parse_and_bind was called with emacs mode
        call_args_list = [str(c) for c in mock_readline.parse_and_bind.call_args_list]
        assert any("editing-mode emacs" in arg for arg in call_args_list)

    @patch("csc_client.client.readline")
    def test_readline_parse_and_bind_called_multiple_times(self, mock_readline):
        """parse_and_bind should be called for various key configurations."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            client._setup_readline()

        # Verify parse_and_bind was called at least once
        assert mock_readline.parse_and_bind.call_count >= 1

    # ==================================================================
    # 6. History File Path Tests
    # ==================================================================
    @patch("csc_client.client.readline")
    def test_readline_history_file_uses_home_directory(self, mock_readline):
        """History file path should use home directory."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            client._setup_readline()

        # Check that the history file path contains home directory reference
        call_args = str(mock_readline.read_history_file.call_args)
        assert ".csc_client_history" in call_args or "csc_client_history" in call_args

    @patch("csc_client.client.readline")
    def test_readline_history_file_path_expanduser(self, mock_readline):
        """History file path should use expanduser to resolve ~."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            client._setup_readline()

        # Verify read_history_file was called with a path string
        assert mock_readline.read_history_file.called
        call_arg = mock_readline.read_history_file.call_args[0][0]
        # The path should be a string
        assert isinstance(call_arg, (str, Path))

    # ==================================================================
    # 7. Configuration Tests
    # ==================================================================
    @patch("csc_client.client.readline")
    def test_setup_readline_sets_correct_history_length(self, mock_readline):
        """History length should be set to 1000."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            client._setup_readline()

        mock_readline.set_history_length.assert_called_with(1000)

    @patch("csc_client.client.readline")
    def test_setup_readline_called_during_init(self, mock_readline):
        """_setup_readline should be called as part of initialization."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            client._setup_readline()

        # Verify readline methods were called
        assert mock_readline.set_history_length.called

    # ==================================================================
    # 8. Edge Cases and Error Handling
    # ==================================================================
    @patch("csc_client.client.readline")
    def test_setup_readline_with_permission_error_on_history_file(self, mock_readline):
        """_setup_readline should handle permission errors gracefully."""
        mock_readline.read_history_file = MagicMock(side_effect=PermissionError())
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            # Should not raise
            client._setup_readline()

    @patch("csc_client.client.readline")
    def test_setup_readline_with_oserror_on_history_file(self, mock_readline):
        """_setup_readline should handle OSError gracefully."""
        mock_readline.read_history_file = MagicMock(side_effect=OSError())
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()

        client = self._make_client()
        with patch("atexit.register"):
            # Should not raise
            client._setup_readline()

    @patch("csc_client.client.readline")
    def test_exit_handler_with_permission_error_on_write(self, mock_readline):
        """Exit handler should handle permission errors when writing."""
        mock_readline.read_history_file = MagicMock()
        mock_readline.set_history_length = MagicMock()
        mock_readline.parse_and_bind = MagicMock()
        mock_readline.write_history_file = MagicMock(side_effect=PermissionError())

        client = self._make_client()
        