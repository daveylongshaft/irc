import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'irc', 'packages', 'csc-service'))

from csc_service.shared.services.module_manager_service import module_manager


class TestModuleManagerService(unittest.TestCase):
    """Test suite for the module_manager service."""

    def setUp(self):
        """Set up test fixtures."""
        # Create mock server instance
        self.mock_server = Mock()
        self.mock_server.data_dir = tempfile.mkdtemp()
        self.mock_server.loaded_modules = {}
        self.mock_server.log = Mock()
        self.mock_server.create_new_version = Mock()
        
        # Create module_manager service instance
        self.service = module_manager(self.mock_server)
        
        # Create temp directories for testing
        self.temp_services_dir = tempfile.mkdtemp()
        self.temp_staging_dir = tempfile.mkdtemp()
        
        # Override service directories
        self.service.services_dir = self.temp_services_dir
        
        # Create parent directory structure for staging_uploads
        services_parent = os.path.dirname(self.temp_services_dir)
        self.staging_dir = os.path.join(services_parent, "staging_uploads")
        os.makedirs(self.staging_dir, exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures."""
        for directory in [self.temp_services_dir, self.temp_staging_dir, 
                         self.mock_server.data_dir, self.staging_dir]:
            if os.path.exists(directory):
                shutil.rmtree(directory)

    def create_test_module(self, name, content, in_staging=False):
        """Helper to create a test service module file."""
        if in_staging:
            target_dir = self.staging_dir
        else:
            target_dir = self.temp_services_dir
        
        os.makedirs(target_dir, exist_ok=True)
        filepath = os.path.join(target_dir, f"{name.lower()}_service.py")
        
        with open(filepath, 'w') as f:
            f.write(content)
        
        return filepath

    def get_valid_module_code(self, class_name):
        """Return valid Python module code with a service class."""
        return f'''from csc_service.server.service import Service

class {class_name}(Service):
    """Test service module."""
    
    def __init__(self, server_instance):
        super().__init__(server_instance)
        self.name = "{class_name.lower()}"
    
    def hello(self):
        return "Hello from {class_name}"
    
    def default(self, *args):
        return "Help for {class_name}"
'''

    # ===== LIST TESTS =====

    def test_list_empty_services_dir(self):
        """Test list when no service modules exist."""
        result = self.service.list()
        
        self.assertIn("No service modules found", result)

    def test_list_single_module(self):
        """Test listing with one service module."""
        self.create_test_module("test_service", self.get_valid_module_code("test_service"))
        
        result = self.service.list()
        
        self.assertIn("Available Service Modules", result)
        self.assertIn("test_service", result)
        self.assertIn("[available]", result)

    def test_list_multiple_modules(self):
        """Test listing with multiple service modules."""
        self.create_test_module("module1", self.get_valid_module_code("module1"))
        self.create_test_module("module2", self.get_valid_module_code("module2"))
        self.create_test_module("module3", self.get_valid_module_code("module3"))
        
        result = self.service.list()
        
        self.assertIn("module1", result)
        self.assertIn("module2", result)
        self.assertIn("module3", result)

    def test_list_shows_loaded_status(self):
        """Test that list shows loaded/available status."""
        # Create a module file
        self.create_test_module("testmod", self.get_valid_module_code("testmod"))
        
        result = self.service.list()
        
        # Should show either [loaded] or [available]
        self.assertTrue("[available]" in result or "[loaded]" in result)

    def test_list_shows_active_instances(self):
        """Test that list shows active module instances when server has loaded_modules."""
        self.mock_server.loaded_modules = {"active1": Mock(), "active2": Mock()}
        self.create_test_module("active1", self.get_valid_module_code("active1"))
        self.create_test_module("active2", self.get_valid_module_code("active2"))
        
        result = self.service.list()
        
        self.assertIn("Active Instances", result)
        self.assertIn("active1", result)
        self.assertIn("active2", result)

    def test_list_ignores_non_service_files(self):
        """Test that list ignores non-service Python files."""
        # Create non-service file
        other_file = os.path.join(self.temp_services_dir, "other.py")
        with open(other_file, 'w') as f:
            f.write("# not a service")
        
        # Create valid service
        self.create_test_module("valid", self.get_valid_module_code("valid"))
        
        result = self.service.list()
        
        self.assertIn("valid", result)
        self.assertNotIn("other", result)

    # ===== READ TESTS =====

    def test_read_existing_module(self):
        """Test reading source of an existing module."""
        code = self.get_valid_module_code("existing")
        self.create_test_module("existing", code)
        
        result = self.service.read("existing")
        
        self.assertIn("existing_service.py", result)
        self.assertIn("class existing", result)
        self.assertIn(code, result)

    def test_read_nonexistent_module(self):
        """Test reading a module that doesn't exist."""
        result = self.service.read("nonexistent")
        
        self.assertIn("Error", result)
        self.assertIn("not found", result)
        self.assertIn("nonexistent_service.py", result)

    def test_read_lowercase_normalization(self):
        """Test that read normalizes module names to lowercase."""
        code = self.get_valid_module_code("testmod")
        self.create_test_module("testmod", code)
        
        # Try to read with different case
        result = self.service.read("TESTMOD")
        
        self.assertIn("testmod_service.py", result)
        self.assertIn(code, result)

    def test_read_returns_full_content(self):
        """Test that read returns the complete file content."""
        code = self.get_valid_module_code("fullread")
        self.create_test_module("fullread", code)
        
        result = self.service.read("fullread")
        
        self.assertIn("fullread_service.py", result)
        self.assertIn("from csc_service.server.service import Service", result)
        self.assertIn("def __init__", result)

    # ===== CREATE TESTS =====

    def test_create_from_base64(self):
        """Test creating a module from base64-encoded content."""
        import base64
        
        code = self.get_valid_module_code("newmod")
        encoded = base64.b64encode(code.encode('utf-8')).decode('ascii')
        
        result = self.service.create("newmod", encoded)
        
        self.assertIn("Module 'newmod' created successfully", result)
        
        # Verify file was created
        filepath = os.path.join(self.temp_services_dir, "newmod_service.py")
        self.assertTrue(os.path.exists(filepath))
        
        with open(filepath, 'r') as f:
            content = f.read()
        self.assertEqual(content, code)

    def test_create_invalid_base64(self):
        """Test creating with invalid base64 content."""
        result = self.service.create("badmod", "not!!valid@@base64@@")
        
        self.assertIn("Error", result)
        self.assertIn("Could not decode", result)

    def test_create_versions_existing_file(self):
        """Test that create versions an existing file before overwriting."""
        code1 = self.get_valid_module_code("versioned")
        self.create_test_module("versioned", code1)
        
        import base64
        code2 = "# New version"
        encoded = base64.b64encode(code2.encode('utf-8')).decode('ascii')
        
        self.service.create("versioned", encoded)
        
        # Verify create_new_version was called
        self.mock_server.create_new_version.assert_called()

    def test_create_lowercase_normalization(self):
        """Test that create normalizes module names to lowercase."""
        import base64
        
        code = self.get_valid_module_code("mymod")
        encoded = base64.b64encode(code.encode('utf-8')).decode('ascii')
        
        self.service.create("MYMOD", encoded)
        
        # File should be created as lowercase
        filepath = os.path.join(self.temp_services_dir, "mymod_service.py")
        self.assertTrue(os.path.exists(filepath))

    def test_create_handles_write_errors(self):
        """Test that create handles file write errors gracefully."""
        import base64
        
        code = self.get_valid_module_code("test")
        encoded = base64.b64encode(code.encode('utf-8')).decode('ascii')
        
        # Make services_dir read-only to cause write error
        os.chmod(self.temp_services_dir, 0o444)
        
        result = self.service.create("test", encoded)
        
        self.assertIn("Error creating module", result)
        
        # Restore permissions for cleanup
        os.chmod(self.temp_services_dir, 0o755)

    # ===== STAGING TESTS =====

    def test_staging_empty(self):
        """Test staging when no files are waiting."""
        result = self.service.staging()
        
        self.assertIn("No service modules in staging", result)

    def test_staging_lists_awaiting_files(self):
        """Test staging lists files waiting for approval."""
        self.create_test_module("pending1", self.get_valid_module_code("pending1"), in_staging=True)
        self.create_test_module("pending2", self.get_valid_module_code("pending2"), in_staging=True)
        
        result = self.service.staging()
        
        self.assertIn("Staged Service Modules", result)
        self.assertIn("pending1_service.py", result)
        self.assertIn("pending2_service.py", result)

    def test_staging_ignores_non_service_files(self):
        """Test that staging ignores non-service files."""
        # Create non-service file in staging
        other_file = os.path.join(self.staging_dir, "other.py")
        with open(other_file, 'w') as f:
            f.write("# not a service")
        
        # Create valid service in staging
        self.create_test_module("valid", self.get_valid_module_code("valid"), in_staging=True)
        
        result = self.service.staging()
        
        self.assertIn("valid_service.py", result)
        self.assertNotIn("other.py", result)

    # ===== VALIDATE SERVICE FILE TESTS =====

    def test_validate_service_file_valid(self):
        """Test validation of a properly formatted service file."""
        code = self.get_valid_module_code("goodmod")
        filepath = os.path.join(self.staging_dir, "goodmod_service.py")
        
        with open(filepath, 'w') as f:
            f.write(code)
        
        is_valid, error = self.service._validate_service_file(Path(filepath), "goodmod")
        
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_validate_service_file_syntax_error(self):
        """Test validation detects Python syntax errors."""
        bad_code = "this is not valid python!!!"
        filepath = os.path.join(self.staging_dir, "badmod_service.py")
        
        with open(filepath, 'w') as f:
            f.write(bad_code)
        
        is_valid, error = self.service._validate_service_file(Path(filepath), "badmod")
        
        self.assertFalse(is_valid)
        self.assertIn("syntax error", error.lower())

    def test_validate_service_file_no_classes(self):
        """Test validation detects files with no class definitions."""
        no_class_code = "def some_function():\n    pass"
        filepath = os.path.join(self.staging_dir, "noclass_service.py")
        
        with open(filepath, 'w') as f:
            f.write(no_class_code)
        
        is_valid, error = self.service._validate_service_file(Path(filepath), "noclass")
        
        self.assertFalse(is_valid)
        self.assertIn("0 classes", error)

    def test_validate_service_file_multiple_classes(self):
        """Test validation detects files with multiple class definitions."""
        multi_class_code = """
class class1:
    pass

class class2:
    pass
"""
        filepath = os.path.join(self.staging_dir, "multiclass_service.py")
        
        with open(filepath, 'w') as f:
            f.write(multi_class_code)
        
        is_valid, error = self.service._validate_service_file(Path(filepath), "multiclass")
        
        self.assertFalse(is_valid)
        self.assertIn("2 classes", error)

    def test_validate_service_file_class_name_mismatch(self):
        """Test validation detects class name mismatch."""
        code = self.get_valid_module_code("wrongname")
        filepath = os.path.join(self.staging_dir, "goodmod_service.py")
        
        with open(filepath, 'w') as f:
            f.write(code)
        
        is_valid, error = self.service._validate_service_file(Path(filepath), "goodmod")
        
        self.assertFalse(is_valid)
        self.assertIn("does not match", error)

    def test_validate_service_file_case_insensitive_match(self):
        """Test that class name matching is case-insensitive."""
        code = self.get_valid_module_code("MyModule")
        filepath = os.path.join(self.staging_dir, "mymodule_service.py")
        
        with open(filepath, 'w') as f:
            f.write(code)
        
        is_valid, error = self.service._validate_service_file(Path(filepath), "mymodule")
        
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_validate_service_file_nonexistent_file(self):
        """Test validation handles nonexistent files."""
        is_valid, error = self.service._validate_service_file(
            Path("/nonexistent/path/file.py"), "test"
        )
        
        self.assertFalse(is_valid)
        self.assertIn("Error reading file", error)

    # ===== APPROVE TESTS =====

    def test_approve_valid_module(self):
        """Test approving a valid staged module."""
        code = self.get_valid_module_code("approve_test")
        self.create_test_module("approve_test", code, in_staging=True)
        
        result = self.service.approve("approve_test")
        
        self.assertIn("approved and activated", result)
        
        # Verify file moved to services directory
        filepath = os.path.join(self.temp_services_dir, "approve_test_service.py")
        self.assertTrue(os.path.exists(filepath))
        
        # Verify not in staging anymore
        staging_path = os.path.join(self.staging_dir, "approve_test_service.py")
        self.assertFalse(os.path.exists(staging_path))

    def test_approve_nonexistent_module(self):
        """Test approving a module that doesn't exist in staging."""
        result = self.service.approve("nonexistent")
        
        self.assertIn("Error", result)
        self.assertIn("not found in staging", result)

    def test_approve_invalid_module(self):
        """Test approving a module with invalid Python code."""
        bad_code = "this is not python!!!"
        self.create_test_module("badcode", bad_code, in_staging=True)
        
        result = self.service.approve("badcode")
        
        self.assertIn("Validation failed", result)
        self.assertIn("syntax error", result.lower())

    def test_approve_wrong_class_name(self):
        """Test approving a module with wrong class name."""
        code = self.get_valid_module_code("wrongclass")
        self.create_test_module("othername", code, in_staging=True)
        
        result = self.service.approve("othername")
        
        self.assertIn("Validation failed", result)
        self.assertIn("does not match", result)

    def test_approve_versions_existing_file(self):
        """Test that approve versions an existing file in services."""
        # Create existing module in services
        old_code = self.get_valid_module_code("tooverwrite")
        self.create_test_module("tooverwrite", old_code, in_staging=False)
        
        # Create new version in staging
        new_code = self.get_valid_module_code("tooverwrite")
        self.create_test_module("tooverwrite", new_code, in_staging=True)
        
        self.service.approve("tooverwrite")
        
        # Verify version was called
        self.mock_server.create_new_version.assert_called()

    def test_approve_clears_cached_instance(self):
        """Test that approve clears cached module instance."""
        code = self.get_valid_module_code("cached")
        self.create_test_module("cached", code, in_staging=True)
        
        # Add to loaded_modules
        self.mock_server.loaded_modules["cached"] = Mock()
        
        self.service.approve("cached")
        
        # Verify instance was removed
        self.assertNotIn("cached", self.mock_server.loaded_modules)

    def test_approve_lowercase_normalization(self):
        """Test that approve normalizes module names to lowercase."""
        code = self.get_valid_module_code("lowermod")
        self.create_test_module("lowermod", code, in_staging=True)
        
        result = self.service.approve("LOWERMOD")
        
        self.assertIn("approved and activated", result)
        
        # File should be in lowercase
        filepath = os.path.join(self.temp_services_dir, "lowermod_service.py")
        self.assertTrue(os.path.exists(filepath))

    # ===== REJECT TESTS =====

    def test_reject_staged_module(self):
        """Test rejecting a staged module."""
        code = self.get_valid_module_code("toreject")
        self.create_test_module("toreject", code, in_staging=True)
        
        result = self.service.reject("toreject")
        
        self.assertIn("Rejected and deleted", result)
        
        # Verify file was deleted from staging
        staging_path = os.path.join(self.staging_dir, "toreject_service.py")
        self.assertFalse(os.path.exists(staging_path))

    def test_reject_nonexistent_module(self):
        """Test rejecting a module that doesn't exist."""
        result = self.service.reject("nonexistent")
        
        self.assertIn("Error", result)
        self.assertIn("not found", result)

    def test_reject_versions_before_deletion(self):
        """Test that reject versions the file before deleting."""
        code = self.get_valid_module_code("tobeverioned")
        self.create_test_module("tobeverioned", code, in_staging=True)
        
        self.service.reject("tobeverioned")
        
        # Verify version was called
        self.mock_server.create_new_version.assert_called()

    def test_reject_lowercase_normalization(self):
        """Test that reject normalizes module names to lowercase."""
        code = self.get_valid_module_code("rejectlow")
        self.create_test_module("rejectlow", code, in_staging=True)
        
        result = self.service.reject("REJECTLOW")
        
        self.assertIn("Rejected and deleted", result)
        
        # Verify file was deleted
        staging_path = os.path.join(self.staging_dir, "rejectlow_service.py")
        self.assertFalse(os.path.exists(staging_path))

    # ===== REHASH TESTS =====

    def test_rehash_no_modules(self):
        """Test rehash with no module names specified."""
        result = self.service.rehash()
        
        self.assertIn("Error", result)
        self.assertIn("No module names specified", result)

    def test_rehash_single_module(self):
        """Test rehashing a single module."""
        with patch('sys.modules', {}):
            result = self.service.rehash("testmod")
        
        self.assertIn("Rehash Results", result)
        self.assertIn("testmod", result)

    def test_rehash_multiple_modules(self):
        """Test rehashing multiple modules."""
        with patch('sys.modules', {}):
            result = self.service.rehash("mod1", "mod2", "mod3")
        
        self.assertIn("Rehash Results", result)
        self.assertIn("mod1", result)
        self.assertIn("mod2", result)
        self.assertIn("mod3", result)

    def test_rehash_removes_cached_instance(self):
        """Test that rehash removes cached instances."""
        self.mock_server.loaded_modules["testmod"] = Mock()
        
        with patch('sys.modules', {}):
            with patch('importlib.import_module'):
                self.service.rehash("testmod")
        
        self.assertNotIn("testmod", self.mock_server.loaded_modules)

    def test_rehash_handles_import_errors(self):
        """Test that rehash handles import errors gracefully."""
        with patch('sys.modules', {}):
            with patch('importlib.import_module', side_effect=ImportError("Module not found")):
                result = self.service.rehash("badmod")
        
        self.assertIn("ERROR", result)
        self.assertIn("badmod", result)

    def test_rehash_lowercase_normalization(self):
        """Test that rehash normalizes module names to lowercase."""
        with patch('sys.modules', {}):
            result = self.service.rehash("TESTMOD")
        
        self.assertIn("testmod", result.lower())

    # ===== DEFAULT (HELP) TESTS =====

    def test_default_shows_all_commands(self):
        """Test that default help shows all available commands."""
        result = self.service.default()
        
        self.assertIn("Module Manager Service Commands", result)
        self.assertIn("list", result)
        self.assertIn("staging", result)
        self.assertIn("approve", result)
        self.assertIn("reject", result)
        self.assertIn("read", result)
        self.assertIn("create", result)
        self.assertIn("rehash", result)

    def test_default_shows_command_syntax(self):
        """Test that default help shows command syntax."""
        result = self.service.default()
        
        self.assertIn("<name>", result)
        self.assertIn("<content_b64>", result)
        self.assertIn("[module2...]", result)

    def test_default_with_arguments(self):
        """Test default with arguments (should still show help)."""
        result = self.service.default("arg1", "arg2")
        
        self.assertIn("Module Manager Service Commands", result)

    # ===== INTEGRATION TESTS =====

    def test_full_workflow_create_stage_approve(self):
        """Test complete workflow: create -> stage -> approve."""
        import base64
        
        # Step 1: Create module from base64
        code = self.get_valid_module_code("workflow")
        encoded = base64.b64encode(code.encode('utf-8')).decode('ascii')
        
        # Step 2: Manually move to staging (simulating upload)
        self.create_test_module("workflow", code, in_staging=True)
        
        # Step 3: Approve from staging
        result = self.service.approve("workflow")
        
        self.assertIn("approved and activated", result)
        
        # Verify final state
        final_path = os.path.join(self.temp_services_dir, "workflow_service.py")
        self.assertTrue(os.path.exists(final_path))

    def test_list_read_workflow(self):
        """Test workflow: list -> read."""
        code = self.get_valid_module_code("toread")
        self.create_test_module("toread", code, in_staging=False)
        
        # List modules
        list_result = self.service.list()
        self.assertIn("toread", list_result)
        
        # Read specific module
        read_result = self.service.read("toread")
        self.assertIn(code, read_result)

    def test_staging_approve_reject_workflow(self):
        """Test workflow with staging, approval, and rejection."""
        code1 = self.get_valid_module_code("approve_me")
        code2 = self.get_valid_module_code("reject_me")
        
        # Create both in staging
        self.create_test_module("approve_me", code1, in_staging=True)
        self.create_test_module("reject_me", code2, in_staging=True)
        
        # Check staging
        staging_result = self.service.staging()
        self.assertIn("approve_me", staging_result)
        self.assertIn("reject_me", staging_result)
        
        # Approve first
        approve_result = self.service.approve("approve_me")
        self.assertIn("approved", approve_result)
        
        # Reject second
        reject_result = self.service.reject("reject_me")
        self.assertIn("Rejected", reject_result)
        
        # Verify final state
        staging_result = self.service.staging()
        self.assertNotIn("approve_me", staging_result)
        self.assertNotIn("reject_me", staging_result)
        
        services_result = self.service.list()
        self.assertIn("approve_me", services_result)


if __name__ == '__main__':
    unittest.main()
