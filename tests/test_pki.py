"""
Comprehensive test suite for the PKI certificate enrollment system.

Tests the PKI service IRC commands, enrollment server HTTP endpoints,
token management, certificate status checking, and Platform.check_s2s_cert().
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, mock_open
from http.server import HTTPServer
import threading
import io


# ---------------------------------------------------------------------------
# PKI Service (IRC command handler) tests
# ---------------------------------------------------------------------------

class TestPKIServiceToken(unittest.TestCase):
    """Test PKI TOKEN command."""

    def setUp(self):
        self.mock_server = Mock()
        # Patch token file to use temp dir
        self.tmpdir = tempfile.mkdtemp()
        self.token_file = Path(self.tmpdir) / "pki_tokens.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("csc_service.shared.services.pki_service.TOKEN_FILE")
    @patch("csc_service.shared.services.pki_service._save_tokens")
    @patch("csc_service.shared.services.pki_service._load_tokens")
    def test_token_generates_for_new_shortname(self, mock_load, mock_save, mock_file):
        """Test that TOKEN command generates a token for a new shortname."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        mock_load.return_value = {}
        mock_file.__class__ = type(self.token_file)

        service = pki(self.mock_server)
        result = service.token("crest.a2b3")

        self.assertIn("Enrollment token for crest.a2b3:", result)
        mock_save.assert_called_once()
        # Verify token was saved with correct structure
        saved_tokens = mock_save.call_args[0][0]
        self.assertEqual(len(saved_tokens), 1)
        token_key = list(saved_tokens.keys())[0]
        self.assertEqual(saved_tokens[token_key]["shortname"], "crest.a2b3")
        self.assertFalse(saved_tokens[token_key]["used"])

    @patch("csc_service.shared.services.pki_service._save_tokens")
    @patch("csc_service.shared.services.pki_service._load_tokens")
    def test_token_rejects_duplicate_active(self, mock_load, mock_save):
        """Test that TOKEN rejects when an active token already exists."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        mock_load.return_value = {
            "existing_token": {
                "shortname": "crest.a2b3",
                "created_at": time.time(),
                "used": False,
            }
        }

        service = pki(self.mock_server)
        result = service.token("crest.a2b3")

        self.assertIn("Active token already exists", result)
        mock_save.assert_not_called()

    @patch("csc_service.shared.services.pki_service._save_tokens")
    @patch("csc_service.shared.services.pki_service._load_tokens")
    def test_token_allows_after_used(self, mock_load, mock_save):
        """Test that TOKEN allows a new token if previous was used."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        mock_load.return_value = {
            "old_token": {
                "shortname": "crest.a2b3",
                "created_at": time.time(),
                "used": True,
            }
        }

        service = pki(self.mock_server)
        result = service.token("crest.a2b3")

        self.assertIn("Enrollment token for crest.a2b3:", result)
        mock_save.assert_called_once()

    def test_token_missing_shortname(self):
        """Test that TOKEN without shortname returns usage."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        service = pki(self.mock_server)
        result = service.token()

        self.assertIn("Usage:", result)


class TestPKIServiceList(unittest.TestCase):
    """Test PKI LIST command."""

    def setUp(self):
        self.mock_server = Mock()

    @patch("csc_service.shared.services.pki_service.ISSUED_DIR")
    def test_list_no_certs(self, mock_dir):
        """Test LIST when no certs are issued."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        mock_dir.exists.return_value = False

        service = pki(self.mock_server)
        result = service.list()

        self.assertIn("not found", result.lower())

    @patch("subprocess.run")
    @patch("csc_service.shared.services.pki_service.ISSUED_DIR")
    def test_list_with_certs(self, mock_dir, mock_run):
        """Test LIST with issued certificates."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        mock_dir.exists.return_value = True

        # Mock glob to return cert files
        mock_crt = MagicMock()
        mock_crt.stem = "haven.ef6e"
        mock_dir.glob.return_value = [mock_crt]

        # Mock openssl output
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="notAfter=Mar 11 00:00:00 2027 GMT\nserial=ABCD1234\n",
        )

        service = pki(self.mock_server)
        result = service.list()

        self.assertIn("haven.ef6e", result)
        self.assertIn("Issued certificates", result)


class TestPKIServiceRevoke(unittest.TestCase):
    """Test PKI REVOKE command."""

    def setUp(self):
        self.mock_server = Mock()

    def test_revoke_missing_shortname(self):
        """Test REVOKE without shortname returns usage."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        service = pki(self.mock_server)
        result = service.revoke()

        self.assertIn("Usage:", result)

    @patch("csc_service.shared.services.pki_service.ISSUED_DIR")
    def test_revoke_nonexistent_cert(self, mock_dir):
        """Test REVOKE with non-existent certificate."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        mock_cert = MagicMock()
        mock_cert.exists.return_value = False
        mock_dir.__truediv__ = Mock(return_value=mock_cert)

        service = pki(self.mock_server)
        result = service.revoke("nonexistent.host")

        self.assertIn("No certificate found", result)


class TestPKIServiceStatus(unittest.TestCase):
    """Test PKI STATUS command."""

    def setUp(self):
        self.mock_server = Mock()

    @patch("csc_service.shared.services.pki_service._load_tokens")
    @patch("csc_service.shared.services.pki_service.ISSUED_DIR")
    @patch("csc_service.shared.services.pki_service.CRL_PEM")
    @patch("csc_service.shared.services.pki_service.CA_CRT")
    def test_status_no_ca(self, mock_ca, mock_crl, mock_issued, mock_tokens):
        """Test STATUS when CA is not present."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        mock_ca.exists.return_value = False
        mock_crl.exists.return_value = False
        mock_issued.exists.return_value = False
        mock_tokens.return_value = {}

        service = pki(self.mock_server)
        result = service.status()

        self.assertIn("CA: NOT FOUND", result)
        self.assertIn("CRL: not generated", result)

    @patch("subprocess.run")
    @patch("csc_service.shared.services.pki_service._load_tokens")
    @patch("csc_service.shared.services.pki_service.ISSUED_DIR")
    @patch("csc_service.shared.services.pki_service.CRL_PEM")
    @patch("csc_service.shared.services.pki_service.CA_CRT")
    def test_status_with_ca(self, mock_ca, mock_crl, mock_issued, mock_tokens, mock_run):
        """Test STATUS when CA is present."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        mock_ca.exists.return_value = True
        mock_crl.exists.return_value = False
        mock_issued.exists.return_value = True
        mock_issued.glob.return_value = [MagicMock(), MagicMock()]
        mock_tokens.return_value = {
            "tok1": {"used": False, "created_at": time.time()},
            "tok2": {"used": True, "created_at": time.time()},
        }

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="notAfter=Mar 11 00:00:00 2030 GMT\n",
        )

        service = pki(self.mock_server)
        result = service.status()

        self.assertIn("CA: present", result)
        self.assertIn("Tokens: 1 active, 1 used", result)
        self.assertIn("Issued certs: 2", result)


class TestPKIServicePending(unittest.TestCase):
    """Test PKI PENDING command."""

    def setUp(self):
        self.mock_server = Mock()

    @patch("csc_service.shared.services.pki_service._save_tokens")
    @patch("csc_service.shared.services.pki_service._load_tokens")
    def test_pending_no_tokens(self, mock_load, mock_save):
        """Test PENDING with no active tokens."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        mock_load.return_value = {}

        service = pki(self.mock_server)
        result = service.pending()

        self.assertIn("No pending tokens", result)

    @patch("csc_service.shared.services.pki_service._save_tokens")
    @patch("csc_service.shared.services.pki_service._load_tokens")
    def test_pending_with_tokens(self, mock_load, mock_save):
        """Test PENDING with active tokens."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        now = time.time()
        mock_load.return_value = {
            "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890": {
                "shortname": "crest.a2b3",
                "created_at": now,
                "used": False,
            },
            "usedtoken123456": {
                "shortname": "old.host",
                "created_at": now,
                "used": True,
            },
        }

        service = pki(self.mock_server)
        result = service.pending()

        self.assertIn("Pending tokens (1)", result)
        self.assertIn("crest.a2b3", result)
        self.assertNotIn("old.host", result)


class TestPKIServiceDefault(unittest.TestCase):
    """Test PKI default handler."""

    def setUp(self):
        self.mock_server = Mock()

    def test_default_shows_help(self):
        """Test default handler returns command help."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        service = pki(self.mock_server)
        result = service.default()

        self.assertIn("PKI commands:", result)
        self.assertIn("TOKEN", result)
        self.assertIn("LIST", result)
        self.assertIn("REVOKE", result)
        self.assertIn("STATUS", result)
        self.assertIn("PENDING", result)


# ---------------------------------------------------------------------------
# Token management utility tests
# ---------------------------------------------------------------------------

class TestTokenManagement(unittest.TestCase):
    """Test token load/save/prune utilities."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.token_file = Path(self.tmpdir) / "pki_tokens.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("csc_service.shared.services.pki_service.TOKEN_FILE")
    def test_load_tokens_empty(self, mock_file):
        """Test loading tokens when file doesn't exist."""
        from csc_service.shared.services.pki_service import _load_tokens

        mock_file.exists.return_value = False
        result = _load_tokens()
        self.assertEqual(result, {})

    def test_prune_expired_tokens(self):
        """Test pruning of expired tokens."""
        from csc_service.shared.services.pki_service import _prune_expired

        tokens = {
            "fresh": {"created_at": time.time(), "used": False},
            "expired": {"created_at": time.time() - 100000, "used": False},
        }

        pruned = _prune_expired(tokens)
        self.assertEqual(pruned, 1)
        self.assertIn("fresh", tokens)
        self.assertNotIn("expired", tokens)


# ---------------------------------------------------------------------------
# Enrollment server tests
# ---------------------------------------------------------------------------

class TestEnrollmentServerEnroll(unittest.TestCase):
    """Test enrollment endpoint."""

    @patch("csc_service.shared.services.pki_service._save_tokens")
    @patch("csc_service.shared.services.pki_service._load_tokens")
    def test_token_normalizes_shortname(self, mock_load, mock_save):
        """Test that shortname is normalized to lowercase."""
<<<<<<< HEAD
        from csc_service.shared.services.pki_service import Pki as pki
=======
        from csc_service.shared.services.pki_service import pki
>>>>>>> origin/feature/pki-certificate-enrollment

        mock_load.return_value = {}

        service = pki(Mock())
        result = service.token("Haven.EF6E")

        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        token_key = list(saved.keys())[0]
        self.assertEqual(saved[token_key]["shortname"], "haven.ef6e")


class TestEnrollmentServerRouting(unittest.TestCase):
    """Test enrollment server HTTP routing."""

    def test_handler_class_exists(self):
        """Test that PKIRequestHandler class is importable."""
        from csc_service.pki.enrollment_server import PKIRequestHandler
        self.assertIsNotNone(PKIRequestHandler)

    def test_run_server_function_exists(self):
        """Test that run_server function is importable."""
        from csc_service.pki.enrollment_server import run_server
        self.assertTrue(callable(run_server))


# ---------------------------------------------------------------------------
# PKI main entry point tests
# ---------------------------------------------------------------------------

class TestPKIMain(unittest.TestCase):
    """Test PKI main module."""

    def test_start_function_exists(self):
        """Test that start() is importable."""
        from csc_service.pki.main import start
        self.assertTrue(callable(start))

    def test_is_alive_when_not_started(self):
        """Test is_alive returns False when not started."""
        from csc_service.pki.main import is_alive
        # Reset the module-level thread reference
        import csc_service.pki.main as pki_main
        pki_main._thread = None
        self.assertFalse(is_alive())


# ---------------------------------------------------------------------------
# Platform.check_s2s_cert() tests
# ---------------------------------------------------------------------------

class TestCheckS2SCert(unittest.TestCase):
    """Test Platform.check_s2s_cert() classmethod."""

    def test_no_config(self):
        """Test with empty config returns not configured."""
        from csc_service.shared.platform import Platform

        ok, reason = Platform.check_s2s_cert(config={})
        self.assertFalse(ok)
        self.assertIn("not configured", reason)

    def test_missing_cert_file(self):
        """Test with non-existent cert file."""
        from csc_service.shared.platform import Platform

        ok, reason = Platform.check_s2s_cert(
            config={"s2s_cert": "/nonexistent/path/cert.pem"}
        )
        self.assertFalse(ok)
        self.assertIn("not found", reason)

    @patch("subprocess.run")
    def test_expired_cert(self, mock_run):
        """Test with expired certificate."""
        from csc_service.shared.platform import Platform

        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as f:
            f.write(b"fake cert")
            cert_path = f.name

        try:
            # First call (checkend 0) returns non-zero = expired
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")

            ok, reason = Platform.check_s2s_cert(
                config={"s2s_cert": cert_path}
            )
            self.assertFalse(ok)
            self.assertIn("expired", reason)
        finally:
            os.unlink(cert_path)

    @patch("subprocess.run")
    def test_valid_cert(self, mock_run):
        """Test with valid certificate."""
        from csc_service.shared.platform import Platform

        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as f:
            f.write(b"fake cert")
            cert_path = f.name

        try:
            # Both checkend calls return 0 = not expired
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            ok, reason = Platform.check_s2s_cert(
                config={"s2s_cert": cert_path}
            )
            self.assertTrue(ok)
            self.assertEqual(reason, "valid")
        finally:
            os.unlink(cert_path)

    @patch("subprocess.run")
    def test_cert_expiring_soon(self, mock_run):
        """Test with certificate expiring within 30 days."""
        from csc_service.shared.platform import Platform

        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as f:
            f.write(b"fake cert")
            cert_path = f.name

        try:
            # First checkend (0 seconds) = ok, second (30 days) = expiring
            mock_run.side_effect = [
                MagicMock(returncode=0),  # checkend 0 — not expired
                MagicMock(returncode=1),  # checkend 2592000 — expiring within 30 days
            ]

            ok, reason = Platform.check_s2s_cert(
                config={"s2s_cert": cert_path}
            )
            self.assertTrue(ok)
            self.assertIn("expiring within 30 days", reason)
        finally:
            os.unlink(cert_path)


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------

class TestCLIEnrollCommand(unittest.TestCase):
    """Test csc-ctl enroll command handler."""

    def test_get_server_shortname_from_hostname(self):
        """Test fallback to hostname when server_name file doesn't exist."""
        from csc_service.cli.commands.pki_cmd import _get_server_shortname

        with patch("csc_service.cli.commands.pki_cmd.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            with patch("socket.gethostname", return_value="test.host.example"):
                name = _get_server_shortname()
                self.assertEqual(name, "test")

    def test_generate_key_and_csr(self):
        """Test key/CSR generation function exists and is callable."""
        from csc_service.cli.commands.pki_cmd import _generate_key_and_csr
        self.assertTrue(callable(_generate_key_and_csr))


class TestCLICertStatusCommand(unittest.TestCase):
    """Test csc-ctl cert status command handler."""

    def test_cert_status_function_exists(self):
        """Test cert_status function is importable."""
        from csc_service.cli.commands.pki_cmd import cert_status
        self.assertTrue(callable(cert_status))


# ---------------------------------------------------------------------------
# Status/service_cmd integration tests
# ---------------------------------------------------------------------------

class TestInprocServicesPKI(unittest.TestCase):
    """Test that PKI is registered in INPROC_SERVICES."""

    def test_pki_in_inproc_services(self):
        """Test PKI is listed in status_cmd INPROC_SERVICES."""
        from csc_service.cli.commands.status_cmd import INPROC_SERVICES

        self.assertIn("enable_pki", INPROC_SERVICES)
        self.assertEqual(INPROC_SERVICES["enable_pki"], "pki")

    def test_pki_in_unit_map(self):
        """Test PKI is listed in service_cmd UNIT_MAP."""
        from csc_service.cli.commands.service_cmd import UNIT_MAP

        self.assertIn("pki", UNIT_MAP)
        unit, scope = UNIT_MAP["pki"]
        self.assertEqual(unit, "csc-service.service")
        self.assertEqual(scope, "user")


# ---------------------------------------------------------------------------
# PKI log format tests
# ---------------------------------------------------------------------------

class TestPKILogFormat(unittest.TestCase):
    """Test PKI log writing format."""

    def test_write_pki_log_format(self):
        """Test that log entries match expected format."""
        from csc_service.shared.services.pki_service import _write_pki_log

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False
        ) as f:
            log_path = f.name

        try:
            with patch(
                "csc_service.shared.services.pki_service.PKI_LOG",
                Path(log_path),
            ):
                _write_pki_log("cert issued:  haven.ef6e  valid 2026-03-11 → 2027-03-11")

            content = Path(log_path).read_text(encoding="utf-8")
            self.assertIn("[PKI]", content)
            self.assertIn("cert issued:", content)
            self.assertIn("haven.ef6e", content)
            # Verify timestamp format (ISO 8601)
            self.assertRegex(content, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        finally:
            os.unlink(log_path)


if __name__ == "__main__":
    unittest.main()
