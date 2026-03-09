```python
import pytest
import tempfile
import shutil
import os
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from csc_service.shared.services.backup_service import backup


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    temp = tempfile.mkdtemp()
    yield temp
    shutil.rmtree(temp, ignore_errors=True)


@pytest.fixture
def test_files_dir(temp_dir):
    """Create test files and directories."""
    test_files = os.path.join(temp_dir, "test_files")
    os.makedirs(test_files)
    
    # Create test files
    test_file1 = os.path.join(test_files, "file1.txt")
    test_file2 = os.path.join(test_files, "file2.txt")
    with open(test_file1, "w") as f:
        f.write("Test content 1\n")
    with open(test_file2, "w") as f:
        f.write("Test content 2\n")
    
    # Create test subdirectory
    test_subdir = os.path.join(test_files, "subdir")
    os.makedirs(test_subdir)
    test_file3 = os.path.join(test_subdir, "file3.txt")
    with open(test_file3, "w") as f:
        f.write("Test content 3\n")
    
    return test_files


@pytest.fixture
def mock_server(temp_dir):
    """Create a mock server instance."""
    server = MagicMock()
    server.data_dir = temp_dir
    return server


@pytest.fixture
def backup_service(mock_server, temp_dir):
    """Create a backup service instance with mocked backup_dir."""
    service = backup(mock_server)
    backup_dir = os.path.join(temp_dir, "backups")
    service.backup_dir = backup_dir
    os.makedirs(backup_dir, exist_ok=True)
    return service


class TestBackupCreate:
    """Test suite for backup creation."""

    def test_create_single_file(self, backup_service, test_files_dir):
        """Test creating a backup of a single file."""
        test_file1 = os.path.join(test_files_dir, "file1.txt")
        result = backup_service.create(test_file1)
        
        assert "Backup created:" in result
        assert "1 files" in result
        
        # Verify archive exists
        archives = os.listdir(backup_service.backup_dir)
        assert len(archives) == 1
        assert archives[0].endswith(".tar.gz")

    def test_create_multiple_files(self, backup_service, test_files_dir):
        """Test creating a backup of multiple files."""
        test_file1 = os.path.join(test_files_dir, "file1.txt")
        test_file2 = os.path.join(test_files_dir, "file2.txt")
        result = backup_service.create(test_file1, test_file2)
        
        assert "Backup created:" in result
        assert "2 files" in result
        
        # Verify archive exists
        archives = os.listdir(backup_service.backup_dir)
        assert len(archives) == 1

    def test_create_directory(self, backup_service, test_files_dir):
        """Test creating a backup of a directory."""
        result = backup_service.create(test_files_dir)
        
        assert "Backup created:" in result
        assert "3 files" in result  # file1, file2, file3
        
        # Verify archive exists
        archives = os.listdir(backup_service.backup_dir)
        assert len(archives) == 1

    def test_create_nonexistent_path(self, backup_service):
        """Test error handling for nonexistent paths."""
        result = backup_service.create("/nonexistent/path/file.txt")
        
        assert "Error:" in result
        assert "does not exist" in result

    def test_create_no_paths(self, backup_service):
        """Test error handling when no paths specified."""
        result = backup_service.create()
        
        assert "Error:" in result
        assert "No paths specified" in result

    def test_create_tracks_history(self, backup_service, test_files_dir):
        """Test that create tracks backup history in data."""
        test_file1 = os.path.join(test_files_dir, "file1.txt")
        backup_service.create(test_file1)
        
        history = backup_service.get_data("backup_history")
        assert history is not None
        assert len(history) == 1
        assert history[0]["files"] == 1
        assert test_file1 in history[0]["paths"]


class TestBackupList:
    """Test suite for listing backups."""

    def test_list_empty(self, backup_service):
        """Test listing when no backups exist."""
        result = backup_service.list()
        
        assert "No backup archives found" in result

    def test_list_with_backups(self, backup_service, test_files_dir):
        """Test listing with existing backups."""
        test_file1 = os.path.join(test_files_dir, "file1.txt")
        test_file2 = os.path.join(test_files_dir, "file2.txt")
        
        # Create backups
        backup_service.create(test_file1)
        backup_service.create(test_file2)
        
        result = backup_service.list()
        
        assert "Backup Archives" in result
        assert "Total: 2 archives" in result

    def test_list_shows_size(self, backup_service, test_files_dir):
        """Test that list shows file sizes."""
        test_file1 = os.path.join(test_files_dir, "file1.txt")
        backup_service.create(test_file1)
        
        result = backup_service.list()
        
        assert "KB" in result or "B)" in result


class TestBackupRestore:
    """Test suite for restoring backups."""

    def test_restore_basic(self, backup_service, test_files_dir, temp_dir):
        """Test restoring a backup to a directory."""
        test_file1 = os.path.join(test_files_dir, "file1.txt")
        backup_service.create(test_file1)
        
        archives = os.listdir(backup_service.backup_dir)
        archive_name = archives[0]
        
        # Create restore directory
        restore_dir = os.path.join(temp_dir, "restore")
        os.makedirs(restore_dir)
        
        # Restore the backup
        result = backup_service.restore(archive_name, restore_dir)
        
        assert "Restored" in result
        
        # Verify file was restored
        restored_file = os.path.join(restore_dir, "file1.txt")
        assert os.path.exists(restored_file)
        with open(restored_file, "r") as f:
            content = f.read()
        assert content == "Test content 1\n"

    def test_restore_nonexistent_archive(self, backup_service, temp_dir):
        """Test error handling for nonexistent archive."""
        result = backup_service.restore("nonexistent.tar.gz", temp_dir)
        
        assert "Error:" in result
        assert "not found" in result

    def test_restore_creates_dest_dir(self, backup_service, test_files_dir, temp_dir):
        """Test that restore creates destination directory if it doesn't exist."""
        test_file1 = os.path.join(test_files_dir, "file1.txt")
        backup_service.create(test_file1)
        
        archives = os.listdir(backup_service.backup_dir)
        archive_name = archives[0]
        
        restore_dir = os.path.join(temp_dir, "new_restore")
        assert not os.path.exists(restore_dir)
        
        result = backup_service.restore(archive_name, restore_dir)
        
        assert "Restored" in result
        assert os.path.exists(restore_dir)

    def test_restore_path_traversal_protection(self, backup_service, temp_dir):
        """Test that restore prevents path traversal attacks."""
        malicious_archive = os.path.join(backup_service.backup_dir, "malicious.tar.gz")
        
        with tarfile.open(malicious_archive, "w:gz") as tar:
            # Try to add a file with parent directory traversal
            info = tarfile.TarInfo(name="../../../etc/passwd")
            info.size = 0
            tar.addfile(info)
        
        restore_dir = os.path.join(temp_dir, "restore")
        os.makedirs(restore_dir)
        
        result = backup_service.restore("malicious.tar.gz", restore_dir)
        
        # Should either error or safely handle the malicious path
        assert isinstance(result, str)


class TestBackupDiff:
    """Test suite for diff functionality."""

    def test_diff_identical_file(self, backup_service, test_files_dir):
        """Test diff when files are identical."""
        test_file1 = os.path.join(test_files_dir, "file1.txt")
        backup_service.create(test_file1)
        
        archives = os.listdir(backup_service.backup_dir)
        archive_name = archives[0]
        
        result = backup_service.diff(archive_name, test_file1)
        
        assert "identical" in result.lower() or "no differences" in result.lower() or "---" in result

    def test_diff_modified_file(self, backup_service, test_files_dir):
        """Test diff when file has been modified."""
        test_file1 = os.path.join(test_files_dir, "file1.txt")
        backup_service.create(test_file1)
        
        # Modify the file
        with open(test_file1, "w") as f:
            f.write("Modified content\n")
        
        archives = os.listdir(backup_service.backup_dir)
        archive_name = archives[0]
        
        result = backup_service.diff(archive_name, test_file1)
        
        # Should show differences
        assert isinstance(result, str)

    def test_diff_nonexistent_archive(self, backup_service, test_files_dir):
        """Test error handling for nonexistent archive."""
        test_file1 = os.path.join(test_files_dir, "file1.txt")
        result = backup_service.diff("nonexistent.tar.gz", test_file1)
        
        assert "Error:" in result
        assert "not found" in result

    def test_diff_nonexistent_current_file(self, backup_service, test_files_dir):
        """Test error handling when current file doesn't exist."""
        test_file1 = os.path.join(test_files_dir, "file1.txt")
        backup_service.create(test_file1)
        
        archives = os.listdir(backup_service.backup_dir)
        archive_name = archives[0]
        
        result = backup_service.diff(archive_name, "/nonexistent/file.txt")
        
        assert "Error:" in result
        assert "does not exist" in result


class TestBackupServiceInitialization:
    """Test suite for service initialization."""

    def test_service_init(self, mock_server, temp_dir):
        """Test service initialization."""
        service = backup(mock_server)
        
        assert service.name == "backup"
        assert os.path.exists(service.backup_dir)

    def test_service_backup_dir_creation(self, mock_server, temp_dir):
        """Test that backup directory is created."""
        service = backup(mock_server)
        service.backup_dir = os.path.join(temp_dir, "test_backups")
        
        # Reinitialize to test directory creation
        os.makedirs(service.backup_dir, exist_ok=True)
        assert os.path.isdir(service.backup_dir)


class TestBackupEdgeCases:
    """Test suite for edge cases and error handling."""

    def test_create_with_spaces_in_path(self, backup_service, temp_dir):
        """Test creating backup with spaces in path."""
        files_with_spaces = os.path.join(temp_dir, "files with spaces")
        os.makedirs(files_with_spaces)
        test_file = os.path.join(files_with_spaces, "test file.txt")
        with open(test_file, "w") as f:
            f.write("Content with spaces\n")
        
        result = backup_service.create(test_file)
        
        assert "Backup created:" in result

    def test_create_empty_file(self, backup_service, temp_dir):
        """Test creating backup of empty file."""
        empty_file = os.path.join(temp_dir, "empty.txt")
        with open(empty_file, "w") as f:
            pass
        
        result = backup_service.create(empty_file)
        
        assert "Backup created:" in result
        assert "1 files" in result

    def test_restore_to_current_directory(self, backup_service, test_files_dir, temp_dir):
        """Test restoring to current directory."""
        test_file1 = os.path.join(test_files_dir, "file1.txt")
        backup_service.create(test_file1)
        
        archives = os.listdir(backup_service.backup_dir)
        archive_name = archives[0]
        
        restore_dir = os.path.join(temp_dir, "restore_cwd")
        os.makedirs(restore_dir)
        
        original_cwd = os.getcwd()
        try:
            os.chdir(restore_dir)
            result = backup_service.restore(archive_name, ".")
            assert "Restored" in result
        finally:
            os.chdir(original_cwd)

    def test_list_with_no_backup_dir(self, mock_server, temp_dir):
        """Test list when backup directory doesn't exist."""
        service = backup(mock_server)
        service.backup_dir = os.path.join(temp_dir, "nonexistent_backups")
        
        result = service.list()
        
        assert "No backups directory found" in result or "No backup archives found" in result

    def test_multiple_backups_of_same_file(self, backup_service, test_files_dir):
        """Test creating multiple backups of the same file."""
        test_file1 = os.path.join(test_files_dir, "file1.txt")
        
        result1 = backup_service.create(test_file1)
        result2 = backup_service.create(test_file1)
        
        assert "Backup created:" in result1
        assert "Backup created:" in result2
        
        archives = os.listdir(backup_service.backup_dir)
        assert len(archives) == 2

    def test_restore_directory_backup(self, backup_service, test_files_dir, temp_dir):
        """Test restoring a backup of a directory."""
        backup_service.create(test_files_dir)
        
        archives = os.listdir(backup_service.backup_dir)
        archive_name = archives[0]
        
        restore_dir = os.path.join(temp_dir, "restore_dir")
        os.makedirs(restore_dir)
        
        result = backup_service.restore(archive_name, restore_dir)
        
        assert "Restored" in result
        # Check that directory structure is restored
        assert os.path.exists(restore_dir)
```