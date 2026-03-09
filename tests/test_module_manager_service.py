```python
"""Tests for module_manager_service."""

import os
import sys
import pytest
import shutil
import base64
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from csc_service.shared.services.module_manager_service import module_manager


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directory structure for testing."""
    services_dir = tmp_path / "services"
    staging_dir = tmp_path / "staging_uploads"
    services_dir.mkdir()
    staging_dir.mkdir()
    return {
        "root": tmp_path,
        "services": services_dir,
        "staging": staging_dir,
    }


@pytest.fixture
def mock_server(temp_dirs):
    """Create a mock server instance."""
    server = MagicMock()
    server.project_root_dir = str(temp_dirs["root"])
    server.loaded_modules = {}
    server.create_new_version = MagicMock()
    return server


@pytest.fixture
def module_manager_instance(mock_server, temp_dirs):
    """Create a module_manager instance with mocked dependencies."""
    with patch.object(module_manager, '__init__', lambda x, y: None):
        service = module_manager(mock_server)
        service.server = mock_server
        service.name = "module_manager"
        service.services_dir = str(temp_dirs["services"])
        service.log = MagicMock()
        return service


class TestModuleManagerList:
    """Test cases for list() method."""

    def test_list_no_modules(self, module_manager_instance):
        """Test list when no service modules exist."""
        result = module_manager_instance.list()
        assert "No service modules found." in result

    def test_list_with_available_modules(self, module_manager_instance, temp_dirs):
        """Test list with available service modules."""
        # Create dummy service files
        (temp_dirs["services"] / "dummy_service.py").write_text("pass")
        (temp_dirs["services"] / "test_service.py").write_text("class test: pass")

        result = module_manager_instance.list()
        assert "dummy" in result
        assert "test" in result
        assert "[available]" in result

    def test_list_with_loaded_modules(self, module_manager_instance, temp_dirs):
        """Test list with loaded instances in server."""
        (temp_dirs["services"] / "loaded_service.py").write_text("pass")
        module_manager_instance.server.loaded_modules = {"loaded": MagicMock()}

        result = module_manager_instance.list()
        assert "loaded" in result
        assert "Active Instances" in result

    def test_list_excludes_dunder_files(self, module_manager_instance, temp_dirs):
        """Test that __pycache__ and similar files are excluded."""
        (temp_dirs["services"] / "__init___service.py").write_text("pass")
        (temp_dirs["services"] / "normal_service.py").write_text("pass")

        result = module_manager_instance.list()
        assert "__init__" not in result
        assert "normal" in result


class TestModuleManagerRead:
    """Test cases for read() method."""

    def test_read_existing_module(self, module_manager_instance, temp_dirs):
        """Test reading an existing service module."""
        content = "class dummy: pass\nprint('test')"
        (temp_dirs["services"] / "dummy_service.py").write_text(content)

        result = module_manager_instance.read("dummy")
        assert content in result
        assert "dummy_service.py" in result

    def test_read_nonexistent_module(self, module_manager_instance):
        """Test reading a module that doesn't exist."""
        result = module_manager_instance.read("nonexistent")
        assert "Error: Module 'nonexistent' not found" in result

    def test_read_case_insensitive(self, module_manager_instance, temp_dirs):
        """Test that read is case-insensitive for module names."""
        content = "test content"
        (temp_dirs["services"] / "mymodule_service.py").write_text(content)

        result = module_manager_instance.read("MYMODULE")
        assert content in result

    def test_read_handles_unicode(self, module_manager_instance, temp_dirs):
        """Test reading files with unicode content."""
        content = "# -*- coding: utf-8 -*-\n# Тест unicode\nclass test: pass"
        (temp_dirs["services"] / "unicode_service.py").write_text(content, encoding="utf-8")

        result = module_manager_instance.read("unicode")
        assert "Тест unicode" in result


class TestModuleManagerCreate:
    """Test cases for create() method."""

    def test_create_new_module(self, module_manager_instance, temp_dirs):
        """Test creating a new service module."""
        content = "class new_service: pass"
        content_b64 = base64.b64encode(content.encode()).decode()

        result = module_manager_instance.create("new_svc", content_b64)
        assert "created successfully" in result

        filepath = temp_dirs["services"] / "new_svc_service.py"
        assert filepath.exists()
        assert filepath.read_text() == content

    def test_create_overwrites_existing_with_versioning(self, module_manager_instance, temp_dirs):
        """Test that creating over existing module versions it first."""
        old_content = "class old: pass"
        new_content = "class new: pass"

        (temp_dirs["services"] / "existing_service.py").write_text(old_content)
        new_content_b64 = base64.b64encode(new_content.encode()).decode()

        result = module_manager_instance.create("existing", new_content_b64)
        assert "created successfully" in result
        module_manager_instance.server.create_new_version.assert_called()
        assert (temp_dirs["services"] / "existing_service.py").read_text() == new_content

    def test_create_invalid_base64(self, module_manager_instance):
        """Test creating with invalid base64 content."""
        result = module_manager_instance.create("bad", "not-valid-base64!!!")
        assert "Error: Could not decode base64 content" in result

    def test_create_with_unicode_content(self, module_manager_instance, temp_dirs):
        """Test creating module with unicode content."""
        content = "# -*- coding: utf-8 -*-\nclass тест: pass"
        content_b64 = base64.b64encode(content.encode("utf-8")).decode()

        result = module_manager_instance.create("unicode_mod", content_b64)
        assert "created successfully" in result
        filepath = temp_dirs["services"] / "unicode_mod_service.py"
        assert content in filepath.read_text(encoding="utf-8")

    def test_create_logs_on_versioning_failure(self, module_manager_instance, temp_dirs):
        """Test that versioning failures are logged but don't stop creation."""
        (temp_dirs["services"] / "test_service.py").write_text("old")
        module_manager_instance.server.create_new_version.side_effect = Exception("Version failed")

        content_b64 = base64.b64encode(b"new content").decode()
        result = module_manager_instance.create("test", content_b64)

        assert "created successfully" in result
        assert (temp_dirs["services"] / "test_service.py").read_text() == "new content"
        module_manager_instance.log.assert_called()


class TestModuleManagerRehash:
    """Test cases for rehash() method."""

    def test_rehash_no_args(self, module_manager_instance):
        """Test rehash with no module names."""
        result = module_manager_instance.rehash()
        assert "Error: No module names specified" in result

    @patch('importlib.import_module')
    def test_rehash_new_module(self, mock_import, module_manager_instance):
        """Test rehashing a module that's not yet loaded."""
        result = module_manager_instance.rehash("new_mod")
        assert "new_mod: loaded (new)" in result
        mock_import.assert_called_with("services.new_mod_service")

    @patch('importlib.reload')
    def test_rehash_existing_module(self, mock_reload, module_manager_instance):
        """Test rehashing an already loaded module."""
        # Pre-populate sys.modules
        mock_module = MagicMock()
        sys.modules["services.existing_service"] = mock_module

        try:
            result = module_manager_instance.rehash("existing")
            assert "existing: reloaded" in result
            mock_reload.assert_called_with(mock_module)
        finally:
            del sys.modules["services.existing_service"]

    @patch('importlib.reload')
    def test_rehash_removes_cached_instance(self, mock_reload, module_manager_instance):
        """Test that rehash removes cached instances from server."""
        mock_module = MagicMock()
        sys.modules["services.cached_service"] = mock_module
        module_manager_instance.server.loaded_modules = {"cached": MagicMock()}

        try:
            result = module_manager_instance.rehash("cached")
            assert "cached: reloaded" in result
            assert "cached" not in module_manager_instance.server.loaded_modules
        finally:
            del sys.modules["services.cached_service"]

    @patch('importlib.import_module')
    def test_rehash_multiple_modules(self, mock_import, module_manager_instance):
        """Test rehashing multiple modules at once."""
        result = module_manager_instance.rehash("mod1", "mod2", "mod3")
        assert "mod1: loaded (new)" in result
        assert "mod2: loaded (new)" in result
        assert "mod3: loaded (new)" in result
        assert mock_import.call_count == 3

    @patch('importlib.import_module')
    def test_rehash_handles_import_error(self, mock_import, module_manager_instance):
        """Test rehash handles import errors gracefully."""
        mock_import.side_effect = ImportError("Module not found")
        result = module_manager_instance.rehash("bad_mod")
        assert "bad_mod: ERROR" in result


class TestModuleManagerStaging:
    """Test cases for staging() method."""

    def test_staging_no_directory(self, module_manager_instance, temp_dirs):
        """Test staging when directory doesn't exist."""
        # Use a non-existent parent
        with patch.object(module_manager_instance, 'services_dir', str(temp_dirs["root"] / "nonexistent")):
            result = module_manager_instance.staging()
            assert "No staging directory found" in result

    def test_staging_empty_directory(self, module_manager_instance):
        """Test staging with empty staging directory."""
        result = module_manager_instance.staging()
        assert "No service modules in staging" in result

    def test_staging_with_modules(self, module_manager_instance, temp_dirs):
        """Test staging with service modules waiting for approval."""
        (temp_dirs["staging"] / "staged1_service.py").write_text("pass")
        (temp_dirs["staging"] / "staged2_service.py").write_text("class test: pass")

        # Adjust services_dir to point to services, staging will be parent/staging_uploads
        module_manager_instance.services_dir = str(temp_dirs["services"])

        result = module_manager_instance.staging()
        assert "staged1_service.py" in result
        assert "staged2_service.py" in result
        assert "Staged Service Modules" in result

    def test_staging_ignores_non_service_files(self, module_manager_instance, temp_dirs):
        """Test that staging ignores non-_service.py files."""
        (temp_dirs["staging"] / "random_file.txt").write_text("not a service")
        (temp_dirs["staging"] / "other.py").write_text("pass")
        (temp_dirs["staging"] / "valid_service.py").write_text("pass")

        module_manager_instance.services_dir = str(temp_dirs["services"])

        result = module_manager_instance.staging()
        assert "valid_service.py" in result
        assert "random_file.txt" not in result
        assert "other.py" not in result


class TestModuleManagerValidateServiceFile:
    """Test cases for _validate_service_file() method."""

    def test_validate_valid_service_file(self, module_manager_instance, temp_dirs):
        """Test validating a correct service file."""
        content = """
from service import Service

class myservice(Service):
    def __init__(self, server):
        super().__init__(server)
"""
        filepath = temp_dirs["services"] / "myservice_service.py"
        filepath.write_text(content)

        is_valid, error_msg = module_manager_instance._validate_service_file(filepath, "myservice")
        assert is_valid
        assert error_msg == ""

    def test_validate_wrong_class_name(self, module_manager_instance, temp_dirs):
        """Test validation fails with wrong class name."""
        content = "class wrong_name: pass"
        filepath = temp_dirs["services"] / "test_service.py"
        filepath.write_text(content)

        is_valid, error_msg = module_manager_instance._validate_service_file(filepath, "test")
        assert not is_valid
        assert "does not match expected" in error_msg

    def test_validate_syntax_error(self, module_manager_instance, temp_dirs):
        """Test validation catches syntax errors."""
        content = "class bad syntax here:"
        filepath = temp_dirs["services"] / "bad_service.py"
        filepath.write_text(content)

        is_valid, error_msg = module_manager_instance._validate_service_file(filepath, "bad")
        assert not is_valid
        assert "syntax error" in error_msg.lower()

    def test_validate_file_not_found(self, module_manager_instance, temp_dirs):
        """Test validation handles missing files."""
        filepath = temp_dirs["services"] / "nonexistent_service.py"

        is_valid, error_msg = module_manager_instance._validate_service_file(filepath, "nonexistent")
        assert not is_valid
        assert "Error reading file" in error_msg

    def test_validate_multiple_classes(self, module_manager_instance, temp_dirs):
        """Test validation fails when multiple classes are defined."""
        content = """
class myservice:
    pass

class other:
    pass
"""
        filepath = temp_dirs["services"] / "multi_service.py"
        filepath.write_text(content)

        is_valid, error_msg = module_manager_instance._validate_service_file(filepath, "myservice")
        assert not is_valid


class TestModuleManagerApprove:
    """Test cases for approve() method."""

    def test_approve_valid_module(self, module_manager_instance, temp_dirs):
        """Test approving a valid staged module."""
        content = """
from csc_service.server.service import Service

class valid(Service):
    pass
"""
        staged_file = temp_dirs["staging"] / "valid_service.py"
        staged_file.write_text(content)

        module_manager_instance.services_dir = str(temp_dirs["services"])

        result = module_manager_instance.approve("valid")
        assert "approved and activated" in result
        assert (temp_dirs["services"] / "valid_service.py").exists()
        assert not staged_file.exists()

    def test_approve_nonexistent_module(self, module_manager_instance, temp_dirs):
        """Test approving a module that doesn't exist in staging."""
        module_manager_instance.services_dir = str(temp_dirs["services"])

        result = module_manager_instance.approve("nonex