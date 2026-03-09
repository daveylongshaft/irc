```python
"""Tests for nickserv service."""

import os
import pytest
import tempfile
import time
from unittest.mock import MagicMock, patch, mock_open

from csc_service.shared.services.nickserv_service import Nickserv


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    test_dir = tempfile.mkdtemp()
    yield test_dir
    # Cleanup handled by pytest
    import shutil
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)


@pytest.fixture
def mock_server(temp_dir):
    """Create a mock server instance."""
    server = MagicMock()
    server.project_root_dir = temp_dir
    return server


@pytest.fixture
def nickserv_service(mock_server, temp_dir):
    """Create a Nickserv service instance with mocked dependencies."""
    db_file = os.path.join(temp_dir, "server", "nickserv.db")
    
    with patch('csc_service.server.service.Service.init_data'):
        service = Nickserv(mock_server)
    
    # Override db_file to use temp directory
    service.db_file = db_file
    service._load_db()
    
    return service


class TestNickservRegistration:
    """Test nick registration functionality."""

    def test_register_nick_success(self, nickserv_service):
        """Test successful nick registration."""
        result = nickserv_service._register_nick("Davey", "davey@example.com", "password123")
        
        assert "registered successfully" in result
        assert "davey" in nickserv_service._registry
        assert nickserv_service._registry["davey"]["email"] == "davey@example.com"
        assert nickserv_service._registry["davey"]["nick"] == "Davey"

    def test_register_nick_duplicate(self, nickserv_service):
        """Test that registering duplicate nick fails."""
        nickserv_service._register_nick("Davey", "mail@example.com", "pass123")
        result = nickserv_service._register_nick("davey", "mail2@example.com", "pass456")
        
        assert "already registered" in result

    def test_register_nick_case_insensitive(self, nickserv_service):
        """Test that nick lookup is case-insensitive."""
        nickserv_service._register_nick("DaVeY", "davey@example.com", "password123")
        
        # Should exist in lowercase key
        assert "davey" in nickserv_service._registry
        # Original case should be preserved
        assert nickserv_service._registry["davey"]["nick"] == "DaVeY"

    def test_register_public_placeholder(self, nickserv_service):
        """Test that public register method returns placeholder."""
        result = nickserv_service.register("mail@example.com", "password")
        
        assert "must be called via PRIVMSG" in result

    def test_register_missing_email(self, nickserv_service):
        """Test register fails without email."""
        result = nickserv_service.register("", "password")
        
        assert "Error" in result

    def test_register_missing_password(self, nickserv_service):
        """Test register fails without password."""
        result = nickserv_service.register("mail@example.com", "")
        
        assert "Error" in result


class TestNickservIdentification:
    """Test nick identification functionality."""

    def test_ident_nick_success(self, nickserv_service):
        """Test successful nick identification."""
        nickserv_service._register_nick("Davey", "davey@example.com", "password123")
        success, msg = nickserv_service._ident_nick("Davey", "password123")
        
        assert success is True
        assert "identified successfully" in msg

    def test_ident_nick_wrong_password(self, nickserv_service):
        """Test identification fails with wrong password."""
        nickserv_service._register_nick("Davey", "davey@example.com", "password123")
        success, msg = nickserv_service._ident_nick("Davey", "wrongpassword")
        
        assert success is False
        assert "Password is incorrect" in msg

    def test_ident_nick_not_registered(self, nickserv_service):
        """Test identification fails for unregistered nick."""
        success, msg = nickserv_service._ident_nick("Unknown", "password")
        
        assert success is False
        assert "not registered" in msg

    def test_ident_public_placeholder(self, nickserv_service):
        """Test that public ident method returns placeholder."""
        result = nickserv_service.ident("password")
        
        assert "must be called via PRIVMSG" in result

    def test_ident_missing_password(self, nickserv_service):
        """Test ident fails without password."""
        result = nickserv_service.ident("")
        
        assert "Error" in result


class TestNickservInfo:
    """Test nick info retrieval."""

    def test_info_registered_nick(self, nickserv_service):
        """Test retrieving info for a registered nick."""
        nickserv_service._register_nick("Davey", "davey@example.com", "password123")
        result = nickserv_service.info("Davey")
        
        assert "Nick: Davey" in result
        assert "davey@example.com" in result

    def test_info_unregistered_nick(self, nickserv_service):
        """Test retrieving info for unregistered nick."""
        result = nickserv_service.info("Unknown")
        
        assert "not registered" in result

    def test_info_case_insensitive(self, nickserv_service):
        """Test info lookup is case-insensitive."""
        nickserv_service._register_nick("DaVeY", "davey@example.com", "password123")
        result = nickserv_service.info("davey")
        
        assert "Nick: DaVeY" in result


class TestNickservUnregister:
    """Test nick unregistration."""

    def test_unregister_success(self, nickserv_service):
        """Test successful nick unregistration."""
        nickserv_service._register_nick("Davey", "davey@example.com", "password123")
        result = nickserv_service.unregister("Davey")
        
        assert "has been unregistered" in result
        assert "davey" not in nickserv_service._registry

    def test_unregister_not_registered(self, nickserv_service):
        """Test unregister fails for unregistered nick."""
        result = nickserv_service.unregister("Unknown")
        
        assert "not registered" in result

    def test_unregister_case_insensitive(self, nickserv_service):
        """Test unregister is case-insensitive."""
        nickserv_service._register_nick("DaVeY", "davey@example.com", "password123")
        result = nickserv_service.unregister("davey")
        
        assert "has been unregistered" in result
        assert "davey" not in nickserv_service._registry


class TestNickservPersistence:
    """Test database persistence."""

    def test_save_and_load_db(self, nickserv_service, temp_dir):
        """Test that data persists to disk and can be reloaded."""
        # Register a nick
        nickserv_service._register_nick("User1", "user1@example.com", "password1")
        nickserv_service._register_nick("User2", "user2@example.com", "password2")
        
        # Verify file exists
        assert os.path.exists(nickserv_service.db_file)
        
        # Create new service instance with same DB file
        db_file = nickserv_service.db_file
        with patch('csc_service.server.service.Service.init_data'):
            new_service = Nickserv(MagicMock())
        new_service.db_file = db_file
        new_service._load_db()
        
        # Verify data was loaded
        assert "user1" in new_service._registry
        assert "user2" in new_service._registry
        assert new_service._registry["user1"]["email"] == "user1@example.com"
        assert new_service._registry["user2"]["email"] == "user2@example.com"

    def test_db_file_format(self, nickserv_service):
        """Test that DB file has correct format."""
        nickserv_service._register_nick("TestUser", "test@example.com", "testpass")
        
        with open(nickserv_service.db_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        
        parts = content.split(':')
        assert len(parts) == 4
        assert parts[0] == "TestUser"
        assert parts[2] == "test@example.com"
        # parts[1] is hash, parts[3] is timestamp

    def test_load_db_with_comments(self, nickserv_service):
        """Test that DB loading skips comments."""
        db_file = nickserv_service.db_file
        os.makedirs(os.path.dirname(db_file), exist_ok=True)
        
        # Write file with comments and blank lines
        with open(db_file, 'w', encoding='utf-8') as f:
            f.write("# This is a comment\n")
            f.write("\n")
            f.write("TestUser:hash123:test@example.com:1234567890.0\n")
        
        nickserv_service._load_db()
        assert "testuser" in nickserv_service._registry
        assert len(nickserv_service._registry) == 1

    def test_load_db_nonexistent(self, temp_dir):
        """Test loading DB when file doesn't exist."""
        db_file = os.path.join(temp_dir, "nonexistent", "nickserv.db")
        
        with patch('csc_service.server.service.Service.init_data'):
            service = Nickserv(MagicMock())
        service.db_file = db_file
        service._load_db()
        
        assert len(service._registry) == 0


class TestNickservPasswordHashing:
    """Test password hashing and verification."""

    def test_hash_password(self, nickserv_service):
        """Test password hashing."""
        hash1 = nickserv_service._hash_password("password123")
        hash2 = nickserv_service._hash_password("password123")
        
        # Same password should produce same hash
        assert hash1 == hash2
        # Hash should not be plaintext
        assert hash1 != "password123"

    def test_verify_password_correct(self, nickserv_service):
        """Test verifying correct password."""
        password = "correctpassword"
        hash_val = nickserv_service._hash_password(password)
        
        assert nickserv_service._verify_password(hash_val, password) is True

    def test_verify_password_incorrect(self, nickserv_service):
        """Test verifying incorrect password."""
        password = "correctpassword"
        hash_val = nickserv_service._hash_password(password)
        
        assert nickserv_service._verify_password(hash_val, "wrongpassword") is False


class TestNickservDataStructure:
    """Test the data structure and storage."""

    def test_registry_structure(self, nickserv_service):
        """Test that registry has correct structure."""
        nickserv_service._register_nick("TestNick", "test@example.com", "password")
        
        record = nickserv_service._registry["testnick"]
        assert "nick" in record
        assert "pass_hash" in record
        assert "email" in record
        assert "registered_timestamp" in record

    def test_registry_timestamp(self, nickserv_service):
        """Test that registration timestamp is set."""
        before = time.time()
        nickserv_service._register_nick("TestNick", "test@example.com", "password")
        after = time.time()
        
        timestamp = nickserv_service._registry["testnick"]["registered_timestamp"]
        assert before <= timestamp <= after

    def test_multiple_registrations(self, nickserv_service):
        """Test multiple nick registrations."""
        nickserv_service._register_nick("Nick1", "nick1@example.com", "pass1")
        nickserv_service._register_nick("Nick2", "nick2@example.com", "pass2")
        nickserv_service._register_nick("Nick3", "nick3@example.com", "pass3")
        
        assert len(nickserv_service._registry) == 3
        assert "nick1" in nickserv_service._registry
        assert "nick2" in nickserv_service._registry
        assert "nick3" in nickserv_service._registry


class TestNickservErrorHandling:
    """Test error handling."""

    def test_load_db_with_invalid_format(self, nickserv_service):
        """Test loading DB with invalid line format."""
        db_file = nickserv_service.db_file
        os.makedirs(os.path.dirname(db_file), exist_ok=True)
        
        # Write file with invalid format (too few colons)
        with open(db_file, 'w', encoding='utf-8') as f:
            f.write("InvalidLine\n")
            f.write("TestUser:hash:email@test.com:1234567890.0\n")
        
        # Should not raise, should skip invalid lines
        nickserv_service._load_db()
        assert "testuser" in nickserv_service._registry
        assert len(nickserv_service._registry) == 1

    def test_save_db_creates_directory(self, nickserv_service, temp_dir):
        """Test that _save_db creates directory if it doesn't exist."""
        # Set db_file to a path that doesn't exist yet
        db_file = os.path.join(temp_dir, "new", "dir", "nickserv.db")
        nickserv_service.db_file = db_file
        
        nickserv_service._register_nick("TestUser", "test@example.com", "password")
        
        assert os.path.exists(db_file)


class TestNickservIntegration:
    """Integration tests for complete workflows."""

    def test_register_and_identify_flow(self, nickserv_service):
        """Test complete registration and identification flow."""
        # Register
        reg_result = nickserv_service._register_nick("TestUser", "test@example.com", "password123")
        assert "successfully" in reg_result
        
        # Identify with correct password
        success, msg = nickserv_service._ident_nick("TestUser", "password123")
        assert success is True
        
        # Get info
        info = nickserv_service.info("TestUser")
        assert "TestUser" in info
        assert "test@example.com" in info
        
        # Unregister
        unreg_result = nickserv_service.unregister("TestUser")
        assert "unregistered" in unreg_result
        
        # Try to identify after unregister
        success, msg = nickserv_service._ident_nick("TestUser", "password123")
        assert success is False

    def test_multiple_users_workflow(self, nickserv_service):
        """Test workflow with multiple users."""
        users = [
            ("Alice", "alice@example.com", "alicepass"),
            ("Bob", "bob@example.com", "bobpass"),
            ("Charlie", "charlie@example.com", "charliepass"),
        ]
        
        # Register all users
        for nick, email, password in users:
            result = nickserv_service._register_nick(nick, email, password)
            assert "