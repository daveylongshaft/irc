```python
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from csc_shared.services.botserv_service import Botserv


@pytest.fixture
def mock_server():
    """Fixture providing a mocked server with storage."""
    server = MagicMock()
    server.storage = MagicMock()
    server.storage.get.side_effect = lambda key, default: default
    return server


@pytest.fixture
def botserv_instance(mock_server):
    """Fixture providing a Botserv instance with mocked server."""
    return Botserv(mock_server)


@pytest.fixture
def test_log_file():
    """Fixture providing a test log file path."""
    return "/var/log/test_app/test.log"


@pytest.fixture
def channel():
    """Fixture providing a test channel."""
    return "#testchan"


class TestBotservLogread:
    """Test suite for Botserv logread functionality."""

    @patch('csc_shared.services.botserv_service.subprocess.run')
    def test_logread_initial_read_success(self, mock_subprocess_run, botserv_instance, mock_server, test_log_file, channel):
        """Test successful initial reading of a log file, no prior offset."""
        mock_subprocess_run.return_value = MagicMock(
            stdout="Line 1 of log\nLine 2 of log\nLast line of log\n",
            stderr="TOTAL_BYTES_READ:39\n",
            check=True
        )
        
        result = botserv_instance.logread(channel, test_log_file)

        expected_script_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "server", "scripts", "read_privileged_log.py"
        )
        mock_subprocess_run.assert_called_once_with(
            [sys.executable, expected_script_path, test_log_file, "0"],
            capture_output=True, text=True, check=True
        )
        mock_server.storage.get.assert_called_once_with(f"botserv_logread_offset_{channel}_{test_log_file}", 0)
        mock_server.storage.set.assert_called_once_with(f"botserv_logread_offset_{channel}_{test_log_file}", 39)
        
        assert f"Successfully processed new lines from '{test_log_file}' to '{channel}'. Matched lines: 3" in result
        mock_server.send_to_channel.assert_has_calls([
            call(channel, f"Starting to read new lines from: {test_log_file}"),
            call(channel, "Line 1 of log"),
            call(channel, "Line 2 of log"),
            call(channel, "Last line of log"),
            call(channel, f"Finished reading new lines from: {test_log_file}. Total new lines: 3")
        ])

    @patch('csc_shared.services.botserv_service.subprocess.run')
    def test_logread_incremental_read_success(self, mock_subprocess_run, botserv_instance, mock_server, test_log_file, channel):
        """Test successful incremental reading with a prior offset."""
        mock_server.storage.get.side_effect = lambda key, default: (
            39 if key == f"botserv_logread_offset_{channel}_{test_log_file}" else default
        )

        mock_subprocess_run.return_value = MagicMock(
            stdout="New line 1\nNew line 2\n",
            stderr="TOTAL_BYTES_READ:66\n",
            check=True
        )
        
        result = botserv_instance.logread(channel, test_log_file)

        expected_script_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "server", "scripts", "read_privileged_log.py"
        )
        mock_subprocess_run.assert_called_once_with(
            [sys.executable, expected_script_path, test_log_file, "39"],
            capture_output=True, text=True, check=True
        )
        mock_server.storage.get.assert_called_once_with(f"botserv_logread_offset_{channel}_{test_log_file}", 0)
        mock_server.storage.set.assert_called_once_with(f"botserv_logread_offset_{channel}_{test_log_file}", 66)
        
        assert f"Successfully processed new lines from '{test_log_file}' to '{channel}'. Matched lines: 2" in result
        mock_server.send_to_channel.assert_has_calls([
            call(channel, f"Starting to read new lines from: {test_log_file}"),
            call(channel, "New line 1"),
            call(channel, "New line 2"),
            call(channel, f"Finished reading new lines from: {test_log_file}. Total new lines: 2")
        ])

    @patch('csc_shared.services.botserv_service.subprocess.run')
    def test_logread_no_new_lines(self, mock_subprocess_run, botserv_instance, mock_server, test_log_file, channel):
        """Test LOGREAD when there are no new lines in the log file."""
        mock_server.storage.get.side_effect = lambda key, default: (
            39 if key == f"botserv_logread_offset_{channel}_{test_log_file}" else default
        )

        mock_subprocess_run.return_value = MagicMock(
            stdout="",
            stderr="TOTAL_BYTES_READ:39\n",
            check=True
        )
        
        result = botserv_instance.logread(channel, test_log_file)

        assert f"No new lines in '{test_log_file}'." in result
        mock_server.send_to_channel.assert_any_call(channel, f"No new lines in '{test_log_file}'.")
        mock_server.storage.set.assert_called_once_with(f"botserv_logread_offset_{channel}_{test_log_file}", 39)

    @patch('csc_shared.services.botserv_service.subprocess.run')
    def test_logread_with_argument_filter_match(self, mock_subprocess_run, botserv_instance, mock_server, test_log_file, channel):
        """Test LOGREAD with an argument-based filter pattern that matches some lines."""
        mock_subprocess_run.return_value = MagicMock(
            stdout="Line with keyword\nAnother line\nKeyword found here\n",
            stderr="TOTAL_BYTES_READ:57\n",
            check=True
        )
        
        filter_pattern = "keyword"
        result = botserv_instance.logread(channel, test_log_file, filter_pattern)

        assert "Matched lines: 2" in result
        mock_server.send_to_channel.assert_has_calls([
            call(channel, f"Starting to read new lines from: {test_log_file}"),
            call(channel, "Line with keyword"),
            call(channel, "Keyword found here"),
            call(channel, f"Finished reading new lines from: {test_log_file}. Total new lines: 2")
        ])

    @patch('csc_shared.services.botserv_service.subprocess.run')
    def test_logread_with_argument_filter_no_match(self, mock_subprocess_run, botserv_instance, mock_server, test_log_file, channel):
        """Test LOGREAD with a filter pattern that matches no lines."""
        mock_subprocess_run.return_value = MagicMock(
            stdout="Line 1\nLine 2\nLine 3\n",
            stderr="TOTAL_BYTES_READ:21\n",
            check=True
        )
        
        filter_pattern = "nonexistent"
        result = botserv_instance.logread(channel, test_log_file, filter_pattern)

        assert "Matched lines: 0" in result
        mock_server.send_to_channel.assert_has_calls([
            call(channel, f"Starting to read new lines from: {test_log_file}"),
            call(channel, f"Finished reading new lines from: {test_log_file}. Total new lines: 0")
        ])

    @patch('csc_shared.services.botserv_service.subprocess.run')
    def test_logread_subprocess_failure(self, mock_subprocess_run, botserv_instance, mock_server, test_log_file, channel):
        """Test LOGREAD when subprocess call fails."""
        mock_subprocess_run.side_effect = Exception("Subprocess failed")
        
        result = botserv_instance.logread(channel, test_log_file)

        assert "Error" in result or "error" in result.lower()

    @patch('csc_shared.services.botserv_service.subprocess.run')
    def test_logread_malformed_stderr(self, mock_subprocess_run, botserv_instance, mock_server, test_log_file, channel):
        """Test LOGREAD when stderr doesn't contain expected TOTAL_BYTES_READ."""
        mock_subprocess_run.return_value = MagicMock(
            stdout="Line 1\nLine 2\n",
            stderr="Some other error output\n",
            check=True
        )
        
        result = botserv_instance.logread(channel, test_log_file)

        assert isinstance(result, str)

    @patch('csc_shared.services.botserv_service.subprocess.run')
    def test_logread_empty_log_file(self, mock_subprocess_run, botserv_instance, mock_server, test_log_file, channel):
        """Test LOGREAD on an empty log file."""
        mock_subprocess_run.return_value = MagicMock(
            stdout="",
            stderr="TOTAL_BYTES_READ:0\n",
            check=True
        )
        
        result = botserv_instance.logread(channel, test_log_file)

        mock_server.storage.set.assert_called_once_with(f"botserv_logread_offset_{channel}_{test_log_file}", 0)

    @patch('csc_shared.services.botserv_service.subprocess.run')
    def test_logread_multiple_channels_separate_offsets(self, mock_subprocess_run, botserv_instance, mock_server, test_log_file):
        """Test that different channels maintain separate offsets for the same log file."""
        channel1 = "#channel1"
        channel2 = "#channel2"
        
        mock_subprocess_run.return_value = MagicMock(
            stdout="Test line\n",
            stderr="TOTAL_BYTES_READ:10\n",
            check=True
        )
        
        botserv_instance.logread(channel1, test_log_file)
        mock_server.storage.set.assert_called_with(f"botserv_logread_offset_{channel1}_{test_log_file}", 10)
        
        mock_server.reset_mock()
        botserv_instance.logread(channel2, test_log_file)
        mock_server.storage.set.assert_called_with(f"botserv_logread_offset_{channel2}_{test_log_file}", 10)

    @patch('csc_shared.services.botserv_service.subprocess.run')
    def test_logread_large_offset(self, mock_subprocess_run, botserv_instance, mock_server, test_log_file, channel):
        """Test LOGREAD with a large stored offset."""
        large_offset = 1000000
        mock_server.storage.get.side_effect = lambda key, default: (
            large_offset if key == f"botserv_logread_offset_{channel}_{test_log_file}" else default
        )

        mock_subprocess_run.return_value = MagicMock(
            stdout="New content\n",
            stderr=f"TOTAL_BYTES_READ:{large_offset + 12}\n",
            check=True
        )
        
        botserv_instance.logread(channel, test_log_file)

        expected_script_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "server", "scripts", "read_privileged_log.py"
        )
        mock_subprocess_run.assert_called_once_with(
            [sys.executable, expected_script_path, test_log_file, str(large_offset)],
            capture_output=True, text=True, check=True
        )

    @patch('csc_shared.services.botserv_service.subprocess.run')
    def test_logread_special_characters_in_lines(self, mock_subprocess_run, botserv_instance, mock_server, test_log_file, channel):
        """Test LOGREAD with special characters in log lines."""
        special_content = "Line with unicode: \u00e9\u00e8\u00ea\nLine with symbols: !@#$%^&*()\n"
        mock_subprocess_run.return_value = MagicMock(
            stdout=special_content,
            stderr="TOTAL_BYTES_READ:50\n",
            check=True
        )
        
        result = botserv_instance.logread(channel, test_log_file)

        assert "Matched lines: 2" in result

    @patch('csc_shared.services.botserv_service.subprocess.run')
    def test_logread_filter_case_insensitive(self, mock_subprocess_run, botserv_instance, mock_server, test_log_file, channel):
        """Test that filter pattern matching is case-insensitive."""
        mock_subprocess_run.return_value = MagicMock(
            stdout="ERROR in module\nerror occurred\nWarning message\n",
            stderr="TOTAL_BYTES_READ:45\n",
            check=True
        )
        
        result = botserv_instance.logread(channel, test_log_file, "ERROR")

        assert "Matched lines: 2" in result

    @patch('csc_shared.services.botserv_service.subprocess.run')
    def test_logread_very_long_lines(self, mock_subprocess_run, botserv_instance, mock_server, test_log_file, channel):
        """Test LOGREAD with very long lines in the log."""
        long_line = "A" * 5000 + "\n"
        mock_subprocess_run.return_value = MagicMock(
            stdout=long_line,
            stderr="TOTAL_BYTES_READ:5001\n",
            check=True
        )
        
        result = botserv_instance.logread(channel, test_log_file)

        assert "Matched lines: 1" in result
        mock_server.send_to_channel.assert_any_call(channel, "A" * 5000)
```