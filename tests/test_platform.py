```python
"""Tests for Platform detection layer."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import pytest


def test_parse_size_bytes():
    """Test parsing bytes."""
    from csc_service.shared.platform import _parse_size
    assert _parse_size("1024B") == 1024


def test_parse_size_kilobytes():
    """Test parsing kilobytes."""
    from csc_service.shared.platform import _parse_size
    assert _parse_size("1KB") == 1024


def test_parse_size_megabytes():
    """Test parsing megabytes."""
    from csc_service.shared.platform import _parse_size
    assert _parse_size("512MB") == 512 * 1024 * 1024


def test_parse_size_gigabytes():
    """Test parsing gigabytes."""
    from csc_service.shared.platform import _parse_size
    assert _parse_size("2GB") == 2 * 1024 ** 3


def test_parse_size_terabytes():
    """Test parsing terabytes."""
    from csc_service.shared.platform import _parse_size
    assert _parse_size("1TB") == 1024 ** 4


def test_parse_size_bare_number():
    """Test parsing bare number."""
    from csc_service.shared.platform import _parse_size
    assert _parse_size("4096") == 4096


def test_parse_size_whitespace():
    """Test parsing with whitespace."""
    from csc_service.shared.platform import _parse_size
    assert _parse_size("  2GB  ") == 2 * 1024 ** 3


def test_parse_size_case_insensitive():
    """Test parsing is case insensitive."""
    from csc_service.shared.platform import _parse_size
    assert _parse_size("2gb") == 2 * 1024 ** 3


def test_parse_size_invalid():
    """Test parsing invalid input."""
    from csc_service.shared.platform import _parse_size
    assert _parse_size("bogus") == 0


@pytest.fixture
def mock_version_class():
    """Mock the Version base class."""
    with patch('csc_service.shared.platform.Version') as mock_version:
        mock_instance = MagicMock()
        mock_version.return_value = mock_instance
        yield mock_version


@pytest.fixture
def mock_log_class():
    """Mock the Log class."""
    with patch('csc_service.shared.log.Log') as mock_log:
        yield mock_log


@pytest.fixture
def platform_instance(mock_version_class, mock_log_class, tmp_path, monkeypatch):
    """Create a Platform instance with mocked dependencies."""
    monkeypatch.setenv("HOME", str(tmp_path))
    
    with patch('csc_service.shared.platform.Platform._detect_hardware') as mock_hw, \
         patch('csc_service.shared.platform.Platform._detect_os') as mock_os, \
         patch('csc_service.shared.platform.Platform._detect_virtualization') as mock_virt, \
         patch('csc_service.shared.platform.Platform._detect_geography') as mock_geo, \
         patch('csc_service.shared.platform.Platform._detect_time') as mock_time, \
         patch('csc_service.shared.platform.Platform._detect_network') as mock_net, \
         patch('csc_service.shared.platform.Platform._detect_software') as mock_soft, \
         patch('csc_service.shared.platform.Platform._detect_docker') as mock_docker, \
         patch('csc_service.shared.platform.Platform._detect_ai_agents') as mock_ai, \
         patch('csc_service.shared.platform.Platform._assess_resources') as mock_assess, \
         patch('csc_service.shared.platform.Platform._detect_runtime') as mock_runtime, \
         patch('csc_service.shared.platform.Platform._persist_platform'), \
         patch('csc_service.shared.platform.Platform.export_env_paths'), \
         patch('csc_service.shared.platform.Platform.log'):
        
        mock_hw.return_value = {"cpu_cores": 4, "architecture": "x86_64"}
        mock_os.return_value = {"system": "Linux", "python_version": "3.10"}
        mock_virt.return_value = {"virtualized": False}
        mock_geo.return_value = {"timezone": "UTC"}
        mock_time.return_value = {"utc_offset": "+0000"}
        mock_net.return_value = {"hostname": "test-host"}
        mock_soft.return_value = {"python3": {"installed": True}}
        mock_docker.return_value = {"installed": False, "daemon_running": False, "usable": False}
        mock_ai.return_value = {}
        mock_assess.return_value = {"resource_level": "medium"}
        mock_runtime.return_value = {"temp_dir_linux": str(tmp_path)}
        
        from csc_service.shared.platform import Platform
        platform = Platform()
        platform.PROJECT_ROOT = tmp_path
        return platform


class TestPlatformDetection:
    """Test Platform class detection routines."""

    def test_platform_data_populated(self, platform_instance):
        """Platform data dict should have all expected top-level keys."""
        expected_keys = [
            "detected_at", "hardware", "os", "virtualization",
            "geography", "time", "software", "docker",
            "ai_agents", "resource_assessment", "network", "runtime",
        ]
        for key in expected_keys:
            assert key in platform_instance.platform_data, f"Missing key: {key}"

    def test_hardware_has_cpu_cores(self, platform_instance):
        """Hardware should have cpu_cores."""
        hw = platform_instance.platform_data["hardware"]
        assert "cpu_cores" in hw
        assert isinstance(hw["cpu_cores"], int)
        assert hw["cpu_cores"] > 0

    def test_hardware_has_architecture(self, platform_instance):
        """Hardware should have architecture."""
        hw = platform_instance.platform_data["hardware"]
        assert "architecture" in hw

    def test_os_has_system(self, platform_instance):
        """OS info should have system."""
        os_info = platform_instance.platform_data["os"]
        assert "system" in os_info

    def test_os_has_python_version(self, platform_instance):
        """OS info should have python_version."""
        os_info = platform_instance.platform_data["os"]
        assert "python_version" in os_info

    def test_software_detection(self, platform_instance):
        """Software should have expected tools."""
        sw = platform_instance.platform_data["software"]
        assert "python3" in sw
        assert sw["python3"]["installed"] is True

    def test_software_has_installed_flag(self, platform_instance):
        """All software entries should have installed flag."""
        sw = platform_instance.platform_data["software"]
        for name, info in sw.items():
            assert "installed" in info, f"Tool '{name}' missing 'installed' key"
            assert isinstance(info["installed"], bool)

    def test_docker_structure(self, platform_instance):
        """Docker info should have expected structure."""
        docker = platform_instance.platform_data["docker"]
        assert "installed" in docker
        assert "daemon_running" in docker
        assert "usable" in docker

    def test_ai_agents_structure(self, platform_instance):
        """AI agents should be a dict."""
        agents = platform_instance.platform_data["ai_agents"]
        assert isinstance(agents, dict)

    def test_resource_assessment(self, platform_instance):
        """Resource assessment should have resource_level."""
        assessment = platform_instance.platform_data["resource_assessment"]
        assert "resource_level" in assessment
        assert assessment["resource_level"] in ["minimal", "low", "medium", "high"]

    def test_geography_has_timezone(self, platform_instance):
        """Geography should have timezone."""
        geo = platform_instance.platform_data["geography"]
        assert "timezone" in geo


class TestPlatformPersistence:
    """Test platform.json persistence."""

    def test_persist_platform_creates_json(self, tmp_path, monkeypatch):
        """_persist_platform should create platform.json."""
        monkeypatch.setenv("HOME", str(tmp_path))
        
        with patch('csc_service.shared.platform.Platform._detect_hardware') as mock_hw, \
             patch('csc_service.shared.platform.Platform._detect_os') as mock_os, \
             patch('csc_service.shared.platform.Platform._detect_virtualization'), \
             patch('csc_service.shared.platform.Platform._detect_geography'), \
             patch('csc_service.shared.platform.Platform._detect_time'), \
             patch('csc_service.shared.platform.Platform._detect_network'), \
             patch('csc_service.shared.platform.Platform._detect_software'), \
             patch('csc_service.shared.platform.Platform._detect_docker'), \
             patch('csc_service.shared.platform.Platform._detect_ai_agents'), \
             patch('csc_service.shared.platform.Platform._assess_resources'), \
             patch('csc_service.shared.platform.Platform._detect_runtime'), \
             patch('csc_service.shared.platform.Platform.export_env_paths'), \
             patch('csc_service.shared.platform.Platform.log'):
            
            mock_hw.return_value = {"cpu_cores": 4, "architecture": "x86_64"}
            mock_os.return_value = {"system": "Linux", "python_version": "3.10"}
            
            from csc_service.shared.platform import Platform
            platform = Platform()
            platform.PROJECT_ROOT = tmp_path
            platform._persist_platform()
            
            json_file = tmp_path / "platform.json"
            assert json_file.exists(), "platform.json not created"

    def test_platform_json_valid(self, tmp_path, monkeypatch):
        """platform.json should be valid JSON."""
        monkeypatch.setenv("HOME", str(tmp_path))
        
        with patch('csc_service.shared.platform.Platform._detect_hardware') as mock_hw, \
             patch('csc_service.shared.platform.Platform._detect_os') as mock_os, \
             patch('csc_service.shared.platform.Platform._detect_virtualization'), \
             patch('csc_service.shared.platform.Platform._detect_geography'), \
             patch('csc_service.shared.platform.Platform._detect_time'), \
             patch('csc_service.shared.platform.Platform._detect_network'), \
             patch('csc_service.shared.platform.Platform._detect_software'), \
             patch('csc_service.shared.platform.Platform._detect_docker'), \
             patch('csc_service.shared.platform.Platform._detect_ai_agents'), \
             patch('csc_service.shared.platform.Platform._assess_resources'), \
             patch('csc_service.shared.platform.Platform._detect_runtime'), \
             patch('csc_service.shared.platform.Platform.export_env_paths'), \
             patch('csc_service.shared.platform.Platform.log'):
            
            mock_hw.return_value = {"cpu_cores": 4, "architecture": "x86_64"}
            mock_os.return_value = {"system": "Linux", "python_version": "3.10"}
            
            from csc_service.shared.platform import Platform
            platform = Platform()
            platform.PROJECT_ROOT = tmp_path
            platform.platform_data = {
                "hardware": {"cpu_cores": 4},
                "os": {"system": "Linux"}
            }
            platform._persist_platform()
            
            json_file = tmp_path / "platform.json"
            with open(json_file, "r") as f:
                data = json.load(f)
            assert isinstance(data, dict)
            assert "hardware" in data

    def test_load_platform_json_missing_file(self, tmp_path):
        """Loading from nonexistent path should return empty dict."""
        from csc_service.shared.platform import Platform
        data = Platform.load_platform_json(tmp_path / "nonexistent_platform.json")
        assert data == {}

    def test_load_platform_json_valid_file(self, tmp_path):
        """Loading from valid file should return data."""
        from csc_service.shared.platform import Platform
        json_file = tmp_path / "platform.json"
        test_data = {"hardware": {"cpu_cores": 4}}
        with open(json_file, "w") as f:
            json.dump(test_data, f)
        
        data = Platform.load_platform_json(json_file)
        assert data == test_data


class TestPlatformCapabilityChecks:
    """Test capability checking methods."""

    def test_has_tool_python3(self, platform_instance):
        """Python3 should be detected."""
        assert platform_instance.platform_data["software"]["python3"]["installed"] is True

    def test_configure_install_mode_at_startup(self, platform_instance):
        """Configure install mode at startup."""
        platform_instance.configure_install_mode(install_at_startup=True)
        assert platform_instance._install_at_startup is True
        assert platform_instance._install_as_needed is False

    def test_configure_install_mode_as_needed(self, platform_instance):
        """Configure install mode as needed."""
        platform_instance.configure_install_mode(install_as_needed=True)
        assert platform_instance._install_at_startup is False
        assert platform_instance._install_as_needed is True


class TestPlatformDetectionMethods:
    """Test individual detection methods."""

    def test_detect_hardware_structure(self):
        """_detect_hardware should return dict with expected keys."""
        from csc_service.shared.platform import Platform
        with patch('csc_service.shared.platform.Platform._detect_os'), \
             patch('csc_service.shared.platform.Platform._detect_virtualization'), \
             patch('csc_service.shared.platform.Platform._detect_geography'), \
             patch('csc_service.shared.platform.Platform._detect_time'), \
             patch('csc_service.shared.platform.Platform._detect_network'), \
             patch('csc_service.shared.platform.Platform._detect_software'), \
             patch('csc_service.shared.platform.Platform._detect_docker'), \
             patch('csc_service.shared.platform.Platform._detect_ai_agents'), \
             patch('csc_service.shared.platform.Platform._assess_resources'), \
             patch('csc_service.shared.platform.Platform._detect_runtime'), \
             patch('csc_service.shared.platform.Platform._persist_platform'), \
             patch('csc_service.shared.platform.Platform.export_env_paths'), \
             patch('csc_service.shared.platform.Platform.log'):
            
            platform = Platform()
            hardware = platform._detect_hardware()
            assert isinstance(hardware, dict)
            assert "architecture" in hardware
            assert "cpu_cores" in hardware

    def test_detect_os_structure(self):
        """_detect_os should return dict with expected keys."""
        from csc_service.shared.platform import Platform
        with patch('csc_service.shared.platform.Platform._detect_hardware'), \
             patch('csc_service.shared.platform.Platform._detect_virtualization'), \
             patch('csc_service.shared.platform.Platform._detect_geography'), \
             patch('csc_service.shared.platform.Platform._detect_time'), \
             patch('csc_service.shared.platform.Platform._detect_network'), \
             patch('csc_service.shared.platform.Platform._detect_software'), \
             patch('csc_service.shared.platform.Platform._detect_docker'), \
             patch('csc_service.shared.platform.Platform._detect_ai_agents'), \
             