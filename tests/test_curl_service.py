```python
"""Tests for curl service."""

import pytest
from unittest.mock import MagicMock, patch, call


@pytest.fixture
def mock_server():
    """Create a mock server instance."""
    server = MagicMock()
    server.project_root_dir = "/mock/path"
    return server


@pytest.fixture
def curl_service(mock_server):
    """Create a curl service instance with mocked dependencies."""
    with patch('csc_service.shared.services.curl_service.Service.__init__', return_value=None):
        from csc_service.shared.services.curl_service import curl
        service = curl(mock_server)
        service.log = MagicMock()
        service.server_instance = mock_server
    return service


class TestCurlService:
    """Test cases for the curl service."""

    def test_initialization(self, mock_server):
        """Test that curl service initializes correctly."""
        with patch('csc_service.shared.services.curl_service.Service.__init__', return_value=None):
            from csc_service.shared.services.curl_service import curl
            service = curl(mock_server)
            service.log = MagicMock()
            service.log.assert_called_with("Curl service initialized.")

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_get_simple(self, mock_requests, curl_service):
        """Test simple GET request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Response Data"
        mock_requests.get.return_value = mock_response

        result = curl_service.run("https://example.com")

        assert "Success (200)" in result
        assert "Response Data" in result
        mock_requests.get.assert_called_with("https://example.com", headers={}, timeout=10)

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_post_with_data(self, mock_requests, curl_service):
        """Test POST request with data."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.text = "Created"
        mock_requests.post.return_value = mock_response

        result = curl_service.run("-d", "test data", "https://example.com")

        assert "Success (201)" in result
        assert "Created" in result
        mock_requests.post.assert_called_with(
            "https://example.com",
            data=b"test data",
            headers={},
            timeout=10
        )

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_with_single_header(self, mock_requests, curl_service):
        """Test GET request with a single header."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_requests.get.return_value = mock_response

        result = curl_service.run("-H", "User-Agent: CustomAgent", "https://example.com")

        assert "Success (200)" in result
        assert "OK" in result
        mock_requests.get.assert_called_with(
            "https://example.com",
            headers={"User-Agent": "CustomAgent"},
            timeout=10
        )

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_with_multiple_headers(self, mock_requests, curl_service):
        """Test GET request with multiple headers."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Multi-header response"
        mock_requests.get.return_value = mock_response

        result = curl_service.run(
            "-H", "User-Agent: Test",
            "-H", "Content-Type: application/json",
            "https://example.com"
        )

        assert "Success (200)" in result
        assert "Multi-header response" in result
        call_args = mock_requests.get.call_args
        assert call_args[1]["headers"]["User-Agent"] == "Test"
        assert call_args[1]["headers"]["Content-Type"] == "application/json"

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_post_with_headers_and_data(self, mock_requests, curl_service):
        """Test POST request with both headers and data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Success"
        mock_requests.post.return_value = mock_response

        result = curl_service.run(
            "-H", "Authorization: Bearer token",
            "-d", "payload",
            "https://api.example.com"
        )

        assert "Success (200)" in result
        call_args = mock_requests.post.call_args
        assert call_args[0][0] == "https://api.example.com"
        assert call_args[1]["data"] == b"payload"
        assert call_args[1]["headers"]["Authorization"] == "Bearer token"

    def test_run_missing_url(self, curl_service):
        """Test error when no URL is specified."""
        result = curl_service.run("-H", "Header: Value")

        assert "Error: No URL specified" in result

    def test_run_missing_url_only_flags(self, curl_service):
        """Test error when only flags are provided without URL."""
        result = curl_service.run("-d", "data", "-H", "Type: JSON")

        assert "Error: No URL specified" in result

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_exception_connection_error(self, mock_requests, curl_service):
        """Test exception handling for connection errors."""
        mock_requests.get.side_effect = Exception("Connection refused")

        result = curl_service.run("https://bad.url")

        assert "Error: Connection refused" in result

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_exception_timeout(self, mock_requests, curl_service):
        """Test exception handling for timeout errors."""
        mock_requests.post.side_effect = Exception("Timeout")

        result = curl_service.run("-d", "data", "https://slow.example.com")

        assert "Error: Timeout" in result

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_http_error_404(self, mock_requests, curl_service):
        """Test handling of HTTP 404 error."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")
        mock_requests.get.return_value = mock_response

        result = curl_service.run("https://example.com/notfound")

        assert "Error: 404 Not Found" in result

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_http_error_500(self, mock_requests, curl_service):
        """Test handling of HTTP 500 error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = Exception("500 Internal Server Error")
        mock_requests.post.return_value = mock_response

        result = curl_service.run("-d", "data", "https://example.com/api")

        assert "Error: 500 Internal Server Error" in result

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_header_with_spaces(self, mock_requests, curl_service):
        """Test header parsing with spaces around colon."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_requests.get.return_value = mock_response

        result = curl_service.run(
            "-H", "X-Custom-Header : value with spaces ",
            "https://example.com"
        )

        assert "Success (200)" in result
        call_args = mock_requests.get.call_args
        assert call_args[1]["headers"]["X-Custom-Header"] == "value with spaces"

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_data_encoding(self, mock_requests, curl_service):
        """Test that data is properly encoded to UTF-8."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Received"
        mock_requests.post.return_value = mock_response

        result = curl_service.run("-d", "unicode: café", "https://example.com")

        assert "Success (200)" in result
        call_args = mock_requests.post.call_args
        assert call_args[1]["data"] == "unicode: café".encode('utf-8')

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_full_response_text(self, mock_requests, curl_service):
        """Test that full response text is returned (not truncated)."""
        long_response = "A" * 1000
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = long_response
        mock_requests.get.return_value = mock_response

        result = curl_service.run("https://example.com")

        assert long_response in result
        assert "Success (200)" in result

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_empty_response(self, mock_requests, curl_service):
        """Test handling of empty response text."""
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.text = ""
        mock_requests.get.return_value = mock_response

        result = curl_service.run("https://example.com")

        assert "Success (204)" in result

    def test_default_help_message(self, curl_service):
        """Test default help message."""
        result = curl_service.default()

        assert "Curl service ready" in result
        assert "curl-like flags" in result
        assert "-H" in result
        assert "-d" in result

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_logs_execution(self, mock_requests, curl_service):
        """Test that service logs request execution."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_requests.get.return_value = mock_response

        curl_service.run("-H", "Type: JSON", "https://example.com")

        # Check that log was called with execution details
        log_calls = [call for call in curl_service.log.call_args_list if "GET" in str(call)]
        assert len(log_calls) > 0

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_logs_errors(self, mock_requests, curl_service):
        """Test that service logs errors."""
        mock_requests.get.side_effect = Exception("Network error")

        curl_service.run("https://example.com")

        log_calls = [call for call in curl_service.log.call_args_list if "error" in str(call).lower()]
        assert len(log_calls) > 0

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_url_as_first_arg(self, mock_requests, curl_service):
        """Test URL as first argument without flags."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Response"
        mock_requests.get.return_value = mock_response

        result = curl_service.run("https://example.com")

        assert "Success (200)" in result

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_url_as_last_arg(self, mock_requests, curl_service):
        """Test URL as last argument."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Response"
        mock_requests.get.return_value = mock_response

        result = curl_service.run("-H", "Custom: Header", "https://example.com")

        assert "Success (200)" in result

    @patch('csc_service.shared.services.curl_service.requests')
    def test_run_special_characters_in_data(self, mock_requests, curl_service):
        """Test data with special characters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_requests.post.return_value = mock_response

        special_data = '{"key": "value", "special": "!@#$%^&*()"}'
        result = curl_service.run("-d", special_data, "https://example.com")

        assert "Success (200)" in result
        call_args = mock_requests.post.call_args
        assert call_args[1]["data"] == special_data.encode('utf-8')
```