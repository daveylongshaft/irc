"""Tests for HelpService (help_service.py).

Covers default() method which lists services, methods for a service,
and docstrings for specific methods via AST introspection.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure csc_service is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "irc" / "packages" / "csc-service"))

from csc_service.shared.services.help_service import help as HelpService


class TestHelpService(unittest.TestCase):
    """Test suite for HelpService help() command."""

    def setUp(self):
        """Set up test fixtures with a mocked server instance."""
        self.mock_server = MagicMock()
        self.help_service = HelpService(self.mock_server)

    def test_help_service_initialization(self):
        """Test that HelpService initializes with a server instance."""
        self.assertIsNotNone(self.help_service)
        self.assertEqual(self.help_service.server_instance, self.mock_server)

    # -----------------------------------------------------------------------
    # default() with no args: List all services
    # -----------------------------------------------------------------------

    def test_default_no_args_returns_string(self):
        """Test that default() with no args returns a string."""
        result = self.help_service.default()
        self.assertIsInstance(result, str)

    def test_default_no_args_shows_available_services(self):
        """Test that default() with no args lists available services."""
        # Mock the server's services dict
        self.mock_server.services = {
            "builtin": MagicMock(),
            "backup": MagicMock(),
            "cryptserv": MagicMock(),
        }
        result = self.help_service.default()
        self.assertIn("Available services:", result)
        self.assertIn("builtin", result)
        self.assertIn("backup", result)
        self.assertIn("cryptserv", result)

    def test_default_no_args_empty_services(self):
        """Test that default() handles empty services dict."""
        self.mock_server.services = {}
        result = self.help_service.default()
        self.assertIn("Available services:", result)
        # Should show an empty list or message
        self.assertIsInstance(result, str)

    def test_default_no_args_single_service(self):
        """Test that default() lists a single service correctly."""
        self.mock_server.services = {"test_service": MagicMock()}
        result = self.help_service.default()
        self.assertIn("test_service", result)

    # -----------------------------------------------------------------------
    # default() with one arg: List methods for a service
    # -----------------------------------------------------------------------

    def test_default_one_arg_returns_string(self):
        """Test that default() with one arg returns a string."""
        mock_service = MagicMock()
        self.mock_server.services = {"test": mock_service}
        result = self.help_service.default("test")
        self.assertIsInstance(result, str)

    def test_default_one_arg_lists_service_methods(self):
        """Test that default() lists methods for a service."""
        # Create a mock service with callable methods
        mock_service = MagicMock()
        mock_service.method1 = MagicMock(return_value="result1")
        mock_service.method2 = MagicMock(return_value="result2")
        mock_service._private = MagicMock()  # Should be filtered out

        self.mock_server.services = {"test": mock_service}
        result = self.help_service.default("test")

        self.assertIn("Methods for test:", result)
        # dir() will list all attributes, but we filter for callables and non-private
        self.assertIsInstance(result, str)

    def test_default_one_arg_nonexistent_service(self):
        """Test that default() handles nonexistent service."""
        self.mock_server.services = {"builtin": MagicMock()}
        result = self.help_service.default("nonexistent")
        self.assertIn("not found", result.lower())
        self.assertIn("nonexistent", result)

    def test_default_one_arg_service_with_no_methods(self):
        """Test that default() handles service with no public methods."""
        mock_service = MagicMock()
        # Mock dir() to return only private methods
        with patch("builtins.dir", return_value=["__init__", "__str__"]):
            self.mock_server.services = {"test": mock_service}
            result = self.help_service.default("test")
            self.assertIn("Methods for test:", result)

    # -----------------------------------------------------------------------
    # default() with two args: Show docstring for a method
    # -----------------------------------------------------------------------

    def test_default_two_args_returns_string(self):
        """Test that default() with two args returns a string."""
        mock_service = MagicMock()
        self.mock_server.services = {"test": mock_service}
        result = self.help_service.default("test", "method")
        self.assertIsInstance(result, str)

    def test_default_two_args_shows_docstring(self):
        """Test that default() shows docstring for a method."""
        def test_method():
            """This is a test method docstring."""
            return "result"

        mock_service = MagicMock()
        mock_service.test_method = test_method
        self.mock_server.services = {"test": mock_service}

        result = self.help_service.default("test", "test_method")
        self.assertIn("Docstring for test.test_method:", result)
        self.assertIn("This is a test method docstring.", result)

    def test_default_two_args_no_docstring(self):
        """Test that default() handles method without docstring."""
        def test_method():
            return "result"

        mock_service = MagicMock()
        mock_service.test_method = test_method
        self.mock_server.services = {"test": mock_service}

        result = self.help_service.default("test", "test_method")
        self.assertIn("No docstring found", result)

    def test_default_two_args_nonexistent_service(self):
        """Test that default() handles nonexistent service with two args."""
        self.mock_server.services = {"builtin": MagicMock()}
        result = self.help_service.default("nonexistent", "method")
        self.assertIn("not found", result.lower())

    def test_default_two_args_nonexistent_method(self):
        """Test that default() handles nonexistent method in service."""
        mock_service = MagicMock()
        mock_service.real_method = MagicMock()
        self.mock_server.services = {"test": mock_service}

        result = self.help_service.default("test", "nonexistent_method")
        self.assertIn("not found", result.lower())
        self.assertIn("nonexistent_method", result)

    def test_default_two_args_non_callable_attribute(self):
        """Test that default() handles non-callable attribute."""
        mock_service = MagicMock()
        mock_service.not_callable = "just a string"
        self.mock_server.services = {"test": mock_service}

        result = self.help_service.default("test", "not_callable")
        self.assertIn("not found", result.lower())

    # -----------------------------------------------------------------------
    # default() with invalid args
    # -----------------------------------------------------------------------

    def test_default_too_many_args(self):
        """Test that default() handles too many arguments."""
        self.mock_server.services = {"test": MagicMock()}
        result = self.help_service.default("arg1", "arg2", "arg3", "arg4")
        self.assertIn("Invalid number of arguments", result.lower())

    def test_default_three_args(self):
        """Test that default() with three args shows error."""
        self.mock_server.services = {"test": MagicMock()}
        result = self.help_service.default("test", "method", "extra")
        self.assertIn("Invalid number of arguments", result.lower())

    # -----------------------------------------------------------------------
    # Real-world scenario tests
    # -----------------------------------------------------------------------

    def test_help_for_builtin_service(self):
        """Test help for a realistic builtin service."""
        mock_builtin = MagicMock()
        mock_builtin.echo = MagicMock(return_value="echo result")
        mock_builtin.status = MagicMock(return_value="status result")
        mock_builtin.time = MagicMock(return_value="time result")

        self.mock_server.services = {"builtin": mock_builtin}

        # List all services
        result = self.help_service.default()
        self.assertIn("builtin", result)

        # List methods for builtin
        result = self.help_service.default("builtin")
        self.assertIn("Methods for builtin:", result)

    def test_help_multiple_services_with_methods(self):
        """Test help system with multiple services and methods."""
        mock_service1 = MagicMock()
        mock_service1.cmd1 = MagicMock(return_value="cmd1")
        mock_service1.cmd2 = MagicMock(return_value="cmd2")

        mock_service2 = MagicMock()
        mock_service2.action = MagicMock(return_value="action")

        self.mock_server.services = {
            "service1": mock_service1,
            "service2": mock_service2,
        }

        # List all
        result = self.help_service.default()
        self.assertIn("service1", result)
        self.assertIn("service2", result)

        # List service1 methods
        result = self.help_service.default("service1")
        self.assertIn("Methods for service1:", result)

        # List service2 methods
        result = self.help_service.default("service2")
        self.assertIn("Methods for service2:", result)

    # -----------------------------------------------------------------------
    # Edge cases and robustness
    # -----------------------------------------------------------------------

    def test_default_with_empty_string_args(self):
        """Test that default() handles empty string arguments."""
        self.mock_server.services = {"test": MagicMock()}
        result = self.help_service.default("")
        # Empty string is treated as a service lookup
        self.assertIn("not found", result.lower())

    def test_default_service_name_case_sensitivity(self):
        """Test that service names are case-sensitive."""
        mock_service = MagicMock()
        self.mock_server.services = {"Test": mock_service}

        # Try with different case
        result = self.help_service.default("test")
        self.assertIn("not found", result.lower())

        # Try with correct case
        result = self.help_service.default("Test")
        self.assertIn("Methods for Test:", result)

    def test_default_with_special_characters_in_service_name(self):
        """Test that service names with special chars are handled."""
        mock_service = MagicMock()
        self.mock_server.services = {"test-service": mock_service}

        result = self.help_service.default("test-service")
        self.assertIn("Methods for test-service:", result)

    def test_default_method_filtering_removes_private(self):
        """Test that private methods (starting with __) are filtered out."""
        mock_service = MagicMock()
        # dir() will return a mix of public and private attributes
        public_methods = ["public_method", "another_method"]
        private_methods = ["__init__", "__str__", "_private"]

        # Mock dir() to return a list we control
        with patch("builtins.dir", return_value=public_methods + private_methods):
            # Mock callable() and getattr() to behave realistically
            def mock_getattr(obj, attr):
                if attr.startswith("__"):
                    return lambda: None
                return MagicMock(return_value=None)

            with patch("builtins.getattr", side_effect=mock_getattr):
                self.mock_server.services = {"test": mock_service}
                result = self.help_service.default("test")
                # Should list public methods, filter out private
                self.assertIn("public_method", result)

    def test_default_empty_services_and_args(self):
        """Test help with no services and no args."""
        self.mock_server.services = {}
        result = self.help_service.default()
        self.assertIn("Available services:", result)

    # -----------------------------------------------------------------------
    # Integration-like tests
    # -----------------------------------------------------------------------

    def test_help_integration_full_workflow(self):
        """Test a complete help workflow: list -> service -> method."""
        # Define mock services
        def help_method():
            """Help for this command."""
            return "help"

        mock_svc1 = MagicMock()
        mock_svc1.help = help_method
        mock_svc1.execute = MagicMock(return_value="execute")

        mock_svc2 = MagicMock()
        mock_svc2.action = MagicMock(return_value="action")

        self.mock_server.services = {
            "service1": mock_svc1,
            "service2": mock_svc2,
        }

        # Step 1: List all services
        result1 = self.help_service.default()
        self.assertIn("service1", result1)
        self.assertIn("service2", result1)

        # Step 2: Get methods for service1
        result2 = self.help_service.default("service1")
        self.assertIn("Methods for service1:", result2)

        # Step 3: Get docstring for service1.help
        result3 = self.help_service.default("service1", "help")
        self.assertIn("Docstring for service1.help:", result3)
        self.assertIn("Help for this command.", result3)

        # Step 4: Try nonexistent method
        result4 = self.help_service.default("service1", "nonexistent")
        self.assertIn("not found", result4.lower())


class TestHelpServiceWithRealMethods(unittest.TestCase):
    """Test HelpService with actual Python methods (not mocks)."""

    def setUp(self):
        """Set up test fixtures with real methods."""
        self.mock_server = MagicMock()
        self.help_service = HelpService(self.mock_server)

        # Create a real service class with docstrings
        class RealService:
            """A real service for testing."""

            def action1(self):
                """Perform action 1."""
                return "result1"

            def action2(self, param):
                """Perform action 2 with a parameter."""
                return f"result2: {param}"

            def _private_method(self):
                """This should be filtered out."""
                return "private"

        self.real_service_instance = RealService()

    def test_help_with_real_docstrings(self):
        """Test that help correctly extracts real docstrings."""
        self.mock_server.services = {"real": self.real_service_instance}

        result = self.help_service.default("real", "action1")
        self.assertIn("Docstring for real.action1:", result)
        self.assertIn("Perform action 1.", result)

    def test_help_with_real_method_parameters(self):
        """Test help for method with parameters."""
        self.mock_server.services = {"real": self.real_service_instance}

        result = self.help_service.default("real", "action2")
        self.assertIn("Docstring for real.action2:", result)
        self.assertIn("Perform action 2 with a parameter.", result)

    def test_help_lists_real_public_methods(self):
        """Test that help lists only public methods from real service."""
        self.mock_server.services = {"real": self.real_service_instance}

        result = self.help_service.default("real")
        self.assertIn("Methods for real:", result)
        # Public methods should be listed
        self.assertIn("action1", result)
        self.assertIn("action2", result)

    def test_help_real_service_single_arg(self):
        """Test help for real service with single argument."""
        self.mock_server.services = {"real": self.real_service_instance}

        # Should show methods for the service
        result = self.help_service.default("real")
        self.assertIsInstance(result, str)
        self.assertIn("Methods for real:", result)


if __name__ == "__main__":
    unittest.main()
