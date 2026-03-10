"""
Comprehensive test suite for curl service.

Tests HTTP request handling, header parsing, method selection, error handling,
and timeout behavior using mocked requests library and server instance.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import requests

from csc_service.shared.services.curl_service import curl


class TestCurlServiceBasics(unittest.TestCase):
    """Test basic curl service initialization and default behavior."""

    def setUp(self):
        """Set up mock server instance for each test."""
        self.mock_server = Mock()
        self.service = curl(self.mock_server)

    def test_init(self):
        """Test curl service initializes correctly."""
        # Service inherits from Service base class
        self.assertEqual(self.service.server, self.mock_server)
        # Verify service was created without errors
        self.assertIsNotNone(self.service)

    def test_default_help(self):
        """Test default command returns help message."""
        result = self.service.default()
        self.assertIn("Curl service ready", result)
        self.assertIn("curl-like flags", result)
        self.assertIn("-H", result)
        self.assertIn("-d", result)


class TestCurlServiceGetRequest(unittest.TestCase):
    """Test GET request handling."""

    def setUp(self):
        """Set up mock server instance for each test."""
        self.mock_server = Mock()
        self.service = curl(self.mock_server)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_simple_get_request(self, mock_get):
        """Test simple GET request without headers."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Success response"
        mock_get.return_value = mock_response

        result = self.service.run("https://example.com")

        mock_get.assert_called_once_with(
            "https://example.com",
            headers={},
            timeout=10
        )
        self.assertIn("Success (200)", result)
        self.assertIn("Success response", result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_get_with_single_header(self, mock_get):
        """Test GET request with one custom header."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Response data"
        mock_get.return_value = mock_response

        result = self.service.run("-H", "Authorization: Bearer token123", "https://api.example.com")

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        self.assertEqual(call_kwargs['headers']['Authorization'], 'Bearer token123')
        self.assertEqual(call_kwargs['timeout'], 10)
        self.assertIn("Success (200)", result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_get_with_multiple_headers(self, mock_get):
        """Test GET request with multiple custom headers."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "API response"
        mock_get.return_value = mock_response

        result = self.service.run(
            "-H", "Authorization: Bearer xyz",
            "-H", "User-Agent: CSC-Client",
            "-H", "Accept: application/json",
            "https://api.example.com/data"
        )

        call_kwargs = mock_get.call_args[1]
        headers = call_kwargs['headers']
        self.assertEqual(headers['Authorization'], 'Bearer xyz')
        self.assertEqual(headers['User-Agent'], 'CSC-Client')
        self.assertEqual(headers['Accept'], 'application/json')
        self.assertIn("Success (200)", result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_get_header_whitespace_trimming(self, mock_get):
        """Test that header keys and values have whitespace trimmed."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_get.return_value = mock_response

        result = self.service.run(
            "-H", "  X-Custom  :  value with spaces  ",
            "https://example.com"
        )

        call_kwargs = mock_get.call_args[1]
        headers = call_kwargs['headers']
        # Key and value should be trimmed
        self.assertIn('X-Custom', headers)
        self.assertEqual(headers['X-Custom'], 'value with spaces')

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_get_with_200_response(self, mock_get):
        """Test successful 200 response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_get.return_value = mock_response

        result = self.service.run("https://example.com")

        self.assertIn("Success (200)", result)
        self.assertIn("OK", result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_get_with_201_response(self, mock_get):
        """Test 201 Created response."""
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.text = "Created"
        mock_get.return_value = mock_response

        result = self.service.run("https://api.example.com")

        self.assertIn("Success (201)", result)
        self.assertIn("Created", result)


class TestCurlServicePostRequest(unittest.TestCase):
    """Test POST request handling."""

    def setUp(self):
        """Set up mock server instance for each test."""
        self.mock_server = Mock()
        self.service = curl(self.mock_server)

    @patch('csc_service.shared.services.curl_service.requests.post')
    def test_simple_post_request(self, mock_post):
        """Test POST request with body data."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Created"
        mock_post.return_value = mock_response

        result = self.service.run("-d", "request body", "https://example.com/api")

        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        self.assertEqual(call_args[0], "https://example.com/api")
        # Data should be encoded as UTF-8 bytes
        self.assertEqual(call_kwargs['data'], b'request body')
        self.assertEqual(call_kwargs['headers'], {})
        self.assertEqual(call_kwargs['timeout'], 10)
        self.assertIn("Success (200)", result)

    @patch('csc_service.shared.services.curl_service.requests.post')
    def test_post_with_headers(self, mock_post):
        """Test POST request with body and custom headers."""
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.text = "Accepted"
        mock_post.return_value = mock_response

        result = self.service.run(
            "-H", "Content-Type: application/json",
            "-d", '{"key": "value"}',
            "https://api.example.com/data"
        )

        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs['data'], b'{"key": "value"}')
        self.assertEqual(call_kwargs['headers']['Content-Type'], 'application/json')
        self.assertEqual(call_kwargs['timeout'], 10)
        self.assertIn("Success (201)", result)

    @patch('csc_service.shared.services.curl_service.requests.post')
    def test_post_method_inferred_from_data(self, mock_post):
        """Test that POST method is inferred when -d is present."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_post.return_value = mock_response

        # Providing -d should trigger POST, not GET
        self.service.run("-d", "data", "https://example.com")

        # Verify post was called, not get
        mock_post.assert_called_once()

    @patch('csc_service.shared.services.curl_service.requests.post')
    def test_post_with_empty_body(self, mock_post):
        """Test POST with empty data body."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_post.return_value = mock_response

        result = self.service.run("-d", "", "https://example.com")

        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs['data'], b'')
        self.assertIn("Success (200)", result)

    @patch('csc_service.shared.services.curl_service.requests.post')
    def test_post_with_special_characters(self, mock_post):
        """Test POST with special characters in body."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_post.return_value = mock_response

        special_data = "key=value&foo=bar&emoji=😀"
        result = self.service.run("-d", special_data, "https://example.com")

        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs['data'], special_data.encode('utf-8'))

    @patch('csc_service.shared.services.curl_service.requests.post')
    def test_post_notification_service(self, mock_post):
        """Test real-world use case: ntfy.sh notification."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = ""
        mock_post.return_value = mock_response

        result = self.service.run(
            "-H", "Title: Alert",
            "-d", "Server is down",
            "https://ntfy.sh/myalerts"
        )

        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs['headers']['Title'], 'Alert')
        self.assertEqual(call_kwargs['data'], b'Server is down')
        self.assertIn("Success (200)", result)


class TestCurlServiceErrorHandling(unittest.TestCase):
    """Test error handling and edge cases."""

    def setUp(self):
        """Set up mock server instance for each test."""
        self.mock_server = Mock()
        self.service = curl(self.mock_server)

    def test_no_url_specified(self):
        """Test error when no URL is provided."""
        result = self.service.run()
        self.assertIn("Error", result)
        self.assertIn("No URL specified", result)

    def test_no_url_only_headers(self):
        """Test error when headers provided but no URL."""
        result = self.service.run("-H", "Authorization: Bearer xyz")
        self.assertIn("Error", result)
        self.assertIn("No URL specified", result)

    def test_no_url_only_data(self):
        """Test error when data provided but no URL."""
        result = self.service.run("-d", "some data")
        self.assertIn("Error", result)
        self.assertIn("No URL specified", result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_http_error_404(self, mock_get):
        """Test HTTP 404 Not Found error handling."""
        mock_get.side_effect = requests.HTTPError("404 Not Found")

        result = self.service.run("https://example.com/missing")

        self.assertIn("Error", result)
        self.assertIn("404 Not Found", result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_http_error_500(self, mock_get):
        """Test HTTP 500 Server Error handling."""
        mock_get.side_effect = requests.HTTPError("500 Internal Server Error")

        result = self.service.run("https://example.com/error")

        self.assertIn("Error", result)
        self.assertIn("500 Internal Server Error", result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_connection_timeout(self, mock_get):
        """Test connection timeout error handling."""
        mock_get.side_effect = requests.Timeout("Connection timeout")

        result = self.service.run("https://slow.example.com")

        self.assertIn("Error", result)
        self.assertIn("Connection timeout", result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_invalid_url_from_requests(self, mock_get):
        """Test invalid URL error from requests library."""
        # Use the actual exception class from requests
        from requests.exceptions import InvalidURL
        mock_get.side_effect = InvalidURL("Invalid URL format")

        result = self.service.run("not a url")

        self.assertIn("Error", result)
        self.assertIn("Invalid URL", result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_connection_error_dns(self, mock_get):
        """Test DNS resolution failure."""
        mock_get.side_effect = requests.ConnectionError("Name or service not known")

        result = self.service.run("https://invalid-host-12345.com")

        self.assertIn("Error", result)
        self.assertIn("Name or service not known", result)

    @patch('csc_service.shared.services.curl_service.requests.post')
    def test_request_exception(self, mock_post):
        """Test generic request exception handling."""
        mock_post.side_effect = requests.RequestException("Generic error")

        result = self.service.run("-d", "data", "https://example.com")

        self.assertIn("Error", result)
        self.assertIn("Generic error", result)

    def test_malformed_header_caught_in_exception(self):
        """Test that malformed headers (missing colon) are caught as error."""
        # This should result in an error being returned (not raising)
        result = self.service.run("-H", "NoColonHeader", "https://example.com")
        # Should handle the ValueError gracefully and return error
        self.assertIn("Error", result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_header_with_multiple_colons(self, mock_get):
        """Test header value containing colons (e.g., URL)."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_get.return_value = mock_response

        # Header value contains colons (e.g., scheme://host)
        result = self.service.run(
            "-H", "Referer: https://example.com:8080/path",
            "https://api.example.com"
        )

        call_kwargs = mock_get.call_args[1]
        # split(':', 1) means value gets everything after first colon
        self.assertEqual(call_kwargs['headers']['Referer'], 'https://example.com:8080/path')


class TestCurlServiceTimeout(unittest.TestCase):
    """Test timeout configuration and behavior."""

    def setUp(self):
        """Set up mock server instance for each test."""
        self.mock_server = Mock()
        self.service = curl(self.mock_server)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_get_timeout_value(self, mock_get):
        """Test that GET requests use 10 second timeout."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_get.return_value = mock_response

        self.service.run("https://example.com")

        call_kwargs = mock_get.call_args[1]
        self.assertEqual(call_kwargs['timeout'], 10)

    @patch('csc_service.shared.services.curl_service.requests.post')
    def test_post_timeout_value(self, mock_post):
        """Test that POST requests use 10 second timeout."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_post.return_value = mock_response

        self.service.run("-d", "data", "https://example.com")

        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs['timeout'], 10)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_timeout_exception_handling(self, mock_get):
        """Test handling of timeout exceptions."""
        mock_get.side_effect = requests.Timeout("Read timed out")

        result = self.service.run("https://example.com")

        self.assertIn("Error", result)
        self.assertIn("Read timed out", result)


class TestCurlServiceArgumentParsing(unittest.TestCase):
    """Test argument parsing and ordering."""

    def setUp(self):
        """Set up mock server instance for each test."""
        self.mock_server = Mock()
        self.service = curl(self.mock_server)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_url_at_beginning(self, mock_get):
        """Test URL at beginning with trailing headers."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_get.return_value = mock_response

        # URL first, then headers - last URL wins (or flags override)
        result = self.service.run("https://example.com", "-H", "X-Test: value")

        # The URL at the beginning gets overridden; -H takes the next arg
        # So "https://example.com" becomes the URL, then -H X-Test: value adds header
        mock_get.assert_called_once()

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_flags_mixed_order(self, mock_get):
        """Test that flag order doesn't matter."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_get.return_value = mock_response

        result = self.service.run(
            "https://example.com",
            "-H", "Header1: value1",
            "-H", "Header2: value2"
        )

        call_kwargs = mock_get.call_args[1]
        headers = call_kwargs['headers']
        self.assertIn('Header1', headers)
        self.assertIn('Header2', headers)

    @patch('csc_service.shared.services.curl_service.requests.post')
    def test_data_before_url(self, mock_post):
        """Test parsing when -d appears before URL."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_post.return_value = mock_response

        result = self.service.run("-d", "body", "https://example.com")

        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs['data'], b'body')

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_ignores_unknown_flags(self, mock_get):
        """Test that unknown flags are skipped gracefully."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_get.return_value = mock_response

        # -X is not recognized, should be skipped
        result = self.service.run("-X", "POST", "https://example.com")

        # Should still work, treating -X POST as non-URL args
        call_args = mock_get.call_args[0]
        self.assertEqual(call_args[0], "https://example.com")


class TestCurlServiceResponseHandling(unittest.TestCase):
    """Test response handling and formatting."""

    def setUp(self):
        """Set up mock server instance for each test."""
        self.mock_server = Mock()
        self.service = curl(self.mock_server)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_response_with_json(self, mock_get):
        """Test response containing JSON data."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "data": [1, 2, 3]}'
        mock_get.return_value = mock_response

        result = self.service.run("https://api.example.com/json")

        self.assertIn("Success (200)", result)
        self.assertIn('{"status": "ok"', result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_response_with_html(self, mock_get):
        """Test response containing HTML."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Hello World</body></html>"
        mock_get.return_value = mock_response

        result = self.service.run("https://example.com")

        self.assertIn("Success (200)", result)
        self.assertIn("<html>", result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_response_with_empty_body(self, mock_get):
        """Test response with empty body."""
        mock_response = Mock()
        mock_response.status_code = 204
        mock_response.text = ""
        mock_get.return_value = mock_response

        result = self.service.run("https://example.com")

        self.assertIn("Success (204)", result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_response_with_long_text(self, mock_get):
        """Test response with very long body (no truncation)."""
        mock_response = Mock()
        mock_response.status_code = 200
        # Large response text
        long_text = "x" * 10000
        mock_response.text = long_text
        mock_get.return_value = mock_response

        result = self.service.run("https://example.com")

        self.assertIn("Success (200)", result)
        # Full response should be included (no truncation)
        self.assertIn(long_text, result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_response_with_special_characters(self, mock_get):
        """Test response containing special characters and unicode."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Response with emoji 😀 and symbols ©®™"
        mock_get.return_value = mock_response

        result = self.service.run("https://example.com")

        self.assertIn("Success (200)", result)
        self.assertIn("😀", result)


class TestCurlServiceIntegration(unittest.TestCase):
    """Integration tests combining multiple features."""

    def setUp(self):
        """Set up mock server instance for each test."""
        self.mock_server = Mock()
        self.service = curl(self.mock_server)

    @patch('csc_service.shared.services.curl_service.requests.post')
    def test_complex_workflow_api_call(self, mock_post):
        """Test complex real-world API call with multiple headers and JSON body."""
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.text = '{"id": 123, "status": "created"}'
        mock_post.return_value = mock_response

        result = self.service.run(
            "-H", "Authorization: Bearer secret-token",
            "-H", "Content-Type: application/json",
            "-H", "User-Agent: CSC-Bot/1.0",
            "-d", '{"name": "test", "value": 42}',
            "https://api.example.com/v1/resources"
        )

        call_kwargs = mock_post.call_args[1]
        headers = call_kwargs['headers']
        self.assertEqual(headers['Authorization'], 'Bearer secret-token')
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(headers['User-Agent'], 'CSC-Bot/1.0')
        self.assertEqual(call_kwargs['data'], b'{"name": "test", "value": 42}')
        self.assertIn("Success (201)", result)
        self.assertIn("created", result)

    @patch('csc_service.shared.services.curl_service.requests.post')
    def test_webhook_notification_workflow(self, mock_post):
        """Test webhook notification use case (ntfy.sh)."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = ""
        mock_post.return_value = mock_response

        result = self.service.run(
            "-H", "Title: Critical Alert",
            "-H", "Priority: high",
            "-d", "Database connection lost in production",
            "https://ntfy.sh/devops-alerts"
        )

        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs['headers']['Title'], 'Critical Alert')
        self.assertEqual(call_kwargs['headers']['Priority'], 'high')
        self.assertIn("Success (200)", result)

    @patch('csc_service.shared.services.curl_service.requests.get')
    def test_multiple_sequential_requests(self, mock_get):
        """Test making multiple requests in sequence."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_get.return_value = mock_response

        # First request
        result1 = self.service.run("https://api1.example.com/status")
        self.assertIn("Success (200)", result1)

        # Second request
        result2 = self.service.run("-H", "Token: xyz", "https://api2.example.com/data")
        self.assertIn("Success (200)", result2)

        # Verify both calls were made
        self.assertEqual(mock_get.call_count, 2)


if __name__ == '__main__':
    unittest.main()
