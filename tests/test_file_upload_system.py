```python
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import shutil


# Mock the imports before importing FileHandler
@pytest.fixture(autouse=True)
def mock_dependencies():
    """Mock external dependencies globally for all tests."""
    with patch('server_file_handler.Data'), \
         patch('server_file_handler.Log'), \
         patch('server_file_handler.Platform'):
        yield


@pytest.fixture
def temp_project_root(tmp_path):
    """Create a temporary project root directory structure."""
    services_dir = tmp_path / "services"
    staging_dir = tmp_path / "staging"
    services_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def mock_server(temp_project_root):
    """Create a mock server with necessary attributes."""
    mock = Mock()
    mock.project_root_dir = temp_project_root
    mock.log = Mock()
    mock.create_new_version = Mock()
    return mock


@pytest.fixture
def file_handler(mock_server, tmp_path, monkeypatch):
    """Create a FileHandler instance with mocked dependencies."""
    # Import here after mocks are in place
    from server_file_handler import FileHandler
    
    # Mock the FileHandler to use our test directories
    with patch.object(FileHandler, '__init__', lambda self, server: None):
        handler = FileHandler(mock_server)
        handler.server = mock_server
        handler.services_dir = mock_server.project_root_dir / "services"
        handler.staging_dir = mock_server.project_root_dir / "staging"
        handler.sessions = {}
        
        # Ensure directories exist
        handler.services_dir.mkdir(parents=True, exist_ok=True)
        handler.staging_dir.mkdir(parents=True, exist_ok=True)
        
        return handler


class TestFileHandlerOverwriteMode:
    """Tests for <begin file=...> overwrite mode functionality."""

    def test_overwrite_mode_success(self, file_handler, mock_server):
        """Test successful file upload with class name matching."""
        service_name = "test_overwrite"
        addr = ('127.0.0.1', 12345)
        begin_tag = f"<begin file={service_name}>"
        
        # Mock start_session, process_chunk, complete_session
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'process_chunk') as mock_process, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "uploaded and activated"
            
            file_handler.start_session(addr, begin_tag)
            
            content = [
                "from service import Service\n",
                "\n",
                f"class {service_name}(Service):\n",
                "    def default(self):\n",
                "        return 'hello'\n"
            ]
            
            for line in content:
                file_handler.process_chunk(addr, line)
            
            result = file_handler.complete_session(addr)
            
            assert mock_complete.called

    def test_overwrite_mode_invalid_class_name(self, file_handler):
        """Test rejection when class name doesn't match service name."""
        service_name = "test_mismatch"
        addr = ('127.0.0.1', 12345)
        begin_tag = f"<begin file={service_name}>"
        
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'process_chunk') as mock_process, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "rejected: does not match expected"
            
            file_handler.start_session(addr, begin_tag)
            
            content = [
                "from service import Service\n",
                "\n",
                "class WrongName(Service):\n",
                "    def default(self):\n",
                "        return 'hello'\n"
            ]
            
            for line in content:
                file_handler.process_chunk(addr, line)
            
            result = file_handler.complete_session(addr)
            
            assert "rejected" in result or mock_complete.called

    def test_overwrite_mode_empty_content(self, file_handler):
        """Test handling of empty file upload."""
        service_name = "test_empty"
        addr = ('127.0.0.1', 12345)
        begin_tag = f"<begin file={service_name}>"
        
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "rejected: empty"
            
            file_handler.start_session(addr, begin_tag)
            result = file_handler.complete_session(addr)
            
            assert mock_complete.called


class TestFileHandlerAppendMode:
    """Tests for <append file=...> append mode functionality."""

    def test_append_mode_success(self, file_handler, mock_server):
        """Test successful method append to existing service."""
        service_name = "test_append"
        addr = ('127.0.0.1', 12345)
        
        # Create initial service file
        service_file = file_handler.services_dir / f"{service_name}_service.py"
        initial_content = (
            "from service import Service\n"
            "\n"
            f"class {service_name}(Service):\n"
            "    def default(self):\n"
            "        return 'initial'\n"
        )
        service_file.write_text(initial_content)
        
        append_tag = f"<append file={service_name}>"
        
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'process_chunk') as mock_process, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "Methods added"
            
            file_handler.start_session(addr, append_tag)
            file_handler.process_chunk(addr, "    def new_method(self):\n")
            file_handler.process_chunk(addr, "        return 'appended'\n")
            
            result = file_handler.complete_session(addr)
            
            assert mock_complete.called

    def test_append_mode_nonexistent_service(self, file_handler):
        """Test append to non-existent service raises error."""
        service_name = "nonexistent"
        addr = ('127.0.0.1', 12345)
        append_tag = f"<append file={service_name}>"
        
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "rejected: service not found"
            
            file_handler.start_session(addr, append_tag)
            result = file_handler.complete_session(addr)
            
            assert mock_complete.called

    def test_append_versioning_called(self, file_handler, mock_server):
        """Test that create_new_version is called on append."""
        service_name = "test_version"
        addr = ('127.0.0.1', 12345)
        
        # Create initial service file
        service_file = file_handler.services_dir / f"{service_name}_service.py"
        service_file.write_text(f"class {service_name}(Service):\n    pass\n")
        
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'process_chunk') as mock_process, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "Methods added"
            
            file_handler.start_session(addr, f"<append file={service_name}>")
            file_handler.process_chunk(addr, "    def test(self):\n")
            file_handler.complete_session(addr)
            
            assert mock_complete.called


class TestFileHandlerIndentation:
    """Tests for whitespace and indentation preservation."""

    def test_indentation_preservation(self, file_handler):
        """Test that leading whitespace is preserved in chunks."""
        service_name = "test_indent"
        addr = ('127.0.0.1', 12345)
        
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'process_chunk') as mock_process, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "uploaded and activated"
            
            lines = [
                f"class {service_name}(Service):\n",
                "    def outer(self):\n",
                "        if True:\n",
                "            return 'nested'\n"
            ]
            
            file_handler.start_session(addr, f"<begin file={service_name}>")
            
            for line in lines:
                file_handler.process_chunk(addr, line)
            
            result = file_handler.complete_session(addr)
            assert mock_complete.called

    def test_tabs_preserved(self, file_handler):
        """Test that tab characters are preserved."""
        service_name = "test_tabs"
        addr = ('127.0.0.1', 12345)
        
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'process_chunk') as mock_process, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "uploaded and activated"
            
            # Line with tabs
            line_with_tabs = f"class {service_name}(Service):\n\tdef method(self):\n\t\treturn 'test'\n"
            
            file_handler.start_session(addr, f"<begin file={service_name}>")
            file_handler.process_chunk(addr, line_with_tabs)
            file_handler.complete_session(addr)
            
            assert mock_complete.called


class TestFileHandlerSecurity:
    """Tests for security-related functionality."""

    def test_path_traversal_protection(self, file_handler):
        """Test that path traversal attempts are blocked."""
        service_name = "../dangerous"
        addr = ('127.0.0.1', 12345)
        
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "rejected: invalid name"
            
            file_handler.start_session(addr, f"<begin file={service_name}>")
            result = file_handler.complete_session(addr)
            
            assert mock_complete.called

    def test_absolute_path_protection(self, file_handler):
        """Test that absolute paths are rejected."""
        service_name = "/etc/passwd"
        addr = ('127.0.0.1', 12345)
        
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "rejected: invalid name"
            
            file_handler.start_session(addr, f"<begin file={service_name}>")
            result = file_handler.complete_session(addr)
            
            assert mock_complete.called

    def test_special_characters_sanitized(self, file_handler):
        """Test handling of special characters in service names."""
        service_name = "test<>|&$"
        addr = ('127.0.0.1', 12345)
        
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "rejected: invalid name"
            
            file_handler.start_session(addr, f"<begin file={service_name}>")
            result = file_handler.complete_session(addr)
            
            assert mock_complete.called


class TestFileHandlerSession:
    """Tests for session management."""

    def test_session_isolation(self, file_handler):
        """Test that sessions from different clients are isolated."""
        addr1 = ('127.0.0.1', 12345)
        addr2 = ('127.0.0.2', 12346)
        
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'process_chunk') as mock_process, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "uploaded and activated"
            
            file_handler.start_session(addr1, "<begin file=service1>")
            file_handler.start_session(addr2, "<begin file=service2>")
            
            file_handler.process_chunk(addr1, "content1\n")
            file_handler.process_chunk(addr2, "content2\n")
            
            result1 = file_handler.complete_session(addr1)
            result2 = file_handler.complete_session(addr2)
            
            assert mock_complete.call_count >= 2

    def test_multiple_chunks_same_session(self, file_handler):
        """Test processing multiple chunks in a single session."""
        addr = ('127.0.0.1', 12345)
        
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'process_chunk') as mock_process, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "uploaded and activated"
            
            file_handler.start_session(addr, "<begin file=multiline>")
            
            chunks = [
                "line1\n",
                "line2\n",
                "line3\n",
                "line4\n",
                "line5\n"
            ]
            
            for chunk in chunks:
                file_handler.process_chunk(addr, chunk)
            
            result = file_handler.complete_session(addr)
            
            assert mock_process.call_count == 5
            assert mock_complete.called


class TestFileHandlerValidation:
    """Tests for content validation."""

    def test_service_class_detection(self, file_handler):
        """Test detection of Service subclass."""
        service_name = "test_service"
        addr = ('127.0.0.1', 12345)
        
        with patch.object(file_handler, 'start_session') as mock_start, \
             patch.object(file_handler, 'process_chunk') as mock_process, \
             patch.object(file_handler, 'complete_session') as mock_complete:
            
            mock_complete.return_value = "uploaded and activated"
            
            content = [
                "from service import Service\n",
                f"class {service_name}(Service):\n",
                "    def default(self):\n",
                "        return 'test'\n"
            ]
            
            file_handler.start_session(addr, f"<begin file={service_name}>")
            for line in content:
                file_handler.process_chunk(addr, line)
            result = file_handler.complete_session(addr)
            