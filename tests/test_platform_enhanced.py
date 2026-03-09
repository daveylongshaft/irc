```python
import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch, mock_open, MagicMock
import tempfile
import os


class TestPlatformEnhanced:
    """Test suite for Platform class with enhanced fields."""

    @patch('csc_shared.platform.Platform.PLATFORM_JSON_FILENAME', 'test_platform.json')
    @patch('csc_shared.platform.Platform._get_cpu_speed_mhz')
    @patch('csc_shared.platform.Platform._get_hostname')
    @patch('csc_shared.platform.Platform._get_ips')
    def test_new_fields_present(self, mock_ips, mock_hostname, mock_cpu_speed, tmp_path, monkeypatch):
        """Test that new hardware and network fields are present in platform_data."""
        # Setup mocks
        mock_cpu_speed.return_value = 2400
        mock_hostname.return_value = "test-host"
        mock_ips.return_value = ["192.168.1.100", "10.0.0.50"]
        
        # Change working directory to temp path
        monkeypatch.chdir(tmp_path)
        
        # Import here to ensure mocks are in place
        from csc_shared.platform import Platform
        
        with patch.object(Platform, 'PLATFORM_JSON_FILENAME', str(tmp_path / 'platform.json')):
            p = Platform()
            data = p.platform_data
            
            # Test hardware section
            assert "hardware" in data
            assert "cpu_speed_mhz" in data["hardware"]
            assert isinstance(data["hardware"]["cpu_speed_mhz"], (int, float))
            
            # Test network section
            assert "network" in data
            assert "hostname" in data["network"]
            assert "ips" in data["network"]
            assert isinstance(data["network"]["ips"], list)
            assert len(data["network"]["ips"]) > 0

    @patch('csc_shared.platform.Platform.PLATFORM_JSON_FILENAME', 'test_platform.json')
    @patch('csc_shared.platform.Platform._get_cpu_speed_mhz')
    @patch('csc_shared.platform.Platform._get_hostname')
    @patch('csc_shared.platform.Platform._get_ips')
    def test_platform_data_persistence(self, mock_ips, mock_hostname, mock_cpu_speed, tmp_path, monkeypatch):
        """Verify that platform data is persisted to JSON file."""
        # Setup mocks
        mock_cpu_speed.return_value = 3000
        mock_hostname.return_value = "persistent-host"
        mock_ips.return_value = ["172.16.0.1"]
        
        monkeypatch.chdir(tmp_path)
        platform_file = tmp_path / "platform.json"
        
        from csc_shared.platform import Platform
        
        with patch.object(Platform, 'PLATFORM_JSON_FILENAME', str(platform_file)):
            p = Platform()
            
            # Verify file was created
            assert platform_file.exists()
            
            # Load and verify saved data
            with open(platform_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
            
            assert "network" in saved_data
            assert "hostname" in saved_data["network"]
            assert saved_data["network"]["hostname"] == "persistent-host"
            assert "ips" in saved_data["network"]
            assert isinstance(saved_data["network"]["ips"], list)
            assert "hardware" in saved_data
            assert "cpu_speed_mhz" in saved_data["hardware"]

    @patch('csc_shared.platform.Platform._get_cpu_speed_mhz')
    @patch('csc_shared.platform.Platform._get_hostname')
    @patch('csc_shared.platform.Platform._get_ips')
    def test_network_section_structure(self, mock_ips, mock_hostname, mock_cpu_speed, tmp_path, monkeypatch):
        """Test the structure and content of the network section."""
        mock_cpu_speed.return_value = 2800
        mock_hostname.return_value = "network-test-host"
        mock_ips.return_value = ["192.168.0.1", "192.168.0.2", "10.0.0.1"]
        
        monkeypatch.chdir(tmp_path)
        platform_file = tmp_path / "platform_network.json"
        
        from csc_shared.platform import Platform
        
        with patch.object(Platform, 'PLATFORM_JSON_FILENAME', str(platform_file)):
            p = Platform()
            data = p.platform_data
            
            network = data.get("network", {})
            assert isinstance(network, dict)
            assert network.get("hostname") == "network-test-host"
            assert len(network.get("ips", [])) == 3
            assert "192.168.0.1" in network["ips"]
            assert "10.0.0.1" in network["ips"]

    @patch('csc_shared.platform.Platform._get_cpu_speed_mhz')
    @patch('csc_shared.platform.Platform._get_hostname')
    @patch('csc_shared.platform.Platform._get_ips')
    def test_hardware_section_structure(self, mock_ips, mock_hostname, mock_cpu_speed, tmp_path, monkeypatch):
        """Test the structure and content of the hardware section."""
        mock_cpu_speed.return_value = 3500
        mock_hostname.return_value = "hardware-test-host"
        mock_ips.return_value = ["192.168.1.1"]
        
        monkeypatch.chdir(tmp_path)
        platform_file = tmp_path / "platform_hardware.json"
        
        from csc_shared.platform import Platform
        
        with patch.object(Platform, 'PLATFORM_JSON_FILENAME', str(platform_file)):
            p = Platform()
            data = p.platform_data
            
            hardware = data.get("hardware", {})
            assert isinstance(hardware, dict)
            assert "cpu_speed_mhz" in hardware
            assert hardware["cpu_speed_mhz"] == 3500
            assert isinstance(hardware["cpu_speed_mhz"], (int, float))

    @patch('csc_shared.platform.Platform._get_cpu_speed_mhz')
    @patch('csc_shared.platform.Platform._get_hostname')
    @patch('csc_shared.platform.Platform._get_ips')
    def test_empty_ips_list_handled(self, mock_ips, mock_hostname, mock_cpu_speed, tmp_path, monkeypatch):
        """Test that empty IPs list is handled gracefully."""
        mock_cpu_speed.return_value = 2400
        mock_hostname.return_value = "empty-ips-host"
        mock_ips.return_value = []
        
        monkeypatch.chdir(tmp_path)
        platform_file = tmp_path / "platform_empty_ips.json"
        
        from csc_shared.platform import Platform
        
        with patch.object(Platform, 'PLATFORM_JSON_FILENAME', str(platform_file)):
            p = Platform()
            data = p.platform_data
            
            assert "network" in data
            assert isinstance(data["network"]["ips"], list)
            assert len(data["network"]["ips"]) == 0

    @patch('csc_shared.platform.Platform._get_cpu_speed_mhz')
    @patch('csc_shared.platform.Platform._get_hostname')
    @patch('csc_shared.platform.Platform._get_ips')
    def test_json_serialization(self, mock_ips, mock_hostname, mock_cpu_speed, tmp_path, monkeypatch):
        """Test that platform data is properly JSON serializable."""
        mock_cpu_speed.return_value = 2200
        mock_hostname.return_value = "json-test-host"
        mock_ips.return_value = ["192.168.1.5"]
        
        monkeypatch.chdir(tmp_path)
        platform_file = tmp_path / "platform_json_test.json"
        
        from csc_shared.platform import Platform
        
        with patch.object(Platform, 'PLATFORM_JSON_FILENAME', str(platform_file)):
            p = Platform()
            data = p.platform_data
            
            # Verify it can be serialized
            json_str = json.dumps(data)
            assert isinstance(json_str, str)
            
            # Verify it can be deserialized
            deserialized = json.loads(json_str)
            assert deserialized == data

    @patch('csc_shared.platform.Platform._get_cpu_speed_mhz')
    @patch('csc_shared.platform.Platform._get_hostname')
    @patch('csc_shared.platform.Platform._get_ips')
    def test_platform_data_immutability_in_save(self, mock_ips, mock_hostname, mock_cpu_speed, tmp_path, monkeypatch):
        """Test that saved platform data matches the platform_data property."""
        mock_cpu_speed.return_value = 2600
        mock_hostname.return_value = "immutability-test-host"
        mock_ips.return_value = ["10.1.1.1", "10.1.1.2"]
        
        monkeypatch.chdir(tmp_path)
        platform_file = tmp_path / "platform_immutability.json"
        
        from csc_shared.platform import Platform
        
        with patch.object(Platform, 'PLATFORM_JSON_FILENAME', str(platform_file)):
            p = Platform()
            platform_data = p.platform_data
            
            # Load from file
            with open(platform_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
            
            # Compare relevant sections
            assert saved_data["network"]["hostname"] == platform_data["network"]["hostname"]
            assert saved_data["network"]["ips"] == platform_data["network"]["ips"]
            assert saved_data["hardware"]["cpu_speed_mhz"] == platform_data["hardware"]["cpu_speed_mhz"]
```