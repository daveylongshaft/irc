```python
"""Tests for help service."""

import pytest
from unittest.mock import MagicMock, patch
from csc_service.shared.services.help_service import help as HelpService


@pytest.fixture
def mock_server():
    """Create a mock server instance."""
    server = MagicMock()
    server.services = {}
    return server


@pytest.fixture
def help_service(mock_server):
    """Create a HelpService instance with mock server."""
    service = HelpService(mock_server)
    service.server_instance = mock_server
    return service


class TestHelpServiceDefault:
    """Tests for help service default method."""

    def test_list_all_services_no_args(self, help_service, mock_server):
        """Test listing all available services when no arguments provided."""
        mock_server.services = {
            "service1": MagicMock(),
            "service2": MagicMock(),
            "service3": MagicMock(),
        }
        
        result = help_service.default()
        
        assert "Available services:" in result
        assert "service1" in result
        assert "service2" in result
        assert "service3" in result

    def test_list_all_services_empty(self, help_service, mock_server):
        """Test listing services when none are available."""
        mock_server.services = {}
        
        result = help_service.default()
        
        assert "Available services:" in result

    def test_list_methods_for_service(self, help_service, mock_server):
        """Test listing methods for a specific service."""
        mock_service = MagicMock()
        mock_service.method1 = MagicMock()
        mock_service.method2 = MagicMock()
        mock_service._private = MagicMock()
        
        mock_server.services = {"test_service": mock_service}
        
        result = help_service.default("test_service")
        
        assert "Methods for test_service:" in result
        assert "method1" in result
        assert "method2" in result

    def test_list_methods_service_not_found(self, help_service, mock_server):
        """Test listing methods when service does not exist."""
        mock_server.services = {}
        
        result = help_service.default("nonexistent")
        
        assert "Service 'nonexistent' not found." in result

    def test_get_method_docstring(self, help_service, mock_server):
        """Test getting docstring for a specific method."""
        def test_method():
            """This is a test method."""
            pass
        
        mock_service = MagicMock()
        mock_service.my_method = test_method
        
        mock_server.services = {"test_service": mock_service}
        
        result = help_service.default("test_service", "my_method")
        
        assert "Docstring for test_service.my_method:" in result
        assert "This is a test method." in result

    def test_get_method_docstring_no_docstring(self, help_service, mock_server):
        """Test getting docstring when method has no docstring."""
        def test_method():
            pass
        
        mock_service = MagicMock()
        mock_service.my_method = test_method
        
        mock_server.services = {"test_service": mock_service}
        
        result = help_service.default("test_service", "my_method")
        
        assert "No docstring found for test_service.my_method" in result

    def test_get_method_service_not_found(self, help_service, mock_server):
        """Test getting method docstring when service does not exist."""
        mock_server.services = {}
        
        result = help_service.default("nonexistent", "method")
        
        assert "Service 'nonexistent' not found." in result

    def test_get_method_method_not_found(self, help_service, mock_server):
        """Test getting docstring when method does not exist in service."""
        mock_service = MagicMock(spec=['other_method'])
        mock_service.other_method = MagicMock()
        
        mock_server.services = {"test_service": mock_service}
        
        result = help_service.default("test_service", "nonexistent_method")
        
        assert "Method 'nonexistent_method' not found in service 'test_service'." in result

    def test_invalid_number_of_arguments(self, help_service):
        """Test error message for too many arguments."""
        result = help_service.default("service", "method", "extra", "args")
        
        assert "Invalid number of arguments" in result
        assert "help <service> <method>" in result

    def test_method_not_callable(self, help_service, mock_server):
        """Test when service attribute is not callable."""
        mock_service = MagicMock()
        mock_service.not_method = "just a string"
        
        mock_server.services = {"test_service": mock_service}
        
        result = help_service.default("test_service", "not_method")
        
        assert "Method 'not_method' not found in service 'test_service'." in result

    def test_list_methods_excludes_dunder_methods(self, help_service, mock_server):
        """Test that dunder methods are excluded from method listing."""
        mock_service = MagicMock()
        mock_service.public_method = MagicMock()
        mock_service.__str__ = MagicMock()
        mock_service.__repr__ = MagicMock()
        
        mock_server.services = {"test_service": mock_service}
        
        result = help_service.default("test_service")
        
        assert "public_method" in result
        assert "__str__" not in result
        assert "__repr__" not in result

    def test_get_docstring_with_multiline_docstring(self, help_service, mock_server):
        """Test getting multiline docstring."""
        def test_method():
            """
            First line of docstring.
            Second line with more details.
            Third line with even more.
            """
            pass
        
        mock_service = MagicMock()
        mock_service.my_method = test_method
        
        mock_server.services = {"test_service": mock_service}
        
        result = help_service.default("test_service", "my_method")
        
        assert "Docstring for test_service.my_method:" in result
        assert "First line of docstring." in result
        assert "Second line with more details." in result
        assert "Third line with even more." in result

    def test_service_with_multiple_methods(self, help_service, mock_server):
        """Test service with multiple methods."""
        def method_a():
            pass
        
        def method_b():
            """Method B documentation."""
            pass
        
        def method_c():
            """Method C documentation."""
            pass
        
        mock_service = MagicMock()
        mock_service.method_a = method_a
        mock_service.method_b = method_b
        mock_service.method_c = method_c
        
        mock_server.services = {"test_service": mock_service}
        
        # Test listing methods
        result = help_service.default("test_service")
        assert "method_a" in result
        assert "method_b" in result
        assert "method_c" in result
        
        # Test getting specific docstrings
        result_b = help_service.default("test_service", "method_b")
        assert "Method B documentation." in result_b
        
        result_c = help_service.default("test_service", "method_c")
        assert "Method C documentation." in result_c

    def test_single_arg_is_service_lookup(self, help_service, mock_server):
        """Test that single argument is treated as service name."""
        mock_service = MagicMock()
        mock_service.test_method = MagicMock()
        mock_server.services = {"my_service": mock_service}
        
        result = help_service.default("my_service")
        
        assert "Methods for my_service:" in result
        assert "test_method" in result

    def test_two_args_service_and_method(self, help_service, mock_server):
        """Test that two arguments are treated as service and method."""
        def test_method():
            """Test documentation."""
            pass
        
        mock_service = MagicMock()
        mock_service.test_method = test_method
        mock_server.services = {"my_service": mock_service}
        
        result = help_service.default("my_service", "test_method")
        
        assert "Docstring for my_service.test_method:" in result
        assert "Test documentation." in result
```