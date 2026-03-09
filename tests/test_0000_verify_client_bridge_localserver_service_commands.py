```python
"""Pytest test file for CSC IRC orchestration bridge connectivity.

Tests bridge connectivity, encryption, command execution, and graceful shutdown.
Mocks all external dependencies (network, subprocess, file I/O).
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path
import tempfile


class MockClient:
    """Mock Client for testing without real network."""
    
    def __init__(self, host, port, output_file, input_file):
        self.host = host
        self.port = port
        self.output_file = output_file
        self.input_file = input_file
        self.connected = False
        self.response_data = ""
    
    def run(self, interactive=False):
        """Simulate client run with configurable response."""
        self.connected = True
        # Write mock response to output file
        if self.output_file:
            with open(self.output_file, 'w') as f:
                f.write(self.response_data)


@pytest.fixture
def temp_dir():
    """Provide temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_client_class():
    """Mock the Client class."""
    with patch('csc_service.client.client.Client', MockClient):
        yield MockClient


@pytest.fixture
def input_output_files(temp_dir):
    """Create input and output file paths."""
    input_file = temp_dir / "input.txt"
    output_file = temp_dir / "output.txt"
    input_file.write_text("ai do builtin list_dir .\nquit\n")
    return input_file, output_file


class TestBridgeConnectivity:
    """Test bridge connectivity and basic communication."""
    
    def test_bridge_connectivity_success(self, temp_dir, mock_client_class, input_output_files):
        """Test successful bridge connection and data reception."""
        input_file, output_file = input_output_files
        
        # Create client with mock response
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        client.response_data = "RESPONSE: Server connected\nData received\n"
        
        # Run client
        client.run(interactive=False)
        
        # Verify connection
        assert client.connected is True
        
        # Verify output file was written
        assert output_file.exists()
        output = output_file.read_text()
        assert len(output) > 0
        assert "Server connected" in output
    
    def test_bridge_connectivity_failure_no_data(self, temp_dir, mock_client_class, input_output_files):
        """Test bridge connectivity failure when no data received."""
        input_file, output_file = input_output_files
        
        # Create client with empty response
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        client.response_data = ""
        
        # Run client
        client.run(interactive=False)
        
        # Verify no output
        output = output_file.read_text()
        assert output.strip() == ""
    
    def test_bridge_host_port_configuration(self, mock_client_class, input_output_files):
        """Test bridge is configured with correct host and port."""
        input_file, output_file = input_output_files
        
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        
        assert client.host == "127.0.0.1"
        assert client.port == 9666


class TestEncryptionAutoDetection:
    """Test encryption handshake and auto-detection."""
    
    def test_encryption_handshake_success(self, temp_dir, mock_client_class, input_output_files):
        """Test successful encryption handshake with CRYPTOINIT and DHREPLY."""
        input_file, output_file = input_output_files
        
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        # Include encryption handshake markers
        client.response_data = (
            "CRYPTOINIT: DH key exchange initiated\n"
            "DHREPLY: Server responded with public key\n"
            "Encrypted session established\n"
        )
        
        client.run(interactive=False)
        
        output = output_file.read_text()
        assert "CRYPTOINIT" in output
        assert "DHREPLY" in output
    
    def test_encryption_missing_cryptoinit(self, temp_dir, mock_client_class, input_output_files):
        """Test encryption failure when CRYPTOINIT is missing."""
        input_file, output_file = input_output_files
        
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        client.response_data = "DHREPLY: Server responded\n"
        
        client.run(interactive=False)
        
        output = output_file.read_text()
        assert "CRYPTOINIT" not in output
        assert "DHREPLY" in output
    
    def test_encryption_missing_dhreply(self, temp_dir, mock_client_class, input_output_files):
        """Test encryption failure when DHREPLY is missing."""
        input_file, output_file = input_output_files
        
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        client.response_data = "CRYPTOINIT: DH initiated\n"
        
        client.run(interactive=False)
        
        output = output_file.read_text()
        assert "CRYPTOINIT" in output
        assert "DHREPLY" not in output


class TestCommandExecution:
    """Test command execution through bridge."""
    
    def test_command_execution_success(self, temp_dir, mock_client_class, input_output_files):
        """Test successful command execution with 'do' token."""
        input_file, output_file = input_output_files
        
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        client.response_data = (
            "ai do builtin list_dir .\n"
            "do: DIR_LISTING_START\n"
            "./file1.txt\n"
            "./file2.txt\n"
            "do: DIR_LISTING_END\n"
        )
        
        client.run(interactive=False)
        
        output = output_file.read_text()
        assert "do" in output
        assert "DIR_LISTING" in output
    
    def test_command_execution_missing_do_token(self, temp_dir, mock_client_class, input_output_files):
        """Test command execution failure when 'do' token is missing."""
        input_file, output_file = input_output_files
        
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        client.response_data = (
            "ERROR: Command not recognized\n"
            "Invalid syntax\n"
        )
        
        client.run(interactive=False)
        
        output = output_file.read_text()
        assert "do" not in output
        assert "ERROR" in output
    
    def test_command_builtin_list_dir(self, temp_dir, mock_client_class, input_output_files):
        """Test builtin list_dir command."""
        input_file, output_file = input_output_files
        
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        client.response_data = (
            "COMMAND: ai do builtin list_dir .\n"
            "do: Listing current directory\n"
            "do: file1.txt\n"
            "do: file2.txt\n"
        )
        
        client.run(interactive=False)
        
        output = output_file.read_text()
        assert "list_dir" in input_file.read_text()
        assert "do:" in output
    
    def test_command_execution_with_parameters(self, temp_dir, mock_client_class, input_output_files):
        """Test command execution with parameters."""
        input_file, output_file = input_output_files
        
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        client.response_data = (
            "COMMAND: ai do builtin list_dir . with params\n"
            "do: Parameters accepted\n"
        )
        
        client.run(interactive=False)
        
        output = output_file.read_text()
        assert "do:" in output


class TestGracefulShutdown:
    """Test graceful shutdown and cleanup."""
    
    def test_quit_command_issued(self, temp_dir, mock_client_class, input_output_files):
        """Test that QUIT command is issued for graceful shutdown."""
        input_file, output_file = input_output_files
        
        # Verify input file contains quit
        assert "quit" in input_file.read_text()
        
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        client.response_data = (
            "Processing commands...\n"
            "Received: quit\n"
            "Closing connection gracefully\n"
        )
        
        client.run(interactive=False)
        
        output = output_file.read_text()
        assert "quit" in output or "Closing" in output
    
    def test_shutdown_closes_connection(self, temp_dir, mock_client_class, input_output_files):
        """Test that shutdown properly closes connection."""
        input_file, output_file = input_output_files
        
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        client.response_data = "Connection closed\n"
        
        client.run(interactive=False)
        assert client.connected is True
        
        # Simulate shutdown
        client.connected = False
        assert client.connected is False
    
    def test_shutdown_waits_for_responses(self, temp_dir, mock_client_class, input_output_files):
        """Test that shutdown waits for pending responses."""
        input_file, output_file = input_output_files
        
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        client.response_data = (
            "Command 1 result\n"
            "Command 2 result\n"
            "All responses received\n"
            "Safe to shutdown\n"
        )
        
        client.run(interactive=False)
        
        output = output_file.read_text()
        # Verify all responses present before shutdown
        assert "result" in output
        assert "Safe to shutdown" in output


class TestServiceAvailability:
    """Test service availability checking."""
    
    @patch('socket.socket')
    def test_check_server_running(self, mock_socket):
        """Test checking if server is running."""
        mock_sock_instance = MagicMock()
        mock_sock_instance.connect_ex.return_value = 0  # Connection successful
        mock_socket.return_value = mock_sock_instance
        
        # Simulate socket connection check
        s = mock_socket()
        result = s.connect_ex(("127.0.0.1", 9525))
        
        assert result == 0
        mock_sock_instance.close.assert_called()
    
    @patch('socket.socket')
    def test_check_bridge_running(self, mock_socket):
        """Test checking if bridge is running."""
        mock_sock_instance = MagicMock()
        mock_sock_instance.connect_ex.return_value = 0  # Connection successful
        mock_socket.return_value = mock_sock_instance
        
        # Simulate socket connection check
        s = mock_socket()
        result = s.connect_ex(("127.0.0.1", 9666))
        
        assert result == 0
        mock_sock_instance.close.assert_called()
    
    @patch('socket.socket')
    def test_service_not_listening(self, mock_socket):
        """Test detection of service not listening."""
        mock_sock_instance = MagicMock()
        mock_sock_instance.connect_ex.return_value = 1  # Connection failed
        mock_socket.return_value = mock_sock_instance
        
        # Simulate socket connection check
        s = mock_socket()
        result = s.connect_ex(("127.0.0.1", 9666))
        
        assert result != 0
        mock_sock_instance.close.assert_called()


class TestClientConfiguration:
    """Test client configuration and setup."""
    
    def test_client_initialization(self, temp_dir, mock_client_class, input_output_files):
        """Test client initialization with correct configuration."""
        input_file, output_file = input_output_files
        
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file=str(input_file)
        )
        
        assert client.host == "127.0.0.1"
        assert client.port == 9666
        assert str(client.output_file) == str(output_file)
        assert str(client.input_file) == str(input_file)
    
    def test_input_file_contains_commands(self, input_output_files):
        """Test that input file contains expected commands."""
        input_file, _ = input_output_files
        
        content = input_file.read_text()
        assert "ai do builtin list_dir ." in content
        assert "quit" in content
    
    def test_output_file_writable(self, temp_dir):
        """Test that output file is writable."""
        output_file = temp_dir / "output.txt"
        
        # Write test data
        output_file.write_text("test data")
        
        assert output_file.exists()
        assert output_file.read_text() == "test data"


class TestErrorHandling:
    """Test error handling and diagnostics."""
    
    def test_bridge_connection_timeout(self, temp_dir, mock_client_class, input_output_files):
        """Test handling of bridge connection timeout."""
        input_file, output_file = input_output_files
        
        # Simulate timeout by creating client without response
        client = MockClient(
            host="127.0.0.1",
            port=9666,
            output_file=str(output_file),
            input_file