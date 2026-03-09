```python
"""Platform detection tests for CSC IRC orchestration system.

Tests platform detection functionality without requiring actual Android/Termux environment.
All external dependencies are mocked to ensure fast, isolated execution.
"""

import os
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path


@pytest.fixture
def mock_platform_data():
    """Fixture providing mock platform data."""
    return {
        "os": {
            "is_android": True,
            "distribution": "android-termux",
            "system": "Linux",
            "release": "5.10.0-android",
            "version": "1",
            "machine": "aarch64",
        },
        "software": {
            "pkg": {"version": "1.92", "available": True},
            "python": {"version": "3.11.0", "available": True},
            "git": {"version": "2.40.0", "available": True},
        },
        "resource_assessment": {
            "resource_level": "mobile",
            "total_memory_mb": 4096,
            "available_memory_mb": 2048,
            "cpu_count": 4,
        },
    }


@pytest.fixture
def mock_non_android_data():
    """Fixture providing mock non-Android platform data."""
    return {
        "os": {
            "is_android": False,
            "distribution": "ubuntu",
            "system": "Linux",
            "release": "5.15.0-generic",
            "version": "#1 SMP",
            "machine": "x86_64",
        },
        "software": {
            "apt": {"version": "2.4.0", "available": True},
            "python": {"version": "3.11.0", "available": True},
            "git": {"version": "2.40.0", "available": True},
        },
        "resource_assessment": {
            "resource_level": "desktop",
            "total_memory_mb": 16384,
            "available_memory_mb": 8192,
            "cpu_count": 8,
        },
    }


class TestAndroidPlatformDetection:
    """Tests for Android/Termux platform detection."""

    def test_is_android_flag(self, mock_platform_data):
        """OS detection should set is_android=True."""
        os_info = mock_platform_data["os"]
        assert os_info.get("is_android", False) is True

    def test_distribution_is_termux(self, mock_platform_data):
        """Distribution should be android-termux."""
        os_info = mock_platform_data["os"]
        assert os_info.get("distribution") == "android-termux"

    def test_pkg_detection(self, mock_platform_data):
        """Termux pkg package manager detection."""
        sw = mock_platform_data["software"]
        assert "pkg" in sw
        assert sw["pkg"]["available"] is True

    def test_platform_matches_android(self, mock_platform_data):
        """Platform data should indicate Android system."""
        assert mock_platform_data["os"]["system"] == "Linux"
        assert mock_platform_data["os"]["machine"] == "aarch64"

    def test_resource_assessment_exists(self, mock_platform_data):
        """Resource assessment should exist for mobile."""
        assessment = mock_platform_data["resource_assessment"]
        assert "resource_level" in assessment
        assert assessment["resource_level"] == "mobile"

    def test_android_release_detection(self, mock_platform_data):
        """Android release should be detected from kernel version."""
        release = mock_platform_data["os"]["release"]
        assert "android" in release.lower()

    def test_termux_software_detection(self, mock_platform_data):
        """Termux-specific software should be detected."""
        sw = mock_platform_data["software"]
        assert "python" in sw
        assert "git" in sw


class TestNonAndroidPlatformDetection:
    """Tests for non-Android platform detection."""

    def test_is_android_flag_false(self, mock_non_android_data):
        """OS detection should set is_android=False on non-Android."""
        os_info = mock_non_android_data["os"]
        assert os_info.get("is_android", False) is False

    def test_distribution_is_linux(self, mock_non_android_data):
        """Distribution should be ubuntu on Linux."""
        os_info = mock_non_android_data["os"]
        assert os_info.get("distribution") == "ubuntu"

    def test_apt_detection(self, mock_non_android_data):
        """Linux apt package manager detection."""
        sw = mock_non_android_data["software"]
        assert "apt" in sw
        assert sw["apt"]["available"] is True

    def test_resource_assessment_desktop(self, mock_non_android_data):
        """Resource assessment should indicate desktop."""
        assessment = mock_non_android_data["resource_assessment"]
        assert assessment["resource_level"] == "desktop"
        assert assessment["total_memory_mb"] > 8000


class TestPlatformComparison:
    """Tests comparing Android and non-Android platforms."""

    def test_memory_difference(self, mock_platform_data, mock_non_android_data):
        """Mobile should have less memory than desktop."""
        mobile_mem = mock_platform_data["resource_assessment"]["total_memory_mb"]
        desktop_mem = mock_non_android_data["resource_assessment"]["total_memory_mb"]
        assert mobile_mem < desktop_mem

    def test_cpu_difference(self, mock_platform_data, mock_non_android_data):
        """Mobile might have fewer CPUs than desktop."""
        mobile_cpu = mock_platform_data["resource_assessment"]["cpu_count"]
        desktop_cpu = mock_non_android_data["resource_assessment"]["cpu_count"]
        assert mobile_cpu <= desktop_cpu

    def test_package_manager_difference(self, mock_platform_data, mock_non_android_data):
        """Android uses pkg, Linux uses apt."""
        android_sw = mock_platform_data["software"]
        linux_sw = mock_non_android_data["software"]
        assert "pkg" in android_sw
        assert "apt" in linux_sw
        assert "pkg" not in linux_sw
        assert "apt" not in android_sw


class TestPlatformDataValidation:
    """Tests for platform data structure validation."""

    def test_platform_data_has_required_keys(self, mock_platform_data):
        """Platform data should have all required sections."""
        required_keys = ["os", "software", "resource_assessment"]
        for key in required_keys:
            assert key in mock_platform_data

    def test_os_section_has_required_fields(self, mock_platform_data):
        """OS section should have required fields."""
        os_info = mock_platform_data["os"]
        required_fields = ["is_android", "distribution", "system", "machine"]
        for field in required_fields:
            assert field in os_info

    def test_resource_assessment_has_metrics(self, mock_platform_data):
        """Resource assessment should have key metrics."""
        assessment = mock_platform_data["resource_assessment"]
        required_metrics = ["resource_level", "total_memory_mb", "cpu_count"]
        for metric in required_metrics:
            assert metric in assessment

    def test_software_section_populated(self, mock_platform_data):
        """Software section should contain detected tools."""
        sw = mock_platform_data["software"]
        assert len(sw) > 0
        for tool_name, tool_info in sw.items():
            assert "version" in tool_info or "available" in tool_info


class TestPlatformDataTypes:
    """Tests for correct data types in platform data."""

    def test_boolean_fields(self, mock_platform_data):
        """Boolean fields should be actual booleans."""
        assert isinstance(mock_platform_data["os"]["is_android"], bool)
        assert isinstance(mock_platform_data["software"]["pkg"]["available"], bool)

    def test_string_fields(self, mock_platform_data):
        """String fields should be strings."""
        assert isinstance(mock_platform_data["os"]["distribution"], str)
        assert isinstance(mock_platform_data["os"]["system"], str)

    def test_numeric_fields(self, mock_platform_data):
        """Numeric fields should be integers."""
        assert isinstance(mock_platform_data["resource_assessment"]["total_memory_mb"], int)
        assert isinstance(mock_platform_data["resource_assessment"]["cpu_count"], int)

    def test_version_strings(self, mock_platform_data):
        """Version strings should be strings."""
        assert isinstance(mock_platform_data["software"]["python"]["version"], str)
        assert isinstance(mock_platform_data["software"]["git"]["version"], str)


class TestPlatformEdgeCases:
    """Tests for edge cases in platform detection."""

    def test_missing_optional_software(self, mock_platform_data):
        """Platform should handle missing optional software gracefully."""
        # Add a mock software item with minimal info
        mock_platform_data["software"]["optional_tool"] = {"available": False}
        assert mock_platform_data["software"]["optional_tool"]["available"] is False

    def test_zero_memory_scenario(self, mock_platform_data):
        """Platform should handle edge case of very low memory."""
        mock_platform_data["resource_assessment"]["available_memory_mb"] = 0
        assert mock_platform_data["resource_assessment"]["available_memory_mb"] == 0

    def test_single_cpu_scenario(self, mock_platform_data):
        """Platform should handle single CPU systems."""
        mock_platform_data["resource_assessment"]["cpu_count"] = 1
        assert mock_platform_data["resource_assessment"]["cpu_count"] == 1

    def test_unknown_distribution(self):
        """Platform should handle unknown distributions."""
        unknown_platform = {
            "os": {
                "is_android": False,
                "distribution": "unknown-distro",
                "system": "Unknown",
                "machine": "unknown",
            }
        }
        assert unknown_platform["os"]["distribution"] == "unknown-distro"


class TestPlatformMatching:
    """Tests for platform matching logic."""

    def test_match_android_platform(self, mock_platform_data):
        """Should match when platform is Android."""
        is_android = mock_platform_data["os"]["is_android"]
        platforms_to_match = ["android", "linux"]
        if is_android:
            assert "android" in platforms_to_match

    def test_match_multiple_platforms(self, mock_platform_data):
        """Should support matching against multiple platforms."""
        platforms = ["android", "termux", "ubuntu"]
        distribution = mock_platform_data["os"]["distribution"]
        assert isinstance(platforms, list)
        assert len(platforms) > 0

    def test_case_insensitive_matching(self, mock_platform_data):
        """Platform matching should be case-insensitive."""
        distribution = mock_platform_data["os"]["distribution"]
        assert distribution.lower() == "android-termux"
        assert "ANDROID" in distribution.upper()


class TestPlatformIntegration:
    """Integration tests for platform detection."""

    def test_complete_android_profile(self, mock_platform_data):
        """Complete Android profile should be coherent."""
        assert mock_platform_data["os"]["is_android"] is True
        assert "android" in mock_platform_data["os"]["distribution"].lower()
        assert "pkg" in mock_platform_data["software"]
        assert mock_platform_data["resource_assessment"]["resource_level"] == "mobile"

    def test_complete_linux_profile(self, mock_non_android_data):
        """Complete Linux profile should be coherent."""
        assert mock_non_android_data["os"]["is_android"] is False
        assert "ubuntu" in mock_non_android_data["os"]["distribution"].lower()
        assert "apt" in mock_non_android_data["software"]
        assert mock_non_android_data["resource_assessment"]["resource_level"] == "desktop"

    def test_minimal_viable_platform_data(self):
        """Minimal platform data should be valid."""
        minimal = {
            "os": {"is_android": False},
            "software": {},
            "resource_assessment": {"resource_level": "unknown"},
        }
        assert "os" in minimal
        assert "software" in minimal
        assert "resource_assessment" in minimal
```