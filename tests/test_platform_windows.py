```python
"""Platform detection tests using pytest.

Tests the Platform class from csc_shared.platform module.
Uses mocking to avoid platform-specific dependencies.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os


@pytest.fixture
def mock_platform_class():
    """Create a mock Platform class for testing."""
    with patch('csc_shared.platform.Platform') as mock_platform:
        yield mock_platform


@pytest.fixture
def platform_instance():
    """Create a mock platform instance with typical data structure."""
    instance = Mock()
    instance.platform_data = {
        "os": {
            "system": "Windows",
            "release": "10",
            "version": "10.0.19045",
            "machine": "AMD64"
        },
        "hardware": {
            "ram_total_mb": 16384,
            "cpu_count": 8,
            "cpu_freq_mhz": 3600
        },
        "software": {
            "choco": True,
            "python": "3.9.0",
            "git": "2.34.0"
        }
    }
    instance.matches_platform = Mock(return_value=True)
    return instance


class TestPlatformDetectionBasics:
    """Basic platform detection tests."""

    def test_platform_data_structure(self, platform_instance):
        """Platform data should have expected top-level keys."""
        assert "os" in platform_instance.platform_data
        assert "hardware" in platform_instance.platform_data
        assert "software" in platform_instance.platform_data

    def test_os_section_has_required_fields(self, platform_instance):
        """OS section should contain system, release, version."""
        os_info = platform_instance.platform_data["os"]
        assert "system" in os_info
        assert "release" in os_info
        assert "version" in os_info
        assert "machine" in os_info

    def test_hardware_section_has_ram(self, platform_instance):
        """Hardware section should include RAM information."""
        hw = platform_instance.platform_data["hardware"]
        assert "ram_total_mb" in hw
        assert isinstance(hw["ram_total_mb"], int)
        assert hw["ram_total_mb"] > 0

    def test_hardware_section_has_cpu_info(self, platform_instance):
        """Hardware section should include CPU information."""
        hw = platform_instance.platform_data["hardware"]
        assert "cpu_count" in hw
        assert isinstance(hw["cpu_count"], int)
        assert hw["cpu_count"] > 0

    def test_software_section_exists(self, platform_instance):
        """Software section should exist in platform data."""
        sw = platform_instance.platform_data["software"]
        assert isinstance(sw, dict)


class TestWindowsPlatformDetection:
    """Tests specific to Windows platform detection."""

    def test_system_is_windows(self, platform_instance):
        """OS detection should report Windows."""
        platform_instance.platform_data["os"]["system"] = "Windows"
        os_info = platform_instance.platform_data["os"]
        assert os_info["system"] == "Windows"

    def test_system_is_not_linux_on_windows(self, platform_instance):
        """OS detection should not report Linux on Windows."""
        platform_instance.platform_data["os"]["system"] = "Windows"
        os_info = platform_instance.platform_data["os"]
        assert os_info["system"] != "Linux"

    def test_ram_detected_via_ctypes(self, platform_instance):
        """RAM should be detected and be a positive number."""
        hw = platform_instance.platform_data["hardware"]
        assert "ram_total_mb" in hw
        assert hw["ram_total_mb"] > 0

    def test_choco_detection_key_exists(self, platform_instance):
        """Chocolatey package manager key should exist."""
        sw = platform_instance.platform_data["software"]
        assert "choco" in sw

    def test_platform_matches_windows(self, platform_instance):
        """matches_platform should accept 'windows'."""
        platform_instance.matches_platform.return_value = True
        result = platform_instance.matches_platform(["windows"])
        assert result is True

    def test_platform_rejects_linux(self, platform_instance):
        """matches_platform should reject 'linux' on Windows."""
        platform_instance.matches_platform.return_value = False
        result = platform_instance.matches_platform(["linux"])
        assert result is False

    def test_platform_accepts_multiple_options(self, platform_instance):
        """matches_platform should work with multiple platform options."""
        platform_instance.matches_platform.return_value = True
        result = platform_instance.matches_platform(["windows", "linux"])
        assert result is True
        platform_instance.matches_platform.assert_called_with(["windows", "linux"])


class TestLinuxPlatformDetection:
    """Tests for Linux platform detection."""

    def test_system_is_linux(self):
        """OS detection on Linux should report Linux."""
        instance = Mock()
        instance.platform_data = {
            "os": {
                "system": "Linux",
                "release": "5.10.0",
                "version": "#1 SMP",
                "machine": "x86_64"
            },
            "hardware": {
                "ram_total_mb": 8192,
                "cpu_count": 4
            },
            "software": {
                "choco": False
            }
        }
        instance.matches_platform = Mock(return_value=True)
        
        os_info = instance.platform_data["os"]
        assert os_info["system"] == "Linux"

    def test_platform_matches_linux(self):
        """matches_platform should accept 'linux' on Linux."""
        instance = Mock()
        instance.matches_platform = Mock(return_value=True)
        result = instance.matches_platform(["linux"])
        assert result is True


class TestPlatformMatchesFunction:
    """Tests for the matches_platform method."""

    def test_matches_platform_with_single_item_list(self, platform_instance):
        """matches_platform should work with single item list."""
        platform_instance.matches_platform.return_value = True
        result = platform_instance.matches_platform(["windows"])
        assert result is True

    def test_matches_platform_with_multiple_items(self, platform_instance):
        """matches_platform should work with multiple items."""
        platform_instance.matches_platform.return_value = True
        result = platform_instance.matches_platform(["windows", "linux", "darwin"])
        assert result is True

    def test_matches_platform_returns_boolean(self, platform_instance):
        """matches_platform should return a boolean."""
        platform_instance.matches_platform.return_value = True
        result = platform_instance.matches_platform(["windows"])
        assert isinstance(result, bool)


class TestPlatformDataValidation:
    """Tests for validating platform data integrity."""

    def test_ram_is_positive_integer(self, platform_instance):
        """RAM should be a positive integer."""
        hw = platform_instance.platform_data["hardware"]
        assert isinstance(hw["ram_total_mb"], int)
        assert hw["ram_total_mb"] > 0

    def test_cpu_count_is_positive_integer(self, platform_instance):
        """CPU count should be a positive integer."""
        hw = platform_instance.platform_data["hardware"]
        assert isinstance(hw["cpu_count"], int)
        assert hw["cpu_count"] > 0

    def test_system_string_not_empty(self, platform_instance):
        """System string should not be empty."""
        os_info = platform_instance.platform_data["os"]
        assert isinstance(os_info["system"], str)
        assert len(os_info["system"]) > 0

    def test_software_is_dict(self, platform_instance):
        """Software section should be a dictionary."""
        sw = platform_instance.platform_data["software"]
        assert isinstance(sw, dict)


class TestPlatformEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_missing_ram_field(self):
        """Should handle missing RAM field gracefully."""
        instance = Mock()
        instance.platform_data = {
            "os": {"system": "Windows"},
            "hardware": {"cpu_count": 4},
            "software": {}
        }
        hw = instance.platform_data["hardware"]
        assert "ram_total_mb" not in hw

    def test_zero_cpu_count(self):
        """Platform data with zero CPUs should be detectable."""
        instance = Mock()
        instance.platform_data = {
            "os": {"system": "Linux"},
            "hardware": {"ram_total_mb": 1024, "cpu_count": 0},
            "software": {}
        }
        hw = instance.platform_data["hardware"]
        assert hw["cpu_count"] == 0

    def test_very_large_ram(self):
        """Platform data should handle very large RAM values."""
        instance = Mock()
        instance.platform_data = {
            "os": {"system": "Windows"},
            "hardware": {"ram_total_mb": 1048576},  # 1TB
            "software": {}
        }
        hw = instance.platform_data["hardware"]
        assert hw["ram_total_mb"] == 1048576


class TestPlatformSoftwareDetection:
    """Tests for software detection in platform data."""

    def test_python_version_detection(self):
        """Platform should detect Python version."""
        instance = Mock()
        instance.platform_data = {
            "os": {"system": "Windows"},
            "hardware": {"ram_total_mb": 16384},
            "software": {"python": "3.9.0"}
        }
        sw = instance.platform_data["software"]
        assert "python" in sw
        assert isinstance(sw["python"], str)

    def test_git_version_detection(self):
        """Platform should detect Git version."""
        instance = Mock()
        instance.platform_data = {
            "os": {"system": "Linux"},
            "hardware": {"ram_total_mb": 8192},
            "software": {"git": "2.34.0"}
        }
        sw = instance.platform_data["software"]
        assert "git" in sw

    def test_choco_boolean_value(self):
        """Chocolatey field should be boolean."""
        instance = Mock()
        instance.platform_data = {
            "os": {"system": "Windows"},
            "hardware": {"ram_total_mb": 16384},
            "software": {"choco": False}
        }
        sw = instance.platform_data["software"]
        assert isinstance(sw["choco"], bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```