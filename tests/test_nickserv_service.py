"""Tests for NickServ Service (nickserv_service.py).

Covers user registration, identification, unregistration, info queries,
and password hashing/verification.

Note: This tests the Nickserv service module directly (nickserv_service.py).
Separate tests for server-level NickServ handler integration exist in test_nickserv.py.
"""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# Ensure csc_service is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "csc-service"))

from csc_service.shared.services.nickserv_service import Nickserv


class TestNickservServiceBase(unittest.TestCase):
    """Base test class with common setup."""

    def setUp(self):
        """Set up test fixtures with a mocked server instance."""
        self.mock_server = Mock()
        self.mock_server.log = Mock()
        
        # Create a temporary directory for test DB file
        self.temp_dir = tempfile.mkdtemp()
        
        # Patch the db_file path to use our temp directory
        self.db_file_path = os.path.join(self.temp_dir, "nickserv.db")
        
        with patch.object(Nickserv, '_Nickserv__init__db_path', lambda self: self.db_file_path):
            self.service = Nickserv(self.mock_server)
            # Override db_file with our temp path
            self.service.db_file = self.db_file_path

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _add_registration(self, nick, email, password):
        """Helper to add a registration directly (useful for test setup)."""
        self.service._register_nick(nick, email, password)


class TestNickservInitialization(TestNickservServiceBase):
    """Test service initialization."""

    def test_service_initializes_with_server(self):
        """Test that service initializes with a server instance."""
        self.assertIsNotNone(self.service)
        self.assertEqual(self.service.name, "nickserv")

    def test_service_creates_empty_registry(self):
        """Test that service starts with empty registry."""
        self.assertEqual(len(self.service._registry), 0)

    def test_service_db_file_path_is_set(self):
        """Test that DB file path is configured."""
        self.assertIsNotNone(self.service.db_file)
        self.assertTrue(self.service.db_file.endswith("nickserv.db"))

    def test_service_logs_initialization(self):
        """Test that service logs initialization message."""
        self.mock_server.log.assert_called()


class TestPasswordHashing(TestNickservServiceBase):
    """Test password hashing and verification."""

    def test_hash_password_returns_string(self):
        """Test that hash_password returns a string."""
        result = self.service._hash_password("password123")
        self.assertIsInstance(result, str)

    def test_hash_password_is_deterministic(self):
        """Test that same password produces same hash."""
        pass1 = self.service._hash_password("password123")
        pass2 = self.service._hash_password("password123")
        self.assertEqual(pass1, pass2)

    def test_different_passwords_produce_different_hashes(self):
        """Test that different passwords produce different hashes."""
        hash1 = self.service._hash_password("password1")
        hash2 = self.service._hash_password("password2")
        self.assertNotEqual(hash1, hash2)

    def test_verify_password_success(self):
        """Test that correct password verifies."""
        password = "mypassword"
        hashed = self.service._hash_password(password)
        self.assertTrue(self.service._verify_password(hashed, password))

    def test_verify_password_failure(self):
        """Test that wrong password fails verification."""
        password = "mypassword"
        wrong_password = "wrongpassword"
        hashed = self.service._hash_password(password)
        self.assertFalse(self.service._verify_password(hashed, wrong_password))

    def test_verify_password_case_sensitive(self):
        """Test that password verification is case-sensitive."""
        password = "MyPassword"
        wrong_case = "mypassword"
        hashed = self.service._hash_password(password)
        self.assertFalse(self.service._verify_password(hashed, wrong_case))

    def test_hash_password_md5_format(self):
        """Test that hashed password looks like MD5 (hex string, 32 chars)."""
        hashed = self.service._hash_password("test")
        self.assertEqual(len(hashed), 32)
        self.assertTrue(all(c in '0123456789abcdef' for c in hashed))


class TestRegisterNick(TestNickservServiceBase):
    """Test nick registration."""

    def test_register_nick_success(self):
        """Test successful nick registration."""
        result = self.service._register_nick("alice", "alice@example.com", "secret123")
        self.assertIn("registered successfully", result.lower())
        self.assertIn("alice", result)

    def test_register_nick_adds_to_registry(self):
        """Test that registration adds nick to registry."""
        self.service._register_nick("bob", "bob@example.com", "password")
        self.assertIn("bob", self.service._registry)

    def test_register_nick_stores_correct_data(self):
        """Test that registration stores correct data in registry."""
        email = "user@example.com"
        self.service._register_nick("alice", email, "password123")
        
        record = self.service._registry["alice"]
        self.assertEqual(record['nick'], "alice")
        self.assertEqual(record['email'], email)
        self.assertIsNotNone(record['pass_hash'])
        self.assertIsNotNone(record['registered_timestamp'])

    def test_register_nick_case_insensitive(self):
        """Test that nick lookup is case-insensitive."""
        self.service._register_nick("Alice", "alice@example.com", "password")
        # Should be in registry under lowercase key
        self.assertIn("alice", self.service._registry)
        self.assertEqual(self.service._registry["alice"]['nick'], "Alice")

    def test_register_duplicate_nick_fails(self):
        """Test that registering the same nick twice fails."""
        self.service._register_nick("alice", "alice@example.com", "password1")
        result = self.service._register_nick("alice", "alice2@example.com", "password2")
        self.assertIn("already registered", result.lower())
        self.assertIn("error", result.lower())

    def test_register_duplicate_case_insensitive(self):
        """Test that duplicate check is case-insensitive."""
        self.service._register_nick("alice", "alice@example.com", "password1")
        result = self.service._register_nick("ALICE", "alice2@example.com", "password2")
        self.assertIn("already registered", result.lower())

    def test_register_saves_to_disk(self):
        """Test that registration persists to disk."""
        self.service._register_nick("alice", "alice@example.com", "password")
        self.assertTrue(os.path.exists(self.service.db_file))

    def test_register_with_special_characters_in_email(self):
        """Test registration with special characters in email."""
        result = self.service._register_nick(
            "alice",
            "alice+tag@example.co.uk",
            "password"
        )
        self.assertIn("registered successfully", result.lower())
        self.assertEqual(self.service._registry["alice"]['email'], "alice+tag@example.co.uk")

    def test_register_timestamp_is_set(self):
        """Test that registration timestamp is recorded."""
        before = time.time()
        self.service._register_nick("alice", "alice@example.com", "password")
        after = time.time()
        
        record = self.service._registry["alice"]
        self.assertTrue(before <= record['registered_timestamp'] <= after)


class TestIdentNick(TestNickservServiceBase):
    """Test nick identification."""

    def test_ident_unregistered_nick_fails(self):
        """Test that identifying with unregistered nick fails."""
        success, msg = self.service._ident_nick("unregistered", "password")
        self.assertFalse(success)
        self.assertIn("not registered", msg.lower())

    def test_ident_correct_password_succeeds(self):
        """Test that identifying with correct password succeeds."""
        self.service._register_nick("alice", "alice@example.com", "secret123")
        success, msg = self.service._ident_nick("alice", "secret123")
        self.assertTrue(success)
        self.assertIn("identified successfully", msg.lower())

    def test_ident_wrong_password_fails(self):
        """Test that identifying with wrong password fails."""
        self.service._register_nick("alice", "alice@example.com", "correct")
        success, msg = self.service._ident_nick("alice", "wrong")
        self.assertFalse(success)
        self.assertIn("password", msg.lower())
        self.assertIn("incorrect", msg.lower())

    def test_ident_case_insensitive(self):
        """Test that identification is case-insensitive for nick."""
        self.service._register_nick("Alice", "alice@example.com", "password")
        success, msg = self.service._ident_nick("alice", "password")
        self.assertTrue(success)

    def test_ident_password_case_sensitive(self):
        """Test that password identification is case-sensitive."""
        self.service._register_nick("alice", "alice@example.com", "MyPassword")
        success, msg = self.service._ident_nick("alice", "mypassword")
        self.assertFalse(success)

    def test_ident_returns_tuple(self):
        """Test that ident returns a tuple of (bool, str)."""
        result = self.service._ident_nick("notexist", "pass")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], str)

    def test_ident_multiple_nicks_independent(self):
        """Test that identification works independently for multiple nicks."""
        self.service._register_nick("alice", "alice@example.com", "pass_a")
        self.service._register_nick("bob", "bob@example.com", "pass_b")
        
        success_a, _ = self.service._ident_nick("alice", "pass_a")
        success_b, _ = self.service._ident_nick("bob", "pass_b")
        
        self.assertTrue(success_a)
        self.assertTrue(success_b)


class TestUnregisterNick(TestNickservServiceBase):
    """Test nick unregistration."""

    def test_unregister_existing_nick(self):
        """Test unregistering an existing nick."""
        self.service._register_nick("alice", "alice@example.com", "password")
        result = self.service.unregister("alice")
        self.assertIn("unregistered", result.lower())
        self.assertIn("alice", result)

    def test_unregister_removes_from_registry(self):
        """Test that unregister removes nick from registry."""
        self.service._register_nick("alice", "alice@example.com", "password")
        self.service.unregister("alice")
        self.assertNotIn("alice", self.service._registry)

    def test_unregister_nonexistent_nick(self):
        """Test unregistering a nick that doesn't exist."""
        result = self.service.unregister("nonexistent")
        self.assertIn("not registered", result.lower())
        self.assertIn("error", result.lower())

    def test_unregister_case_insensitive(self):
        """Test that unregister is case-insensitive."""
        self.service._register_nick("Alice", "alice@example.com", "password")
        result = self.service.unregister("alice")
        self.assertIn("unregistered", result.lower())

    def test_unregister_saves_to_disk(self):
        """Test that unregister persists to disk."""
        self.service._register_nick("alice", "alice@example.com", "password")
        self.service.unregister("alice")
        
        # Reload from disk to verify
        self.service._load_db()
        self.assertNotIn("alice", self.service._registry)

    def test_unregister_requires_nick_argument(self):
        """Test that unregister requires a nick argument."""
        result = self.service.unregister("")
        self.assertIn("error", result.lower())
        self.assertIn("requires", result.lower())


class TestInfoCommand(TestNickservServiceBase):
    """Test nick info retrieval."""

    def test_info_unregistered_nick(self):
        """Test info for unregistered nick returns error."""
        result = self.service.info("nonexistent")
        self.assertIn("not registered", result.lower())

    def test_info_registered_nick(self):
        """Test info for registered nick returns details."""
        self.service._register_nick("alice", "alice@example.com", "password")
        result = self.service.info("alice")
        self.assertIn("Nick: Alice", result)
        self.assertIn("Email: alice@example.com", result)
        self.assertIn("Registered:", result)

    def test_info_hides_password_hash(self):
        """Test that info does not expose password hash."""
        self.service._register_nick("alice", "alice@example.com", "secret123")
        result = self.service.info("alice")
        # Password hash should not be visible
        pass_hash = self.service._registry["alice"]['pass_hash']
        self.assertNotIn(pass_hash, result)

    def test_info_shows_registration_date(self):
        """Test that info shows registration timestamp."""
        self.service._register_nick("alice", "alice@example.com", "password")
        result = self.service.info("alice")
        # Should show formatted date
        self.assertIn("20", result)  # Year should be 20xx
        self.assertIn("-", result)   # Date separator

    def test_info_case_insensitive(self):
        """Test that info lookup is case-insensitive."""
        self.service._register_nick("Alice", "alice@example.com", "password")
        result = self.service.info("alice")
        self.assertIn("alice", result.lower())

    def test_info_requires_nick_argument(self):
        """Test that info requires a nick argument."""
        result = self.service.info("")
        self.assertIn("error", result.lower())
        self.assertIn("requires", result.lower())

    def test_info_preserves_original_nick_case(self):
        """Test that info shows the nick with original case."""
        self.service._register_nick("AlIcE", "alice@example.com", "password")
        result = self.service.info("alice")
        self.assertIn("Nick: AlIcE", result)


class TestIsRegisteredCheck(TestNickservServiceBase):
    """Test is_registered check method."""

    def test_is_registered_returns_bool(self):
        """Test that is_registered returns a boolean."""
        result = self.service.is_registered("alice")
        self.assertIsInstance(result, bool)

    def test_is_registered_true(self):
        """Test is_registered returns True for registered nick."""
        self.service._register_nick("alice", "alice@example.com", "password")
        self.assertTrue(self.service.is_registered("alice"))

    def test_is_registered_false(self):
        """Test is_registered returns False for unregistered nick."""
        self.assertFalse(self.service.is_registered("unregistered"))

    def test_is_registered_case_insensitive(self):
        """Test that is_registered is case-insensitive."""
        self.service._register_nick("Alice", "alice@example.com", "password")
        self.assertTrue(self.service.is_registered("alice"))
        self.assertTrue(self.service.is_registered("ALICE"))


class TestDatabasePersistence(TestNickservServiceBase):
    """Test database save/load functionality."""

    def test_save_db_creates_file(self):
        """Test that _save_db creates the database file."""
        self.service._register_nick("alice", "alice@example.com", "password")
        self.assertTrue(os.path.exists(self.service.db_file))

    def test_save_db_file_format(self):
        """Test that database file is saved in correct format."""
        self.service._register_nick("alice", "alice@example.com", "password")
        
        with open(self.service.db_file, 'r') as f:
            content = f.read()
        
        # Should have format: nick:hash:email:timestamp
        lines = content.strip().split('\n')
        self.assertEqual(len(lines), 1)
        parts = lines[0].split(':')
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[0], "alice")
        self.assertEqual(parts[2], "alice@example.com")

    def test_load_db_empty_file(self):
        """Test loading from empty database file."""
        # Create empty DB file
        open(self.service.db_file, 'w').close()
        self.service._load_db()
        self.assertEqual(len(self.service._registry), 0)

    def test_load_db_single_entry(self):
        """Test loading a single entry from database."""
        self.service._register_nick("alice", "alice@example.com", "password")
        
        # Create new service instance to test load
        service2 = Nickserv(self.mock_server)
        service2.db_file = self.service.db_file
        service2._load_db()
        
        self.assertIn("alice", service2._registry)
        self.assertEqual(service2._registry["alice"]['email'], "alice@example.com")

    def test_load_db_multiple_entries(self):
        """Test loading multiple entries from database."""
        self.service._register_nick("alice", "alice@example.com", "pass_a")
        self.service._register_nick("bob", "bob@example.com", "pass_b")
        self.service._register_nick("charlie", "charlie@example.com", "pass_c")
        
        service2 = Nickserv(self.mock_server)
        service2.db_file = self.service.db_file
        service2._load_db()
        
        self.assertEqual(len(service2._registry), 3)
        self.assertIn("alice", service2._registry)
        self.assertIn("bob", service2._registry)
        self.assertIn("charlie", service2._registry)

    def test_load_db_ignores_comments(self):
        """Test that load_db ignores comment lines."""
        # Write a file with comments
        with open(self.service.db_file, 'w') as f:
            f.write("# This is a comment\n")
            f.write("alice:hash1234:alice@example.com:1234567890.5\n")
            f.write("# Another comment\n")
        
        self.service._load_db()
        self.assertEqual(len(self.service._registry), 1)
        self.assertIn("alice", self.service._registry)

    def test_load_db_handles_malformed_lines(self):
        """Test that load_db skips malformed lines."""
        with open(self.service.db_file, 'w') as f:
            f.write("alice:hash1234:alice@example.com:1234567890.5\n")
            f.write("malformed_line_without_colons\n")
            f.write("bob:hash5678:bob@example.com:1234567890.5\n")
        
        self.service._load_db()
        self.assertEqual(len(self.service._registry), 2)
        self.assertIn("alice", self.service._registry)
        self.assertIn("bob", self.service._registry)

    def test_save_db_sorted_output(self):
        """Test that save_db writes entries in sorted order."""
        self.service._register_nick("charlie", "charlie@example.com", "pass_c")
        self.service._register_nick("alice", "alice@example.com", "pass_a")
        self.service._register_nick("bob", "bob@example.com", "pass_b")
        
        with open(self.service.db_file, 'r') as f:
            lines = f.read().strip().split('\n')
        
        nicks = [line.split(':')[0] for line in lines]
        self.assertEqual(nicks, sorted(nicks))


class TestDefaultCommand(TestNickservServiceBase):
    """Test default/help command."""

    def test_default_returns_string(self):
        """Test that default() returns a string."""
        result = self.service.default()
        self.assertIsInstance(result, str)

    def test_default_shows_available_commands(self):
        """Test that default() lists available commands."""
        result = self.service.default()
        self.assertIn("REGISTER", result)
        self.assertIn("IDENT", result)
        self.assertIn("UNREGISTER", result)
        self.assertIn("INFO", result)

    def test_default_shows_command_syntax(self):
        """Test that default() shows command syntax."""
        result = self.service.default()
        self.assertIn("<email>", result.lower())
        self.assertIn("<password>", result.lower())

    def test_default_with_args(self):
        """Test that default() handles arguments (should still show help)."""
        result = self.service.default("ignored", "args")
        self.assertIsInstance(result, str)
        self.assertIn("NickServ", result)


class TestPublicRegisterIdentMethods(TestNickservServiceBase):
    """Test public register() and ident() methods (IRC integration stubs)."""

    def test_register_public_method_requires_args(self):
        """Test public register() method with missing arguments."""
        result = self.service.register("", "")
        self.assertIn("Error", result)
        self.assertIn("requires", result.lower())

    def test_register_public_method_returns_error_message(self):
        """Test that public register() returns error (needs IRC integration)."""
        result = self.service.register("alice@example.com", "password")
        # This is a stub that indicates IRC integration is needed
        self.assertIsInstance(result, str)
        self.assertIn("Error", result)

    def test_ident_public_method_requires_password(self):
        """Test public ident() method with missing password."""
        result = self.service.ident("")
        self.assertIn("Error", result)
        self.assertIn("requires", result.lower())

    def test_ident_public_method_returns_error_message(self):
        """Test that public ident() returns error (needs IRC integration)."""
        result = self.service.ident("password")
        # This is a stub that indicates IRC integration is needed
        self.assertIsInstance(result, str)
        self.assertIn("Error", result)


class TestIntegrationScenarios(TestNickservServiceBase):
    """Test realistic end-to-end scenarios."""

    def test_full_registration_and_identification_flow(self):
        """Test complete registration and identification workflow."""
        # Register
        reg_result = self.service._register_nick("alice", "alice@example.com", "secret123")
        self.assertIn("registered successfully", reg_result.lower())
        
        # Identify with correct password
        ident_success, ident_msg = self.service._ident_nick("alice", "secret123")
        self.assertTrue(ident_success)
        self.assertIn("identified successfully", ident_msg.lower())
        
        # Identify with wrong password
        ident_success, ident_msg = self.service._ident_nick("alice", "wrongpass")
        self.assertFalse(ident_success)

    def test_multiple_users_independent_registrations(self):
        """Test that multiple users can register independently."""
        self.service._register_nick("alice", "alice@example.com", "pass_a")
        self.service._register_nick("bob", "bob@example.com", "pass_b")
        self.service._register_nick("charlie", "charlie@example.com", "pass_c")
        
        # Each should identify independently
        alice_ok, _ = self.service._ident_nick("alice", "pass_a")
        bob_ok, _ = self.service._ident_nick("bob", "pass_b")
        charlie_ok, _ = self.service._ident_nick("charlie", "pass_c")
        
        self.assertTrue(alice_ok)
        self.assertTrue(bob_ok)
        self.assertTrue(charlie_ok)
        
        # Bob shouldn't be able to use Alice's password
        bob_fail, _ = self.service._ident_nick("bob", "pass_a")
        self.assertFalse(bob_fail)

    def test_register_identify_unregister_cycle(self):
        """Test registering, identifying, then unregistering."""
        # Register
        self.service._register_nick("alice", "alice@example.com", "password")
        self.assertTrue(self.service.is_registered("alice"))
        
        # Identify
        success, _ = self.service._ident_nick("alice", "password")
        self.assertTrue(success)
        
        # Unregister
        unreg_result = self.service.unregister("alice")
        self.assertIn("unregistered", unreg_result.lower())
        self.assertFalse(self.service.is_registered("alice"))
        
        # Should not be able to identify after unregistration
        success, _ = self.service._ident_nick("alice", "password")
        self.assertFalse(success)

    def test_info_after_registration_persistence(self):
        """Test that info works correctly after database reload."""
        # Register
        self.service._register_nick("alice", "alice@example.com", "password")
        
        # Get info
        info1 = self.service.info("alice")
        self.assertIn("alice@example.com", info1)
        
        # Reload from disk
        self.service._load_db()
        
        # Get info again
        info2 = self.service.info("alice")
        self.assertIn("alice@example.com", info2)
        
        # Info should be consistent
        self.assertEqual(info1, info2)

    def test_many_users_registration(self):
        """Test registration of many users."""
        for i in range(100):
            nick = f"user_{i:03d}"
            email = f"user{i}@example.com"
            password = f"pass_{i}"
            result = self.service._register_nick(nick, email, password)
            self.assertIn("registered successfully", result.lower())
        
        # Verify all are in registry
        self.assertEqual(len(self.service._registry), 100)
        
        # Verify each can identify
        for i in range(0, 100, 10):  # Sample check every 10th user
            nick = f"user_{i:03d}"
            password = f"pass_{i}"
            success, _ = self.service._ident_nick(nick, password)
            self.assertTrue(success)


if __name__ == "__main__":
    unittest.main()
