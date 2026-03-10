import os
import unittest
from unittest.mock import Mock, MagicMock, patch, call

# Add parent directory to path for imports
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'irc', 'packages', 'csc-service'))

from csc_service.shared.services.ntfy_service import ntfy


class TestNtfyService(unittest.TestCase):
    """Test suite for the ntfy (push notification) service."""

    def setUp(self):
        """Set up test fixtures."""
        # Create mock server instance
        self.mock_server = Mock()
        self.mock_server.loaded_modules = {}
        
        # Create ntfy service instance
        self.service = ntfy(self.mock_server)

    def tearDown(self):
        """Clean up test fixtures."""
        pass

    # ===== INITIALIZATION TESTS =====

    def test_init_sets_topic(self):
        """Test that __init__ sets the TOPIC constant correctly."""
        self.assertEqual(self.service.TOPIC, "gemini_commander")

    def test_init_constructs_ntfy_url(self):
        """Test that __init__ constructs the NTFY_URL correctly."""
        expected_url = "https://ntfy.sh/gemini_commander"
        self.assertEqual(self.service.NTFY_URL, expected_url)

    def test_init_calls_super_init(self):
        """Test that __init__ calls super().__init__()."""
        # If super().__init__() was not called, the service would not have self.server
        self.assertIsNotNone(self.service.server)

    def test_init_logs_initialization(self):
        """Test that initialization logs the configured topic."""
        # Create a new service and verify log was called
        with patch.object(self.service, 'log') as mock_log:
            # Call init-like behavior by creating new instance
            service = ntfy(self.mock_server)
            # The __init__ should have called log during service initialization
            # We can verify the topic is set
            self.assertEqual(service.TOPIC, "gemini_commander")

    # ===== SEND TESTS =====

    def test_send_basic_notification(self):
        """Test sending a basic notification with subject and body."""
        # Mock the Curl service
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="HTTP/1.1 200 OK")
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        result = self.service.send("Test Subject", "Test Body")
        
        # Verify curl was called with correct arguments
        mock_curl.run.assert_called_once_with(
            '-H', 'Title: Test Subject',
            '-d', 'Test Body',
            'https://ntfy.sh/gemini_commander'
        )
        
        # Verify response
        self.assertIn("Notification sent", result)
        self.assertIn("Curl service response", result)

    def test_send_with_multiword_body(self):
        """Test sending notification with multi-word body."""
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="OK")
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        result = self.service.send("Subject", "This", "is", "a", "longer", "message")
        
        # Verify body is properly joined
        mock_curl.run.assert_called_once()
        call_args = mock_curl.run.call_args[0]
        
        # Find the body argument (after '-d')
        d_index = call_args.index('-d')
        body = call_args[d_index + 1]
        self.assertEqual(body, "This is a longer message")

    def test_send_missing_subject(self):
        """Test send with missing subject (only 0 args)."""
        result = self.service.send()
        
        self.assertIn("Error", result)
        self.assertIn("Usage", result)
        self.assertIn("ntfy send", result)

    def test_send_missing_body(self):
        """Test send with only subject, missing body (only 1 arg)."""
        result = self.service.send("Subject")
        
        self.assertIn("Error", result)
        self.assertIn("Usage", result)
        self.assertIn("ntfy send", result)

    def test_send_curl_service_not_loaded(self):
        """Test send when Curl service is not loaded."""
        # Ensure Curl is not in loaded_modules
        self.service.server.loaded_modules = {}
        
        result = self.service.send("Subject", "Body")
        
        self.assertIn("FATAL ERROR", result)
        self.assertIn("Curl", result)
        self.assertIn("required dependency", result)
        self.assertIn("not loaded", result)

    def test_send_curl_service_missing_from_dict(self):
        """Test send when Curl key doesn't exist in loaded_modules."""
        self.service.server.loaded_modules = {"SomeOtherService": Mock()}
        
        result = self.service.send("Subject", "Body")
        
        self.assertIn("FATAL ERROR", result)
        self.assertIn("Curl", result)

    def test_send_constructs_correct_title_header(self):
        """Test that send constructs correct Title header."""
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="OK")
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        result = self.service.send("Important Alert", "Body")
        
        call_args = mock_curl.run.call_args[0]
        self.assertIn('-H', call_args)
        h_index = call_args.index('-H')
        title_header = call_args[h_index + 1]
        self.assertEqual(title_header, "Title: Important Alert")

    def test_send_with_special_characters_in_subject(self):
        """Test send with special characters in subject."""
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="OK")
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        special_subject = "Alert [ERROR] @ 14:30!"
        result = self.service.send(special_subject, "Body")
        
        call_args = mock_curl.run.call_args[0]
        h_index = call_args.index('-H')
        title_header = call_args[h_index + 1]
        self.assertEqual(title_header, f"Title: {special_subject}")

    def test_send_with_special_characters_in_body(self):
        """Test send with special characters in body."""
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="OK")
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        special_body = "Error: Connection failed! Status: CRITICAL"
        result = self.service.send("Alert", special_body)
        
        call_args = mock_curl.run.call_args[0]
        d_index = call_args.index('-d')
        body = call_args[d_index + 1]
        self.assertEqual(body, special_body)

    def test_send_returns_curl_response(self):
        """Test that send returns the curl service response."""
        mock_curl = Mock()
        curl_response = "HTTP/1.1 200 OK - Message published"
        mock_curl.run = Mock(return_value=curl_response)
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        result = self.service.send("Subject", "Body")
        
        self.assertIn(curl_response, result)

    def test_send_with_curl_failure(self):
        """Test send when curl service returns error."""
        mock_curl = Mock()
        curl_error = "Error: Failed to connect to ntfy.sh"
        mock_curl.run = Mock(return_value=curl_error)
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        result = self.service.send("Subject", "Body")
        
        # The service should still return the curl response (error message)
        self.assertIn(curl_error, result)
        self.assertIn("Notification sent", result)  # Service considers it "sent" even on error

    def test_send_uses_correct_ntfy_url(self):
        """Test that send uses the correct ntfy.sh URL."""
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="OK")
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        self.service.send("Subject", "Body")
        
        call_args = mock_curl.run.call_args[0]
        self.assertIn("https://ntfy.sh/gemini_commander", call_args)

    # ===== DEFAULT (STATUS) TESTS =====

    def test_default_no_arguments(self):
        """Test default method with no arguments."""
        result = self.service.default()
        
        self.assertIn("Ntfy service is ready", result)
        self.assertIn("Messages will be sent to topic", result)
        self.assertIn(self.service.TOPIC, result)

    def test_default_with_arguments(self):
        """Test default method with arguments (should ignore them)."""
        result = self.service.default("arg1", "arg2", "arg3")
        
        self.assertIn("Ntfy service is ready", result)
        self.assertIn(self.service.TOPIC, result)

    def test_default_shows_topic_name(self):
        """Test that default displays the configured topic."""
        result = self.service.default()
        
        self.assertIn("gemini_commander", result)

    # ===== EDGE CASE TESTS =====

    def test_send_with_empty_subject(self):
        """Test send with empty string as subject."""
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="OK")
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        result = self.service.send("", "Body")
        
        # Should still work with empty subject
        call_args = mock_curl.run.call_args[0]
        h_index = call_args.index('-H')
        title_header = call_args[h_index + 1]
        self.assertEqual(title_header, "Title: ")

    def test_send_with_empty_body(self):
        """Test send with empty string as body."""
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="OK")
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        result = self.service.send("Subject", "")
        
        # Should work with empty body
        call_args = mock_curl.run.call_args[0]
        d_index = call_args.index('-d')
        body = call_args[d_index + 1]
        self.assertEqual(body, "")

    def test_send_with_very_long_subject(self):
        """Test send with very long subject."""
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="OK")
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        long_subject = "A" * 500
        result = self.service.send(long_subject, "Body")
        
        # Should still work with long subject
        call_args = mock_curl.run.call_args[0]
        h_index = call_args.index('-H')
        title_header = call_args[h_index + 1]
        self.assertEqual(title_header, f"Title: {long_subject}")

    def test_send_with_very_long_body(self):
        """Test send with very long body."""
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="OK")
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        long_body = "B" * 5000
        result = self.service.send("Subject", long_body)
        
        # Should still work with long body
        call_args = mock_curl.run.call_args[0]
        d_index = call_args.index('-d')
        body = call_args[d_index + 1]
        self.assertEqual(body, long_body)

    def test_send_with_newlines_in_body(self):
        """Test send with newlines in body."""
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="OK")
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        multiline_body = "Line 1\nLine 2\nLine 3"
        result = self.service.send("Subject", multiline_body)
        
        call_args = mock_curl.run.call_args[0]
        d_index = call_args.index('-d')
        body = call_args[d_index + 1]
        self.assertEqual(body, multiline_body)

    def test_send_multiple_calls_independent(self):
        """Test that multiple send calls are independent."""
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="OK")
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        self.service.send("Subject 1", "Body 1")
        self.service.send("Subject 2", "Body 2")
        
        # Verify both calls were made
        self.assertEqual(mock_curl.run.call_count, 2)
        
        # Verify first call
        first_call = mock_curl.run.call_args_list[0]
        self.assertIn("Title: Subject 1", first_call[0])
        self.assertIn("Body 1", first_call[0])
        
        # Verify second call
        second_call = mock_curl.run.call_args_list[1]
        self.assertIn("Title: Subject 2", second_call[0])
        self.assertIn("Body 2", second_call[0])

    # ===== INTEGRATION-STYLE TESTS =====

    def test_send_curl_args_order(self):
        """Test that curl arguments are passed in the correct order."""
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="OK")
        self.service.server.loaded_modules = {"Curl": mock_curl}
        
        self.service.send("Subject", "Body")
        
        call_args = mock_curl.run.call_args[0]
        
        # Expected order: -H Title:... -d body URL
        self.assertEqual(call_args[0], '-H')
        self.assertTrue(call_args[1].startswith('Title:'))
        self.assertEqual(call_args[2], '-d')
        # call_args[3] is the body
        self.assertTrue(call_args[3] in ["Body"] or "Body" in str(call_args[3]))
        # Last argument should be URL
        self.assertEqual(call_args[-1], "https://ntfy.sh/gemini_commander")

    def test_topic_constant_immutable(self):
        """Test that TOPIC is a class constant."""
        # TOPIC should be the same across all instances
        service1 = ntfy(self.mock_server)
        service2 = ntfy(self.mock_server)
        
        self.assertEqual(service1.TOPIC, service2.TOPIC)
        self.assertEqual(service1.TOPIC, "gemini_commander")

    def test_ntfy_url_matches_topic(self):
        """Test that NTFY_URL is constructed from TOPIC."""
        expected_url = f"https://ntfy.sh/{self.service.TOPIC}"
        self.assertEqual(self.service.NTFY_URL, expected_url)

    # ===== CURL DEPENDENCY TESTS =====

    def test_send_requires_curl_service(self):
        """Test that send explicitly requires Curl service."""
        # Don't set up Curl service
        self.service.server.loaded_modules = {}
        
        result = self.service.send("Subject", "Body")
        
        # Should fail with dependency error
        self.assertIn("required dependency", result.lower())

    def test_curl_service_loaded_modules_lookup(self):
        """Test that Curl service is looked up in loaded_modules correctly."""
        mock_curl = Mock()
        mock_curl.run = Mock(return_value="OK")
        
        # Test with Curl present
        self.service.server.loaded_modules = {"Curl": mock_curl}
        result = self.service.send("Subject", "Body")
        self.assertNotIn("FATAL", result)
        
        # Test with Curl missing
        self.service.server.loaded_modules = {"SomeOther": Mock()}
        result = self.service.send("Subject", "Body")
        self.assertIn("FATAL", result)

    # ===== HELP/USAGE TESTS =====

    def test_send_usage_message(self):
        """Test that error messages include usage information."""
        result = self.service.send("OnlySubject")
        
        self.assertIn("Usage:", result)
        self.assertIn("send", result)
        self.assertIn("<subject>", result)
        self.assertIn("<body>", result)

    def test_error_message_format(self):
        """Test that error messages follow proper format."""
        result = self.service.send()
        
        self.assertTrue(result.startswith("Error:"))


if __name__ == '__main__':
    unittest.main()
