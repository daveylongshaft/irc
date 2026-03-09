```python
"""Tests for the builtin service."""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
import datetime

# Mock the Service parent class and imports before importing builtin_service
sys.modules['csc_service.server.service'] = MagicMock()
sys.modules['csc_service.shared.secret'] = MagicMock()


@pytest.fixture
def mock_server():
    """Create a mock server instance."""
    server = MagicMock()
    server.project_root_dir = "/fake/project/root"
    server.log = MagicMock()
    server.create_new_version = MagicMock()
    return server


@pytest.fixture
def builtin_service(mock_server):
    """Create a builtin service instance with mocked server."""
    # Mock the Service parent class
    with patch('csc_service.server.service.Service'):
        with patch('csc_service.shared.secret.get_known_core_files', return_value=[]):
            from csc_service.shared.services.builtin_service import builtin
            service = builtin(mock_server)
            service.log = MagicMock()
            return service


class TestEchoAndStatus:
    """Test echo and status commands."""

    def test_echo_single_arg(self, builtin_service):
        """Test echo with single argument."""
        result = builtin_service.echo("hello")
        assert result == "Echo: hello"
        builtin_service.log.assert_called()

    def test_echo_multiple_args(self, builtin_service):
        """Test echo with multiple arguments."""
        result = builtin_service.echo("hello", "world", "test")
        assert result == "Echo: hello world test"

    def test_echo_no_args(self, builtin_service):
        """Test echo with no arguments."""
        result = builtin_service.echo()
        assert result == "Echo: "

    def test_status(self, builtin_service):
        """Test status command."""
        result = builtin_service.status()
        assert "System running" in result
        assert "Built-in services are operational" in result

    def test_status_logging(self, builtin_service):
        """Test that status logs appropriately."""
        builtin_service.status()
        assert builtin_service.log.called


class TestCurrentTime:
    """Test current_time command."""

    def test_current_time_format(self, builtin_service):
        """Test current_time returns properly formatted time."""
        result = builtin_service.current_time()
        assert "Current server time:" in result
        # Check that result contains a date-like string
        assert any(char.isdigit() for char in result)

    def test_current_time_logging(self, builtin_service):
        """Test that current_time logs appropriately."""
        builtin_service.current_time()
        assert builtin_service.log.called


class TestURLOperations:
    """Test URL download operations."""

    @patch('csc_service.shared.services.builtin_service.requests')
    def test_download_url_content_success(self, mock_requests, builtin_service):
        """Test successful URL content download."""
        mock_response = MagicMock()
        mock_response.text = "test content"
        mock_requests.get.return_value = mock_response

        result = builtin_service.download_url_content("http://example.com")
        assert result == "test content"
        mock_requests.get.assert_called_once_with("http://example.com", timeout=15)

    @patch('csc_service.shared.services.builtin_service.requests')
    def test_download_url_content_request_error(self, mock_requests, builtin_service):
        """Test URL content download with request error."""
        mock_requests.get.side_effect = Exception("Connection failed")

        result = builtin_service.download_url_content("http://example.com")
        assert "Error" in result or "err" in result

    def test_download_url_content_no_requests(self, builtin_service):
        """Test URL content download when requests module is not available."""
        with patch('csc_service.shared.services.builtin_service.requests', None):
            result = builtin_service.download_url_content("http://example.com")
            assert "requests" in result and "not installed" in result

    @patch('csc_service.shared.services.builtin_service.requests')
    @patch('builtins.open', new_callable=mock_open)
    @patch('os.path.exists')
    @patch('os.makedirs')
    def test_download_url_to_file_success(self, mock_makedirs, mock_exists, mock_file, 
                                         mock_requests, builtin_service, tmp_path):
        """Test successful URL to file download."""
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
        mock_requests.get.return_value = mock_response
        mock_exists.return_value = False

        test_file = str(tmp_path / "test.txt")
        result = builtin_service.download_url_to_file("http://example.com", test_file)
        
        assert "Successfully downloaded" in result
        assert "http://example.com" in result
        mock_makedirs.assert_called()

    @patch('csc_service.shared.services.builtin_service.requests')
    @patch('builtins.open', new_callable=mock_open)
    @patch('os.path.exists')
    @patch('os.makedirs')
    def test_download_url_to_file_with_version(self, mock_makedirs, mock_exists, 
                                               mock_file, mock_requests, builtin_service, tmp_path):
        """Test URL to file download when file exists (triggers versioning)."""
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b"content"]
        mock_requests.get.return_value = mock_response
        mock_exists.return_value = True

        test_file = str(tmp_path / "test.txt")
        result = builtin_service.download_url_to_file("http://example.com", test_file)
        
        assert "Successfully downloaded" in result
        builtin_service.server.create_new_version.assert_called()

    @patch('csc_service.shared.services.builtin_service.requests')
    def test_download_url_to_file_request_error(self, mock_requests, builtin_service, tmp_path):
        """Test URL to file download with request error."""
        mock_requests.get.side_effect = Exception("Network error")

        test_file = str(tmp_path / "test.txt")
        result = builtin_service.download_url_to_file("http://example.com", test_file)
        
        assert "Error" in result or "err" in result

    def test_download_url_to_file_no_requests(self, builtin_service, tmp_path):
        """Test URL to file download when requests module is not available."""
        with patch('csc_service.shared.services.builtin_service.requests', None):
            test_file = str(tmp_path / "test.txt")
            result = builtin_service.download_url_to_file("http://example.com", test_file)
            assert "requests" in result and "not installed" in result


class TestFileSystemOperations:
    """Test local file system operations."""

    @patch('os.listdir')
    @patch('os.path.isdir')
    @patch('os.path.exists')
    def test_list_dir_with_files_and_dirs(self, mock_exists, mock_isdir, mock_listdir, builtin_service):
        """Test list_dir with mixed files and directories."""
        mock_exists.return_value = True
        mock_listdir.return_value = ['file.txt', 'subdir', 'another_file.py']
        mock_isdir.side_effect = lambda path: 'subdir' in path

        result = builtin_service.list_dir(".")
        assert "file.txt" in result
        assert "another_file.py" in result
        assert "subdir/" in result

    @patch('os.listdir')
    @patch('os.path.exists')
    def test_list_dir_empty(self, mock_exists, mock_listdir, builtin_service):
        """Test list_dir with empty directory."""
        mock_exists.return_value = True
        mock_listdir.return_value = []

        result = builtin_service.list_dir(".")
        assert "Directory listing" in result or "empty" in result.lower()

    @patch('os.path.exists')
    def test_list_dir_not_exists(self, mock_exists, builtin_service):
        """Test list_dir with non-existent directory."""
        mock_exists.return_value = False

        result = builtin_service.list_dir("nonexistent")
        assert "does not exist" in result or "not exist" in result

    @patch('os.path.exists')
    @patch('os.path.isfile')
    @patch('builtins.open', new_callable=mock_open, read_data="line1\nline2\nline3")
    def test_read_file_content_success(self, mock_file, mock_isfile, mock_exists, builtin_service):
        """Test successful file reading."""
        mock_exists.return_value = True
        mock_isfile.return_value = True

        result = builtin_service.read_file_content("test.txt")
        assert "<begin file=" in result
        assert "line1" in result
        assert "line2" in result
        assert "<end file=" in result

    @patch('os.path.exists')
    def test_read_file_content_not_exists(self, mock_exists, builtin_service):
        """Test reading non-existent file."""
        mock_exists.return_value = False

        result = builtin_service.read_file_content("nonexistent.txt")
        assert "does not exist" in result or "not exist" in result

    @patch('os.path.exists')
    @patch('os.path.isfile')
    def test_read_file_content_not_file(self, mock_isfile, mock_exists, builtin_service):
        """Test reading when path is not a file."""
        mock_exists.return_value = True
        mock_isfile.return_value = False

        result = builtin_service.read_file_content("directory")
        assert "not a file" in result or "not" in result

    @patch('os.makedirs')
    @patch('os.path.exists')
    def test_create_directory_local_success(self, mock_exists, mock_makedirs, builtin_service):
        """Test successful directory creation."""
        mock_exists.return_value = False

        result = builtin_service.create_directory_local("newdir")
        assert "Successfully created" in result
        mock_makedirs.assert_called()

    @patch('os.path.exists')
    def test_create_directory_local_exists(self, mock_exists, builtin_service):
        """Test directory creation when it already exists."""
        mock_exists.return_value = True

        result = builtin_service.create_directory_local("existingdir")
        assert "already exists" in result or "exists" in result

    @patch('os.remove')
    @patch('os.path.isfile')
    @patch('os.path.exists')
    def test_delete_local_file_success(self, mock_exists, mock_isfile, mock_remove, builtin_service):
        """Test successful file deletion."""
        mock_exists.return_value = True
        mock_isfile.return_value = True

        result = builtin_service.delete_local("file.txt")
        assert "Successfully deleted" in result
        mock_remove.assert_called()

    @patch('os.path.exists')
    def test_delete_local_not_exists(self, mock_exists, builtin_service):
        """Test deleting non-existent file."""
        mock_exists.return_value = False

        result = builtin_service.delete_local("nonexistent.txt")
        assert "does not exist" in result or "not exist" in result

    @patch('os.listdir')
    @patch('os.rmdir')
    @patch('os.path.isdir')
    @patch('os.path.isfile')
    @patch('os.path.exists')
    def test_delete_local_empty_directory(self, mock_exists, mock_isfile, mock_isdir, 
                                         mock_rmdir, mock_listdir, builtin_service):
        """Test deletion of empty directory."""
        mock_exists.return_value = True
        mock_isfile.return_value = False
        mock_isdir.return_value = True
        mock_listdir.return_value = []

        result = builtin_service.delete_local("emptydir")
        assert "Successfully deleted" in result or "empty directory" in result
        mock_rmdir.assert_called()

    @patch('os.listdir')
    @patch('os.path.isdir')
    @patch('os.path.isfile')
    @patch('os.path.exists')
    def test_delete_local_non_empty_directory(self, mock_exists, mock_isfile, mock_isdir, 
                                             mock_listdir, builtin_service):
        """Test deletion of non-empty directory."""
        mock_exists.return_value = True
        mock_isfile.return_value = False
        mock_isdir.return_value = True
        mock_listdir.return_value = ['file.txt']

        result = builtin_service.delete_local("nonemptydir")
        assert "not empty" in result or "not be deleted" in result

    @patch('shutil.move')
    @patch('os.makedirs')
    @patch('os.path.exists')
    def test_move_local_success(self, mock_exists, mock_makedirs, mock_move, builtin_service):
        """Test successful file/directory move."""
        mock_exists.side_effect = [True, False]  # source exists, dest doesn't

        result = builtin_service.move_local("source.txt", "dest.txt")
        assert "Successfully moved" in result
        mock_move.assert_called()

    @patch('os.path.exists')
    def test_move_local_source_not_exists(self, mock_exists, builtin_service):
        """Test move when source doesn't exist."""
        mock_exists.return_value = False

        result = builtin_service.move_local("nonexistent.txt", "dest.txt")
        assert "does not exist" in result or "not exist" in result

    @patch('shutil.move')
    @patch('os.path.exists')
    def test_move_local_dest_exists(self, mock_exists, mock_move, builtin_service):
        """Test move when destination already exists."""
        mock_exists.side_effect = [True, True]  # source exists, dest exists

        result = builtin_service.move_local("source.txt", "existing_dest.txt")
        assert "already exists" in result or "exists" in result

    @patch('shutil.copy2')
    @patch('os.makedirs')
    @patch('os.path.isfile')
    @patch('os.path.exists')
    def test_copy_local_file_success(self, mock_exists, mock_isfile, mock_makedirs, 
                                     mock_copy, builtin_service):
        """Test successful file copy."""
        mock_exists.return_value = True
        mock_isfile.return_value = True

        result = builtin_service.copy_local("source.txt", "dest.txt")
        assert "Successfully copied" in result
        mock_copy.assert_called()

    @patch('os.path.exists')
    def test_copy_local_source_not_exists(self, mock_exists, builtin_service):
        """Test copy when source doesn't exist."""
        mock_exists.return_value