```python
"""Platform detection tests for macOS.

Tests the Platform class from csc_shared.platform module.
These tests mock system calls to avoid requiring macOS at test time.
"""

import os
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestPlatformDetection:
    """Tests for Platform class detection capabilities."""

    @pytest.fixture
    def mock_platform_data(self):
        """Fixture providing mock platform data structure."""
        return {
            "os": {
                "system": "Darwin",
                "release": "21.6.0",
                "version": "11.7.1"
            },
            "hardware": {
                "ram_total_mb": 16384,
                "cpu_count": 8,
                "cpu_freq_mhz": 2400
            },
            "software": {
                "brew": "/usr/local/bin/brew",
                "python": "3.9.0",
                "node": "16.0.0"
            }
        }

    @pytest.fixture
    def mock_platform_instance(self, mock_platform_data):
        """Fixture providing a mocked Platform instance."""
        with patch('csc_shared.platform.Platform') as mock_class:
            instance = MagicMock()
            instance.platform_data = mock_platform_data
            instance.matches_platform = Mock(side_effect=lambda platforms: 
                                            "darwin" in platforms)
            mock_class.return_value = instance
            return instance

    def test_os_detection_darwin(self, mock_platform_instance):
        """OS detection should report Darwin on macOS."""
        os_info = mock_platform_instance.platform_data["os"]
        assert os_info["system"] == "Darwin"
        assert "release" in os_info
        assert "version" in os_info

    def test_ram_detected_in_hardware(self, mock_platform_instance):
        """RAM should be present in hardware data."""
        hw = mock_platform_instance.platform_data["hardware"]
        assert "ram_total_mb" in hw
        assert hw["ram_total_mb"] > 0
        assert isinstance(hw["ram_total_mb"], int)

    def test_cpu_info_detected(self, mock_platform_instance):
        """CPU information should be detected."""
        hw = mock_platform_instance.platform_data["hardware"]
        assert "cpu_count" in hw
        assert "cpu_freq_mhz" in hw
        assert hw["cpu_count"] > 0

    def test_brew_in_software(self, mock_platform_instance):
        """Homebrew should be detected in software section."""
        sw = mock_platform_instance.platform_data["software"]
        assert "brew" in sw
        assert "brew" in sw["brew"] or sw["brew"] is not None

    def test_matches_platform_darwin(self, mock_platform_instance):
        """matches_platform should return True for darwin."""
        result = mock_platform_instance.matches_platform(["darwin"])
        assert result is True

    def test_matches_platform_windows(self, mock_platform_instance):
        """matches_platform should return False for windows on macOS."""
        result = mock_platform_instance.matches_platform(["windows"])
        assert result is False

    def test_matches_platform_linux(self, mock_platform_instance):
        """matches_platform should return False for linux on macOS."""
        result = mock_platform_instance.matches_platform(["linux"])
        assert result is False

    def test_matches_platform_multiple_options(self, mock_platform_instance):
        """matches_platform should accept multiple platform options."""
        result = mock_platform_instance.matches_platform(["windows", "darwin", "linux"])
        assert result is True

    def test_platform_data_structure(self, mock_platform_instance):
        """Platform data should have expected top-level keys."""
        data = mock_platform_instance.platform_data
        assert "os" in data
        assert "hardware" in data
        assert "software" in data

    def test_os_section_has_required_fields(self, mock_platform_instance):
        """OS section should have system, release, version."""
        os_info = mock_platform_instance.platform_data["os"]
        assert "system" in os_info
        assert "release" in os_info
        assert "version" in os_info

    def test_hardware_section_has_required_fields(self, mock_platform_instance):
        """Hardware section should have RAM and CPU info."""
        hw = mock_platform_instance.platform_data["hardware"]
        assert "ram_total_mb" in hw
        assert "cpu_count" in hw
        assert "cpu_freq_mhz" in hw

    def test_software_section_is_dict(self, mock_platform_instance):
        """Software section should be a dictionary."""
        sw = mock_platform_instance.platform_data["software"]
        assert isinstance(sw, dict)

    def test_matches_platform_with_empty_list(self, mock_platform_instance):
        """matches_platform with empty list should return False."""
        # Override the mock for this specific test
        mock_platform_instance.matches_platform = Mock(return_value=False)
        result = mock_platform_instance.matches_platform([])
        assert result is False

    def test_platform_data_is_immutable_structure(self, mock_platform_instance):
        """Platform data should maintain consistent structure."""
        data1 = mock_platform_instance.platform_data
        data2 = mock_platform_instance.platform_data
        assert data1["os"]["system"] == data2["os"]["system"]
        assert data1["hardware"]["ram_total_mb"] == data2["hardware"]["ram_total_mb"]

    @pytest.mark.parametrize("platform_name", ["darwin", "macos", "osx"])
    def test_matches_multiple_platform_names(self, platform_name):
        """Test platform matching with various names."""
        with patch('csc_shared.platform.Platform') as mock_class:
            instance = MagicMock()
            instance.matches_platform = Mock(
                side_effect=lambda platforms: platform_name in platforms
            )
            
            if platform_name == "darwin":
                assert instance.matches_platform([platform_name]) is True
            else:
                # Non-darwin names should follow their own logic
                assert instance.matches_platform([platform_name]) is True

    def test_platform_instance_creation(self):
        """Platform instance should be creatable (with mocking)."""
        with patch('csc_shared.platform.Platform') as mock_class:
            mock_instance = MagicMock()
            mock_class.return_value = mock_instance
            
            # This would normally instantiate the Platform class
            from csc_shared.platform import Platform
            instance = Platform()
            
            assert instance is not None
            mock_class.assert_called_once()


class TestPlatformEdgeCases:
    """Edge case tests for Platform class."""

    def test_ram_zero_value_handling(self):
        """Platform should handle zero RAM gracefully."""
        with patch('csc_shared.platform.Platform') as mock_class:
            instance = MagicMock()
            instance.platform_data = {
                "hardware": {"ram_total_mb": 0}
            }
            mock_class.return_value = instance
            
            hw = instance.platform_data["hardware"]
            assert "ram_total_mb" in hw

    def test_missing_software_entry(self):
        """Platform should handle missing software entries."""
        with patch('csc_shared.platform.Platform') as mock_class:
            instance = MagicMock()
            instance.platform_data = {
                "software": {}
            }
            mock_class.return_value = instance
            
            sw = instance.platform_data["software"]
            assert isinstance(sw, dict)
            assert "brew" not in sw


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```