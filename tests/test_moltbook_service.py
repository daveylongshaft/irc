```python
"""
Tests for the moltbook service.

Tests the Moltbook service functionality including:
- Account registration with shared CSC account
- Status checking
- Posting functionality
- Error handling and rate limit awareness
"""

import pytest
import json
from unittest.mock import MagicMock, patch, Mock
import urllib.error
from io import BytesIO

from csc_service.shared.services.moltbook_service import moltbook


@pytest.fixture
def mock_server():
    """Create a mock server instance."""
    server = MagicMock()
    return server


@pytest.fixture
def service(mock_server, tmp_path, monkeypatch):
    """Create a moltbook service instance with mocked data directory."""
    monkeypatch.setattr("csc_service.server.service.Service.init_data", 
                       lambda self, name=None: None)
    monkeypatch.setattr("csc_service.server.service.Service.get_data", 
                       lambda self, key: getattr(self, f"_data_{key}", None))
    monkeypatch.setattr("csc_service.server.service.Service.put_data", 
                       lambda self, key, value, flush=True: setattr(self, f"_data_{key}", value))
    monkeypatch.setattr("csc_service.server.service.Service.log", 
                       lambda self, msg: None)
    
    service_instance = moltbook(mock_server)
    service_instance._data_store = {}
    
    # Override data methods to use in-memory storage
    def get_data_impl(key):
        return service_instance._data_store.get(key)
    
    def put_data_impl(key, value, flush=True):
        service_instance._data_store[key] = value
    
    service_instance.get_data = get_data_impl
    service_instance.put_data = put_data_impl
    
    return service_instance


class TestMoltbookRegistration:
    """Test account registration functionality."""

    @patch('urllib.request.urlopen')
    def test_register_account_success(self, mock_urlopen, service):
        """Test registering a new moltbook account."""
        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "agent": {
                "name": "CSC-Bot",
                "api_key": "test_api_key_12345",
                "claim_url": "https://www.moltbook.com/claim/test123",
                "verification_code": "VERIFY123"
            }
        }).encode()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        result = service.register("CSC-Bot", "AI", "agent", "collective")

        assert "Registration successful" in result
        assert "CSC-Bot" in result
        assert "api_key" in result.lower()
        assert service.get_data("api_key") == "test_api_key_12345"
        assert service.get_data("agent_name") == "CSC-Bot"

    def test_register_missing_args(self, service):
        """Test registration fails with missing arguments."""
        result = service.register("OnlyName")
        assert "Usage:" in result

    @patch('urllib.request.urlopen')
    def test_register_api_error(self, mock_urlopen, service):
        """Test registration handles API errors."""
        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "error": "Agent name already exists"
        }).encode()
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://www.moltbook.com/api/v1/agents/register",
            400,
            "Bad Request",
            {},
            BytesIO(json.dumps({"error": "Agent name already exists"}).encode())
        )

        result = service.register("ExistingBot", "test agent")
        assert "HTTP 400" in result
        assert "already exists" in result


class TestMoltbookSetup:
    """Test credential setup."""

    def test_setup_credentials(self, service):
        """Test saving credentials for an existing account."""
        result = service.setup("existing_api_key_789", "CSC-Bot")

        assert "Credentials saved" in result
        assert "CSC-Bot" in result
        assert service.get_data("api_key") == "existing_api_key_789"
        assert service.get_data("agent_name") == "CSC-Bot"

    def test_setup_missing_args(self, service):
        """Test setup fails with missing arguments."""
        result = service.setup("OnlyKey")
        assert "Usage:" in result


class TestMoltbookStatus:
    """Test account status checking."""

    @patch('urllib.request.urlopen')
    def test_status_pending_claim(self, mock_urlopen, service):
        """Test checking account status when pending claim."""
        service.put_data("api_key", "test_key_123")

        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "status": "pending_claim"
        }).encode()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        result = service.status()

        assert "pending_claim" in result
        assert "human" in result or "claim" in result

    @patch('urllib.request.urlopen')
    def test_status_claimed(self, mock_urlopen, service):
        """Test checking account status when claimed."""
        service.put_data("api_key", "test_key_123")

        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "status": "claimed"
        }).encode()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        result = service.status()

        assert "claimed" in result
        assert "active" in result or "ready" in result

    def test_status_no_api_key(self, service):
        """Test status check fails without API key."""
        result = service.status()
        assert "No API key" in result
        assert "setup" in result

    @patch('urllib.request.urlopen')
    def test_status_network_error(self, mock_urlopen, service):
        """Test status handles network errors."""
        service.put_data("api_key", "test_key_123")
        
        mock_urlopen.side_effect = urllib.error.URLError("Connection timeout")

        result = service.status()
        assert "Network error" in result


class TestMoltbookPosting:
    """Test posting functionality."""

    @patch('urllib.request.urlopen')
    def test_make_post_success(self, mock_urlopen, service):
        """Test making a post to moltbook."""
        service.put_data("api_key", "test_key_123")

        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "post": {
                "id": "post_123",
                "title": "Test Post",
                "content": "This is a test post"
            }
        }).encode()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        result = service.post("general", "Test", "Post", "Content")

        assert "Post created" in result or "post_123" in result

    def test_post_missing_args(self, service):
        """Test post fails with missing arguments."""
        service.put_data("api_key", "test_key_123")
        result = service.post("general", "title")
        assert "Usage:" in result

    def test_post_no_api_key(self, service):
        """Test post fails without API key."""
        result = service.post("general", "Title", "Content")
        assert "No API key" in result
        assert "setup" in result

    @patch('urllib.request.urlopen')
    def test_post_rate_limit(self, mock_urlopen, service):
        """Test handling of rate limit errors (429)."""
        service.put_data("api_key", "test_key_123")

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://www.moltbook.com/api/v1/posts",
            429,
            "Too Many Requests",
            {},
            BytesIO(json.dumps({
                "error": "Rate limit exceeded",
                "retry_after_minutes": 30,
                "daily_remaining": 0
            }).encode())
        )

        result = service.post("general", "Post", "Content")

        assert "429" in result or "rate limit" in result.lower()

    @patch('urllib.request.urlopen')
    def test_post_network_error(self, mock_urlopen, service):
        """Test post handles network errors."""
        service.put_data("api_key", "test_key_123")
        
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        result = service.post("general", "Title", "Content")
        assert "Network error" in result


class TestMoltbookComments:
    """Test commenting functionality."""

    @patch('urllib.request.urlopen')
    def test_comment_success(self, mock_urlopen, service):
        """Test adding a comment to a post."""
        service.put_data("api_key", "test_key_123")

        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "comment": {
                "id": "comment_456",
                "post_id": "post_123",
                "content": "Great post!"
            }
        }).encode()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        result = service.comment("post_123", "Great", "post!")

        assert "comment_456" in result or "Comment created" in result.lower()

    def test_comment_missing_args(self, service):
        """Test comment fails with missing arguments."""
        service.put_data("api_key", "test_key_123")
        result = service.comment("post_123")
        assert "Usage:" in result

    def test_comment_no_api_key(self, service):
        """Test comment fails without API key."""
        result = service.comment("post_123", "Comment")
        assert "No API key" in result


class TestMoltbookVoting:
    """Test voting functionality."""

    @patch('urllib.request.urlopen')
    def test_vote_post_upvote(self, mock_urlopen, service):
        """Test upvoting a post."""
        service.put_data("api_key", "test_key_123")

        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "post": {
                "id": "post_123",
                "upvotes": 10,
                "downvotes": 2
            }
        }).encode()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        result = service.vote_post("post_123", "up")

        assert "Voted" in result or "post_123" in result

    @patch('urllib.request.urlopen')
    def test_vote_post_downvote(self, mock_urlopen, service):
        """Test downvoting a post."""
        service.put_data("api_key", "test_key_123")

        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "post": {
                "id": "post_123",
                "upvotes": 8,
                "downvotes": 4
            }
        }).encode()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        result = service.vote_post("post_123", "down")

        assert "post_123" in result or "Voted" in result

    def test_vote_missing_args(self, service):
        """Test vote fails with missing arguments."""
        service.put_data("api_key", "test_key_123")
        result = service.vote_post("post_123")
        assert "Usage:" in result

    def test_vote_no_api_key(self, service):
        """Test vote fails without API key."""
        result = service.vote_post("post_123", "up")
        assert "No API key" in result


class TestMoltbookFeed:
    """Test feed functionality."""

    @patch('urllib.request.urlopen')
    def test_feed_home(self, mock_urlopen, service):
        """Test fetching home feed."""
        service.put_data("api_key", "test_key_123")

        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "posts": [
                {"id": "post_1", "title": "First", "upvotes": 5},
                {"id": "post_2", "title": "Second", "upvotes": 3}
            ]
        }).encode()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        result = service.feed()

        assert "post_1" in result or "post_2" in result

    @patch('urllib.request.urlopen')
    def test_feed_submolt(self, mock_urlopen, service):
        """Test fetching a submolt's feed."""
        service.put_data("api_key", "test_key_123")

        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "posts": [
                {"id": "post_3", "title": "Tech", "upvotes": 10}
            ]
        }).encode()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response

        result = service.feed("technology")

        assert "post_3" in result or "Tech" in result

    def test_feed_no_api_key(self, service):
        """Test feed fails without API key."""
        result = service.feed()
        assert "No API key" in result


class TestMoltbookErrorHandling:
    """Test error handling and edge cases."""

    @patch('urllib.request.urlopen')
    def test_http_error_with_hint(self, mock_urlopen, service):
        """Test HTTP error includes hint in response."""
        service.put_data("api_key", "test_key_123")

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://www.moltbook.com/api/v1/posts",
            400,
            "Bad Request",
            {},
            BytesIO(json.dumps({
                "error": "Invalid submolt",
                "hint": "Use lowercase letters only"
            }).encode())
        )

        result = service.post("InvalidSubmolt", "Title", "Content")
        assert "Invalid submolt" in result
        assert "Hint:" in result

    @patch('urllib.request.urlopen')
    def test_http_error_retry_after_seconds(self, mock_urlopen, service):
        """Test HTTP error includes retry_after_seconds."""
        service.put_data("api_key", "test_key_123")

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://www.moltbook.com/api/v1/posts",
            429,
            "Too Many Requests",
            {},
            BytesIO(json.dumps({
                "error": "Rate limited",
                "retry