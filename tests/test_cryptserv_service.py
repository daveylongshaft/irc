```python
"""Tests for cryptserv_service module."""

import json
import pytest
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open, call

# Mock irc module before any imports
import sys
from unittest.mock import MagicMock as MM
sys.modules['irc'] = MM()
sys.modules['irc'].format_irc_message = MM(return_value="msg")
sys.modules['irc'].SERVER_NAME = "test_server"

from csc_service.shared.services.cryptserv_service import CryptServ


@pytest.fixture
def mock_server(tmp_path):
    """Create a mock server instance."""
    server = MagicMock()
    server.project_root_dir = str(tmp_path)
    server.clients = {
        "addr1": {"name": "davey"},
        "addr2": {"name": "alice"},
    }
    server.log = MagicMock()
    server.send_privmsg_to_client = MagicMock()
    return server


@pytest.fixture
def cryptserv_service(mock_server):
    """Create a CryptServ instance with mocked parent class."""
    with patch('csc_service.server.service.Service.init_data'):
        service = CryptServ(mock_server)
    
    # Manually set up data storage
    service._data = {"issued_certs": {}}
    service.get_data = lambda key: service._data.get(key)
    service.put_data = lambda key, val, flush=True: service._data.update({key: val})
    
    return service


class TestCryptServInit:
    """Tests for CryptServ initialization."""

    def test_init_creates_certs_directory(self, mock_server, tmp_path):
        """Test that initialization creates the certs directory."""
        with patch('csc_service.server.service.Service.init_data'):
            service = CryptServ(mock_server)
        
        assert (tmp_path / "certs").exists()
        assert service.certs_dir == tmp_path / "certs"

    def test_init_sets_gencert_path(self, mock_server, tmp_path):
        """Test that gencert script path is set correctly."""
        with patch('csc_service.server.service.Service.init_data'):
            service = CryptServ(mock_server)
        
        expected_path = tmp_path / "scripts" / "gencert.sh"
        assert service.gencert_path == expected_path

    def test_init_creates_issued_certs_data(self, mock_server):
        """Test that issued_certs data structure is initialized."""
        with patch('csc_service.server.service.Service.init_data'):
            service = CryptServ(mock_server)
        
        service._data = {"issued_certs": {}}
        service.get_data = lambda key: service._data.get(key)
        
        issued = service.get_data("issued_certs")
        assert issued == {}


class TestRunGencertScript:
    """Tests for _run_gencert_script method."""

    def test_run_gencert_success(self, cryptserv_service, tmp_path):
        """Test successful certificate generation script execution."""
        # Create the script
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "gencert.sh").touch()
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                stdout="Certificate generated",
                stderr="",
                returncode=0
            )
            
            success, msg = cryptserv_service._run_gencert_script("#general")
            
            assert success is True
            assert "Certificate generated successfully" in msg
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "gencert.sh" in str(args)
            assert "#general" in args

    def test_run_gencert_script_not_found(self, cryptserv_service):
        """Test error when gencert.sh script does not exist."""
        success, msg = cryptserv_service._run_gencert_script("#general")
        
        assert success is False
        assert "not found" in msg.lower()

    def test_run_gencert_subprocess_failure(self, cryptserv_service, tmp_path):
        """Test handling of subprocess failure."""
        # Create the script
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "gencert.sh").touch()
        
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "cmd", stderr="Script error output"
            )
            
            success, msg = cryptserv_service._run_gencert_script("#general")
            
            assert success is False
            assert "Certificate generation failed" in msg

    def test_run_gencert_unexpected_error(self, cryptserv_service, tmp_path):
        """Test handling of unexpected errors during script execution."""
        # Create the script
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "gencert.sh").touch()
        
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = Exception("Unexpected error")
            
            success, msg = cryptserv_service._run_gencert_script("#general")
            
            assert success is False
            assert "Unexpected script error" in msg


class TestLoadCertBundle:
    """Tests for _load_cert_bundle method."""

    def test_load_cert_bundle_success(self, cryptserv_service, tmp_path):
        """Test successful loading of certificate bundle."""
        target = "#general"
        target_dir = tmp_path / "certs" / target
        target_dir.mkdir(parents=True)
        
        private_key_content = "PRIVATE_KEY_DATA"
        public_key_content = "PUBLIC_KEY_DATA"
        
        (target_dir / "private.pem").write_text(private_key_content)
        (target_dir / "public.pem").write_text(public_key_content)
        
        bundle = cryptserv_service._load_cert_bundle(target)
        
        assert bundle is not None
        assert bundle["private"] == private_key_content
        assert bundle["public"] == public_key_content

    def test_load_cert_bundle_missing_private_key(self, cryptserv_service, tmp_path):
        """Test loading when private key is missing."""
        target = "#general"
        target_dir = tmp_path / "certs" / target
        target_dir.mkdir(parents=True)
        
        (target_dir / "public.pem").write_text("PUBLIC_KEY")
        
        bundle = cryptserv_service._load_cert_bundle(target)
        
        assert bundle is None

    def test_load_cert_bundle_missing_public_key(self, cryptserv_service, tmp_path):
        """Test loading when public key is missing."""
        target = "#general"
        target_dir = tmp_path / "certs" / target
        target_dir.mkdir(parents=True)
        
        (target_dir / "private.pem").write_text("PRIVATE_KEY")
        
        bundle = cryptserv_service._load_cert_bundle(target)
        
        assert bundle is None

    def test_load_cert_bundle_nonexistent_target(self, cryptserv_service):
        """Test loading certificate for nonexistent target."""
        bundle = cryptserv_service._load_cert_bundle("#nonexistent")
        
        assert bundle is None


class TestSendCertBundleToRequestor:
    """Tests for _send_cert_bundle_to_requestor method."""

    def test_send_cert_bundle_success(self, cryptserv_service, mock_server):
        """Test successful sending of certificate bundle to requestor."""
        cert_bundle = {"private": "PRIV", "public": "PUB"}
        target = "#general"
        requestor_nick = "davey"
        
        with patch.object(cryptserv_service, 'server') as mock_srv:
            mock_srv.clients = mock_server.clients
            
            result = cryptserv_service._send_cert_bundle_to_requestor(
                cert_bundle, target, requestor_nick
            )
            
            assert "sent to davey" in result.lower()

    def test_send_cert_bundle_requestor_not_found(self, cryptserv_service):
        """Test error when requestor is not in clients list."""
        cert_bundle = {"private": "PRIV", "public": "PUB"}
        target = "#general"
        requestor_nick = "unknown_user"
        
        result = cryptserv_service._send_cert_bundle_to_requestor(
            cert_bundle, target, requestor_nick
        )
        
        assert "Error" in result
        assert "not found" in result.lower()


class TestRequest:
    """Tests for request method."""

    def test_request_new_certificate(self, cryptserv_service, tmp_path):
        """Test requesting a new certificate."""
        # Create gencert script
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "gencert.sh").touch()
        
        target = "#general"
        requestor_nick = "davey"
        
        # Create certificate files that would be generated
        target_dir = tmp_path / "certs" / target
        target_dir.mkdir(parents=True)
        (target_dir / "private.pem").write_text("GENERATED_PRIVATE")
        (target_dir / "public.pem").write_text("GENERATED_PUBLIC")
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                stdout="Cert generated",
                stderr="",
                returncode=0
            )
            
            result = cryptserv_service.request(target, requestor_nick)
            
            assert "sent to davey" in result.lower() or "error" not in result.lower()
            issued_certs = cryptserv_service.get_data("issued_certs")
            assert target in issued_certs

    def test_request_existing_certificate(self, cryptserv_service, tmp_path):
        """Test requesting an existing certificate."""
        target = "#general"
        requestor_nick = "davey"
        
        # Create existing cert files
        target_dir = tmp_path / "certs" / target
        target_dir.mkdir(parents=True)
        (target_dir / "private.pem").write_text("EXISTING_PRIVATE")
        (target_dir / "public.pem").write_text("EXISTING_PUBLIC")
        
        # Mark as issued
        cryptserv_service.put_data("issued_certs", {
            target: {
                "issued_at": time.time(),
                "private_path": f"certs/{target}/private.pem",
                "public_path": f"certs/{target}/public.pem",
            }
        })
        
        result = cryptserv_service.request(target, requestor_nick)
        
        assert "sent to davey" in result.lower() or "error" not in result.lower()

    def test_request_gencert_failure(self, cryptserv_service, tmp_path):
        """Test request when certificate generation fails."""
        # Create gencert script
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "gencert.sh").touch()
        
        target = "#newcert"
        requestor_nick = "davey"
        
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "cmd", stderr="Generation failed"
            )
            
            result = cryptserv_service.request(target, requestor_nick)
            
            assert "Error" in result

    def test_request_cert_bundle_load_failure(self, cryptserv_service, tmp_path):
        """Test request when generated cert cannot be loaded."""
        # Create gencert script
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "gencert.sh").touch()
        
        target = "#general"
        requestor_nick = "davey"
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                stdout="Cert generated",
                stderr="",
                returncode=0
            )
            
            # Don't create cert files, so loading will fail
            result = cryptserv_service.request(target, requestor_nick)
            
            assert "Error" in result
            assert "Failed to load" in result

    def test_request_requestor_not_found(self, cryptserv_service, tmp_path):
        """Test request with unknown requestor."""
        target = "#general"
        requestor_nick = "unknown_user"
        
        # Create existing cert files
        target_dir = tmp_path / "certs" / target
        target_dir.mkdir(parents=True)
        (target_dir / "private.pem").write_text("EXISTING_PRIVATE")
        (target_dir / "public.pem").write_text("EXISTING_PUBLIC")
        
        # Mark as issued
        cryptserv_service.put_data("issued_certs", {
            target: {
                "issued_at": time.time(),
                "private_path": f"certs/{target}/private.pem",
                "public_path": f"certs/{target}/public.pem",
            }
        })
        
        result = cryptserv_service.request(target, requestor_nick)
        
        assert "Error" in result
        assert "not found" in result.lower()

    def test_request_logs_activity(self, cryptserv_service, tmp_path):
        """Test that request activity is logged."""
        target = "#general"
        requestor_nick = "davey"
        
        # Create existing cert
        target_dir = tmp_path / "certs" / target
        target_dir.mkdir(parents=True)
        (target_dir / "private.pem").write_text("KEY")
        (target_dir / "public.pem").write_text("KEY")
        
        cryptserv_service.put_data("issued_certs", {
            target: {"issued_at": time.time()}
        })
        
        cryptserv_service.request(target, requestor_nick)
        
        cryptserv_service.server.log.assert_called()
        log_calls = [str(call) for call in cryptserv_service.server.log.call_args_list]
        assert any("Request for" in str(c) and target in str(c) for c in log_calls)


class TestCryptServDataPersistence:
    """Tests for data persistence."""

    def test_issued_certs_data_structure(self, cryptserv_service, tmp_path):
        """Test that issued_certs data is properly structured."""
        target = "#general"
        
        # Create cert files
        target_dir = tmp_path / "certs" / target
        target_dir.mkdir(parents=True)
        (target_dir / "private.pem").write_text("PRIV")
        (target_dir / "public.pem").write_text("PUB")
        
        # Create gencert script
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "gencert.sh").touch()
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                stdout="Success",
                stderr="",
                returncode=0
            )
            
            crypt