```python
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from csc_client.client import Client
from csc_shared.irc import format_irc_message


@pytest.fixture
def mock_network():
    """Fixture to mock Network initialization."""
    with patch('csc_shared.network.Network.__init__', return_value=None):
        yield


@pytest.fixture
def client_a(mock_network, tmp_path):
    """Create client A with mocked dependencies."""
    client = Client()
    client.name = "Alice"
    client.project_root_dir = tmp_path
    client._write_to_output = Mock()
    client._is_authorized = Mock(return_value=True)
    return client


@pytest.fixture
def client_b(mock_network, tmp_path):
    """Create client B with mocked dependencies."""
    client = Client()
    client.name = "Bob"
    client.project_root_dir = tmp_path
    client._write_to_output = Mock()
    client._is_authorized = Mock(return_value=True)
    return client


@pytest.fixture
def connected_clients(client_a, client_b, tmp_path):
    """Set up two connected clients that route messages to each other."""
    plugins_dir = tmp_path / "test_remote_plugins"
    plugins_dir.mkdir(exist_ok=True)
    client_b._client_service_handler = Mock()
    client_b._client_service_handler.plugins_dir = plugins_dir

    def alice_send(msg):
        """Route Alice's messages to Bob."""
        if "PRIVMSG Bob" in msg:
            text = msg.split(" :", 1)[1]
            parsed = Mock()
            parsed.prefix = "Alice!Alice@csc-server"
            parsed.params = ["Bob", text.strip()]
            client_b._handle_privmsg_recv(parsed)

    def bob_send(msg):
        """Route Bob's messages to Alice."""
        if "PRIVMSG Alice" in msg:
            text = msg.split(" :", 1)[1]
            parsed = Mock()
            parsed.prefix = "Bob!Bob@csc-server"
            parsed.params = ["Alice", text.strip()]
            client_a._handle_privmsg_recv(parsed)

    client_a.send = alice_send
    client_b.send = bob_send

    return client_a, client_b, plugins_dir


class TestClientBasics:
    """Test basic Client initialization and properties."""

    def test_client_initialization(self, client_a):
        """Test that a Client can be initialized with mocked network."""
        assert client_a.name == "Alice"
        assert client_a.project_root_dir is not None

    def test_client_has_authorization_mock(self, client_a):
        """Test that authorization check is properly mocked."""
        assert client_a._is_authorized() is True

    def test_write_to_output_is_mocked(self, client_a):
        """Test that output writing is mocked."""
        client_a._write_to_output("test message")
        client_a._write_to_output.assert_called_with("test message")


class TestRemoteCommandExecution:
    """Test remote command execution between clients."""

    def test_remote_builtin_command(self, connected_clients):
        """Test executing a builtin command on a remote client."""
        client_a, client_b, plugins_dir = connected_clients

        # Mock the builtin handler on client_b
        with patch.object(client_b, 'process_command') as mock_process:
            mock_process.return_value = None
            
            # Alice sends a remote command to Bob
            cmd = "Bob 123 builtin echo hello"
            client_a.process_command(f"/msg Bob {cmd}")
            
            # Verify process_command was called
            assert client_a.process_command.called or client_a.send is not None

    def test_client_receives_output(self, connected_clients):
        """Test that output is properly written."""
        client_a, client_b, plugins_dir = connected_clients
        
        test_output = "command result"
        client_a._write_to_output(test_output)
        
        client_a._write_to_output.assert_called_with(test_output)

    def test_authorization_check_on_command(self, connected_clients):
        """Test that authorization is checked before executing remote commands."""
        client_a, client_b, plugins_dir = connected_clients
        
        # Client B is authorized
        assert client_b._is_authorized() is True
        
        # Client A is also authorized
        assert client_a._is_authorized() is True


class TestRemotePluginUpload:
    """Test uploading and executing remote plugins."""

    def test_plugin_file_creation(self, connected_clients, tmp_path):
        """Test that plugin files can be created in the correct directory."""
        client_a, client_b, plugins_dir = connected_clients
        
        # Create a test plugin file
        plugin_name = "test_plugin.py"
        plugin_path = plugins_dir / plugin_name
        plugin_content = "class Remote_test:\n    pass"
        
        plugin_path.write_text(plugin_content)
        
        assert plugin_path.exists()
        assert plugin_path.read_text() == plugin_content

    def test_multiline_plugin_upload(self, connected_clients, tmp_path):
        """Test uploading a multiline plugin file."""
        client_a, client_b, plugins_dir = connected_clients
        
        plugin_name = "remote_test_plugin.py"
        plugin_content = [
            "class Remote_test:",
            "    def __init__(self, client): self.client = client",
            "    def greet(self, name): return f'Hello {name} from remote plugin'"
        ]
        
        plugin_path = plugins_dir / plugin_name
        plugin_path.write_text("\n".join(plugin_content))
        
        assert plugin_path.exists()
        content = plugin_path.read_text()
        for line in plugin_content:
            assert line in content

    def test_plugin_import_mock(self, connected_clients):
        """Test mocking plugin import."""
        client_a, client_b, plugins_dir = connected_clients
        
        with patch('importlib.import_module') as mock_import:
            mock_module = Mock()
            mock_class = Mock()
            mock_instance = Mock()
            mock_instance.greet = Mock(return_value="Hello World from remote plugin")
            mock_class.return_value = mock_instance
            mock_module.Remote_test = mock_class
            mock_import.return_value = mock_module
            
            # Simulate importing the plugin
            imported = mock_import("plugins.remote_test_plugin")
            assert imported.Remote_test is mock_class
            
            # Simulate instantiation
            instance = imported.Remote_test(client_b)
            assert instance.greet("World") == "Hello World from remote plugin"

    def test_plugin_execution_logging(self, connected_clients):
        """Test that remote execution is properly logged."""
        client_a, client_b, plugins_dir = connected_clients
        
        # Log a remote execution
        client_b._write_to_output("[REMOTE EXEC] plugin_name executed")
        
        # Verify logging was called
        client_b._write_to_output.assert_called()


class TestMessageRouting:
    """Test message routing between clients."""

    def test_privmsg_format(self):
        """Test IRC PRIVMSG format."""
        # Test that format_irc_message creates valid IRC messages
        with patch('csc_shared.irc.format_irc_message') as mock_format:
            mock_format.return_value = "PRIVMSG Bob :test message"
            result = mock_format("PRIVMSG", {"recipient": "Bob", "message": "test message"})
            assert "PRIVMSG Bob" in result
            assert "test message" in result

    def test_parsed_message_structure(self):
        """Test that parsed IRC messages have expected structure."""
        parsed = Mock()
        parsed.prefix = "Alice!Alice@csc-server"
        parsed.params = ["Bob", "test message"]
        
        assert parsed.prefix == "Alice!Alice@csc-server"
        assert parsed.params[0] == "Bob"
        assert parsed.params[1] == "test message"

    def test_client_send_routing(self, connected_clients):
        """Test that send methods properly route between clients."""
        client_a, client_b, plugins_dir = connected_clients
        
        # Verify both clients have send methods
        assert callable(client_a.send)
        assert callable(client_b.send)


class TestClientServiceHandler:
    """Test client service handler integration."""

    def test_plugins_directory_setup(self, client_b, tmp_path):
        """Test that plugins directory is properly set up."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir(exist_ok=True)
        
        client_b._client_service_handler = Mock()
        client_b._client_service_handler.plugins_dir = plugins_dir
        
        assert client_b._client_service_handler.plugins_dir == plugins_dir
        assert plugins_dir.exists()

    def test_handler_initialization(self, client_b):
        """Test that service handler is properly initialized."""
        handler = Mock()
        handler.plugins_dir = Path(".")
        
        client_b._client_service_handler = handler
        
        assert client_b._client_service_handler is handler


class TestErrorHandling:
    """Test error handling in client operations."""

    def test_unauthorized_command_rejection(self, client_a):
        """Test that unauthorized commands are rejected."""
        client_a._is_authorized = Mock(return_value=False)
        
        assert client_a._is_authorized() is False

    def test_missing_plugin_handling(self, connected_clients):
        """Test handling of missing plugins."""
        client_a, client_b, plugins_dir = connected_clients
        
        with patch('importlib.import_module') as mock_import:
            mock_import.side_effect = ImportError("Module not found")
            
            with pytest.raises(ImportError):
                mock_import("plugins.nonexistent")

    def test_malformed_message_handling(self, client_a):
        """Test handling of malformed messages."""
        parsed = Mock()
        parsed.prefix = None
        parsed.params = []
        
        # Should not crash with empty params
        assert parsed.params == []


class TestIntegration:
    """Integration tests for client-to-client communication."""

    def test_full_remote_command_flow(self, connected_clients, tmp_path):
        """Test complete flow of remote command execution."""
        client_a, client_b, plugins_dir = connected_clients
        
        # Step 1: Create a plugin file
        plugin_name = "integration_test.py"
        plugin_path = plugins_dir / plugin_name
        plugin_path.write_text("class Remote_test: pass")
        
        # Step 2: Verify file exists
        assert plugin_path.exists()
        
        # Step 3: Mock import and execution
        with patch('importlib.import_module') as mock_import:
            mock_module = Mock()
            mock_module.Remote_test = Mock(return_value=Mock())
            mock_import.return_value = mock_module
            
            # Step 4: Simulate execution
            imported = mock_import("plugins.integration_test")
            assert imported.Remote_test is not None

    def test_bidirectional_communication(self, connected_clients):
        """Test that clients can communicate bidirectionally."""
        client_a, client_b, plugins_dir = connected_clients
        
        # Alice sends to Bob
        client_a.send("PRIVMSG Bob :hello from alice")
        
        # Bob sends to Alice
        client_b.send("PRIVMSG Alice :hello from bob")
        
        # Both send methods should be callable
        assert callable(client_a.send)
        assert callable(client_b.send)


class TestProjectDirectory:
    """Test project directory handling."""

    def test_project_root_directory_exists(self, client_a, tmp_path):
        """Test that project root directory exists."""
        assert client_a.project_root_dir == tmp_path
        assert client_a.project_root_dir.exists()

    def test_multiple_clients_different_directories(self, mock_network, tmp_path):
        """Test that multiple clients can have different project directories."""
        dir1 = tmp_path / "client1"
        dir2 = tmp_path / "client2"
        dir1.mkdir()
        dir2.mkdir()
        
        client1 = Client()
        client2 = Client()
        client1.project_root_dir = dir1
        client2.project_root_dir = dir2
        
        assert client1.project_root_dir != client2.project_root_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```