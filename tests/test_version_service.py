```python
"""
Tests for version_service.py

Tests the version service that wraps the server's file versioning system.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from csc_service.shared.services.version_service import version


@pytest.fixture
def mock_server():
    """Create a mock server object."""
    server = Mock()
    server.version_backup_dir = Path("/opt/csc/.versions")
    return server


@pytest.fixture
def version_service(mock_server):
    """Create a version service instance with mocked dependencies."""
    with patch('csc_service.server.service.Service.__init__', lambda self, *a, **kw: None):
        service = version(mock_server)
    service.server = mock_server
    service.name = "version"
    service.log = Mock()
    return service


class TestVersionServiceCreate:
    """Test cases for the create method."""

    def test_create_success(self, version_service, mock_server):
        """Test successful version creation."""
        test_file = "/opt/csc/services/test.py"
        
        with patch('os.path.exists', return_value=True):
            with patch('os.path.abspath', return_value=test_file):
                mock_server.create_new_version.return_value = 5
                
                result = version_service.create("services/test.py")
                
                assert "Created version 5" in result
                assert "test.py" in result
                mock_server.create_new_version.assert_called_once_with(test_file)

    def test_create_file_not_exists(self, version_service, mock_server):
        """Test create when file doesn't exist."""
        with patch('os.path.exists', return_value=False):
            with patch('os.path.abspath', return_value="/opt/csc/nonexistent.py"):
                result = version_service.create("nonexistent.py")
                
                assert "Error" in result
                assert "does not exist" in result
                mock_server.create_new_version.assert_not_called()

    def test_create_failure(self, version_service, mock_server):
        """Test create when server fails to create version."""
        test_file = "/opt/csc/services/test.py"
        
        with patch('os.path.exists', return_value=True):
            with patch('os.path.abspath', return_value=test_file):
                mock_server.create_new_version.return_value = None
                
                result = version_service.create("services/test.py")
                
                assert "Error" in result
                assert "Failed to create version" in result

    def test_create_logs_action(self, version_service, mock_server):
        """Test that create logs the action."""
        test_file = "/opt/csc/services/test.py"
        
        with patch('os.path.exists', return_value=True):
            with patch('os.path.abspath', return_value=test_file):
                mock_server.create_new_version.return_value = 1
                
                version_service.create("services/test.py")
                
                version_service.log.assert_called()


class TestVersionServiceRestore:
    """Test cases for the restore method."""

    def test_restore_success(self, version_service, mock_server):
        """Test successful version restore."""
        test_file = "/opt/csc/services/test.py"
        
        with patch('os.path.exists', return_value=True):
            with patch('os.path.abspath', return_value=test_file):
                mock_server.restore_version.return_value = 3
                
                result = version_service.restore("services/test.py", "3")
                
                assert "Restored" in result
                assert "version 3" in result
                mock_server.restore_version.assert_called_once_with(test_file, "3")

    def test_restore_default_latest(self, version_service, mock_server):
        """Test restore defaults to 'latest' version."""
        test_file = "/opt/csc/services/test.py"
        
        with patch('os.path.exists', return_value=True):
            with patch('os.path.abspath', return_value=test_file):
                mock_server.restore_version.return_value = 5
                
                result = version_service.restore("services/test.py")
                
                assert "Restored" in result
                assert "version 5" in result
                mock_server.restore_version.assert_called_once_with(test_file, "latest")

    def test_restore_file_not_exists_latest(self, version_service, mock_server):
        """Test restore when file doesn't exist and version is 'latest'."""
        with patch('os.path.exists', return_value=False):
            with patch('os.path.abspath', return_value="/opt/csc/nonexistent.py"):
                result = version_service.restore("nonexistent.py")
                
                assert "Error" in result
                assert "does not exist" in result
                mock_server.restore_version.assert_not_called()

    def test_restore_failure(self, version_service, mock_server):
        """Test restore when server fails."""
        test_file = "/opt/csc/services/test.py"
        
        with patch('os.path.exists', return_value=True):
            with patch('os.path.abspath', return_value=test_file):
                mock_server.restore_version.return_value = None
                
                result = version_service.restore("services/test.py", "2")
                
                assert "Error" in result
                assert "Failed to restore" in result

    def test_restore_file_not_exists_specific_version(self, version_service, mock_server):
        """Test restore with specific version when file doesn't exist."""
        test_file = "/opt/csc/services/test.py"
        
        with patch('os.path.exists', return_value=False):
            with patch('os.path.abspath', return_value=test_file):
                mock_server.restore_version.return_value = 2
                
                # Should not check file existence if version is not "latest"
                result = version_service.restore("services/test.py", "2")
                
                # Should attempt to restore
                mock_server.restore_version.assert_called_once_with(test_file, "2")

    def test_restore_logs_action(self, version_service, mock_server):
        """Test that restore logs the action."""
        test_file = "/opt/csc/services/test.py"
        
        with patch('os.path.exists', return_value=True):
            with patch('os.path.abspath', return_value=test_file):
                mock_server.restore_version.return_value = 1
                
                version_service.restore("services/test.py", "1")
                
                version_service.log.assert_called()


class TestVersionServiceHistory:
    """Test cases for the history method."""

    def test_history_success(self, version_service, mock_server):
        """Test successful version history retrieval."""
        test_file = "/opt/csc/services/test.py"
        backup_dir = Path("/opt/csc/.versions/services/test.py")
        
        version_info = {
            "latest": 3,
            "active": 2,
            "history": {
                "1": "/opt/csc/.versions/services/test.py/test.py.v1",
                "2": "/opt/csc/.versions/services/test.py/test.py.v2",
                "3": "/opt/csc/.versions/services/test.py/test.py.v3"
            }
        }
        
        with patch('os.path.abspath', return_value=test_file):
            mock_server.get_version_dir_for_file.return_value = backup_dir
            mock_server._get_version_info.return_value = version_info
            
            result = version_service.history("services/test.py")
            
            assert "Version History" in result
            assert "Latest: v3" in result
            assert "Active: v2" in result
            assert "v1:" in result
            assert "v2:" in result
            assert "v3:" in result
            assert "<-- active" in result

    def test_history_no_history(self, version_service, mock_server):
        """Test history when no versions exist."""
        test_file = "/opt/csc/services/test.py"
        backup_dir = Path("/opt/csc/.versions/services/test.py")
        
        version_info = {
            "latest": 0,
            "active": 0,
            "history": {}
        }
        
        with patch('os.path.abspath', return_value=test_file):
            mock_server.get_version_dir_for_file.return_value = backup_dir
            mock_server._get_version_info.return_value = version_info
            
            result = version_service.history("services/test.py")
            
            assert "No version history found" in result

    def test_history_exception(self, version_service, mock_server):
        """Test history when server raises exception."""
        test_file = "/opt/csc/services/test.py"
        
        with patch('os.path.abspath', return_value=test_file):
            mock_server.get_version_dir_for_file.side_effect = Exception("Read error")
            
            result = version_service.history("services/test.py")
            
            assert "Error" in result
            assert "Could not read version info" in result

    def test_history_sorts_versions(self, version_service, mock_server):
        """Test that history sorts versions numerically."""
        test_file = "/opt/csc/services/test.py"
        backup_dir = Path("/opt/csc/.versions/services/test.py")
        
        version_info = {
            "latest": 10,
            "active": 5,
            "history": {
                "10": "/opt/csc/.versions/services/test.py/test.py.v10",
                "1": "/opt/csc/.versions/services/test.py/test.py.v1",
                "5": "/opt/csc/.versions/services/test.py/test.py.v5",
                "2": "/opt/csc/.versions/services/test.py/test.py.v2"
            }
        }
        
        with patch('os.path.abspath', return_value=test_file):
            mock_server.get_version_dir_for_file.return_value = backup_dir
            mock_server._get_version_info.return_value = version_info
            
            result = version_service.history("services/test.py")
            
            # Check that versions appear in numerical order
            v1_pos = result.find("v1:")
            v2_pos = result.find("v2:")
            v5_pos = result.find("v5:")
            v10_pos = result.find("v10:")
            
            assert v1_pos < v2_pos < v5_pos < v10_pos

    def test_history_marks_active_version(self, version_service, mock_server):
        """Test that active version is marked."""
        test_file = "/opt/csc/services/test.py"
        backup_dir = Path("/opt/csc/.versions/services/test.py")
        
        version_info = {
            "latest": 3,
            "active": 2,
            "history": {
                "1": "/opt/csc/.versions/services/test.py/test.py.v1",
                "2": "/opt/csc/.versions/services/test.py/test.py.v2",
                "3": "/opt/csc/.versions/services/test.py/test.py.v3"
            }
        }
        
        with patch('os.path.abspath', return_value=test_file):
            mock_server.get_version_dir_for_file.return_value = backup_dir
            mock_server._get_version_info.return_value = version_info
            
            result = version_service.history("services/test.py")
            
            # v2 should be marked as active, others should not
            lines = result.split('\n')
            for line in lines:
                if 'v2:' in line:
                    assert '<-- active' in line
                elif 'v1:' in line or 'v3:' in line:
                    assert '<-- active' not in line

    def test_history_logs_action(self, version_service, mock_server):
        """Test that history logs the action."""
        test_file = "/opt/csc/services/test.py"
        backup_dir = Path("/opt/csc/.versions/services/test.py")
        
        version_info = {
            "latest": 0,
            "active": 0,
            "history": {}
        }
        
        with patch('os.path.abspath', return_value=test_file):
            mock_server.get_version_dir_for_file.return_value = backup_dir
            mock_server._get_version_info.return_value = version_info
            
            version_service.history("services/test.py")
            
            version_service.log.assert_called()


class TestVersionServiceList:
    """Test cases for the list method."""

    def test_list_success(self, version_service, mock_server):
        """Test successful list of versioned files."""
        mock_server.version_backup_dir = Path("/opt/csc/.versions")
        
        with patch('os.walk') as mock_walk:
            mock_walk.return_value = [
                ("/opt/csc/.versions/services/test.py", [], ["versions.json"]),
                ("/opt/csc/.versions/config/settings.json", [], ["versions.json"]),
                ("/opt/csc/.versions/data/cache.db", [], ["versions.json"])
            ]
            
            result = version_service.list()
            
            assert "Versioned Files" in result
            assert "services/test.py" in result or "services" in result
            assert "Total: 3 files" in result

    def test_list_no_versions_directory(self, version_service, mock_server):
        """Test list when version directory doesn't exist."""
        mock_server.version_backup_dir = Path("/nonexistent/.versions")
        
        with patch.object(Path, 'exists', return_value=False):
            result = version_service.list()
            
            assert "No versioned files found" in result

    def test_list_empty_directory(self, version_service, mock_server):
        """Test list when version directory is empty."""
        mock_server.version_backup_dir = Path("/opt/csc/.versions")
        
        with patch('os.walk') as mock_walk:
            mock_walk.return_value = []
            
            result = version_service.list()
            
            assert "No versioned files found" in result

    def test_list_sorts_files(self, version_service, mock_server):
        """Test that list sorts files alphabetically."""
        mock_server.version_backup_dir = Path("/opt/csc/.versions")
        
        with patch('os.walk') as mock_walk:
            mock_walk.return_value = [
                ("/opt/csc/.versions/z_file", [], ["versions.json"]),
                ("/opt/csc/.versions/a_file", [], ["versions.json"]),
                ("/opt/csc/.versions/m_file", [], ["versions.json"])
            ]
            
            result = version_service.list()
            
            # Check that files appear in alphabetical order
            a_pos = result.find("a_file")
            m_pos = result.find("m_file")
            z_pos = result.find("z_file")
            
            assert a_pos < m_pos < z_pos

    def test_list_ignores_dirs_without_versions_json(self, version_service, mock_server):
        """Test that list only counts directories with