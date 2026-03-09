```python
"""Tests for ntfy service."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_server():
    """Create a mock server instance."""
    server = MagicMock()
    server.project_root_dir = "/fake/root"
    server.loaded_modules = {}
    return server


@pytest.fixture
def ntfy_service(mock_server):
    """Create a ntfy service instance with mocked dependencies."""
    # Mock the Service parent class
    with patch('csc_service.server.service.Service.__init__', return_value=None):
        from csc_service.shared.services.ntfy_service import ntfy
        
        service = ntfy(mock_server)
        service.server = mock_server
        service.log = MagicMock()
        return service


class TestNtfyService:
    """Test suite for ntfy service."""

    def test_class_attributes(self, ntfy_service):
        """Test that class has correct attributes."""
        from csc_service.shared.services.ntfy_service import ntfy
        
        assert ntfy.TOPIC == "gemini_commander"
        assert ntfy.NTFY_URL == "https://ntfy.sh/gemini_commander"

    def test_init(self, mock_server):
        """Test service initialization."""
        with patch('csc_service.server.service.Service.__init__', return_value=None):
            from csc_service.shared.services.ntfy_service import ntfy
            
            service = ntfy(mock_server)
            service.server = mock_server
            service.log = MagicMock()
            
            assert service.server == mock_server
            service.log.assert_called_once()
            assert "Ntfy service initialized" in service.log.call_args[0][0]
            assert "gemini_commander" in service.log.call_args[0][0]

    def test_send_success(self, ntfy_service, mock_server):
        """Test successful notification sending."""
        mock_curl = MagicMock()
        mock_curl.run.return_value = "Success"
        mock_server.loaded_modules["Curl"] = mock_curl
        
        result = ntfy_service.send("Subject", "Body", "Content")
        
        assert "Notification sent" in result
        assert "Success" in result
        
        # Verify curl was called with correct arguments
        mock_curl.run.assert_called_once()
        call_args = mock_curl.run.call_args[0]
        assert call_args[0] == '-H'
        assert call_args[1] == 'Title: Subject'
        assert call_args[2] == '-d'
        assert call_args[3] == 'Body Content'
        assert call_args[4] == 'https://ntfy.sh/gemini_commander'

    def test_send_single_subject_only(self, ntfy_service, mock_server):
        """Test send with only subject (missing body)."""
        mock_curl = MagicMock()
        mock_server.loaded_modules["Curl"] = mock_curl
        
        result = ntfy_service.send("SubjectOnly")
        
        assert "Error" in result
        assert "Usage: ntfy send" in result
        mock_curl.run.assert_not_called()

    def test_send_no_args(self, ntfy_service, mock_server):
        """Test send with no arguments."""
        mock_curl = MagicMock()
        mock_server.loaded_modules["Curl"] = mock_curl
        
        result = ntfy_service.send()
        
        assert "Error" in result
        assert "Usage: ntfy send" in result
        mock_curl.run.assert_not_called()

    def test_send_missing_curl_service(self, ntfy_service, mock_server):
        """Test send when Curl service is not loaded."""
        mock_server.loaded_modules = {}  # Empty, no Curl service
        
        result = ntfy_service.send("Subject", "Body")
        
        assert "FATAL ERROR" in result
        assert "Curl" in result
        assert "required dependency" in result

    def test_send_curl_service_none(self, ntfy_service, mock_server):
        """Test send when Curl service is explicitly None."""
        mock_server.loaded_modules["Curl"] = None
        
        result = ntfy_service.send("Subject", "Body")
        
        assert "FATAL ERROR" in result
        assert "Curl" in result

    def test_send_with_multiword_body(self, ntfy_service, mock_server):
        """Test send with multi-word body arguments."""
        mock_curl = MagicMock()
        mock_curl.run.return_value = "Message sent"
        mock_server.loaded_modules["Curl"] = mock_curl
        
        result = ntfy_service.send("Alert", "This", "is", "a", "test")
        
        assert "Notification sent" in result
        call_args = mock_curl.run.call_args[0]
        assert call_args[3] == "This is a test"

    def test_send_logs_action(self, ntfy_service, mock_server):
        """Test that send logs the notification action."""
        mock_curl = MagicMock()
        mock_curl.run.return_value = "OK"
        mock_server.loaded_modules["Curl"] = mock_curl
        
        ntfy_service.send("Subject", "Body")
        
        # Check that logging was called (at least once for the action)
        assert ntfy_service.log.call_count >= 1
        log_calls = [str(call) for call in ntfy_service.log.call_args_list]
        assert any("Sending notification" in str(call) for call in log_calls)

    def test_default_no_args(self, ntfy_service):
        """Test default method with no arguments."""
        result = ntfy_service.default()
        
        assert "Ntfy service is ready" in result
        assert "gemini_commander" in result

    def test_default_with_args_ignored(self, ntfy_service):
        """Test default method ignores arguments."""
        result = ntfy_service.default("arg1", "arg2")
        
        assert "Ntfy service is ready" in result
        assert "gemini_commander" in result

    def test_send_curl_exception_handling(self, ntfy_service, mock_server):
        """Test send when curl service raises an exception."""
        mock_curl = MagicMock()
        mock_curl.run.side_effect = Exception("Curl failed")
        mock_server.loaded_modules["Curl"] = mock_curl
        
        # Service should propagate the exception or handle it gracefully
        # Based on the code, it will raise the exception
        with pytest.raises(Exception):
            ntfy_service.send("Subject", "Body")

    def test_send_preserves_subject_special_chars(self, ntfy_service, mock_server):
        """Test that special characters in subject are preserved."""
        mock_curl = MagicMock()
        mock_curl.run.return_value = "OK"
        mock_server.loaded_modules["Curl"] = mock_curl
        
        special_subject = "Alert: System@100% [CRITICAL]"
        ntfy_service.send(special_subject, "Message")
        
        call_args = mock_curl.run.call_args[0]
        assert call_args[1] == f"Title: {special_subject}"

    def test_send_preserves_body_special_chars(self, ntfy_service, mock_server):
        """Test that special characters in body are preserved."""
        mock_curl = MagicMock()
        mock_curl.run.return_value = "OK"
        mock_server.loaded_modules["Curl"] = mock_curl
        
        ntfy_service.send("Subject", "Body", "with", "special&chars")
        
        call_args = mock_curl.run.call_args[0]
        assert "special&chars" in call_args[3]

    def test_ntfy_url_construction(self, ntfy_service):
        """Test that NTFY_URL is correctly constructed."""
        from csc_service.shared.services.ntfy_service import ntfy
        
        assert ntfy.NTFY_URL.startswith("https://")
        assert "ntfy.sh" in ntfy.NTFY_URL
        assert ntfy.TOPIC in ntfy.NTFY_URL

    def test_send_curl_args_format(self, ntfy_service, mock_server):
        """Test that curl arguments are formatted correctly."""
        mock_curl = MagicMock()
        mock_curl.run.return_value = "Success"
        mock_server.loaded_modules["Curl"] = mock_curl
        
        ntfy_service.send("Test", "Message")
        
        # Verify argument structure
        call_args = mock_curl.run.call_args[0]
        assert len(call_args) == 5
        assert call_args[0:2] == ('-H', 'Title: Test')
        assert call_args[2:4] == ('-d', 'Message')
        assert call_args[4] == 'https://ntfy.sh/gemini_commander'

    def test_send_empty_body(self, ntfy_service, mock_server):
        """Test send with empty body string."""
        mock_curl = MagicMock()
        mock_curl.run.return_value = "OK"
        mock_server.loaded_modules["Curl"] = mock_curl
        
        result = ntfy_service.send("Subject", "")
        
        assert "Notification sent" in result
        call_args = mock_curl.run.call_args[0]
        assert call_args[3] == ""
```