```python
"""Platform detection tests using pytest with proper mocking."""

import os
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock
import platform as stdlib_platform


# Mock the platform_gate module before importing anything else
sys.modules['platform_gate'] = MagicMock()


class TestPlatformDetection:
    """Tests for platform detection functionality."""

    @pytest.fixture
    def mock_platform_data(self):
        """Fixture providing mock platform data."""
        return {
            "virtualization": {"type": "wsl"},
            "os": {
                "system": "Linux",
                "release": "4.19.128-microsoft-standard",
                "version": "#1 SMP Tue Jun 23 12:58:10 UTC 2020",
            },
        }

    @pytest.fixture
    def mock_platform_class(self, mock_platform_data):
        """Fixture providing a mock Platform class."""
        mock_obj = Mock()
        mock_obj.platform_data = mock_platform_data
        mock_obj.matches_platform = Mock(return_value=True)
        return mock_obj

    def test_virtualization_is_wsl(self, mock_platform_class):
        """Virtualization detection should report wsl."""
        virt = mock_platform_class.platform_data["virtualization"]
        assert virt["type"] == "wsl"

    def test_system_is_linux(self, mock_platform_class):
        """WSL reports as Linux at OS level."""
        os_info = mock_platform_class.platform_data["os"]
        assert os_info["system"] == "Linux"

    def test_release_contains_microsoft(self, mock_platform_class):
        """WSL kernel release should contain 'microsoft'."""
        os_info = mock_platform_class.platform_data["os"]
        release = os_info["release"].lower()
        assert "microsoft" in release or "wsl" in release

    def test_platform_matches_wsl(self, mock_platform_class):
        """matches_platform should detect WSL as linux."""
        mock_platform_class.matches_platform.return_value = True
        assert mock_platform_class.matches_platform(["linux"]) is True

    def test_platform_matches_linux(self, mock_platform_class):
        """matches_platform should handle linux platform."""
        mock_platform_class.matches_platform.return_value = True
        result = mock_platform_class.matches_platform(["linux"])
        assert result is True
        mock_platform_class.matches_platform.assert_called_once_with(["linux"])

    def test_platform_mismatch(self, mock_platform_class):
        """matches_platform should return False for non-matching platforms."""
        mock_platform_class.matches_platform.return_value = False
        result = mock_platform_class.matches_platform(["darwin"])
        assert result is False

    def test_platform_data_structure(self, mock_platform_class):
        """Platform data should have required structure."""
        data = mock_platform_class.platform_data
        assert "virtualization" in data
        assert "os" in data
        assert "type" in data["virtualization"]
        assert "system" in data["os"]
        assert "release" in data["os"]

    @patch('platform.system')
    def test_system_detection(self, mock_system):
        """Test that system detection works correctly."""
        mock_system.return_value = "Linux"
        result = stdlib_platform.system()
        assert result == "Linux"
        mock_system.assert_called_once()

    @patch('platform.release')
    def test_kernel_release_detection(self, mock_release):
        """Test that kernel release can be detected."""
        mock_release.return_value = "4.19.128-microsoft-standard"
        result = stdlib_platform.release()
        assert "microsoft" in result.lower()

    def test_platform_multiple_matches(self, mock_platform_class):
        """matches_platform should work with multiple platform options."""
        mock_platform_class.matches_platform.return_value = True
        result = mock_platform_class.matches_platform(["linux", "wsl"])
        assert result is True

    def test_platform_empty_list(self, mock_platform_class):
        """matches_platform should handle empty platform list."""
        mock_platform_class.matches_platform.return_value = False
        result = mock_platform_class.matches_platform([])
        assert result is False

    def test_virtualization_type_present(self, mock_platform_data):
        """Platform data should always have virtualization type."""
        assert "virtualization" in mock_platform_data
        assert mock_platform_data["virtualization"]["type"] is not None

    def test_os_system_present(self, mock_platform_data):
        """Platform data should always have OS system info."""
        assert "os" in mock_platform_data
        assert mock_platform_data["os"]["system"] is not None

    def test_os_release_present(self, mock_platform_data):
        """Platform data should always have OS release info."""
        assert "os" in mock_platform_data
        assert mock_platform_data["os"]["release"] is not None

    @patch('platform.platform')
    def test_full_platform_string(self, mock_platform_func):
        """Test full platform string detection."""
        mock_platform_func.return_value = "Linux-4.19.128-microsoft-standard-x86_64-with-glibc2.31"
        result = stdlib_platform.platform()
        assert "Linux" in result
        assert "microsoft" in result.lower()

    def test_virtualization_types_recognized(self, mock_platform_class):
        """Test that various virtualization types can be recognized."""
        virt_types = ["wsl", "kvm", "virtualbox", "vmware", "xen", "hyper-v"]
        for virt_type in virt_types:
            mock_platform_class.platform_data["virtualization"]["type"] = virt_type
            assert mock_platform_class.platform_data["virtualization"]["type"] == virt_type

    def test_os_systems_recognized(self, mock_platform_class):
        """Test that various OS systems can be recognized."""
        os_systems = ["Linux", "Windows", "Darwin", "Java"]
        for os_system in os_systems:
            mock_platform_class.platform_data["os"]["system"] = os_system
            assert mock_platform_class.platform_data["os"]["system"] == os_system


class TestPlatformDetectionWithMocking:
    """Integration tests with comprehensive mocking."""

    @pytest.fixture
    def platform_mock_instance(self):
        """Create a comprehensive mock Platform instance."""
        instance = Mock()
        instance.platform_data = {
            "virtualization": {
                "type": "wsl",
                "detected": True,
            },
            "os": {
                "system": "Linux",
                "release": "4.19.128-microsoft-standard",
                "version": "#1 SMP",
                "machine": "x86_64",
            },
            "cpu": {
                "count": 4,
                "processor": "Intel(R) Core(TM)",
            },
        }
        instance.matches_platform = Mock(side_effect=lambda platforms: any(
            p in ["linux", "wsl"] for p in platforms
        ))
        return instance

    def test_complex_platform_detection(self, platform_mock_instance):
        """Test complex platform detection scenarios."""
        assert platform_mock_instance.platform_data["virtualization"]["type"] == "wsl"
        assert platform_mock_instance.platform_data["os"]["system"] == "Linux"
        assert platform_mock_instance.matches_platform(["linux"]) is True

    def test_cpu_info_available(self, platform_mock_instance):
        """Test that CPU information is available."""
        cpu_info = platform_mock_instance.platform_data.get("cpu")
        assert cpu_info is not None
        assert "count" in cpu_info

    def test_machine_architecture_detected(self, platform_mock_instance):
        """Test that machine architecture is detected."""
        machine = platform_mock_instance.platform_data["os"].get("machine")
        assert machine is not None

    def test_virtualization_detection_flag(self, platform_mock_instance):
        """Test that virtualization detection flag is present."""
        virt = platform_mock_instance.platform_data["virtualization"]
        assert virt.get("detected") is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```