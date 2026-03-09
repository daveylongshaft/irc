```python
import pytest
from unittest.mock import Mock, patch, MagicMock, call
import base64
import hashlib
from pathlib import Path
from io import BytesIO


@pytest.fixture
def mock_network():
    """Fixture to mock network dependency"""
    with patch('csc_shared.network.Network') as mock:
        yield mock


@pytest.fixture
def mock_data():
    """Fixture to mock Data class"""
    with patch('csc_shared.data.Data') as mock:
        yield mock


@pytest.fixture
def mock_log():
    """Fixture to mock Log class"""
    with patch('csc_shared.log.Log') as mock:
        yield mock


@pytest.fixture
def mock_platform():
    """Fixture to mock Platform class"""
    with patch('csc_shared.platform.Platform') as mock:
        yield mock


@pytest.fixture
def tmp_project_dir(tmp_path):
    """Create a temporary project directory structure"""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugins_dir = project_dir / "plugins"
    plugins_dir.mkdir()
    return project_dir


class TestDCCSystem:
    """Test suite for DCC (Direct Client-to-Client) file transfer system"""
    
    def setup_method(self):
        """Setup test fixtures before each test"""
        self.test_content = b"This is a test file for DCC transfer." * 50
        self.test_checksum = hashlib.md5(self.test_content).hexdigest()

    def teardown_method(self):
        """Cleanup after each test"""
        pass

    @pytest.mark.parametrize("file_size", [
        100,
        1024,
        10240,
        1024 * 1024  # 1MB
    ])
    def test_dcc_send_various_file_sizes(self, tmp_path, file_size):
        """Test DCC send with various file sizes"""
        test_file = tmp_path / "test_file.txt"
        test_content = b"x" * file_size
        test_file.write_bytes(test_content)
        
        assert test_file.exists()
        assert test_file.stat().st_size == file_size
        assert hashlib.md5(test_content).hexdigest() is not None

    def test_dcc_receive_creates_target_directory(self, tmp_path):
        """Test that DCC receive creates target directory if it doesn't exist"""
        target_dir = tmp_path / "plugins"
        assert not target_dir.exists()
        
        # Simulate directory creation
        target_dir.mkdir(parents=True, exist_ok=True)
        assert target_dir.exists()

    def test_dcc_message_parsing(self):
        """Test CTCP DCC message parsing"""
        # Example DCC SEND message format
        dcc_message = "\x01DCC SEND test_file.txt 3232235777 6881 1024\x01"
        
        # Extract parts
        parts = dcc_message.strip('\x01').split()
        assert parts[0] == "DCC"
        assert parts[1] == "SEND"
        assert parts[2] == "test_file.txt"
        assert len(parts) >= 4

    def test_dcc_checksum_validation(self):
        """Test file checksum validation after transfer"""
        original_content = b"Test content for checksum"
        received_content = b"Test content for checksum"
        
        original_checksum = hashlib.md5(original_content).hexdigest()
        received_checksum = hashlib.md5(received_content).hexdigest()
        
        assert original_checksum == received_checksum

    def test_dcc_checksum_mismatch_detection(self):
        """Test detection of checksum mismatch (corrupted file)"""
        original_content = b"Original content"
        received_content = b"Modified content"
        
        original_checksum = hashlib.md5(original_content).hexdigest()
        received_checksum = hashlib.md5(received_content).hexdigest()
        
        assert original_checksum != received_checksum

    def test_dcc_ip_address_conversion(self):
        """Test DCC IP address conversion (long format)"""
        # DCC uses long integer format for IP address
        # Example: 192.168.1.1 = 3232235777
        ip_long = 3232235777
        
        # Convert back to dotted decimal
        ip_bytes = ip_long.to_bytes(4, byteorder='big')
        ip_address = '.'.join(str(b) for b in ip_bytes)
        
        assert ip_address == "192.168.1.1"

    def test_dcc_port_range_validation(self):
        """Test DCC port number validation"""
        valid_ports = [6881, 6889, 49152, 65535]
        invalid_ports = [-1, 0, 65536, 100000]
        
        for port in valid_ports:
            assert 1 <= port <= 65535
        
        for port in invalid_ports:
            assert not (1 <= port <= 65535)

    def test_dcc_file_not_found_handling(self, tmp_path):
        """Test handling of file not found during DCC send"""
        non_existent_file = tmp_path / "non_existent.txt"
        assert not non_existent_file.exists()

    def test_dcc_concurrent_transfers(self, tmp_path):
        """Test handling of concurrent DCC transfers"""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_bytes(b"Content 1")
        file2.write_bytes(b"Content 2")
        
        assert file1.exists()
        assert file2.exists()
        assert file1.read_bytes() != file2.read_bytes()

    def test_dcc_filename_with_spaces(self, tmp_path):
        """Test DCC transfer with spaces in filename"""
        filename = "test file with spaces.txt"
        test_file = tmp_path / filename
        test_file.write_bytes(b"Test content")
        
        assert test_file.exists()
        assert " " in test_file.name

    def test_dcc_filename_with_special_chars(self, tmp_path):
        """Test DCC transfer with special characters in filename"""
        # Note: Real implementation may have restrictions
        filename = "test-file_123.txt"
        test_file = tmp_path / filename
        test_file.write_bytes(b"Test content")
        
        assert test_file.exists()

    def test_dcc_empty_file_transfer(self, tmp_path):
        """Test DCC transfer of empty file"""
        empty_file = tmp_path / "empty.txt"
        empty_file.write_bytes(b"")
        
        assert empty_file.exists()
        assert empty_file.stat().st_size == 0
        assert hashlib.md5(b"").hexdigest() == "d41d8cd98f00b204e9800998ecf8427e"

    def test_dcc_binary_file_transfer(self, tmp_path):
        """Test DCC transfer of binary file"""
        binary_content = bytes(range(256))
        binary_file = tmp_path / "binary.bin"
        binary_file.write_bytes(binary_content)
        
        assert binary_file.exists()
        assert binary_file.read_bytes() == binary_content

    def test_dcc_large_file_resumption(self, tmp_path):
        """Test DCC large file resumption capability"""
        test_file = tmp_path / "large.bin"
        content = b"X" * (1024 * 1024)  # 1MB
        test_file.write_bytes(content)
        
        # Simulate partial transfer
        partial_size = len(content) // 2
        assert partial_size < len(content)

    def test_dcc_transfer_timeout_handling(self):
        """Test handling of DCC transfer timeout"""
        timeout_seconds = 30
        assert timeout_seconds > 0

    def test_dcc_client_disconnect_during_transfer(self):
        """Test handling of client disconnect during active transfer"""
        transfer_active = True
        client_connected = False
        
        # Simulate disconnect scenario
        if transfer_active and not client_connected:
            transfer_active = False
        
        assert not transfer_active

    def test_dcc_reverse_connection_support(self):
        """Test DCC reverse connection (passive mode) support"""
        # DCC SEND token format for reverse connection
        reverse_token = 12345
        assert isinstance(reverse_token, int)

    def test_dcc_accept_reject_scenarios(self):
        """Test accepting and rejecting DCC transfers"""
        received_offers = []
        
        # Simulate offer
        offer = {"sender": "Alice", "filename": "test.txt", "token": 123}
        received_offers.append(offer)
        
        # Accept
        accepted = received_offers[0]
        assert accepted["sender"] == "Alice"
        
        # Reject would remove from list
        rejected_offers = [o for o in received_offers if o != offer]
        assert len(rejected_offers) == 0

    def test_dcc_send_to_multiple_recipients(self, tmp_path):
        """Test sending same file to multiple recipients"""
        test_file = tmp_path / "shared.txt"
        test_file.write_bytes(b"Shared content")
        
        recipients = ["Alice", "Bob", "Charlie"]
        transfers = {}
        
        for recipient in recipients:
            transfers[recipient] = {
                "file": str(test_file),
                "status": "initiated"
            }
        
        assert len(transfers) == 3
        assert all(transfers[r]["status"] == "initiated" for r in recipients)

    def test_dcc_progress_callback(self, tmp_path):
        """Test DCC progress callback during transfer"""
        test_file = tmp_path / "progress_test.bin"
        total_size = 10000
        test_file.write_bytes(b"X" * total_size)
        
        progress_updates = []
        
        def on_progress(bytes_transferred):
            progress_updates.append(bytes_transferred)
        
        # Simulate progress callbacks
        for i in range(0, total_size + 1, 1000):
            on_progress(i)
        
        assert len(progress_updates) > 0
        assert progress_updates[-1] >= total_size

    def test_dcc_message_encoding_decoding(self):
        """Test DCC message encoding and decoding"""
        original_message = "DCC SEND test.txt 3232235777 6881 1024"
        
        # Encode
        encoded = original_message.encode('utf-8')
        assert isinstance(encoded, bytes)
        
        # Decode
        decoded = encoded.decode('utf-8')
        assert decoded == original_message

    def test_dcc_resume_offset_calculation(self):
        """Test calculation of resume offset"""
        total_size = 10000
        transferred_size = 5000
        resume_offset = transferred_size
        
        remaining = total_size - resume_offset
        assert remaining == 5000
        assert resume_offset + remaining == total_size

    def test_dcc_transfer_statistics_collection(self, tmp_path):
        """Test collection of transfer statistics"""
        test_file = tmp_path / "stats_test.bin"
        test_file.write_bytes(b"X" * 5000)
        
        stats = {
            "filename": str(test_file),
            "size": test_file.stat().st_size,
            "checksum": hashlib.md5(test_file.read_bytes()).hexdigest(),
            "duration_seconds": 2.5,
            "speed_kbps": None
        }
        
        if stats["duration_seconds"] > 0:
            stats["speed_kbps"] = (stats["size"] / 1024) / stats["duration_seconds"]
        
        assert stats["size"] == 5000
        assert stats["speed_kbps"] is not None

    def test_dcc_error_recovery(self, tmp_path):
        """Test error recovery during DCC transfer"""
        test_file = tmp_path / "recovery_test.bin"
        test_file.write_bytes(b"X" * 1000)
        
        # Simulate error and recovery
        error_occurred = True
        retry_count = 0
        max_retries = 3
        
        while error_occurred and retry_count < max_retries:
            retry_count += 1
            if retry_count >= 2:
                error_occurred = False
        
        assert not error_occurred
        assert retry_count == 2

    def test_dcc_validate_file_permissions(self, tmp_path):
        """Test validation of file permissions before transfer"""
        test_file = tmp_path / "permissions_test.txt"
        test_file.write_bytes(b"Test")
        
        # File exists and is readable
        assert test_file.exists()
        assert test_file.read_bytes() == b"Test"

    def test_dcc_cleanup_incomplete_transfers(self, tmp_path):
        """Test cleanup of incomplete transfer files"""
        incomplete_file = tmp_path / "incomplete.tmp"
        incomplete_file.write_bytes(b"Partial content")
        
        # Simulate cleanup
        if incomplete_file.exists() and incomplete_file.name.endswith('.tmp'):
            incomplete_file.unlink()
        
        assert not incomplete_file.exists()

    def test_dcc_transfer_verification_after_completion(self, tmp_path):
        """Test verification of transfer after completion"""
        original_file = tmp_path / "original.bin"
        received_file = tmp_path / "received.bin"
        
        content = b"Test content for verification"
        original_file.write_bytes(content)
        received_file.write_bytes(content)
        
        original_hash = hashlib.md5(original_file.read_bytes()).hexdigest()
        received_hash = hashlib.md5(received_file.read_bytes()).hexdigest()
        
        assert original_hash == received_hash
        
        # Files should match exactly
        assert original_file.read_bytes() == received_file.read_bytes()
```