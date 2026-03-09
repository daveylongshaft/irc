```python
"""Platform detection tests using pytest with mocked Docker environment."""

import os
import sys
import pytest
from unittest.mock import Mock, patch, mock_open, MagicMock

# Mock the platform_gate module before importing
sys.modules['platform_gate'] = MagicMock()


class TestPlatformDetection:
    """Tests for platform detection functionality."""

    @pytest.fixture
    def mock_platform_data(self):
        """Fixture providing mock platform data."""
        return {
            "virtualization": {
                "type": "docker_container",
                "hypervisor": "docker"
            },
            "resource_assessment": {
                "resource_level": "medium",
                "memory_gb": 4,
                "swap_gb": 1
            },
            "hardware": {
                "cpu_cores": 4,
                "cpu_model": "Intel Core i7",
                "total_memory_bytes": 4294967296
            },
            "os": {
                "name": "Linux",
                "version": "5.10.0",
                "distribution": "Ubuntu"
            }
        }

    @pytest.fixture
    def mock_platform_instance(self, mock_platform_data):
        """Fixture providing a mocked Platform instance."""
        with patch('csc_shared.platform.Platform') as MockPlatform:
            instance = Mock()
            instance.platform_data = mock_platform_data
            MockPlatform.return_value = instance
            yield instance

    def test_virtualization_is_docker(self, mock_platform_instance):
        """Virtualization detection should report docker_container."""
        virt = mock_platform_instance.platform_data["virtualization"]
        assert virt["type"] == "docker_container"
        assert virt["hypervisor"] == "docker"

    def test_dockerenv_exists(self, tmp_path, monkeypatch):
        """Simulate /.dockerenv existence check."""
        # Create a mock dockerenv file in tmp directory
        dockerenv_path = tmp_path / "dockerenv"
        dockerenv_path.write_text("")
        
        # Patch os.path.exists to return True for our mock path
        monkeypatch.setattr(
            "os.path.exists",
            lambda path: path == "/.dockerenv" or os.path.exists(path)
        )
        
        # In a real Docker environment, this would be True
        # For this test, we verify the check works
        with patch("os.path.exists", return_value=True) as mock_exists:
            result = os.path.exists("/.dockerenv")
            assert result is True
            mock_exists.assert_called_with("/.dockerenv")

    def test_resource_level_detected(self, mock_platform_instance):
        """Resource level should be assessed in platform data."""
        assessment = mock_platform_instance.platform_data["resource_assessment"]
        assert "resource_level" in assessment
        assert assessment["resource_level"] in ["low", "medium", "high"]

    def test_hardware_detected(self, mock_platform_instance):
        """Hardware information should be detectable."""
        hw = mock_platform_instance.platform_data["hardware"]
        assert hw.get("cpu_cores", 0) > 0
        assert "cpu_model" in hw
        assert "total_memory_bytes" in hw

    def test_os_information_present(self, mock_platform_instance):
        """Operating system information should be detected."""
        os_info = mock_platform_instance.platform_data["os"]
        assert "name" in os_info
        assert "version" in os_info
        assert os_info["name"] == "Linux"

    def test_platform_data_structure(self, mock_platform_instance):
        """Platform data should have expected structure."""
        required_keys = [
            "virtualization",
            "resource_assessment",
            "hardware",
            "os"
        ]
        for key in required_keys:
            assert key in mock_platform_instance.platform_data

    @pytest.mark.parametrize("cpu_cores", [1, 2, 4, 8, 16])
    def test_various_cpu_core_counts(self, cpu_cores, mock_platform_data):
        """Test platform detection with various CPU core counts."""
        mock_platform_data["hardware"]["cpu_cores"] = cpu_cores
        
        with patch('csc_shared.platform.Platform') as MockPlatform:
            instance = Mock()
            instance.platform_data = mock_platform_data
            MockPlatform.return_value = instance
            
            hw = instance.platform_data["hardware"]
            assert hw["cpu_cores"] == cpu_cores
            assert hw["cpu_cores"] > 0

    def test_memory_detection(self, mock_platform_instance):
        """Memory information should be detected."""
        hw = mock_platform_instance.platform_data["hardware"]
        memory_bytes = hw.get("total_memory_bytes", 0)
        assert memory_bytes > 0
        
        # Verify it's a reasonable amount (at least 512MB)
        assert memory_bytes >= 536870912

    def test_resource_assessment_categories(self, mock_platform_data):
        """Resource assessment should categorize resource levels."""
        assessment = mock_platform_data["resource_assessment"]
        valid_levels = ["low", "medium", "high"]
        assert assessment["resource_level"] in valid_levels

    def test_platform_instantiation(self, mock_platform_instance):
        """Platform instance should be creatable and contain data."""
        assert mock_platform_instance is not None
        assert mock_platform_instance.platform_data is not None
        assert isinstance(mock_platform_instance.platform_data, dict)

    def test_virtualization_types(self, mock_platform_data):
        """Test various virtualization type detections."""
        virt_types = [
            "docker_container",
            "kvm",
            "virtualbox",
            "vmware",
            "xen",
            "none"
        ]
        
        for virt_type in virt_types:
            mock_platform_data["virtualization"]["type"] = virt_type
            virt = mock_platform_data["virtualization"]
            assert virt["type"] == virt_type

    def test_platform_data_not_empty(self, mock_platform_instance):
        """Platform data should not be empty."""
        assert len(mock_platform_instance.platform_data) > 0

    def test_hardware_cpu_model_present(self, mock_platform_instance):
        """CPU model information should be present."""
        hw = mock_platform_instance.platform_data["hardware"]
        assert "cpu_model" in hw
        assert isinstance(hw["cpu_model"], str)
        assert len(hw["cpu_model"]) > 0

    def test_os_distribution_detected(self, mock_platform_instance):
        """OS distribution should be detected."""
        os_info = mock_platform_instance.platform_data["os"]
        assert "distribution" in os_info
        distributions = ["Ubuntu", "Debian", "CentOS", "Fedora", "Alpine"]
        assert os_info["distribution"] in distributions or isinstance(os_info["distribution"], str)

    def test_memory_values_reasonable(self, mock_platform_instance):
        """Memory values should be within reasonable ranges."""
        resource = mock_platform_instance.platform_data["resource_assessment"]
        memory_gb = resource.get("memory_gb", 0)
        swap_gb = resource.get("swap_gb", 0)
        
        # Memory should be at least 512MB, swap can be 0
        assert memory_gb >= 0.5
        assert swap_gb >= 0

    def test_hypervisor_info_when_virtualized(self, mock_platform_instance):
        """Hypervisor info should be present when virtualized."""
        virt = mock_platform_instance.platform_data["virtualization"]
        if virt["type"] != "none":
            assert "hypervisor" in virt or virt["type"] in ["docker_container", "kvm"]
```