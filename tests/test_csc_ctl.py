```python
#!/usr/bin/env python3
"""
Test suite for csc-ctl cross-platform CLI.

Purpose: Verify csc-ctl CLI argument parsing and command dispatch works correctly
Coverage: Argument parsing, command routing, config manager initialization
"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

from csc_service.cli.csc_ctl import main
from csc_service.config import ConfigManager


@pytest.fixture
def tmp_config(tmp_path):
    """Create a temporary config file for testing."""
    config = {
        "poll_interval": 60,
        "enable_queue_worker": True,
        "enable_test_runner": False,
        "enable_pm": True,
        "enable_server": True,
        "enable_bridge": False,
        "local_mode": False,
        "clients": {
            "gemini": {
                "enabled": True,
                "auto_start": False,
                "model": "gemini-2.5-flash"
            },
            "claude": {
                "enabled": False,
                "auto_start": False,
                "model": "claude-3-5-sonnet"
            }
        }
    }
    cfg_file = tmp_path / "csc-service.json"
    cfg_file.write_text(json.dumps(config, indent=2))
    return cfg_file


@pytest.fixture
def mock_config_manager(tmp_config):
    """Create a mock ConfigManager."""
    with patch('csc_service.cli.csc_ctl.ConfigManager') as mock_cm:
        instance = Mock(spec=ConfigManager)
        instance.config = {
            "poll_interval": 60,
            "enable_queue_worker": True,
            "enable_test_runner": False,
            "clients": {"gemini": {"enabled": True}}
        }
        mock_cm.return_value = instance
        yield mock_cm, instance


# ============================================================================
# Argument Parsing Tests
# ============================================================================

def test_main_no_args(mock_config_manager):
    """Test csc-ctl with no arguments prints help."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl']):
        with patch('sys.exit') as mock_exit:
            with patch('argparse.ArgumentParser.print_help'):
                main()
                mock_exit.assert_called_with(1)


def test_status_command_all_services(mock_config_manager):
    """Test 'status' command without service argument."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'status']):
        with patch('csc_service.cli.commands.status_cmd.status') as mock_status:
            main()
            mock_status.assert_called_once()
            args = mock_status.call_args[0][0]
            assert args.command == 'status'
            assert args.service is None


def test_status_command_specific_service(mock_config_manager):
    """Test 'status' command with specific service."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'status', 'queue-worker']):
        with patch('csc_service.cli.commands.status_cmd.status') as mock_status:
            main()
            mock_status.assert_called_once()
            args = mock_status.call_args[0][0]
            assert args.command == 'status'
            assert args.service == 'queue-worker'


def test_show_command(mock_config_manager):
    """Test 'show' command with service and optional setting."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'show', 'queue-worker']):
        with patch('csc_service.cli.commands.status_cmd.show') as mock_show:
            main()
            mock_show.assert_called_once()
            args = mock_show.call_args[0][0]
            assert args.command == 'show'
            assert args.service == 'queue-worker'
            assert args.setting is None


def test_show_command_with_setting(mock_config_manager):
    """Test 'show' command with specific setting."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'show', 'queue-worker', 'enabled']):
        with patch('csc_service.cli.commands.status_cmd.show') as mock_show:
            main()
            mock_show.assert_called_once()
            args = mock_show.call_args[0][0]
            assert args.service == 'queue-worker'
            assert args.setting == 'enabled'


def test_enable_command(mock_config_manager):
    """Test 'enable' command."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'enable', 'queue-worker']):
        with patch('csc_service.cli.commands.config_cmd.enable') as mock_enable:
            main()
            mock_enable.assert_called_once()
            args = mock_enable.call_args[0][0]
            assert args.command == 'enable'
            assert args.service == 'queue-worker'


def test_disable_command(mock_config_manager):
    """Test 'disable' command."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'disable', 'test-runner']):
        with patch('csc_service.cli.commands.config_cmd.disable') as mock_disable:
            main()
            mock_disable.assert_called_once()
            args = mock_disable.call_args[0][0]
            assert args.command == 'disable'
            assert args.service == 'test-runner'


def test_config_command_get(mock_config_manager):
    """Test 'config' command for getting a value."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'config', 'queue-worker', 'enabled']):
        with patch('csc_service.cli.commands.config_cmd.config') as mock_config:
            main()
            mock_config.assert_called_once()
            args = mock_config.call_args[0][0]
            assert args.command == 'config'
            assert args.service == 'queue-worker'
            assert args.setting == 'enabled'
            assert args.value is None


def test_config_command_set(mock_config_manager):
    """Test 'config' command for setting a value."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'config', 'queue-worker', 'enabled', 'true']):
        with patch('csc_service.cli.commands.config_cmd.config') as mock_config:
            main()
            mock_config.assert_called_once()
            args = mock_config.call_args[0][0]
            assert args.service == 'queue-worker'
            assert args.setting == 'enabled'
            assert args.value == 'true'


def test_set_command(mock_config_manager):
    """Test 'set' command for setting top-level config."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'set', 'poll_interval', '120']):
        with patch('csc_service.cli.commands.config_cmd.set_value') as mock_set:
            main()
            mock_set.assert_called_once()
            args = mock_set.call_args[0][0]
            assert args.command == 'set'
            assert args.key == 'poll_interval'
            assert args.value == '120'


def test_dump_command_all(mock_config_manager):
    """Test 'dump' command without service."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'dump']):
        with patch('csc_service.cli.commands.config_cmd.dump') as mock_dump:
            main()
            mock_dump.assert_called_once()
            args = mock_dump.call_args[0][0]
            assert args.command == 'dump'
            assert args.service is None


def test_dump_command_service(mock_config_manager):
    """Test 'dump' command for specific service."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'dump', 'queue-worker']):
        with patch('csc_service.cli.commands.config_cmd.dump') as mock_dump:
            main()
            mock_dump.assert_called_once()
            args = mock_dump.call_args[0][0]
            assert args.service == 'queue-worker'


def test_import_command(mock_config_manager):
    """Test 'import' command."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'import', 'queue-worker']):
        with patch('csc_service.cli.commands.config_cmd.import_cmd') as mock_import:
            main()
            mock_import.assert_called_once()
            args = mock_import.call_args[0][0]
            assert args.command == 'import'
            assert args.service == 'queue-worker'


def test_restart_command(mock_config_manager):
    """Test 'restart' command."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'restart', 'queue-worker']):
        with patch('csc_service.cli.commands.service_cmd.restart') as mock_restart:
            main()
            mock_restart.assert_called_once()
            args = mock_restart.call_args[0][0]
            assert args.command == 'restart'
            assert args.service == 'queue-worker'
            assert args.force is False


def test_restart_command_force(mock_config_manager):
    """Test 'restart' command with --force flag."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'restart', 'queue-worker', '--force']):
        with patch('csc_service.cli.commands.service_cmd.restart') as mock_restart:
            main()
            mock_restart.assert_called_once()
            args = mock_restart.call_args[0][0]
            assert args.force is True


def test_install_command_all(mock_config_manager):
    """Test 'install' command without service."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'install']):
        with patch('csc_service.cli.commands.service_cmd.install') as mock_install:
            main()
            mock_install.assert_called_once()
            args = mock_install.call_args[0][0]
            assert args.command == 'install'
            assert args.service == 'all'
            assert args.list_only is False


def test_install_command_specific(mock_config_manager):
    """Test 'install' command for specific service."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'install', 'queue-worker']):
        with patch('csc_service.cli.commands.service_cmd.install') as mock_install:
            main()
            mock_install.assert_called_once()
            args = mock_install.call_args[0][0]
            assert args.service == 'queue-worker'


def test_install_command_list(mock_config_manager):
    """Test 'install' command with --list flag."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'install', '--list']):
        with patch('csc_service.cli.commands.service_cmd.install') as mock_install:
            main()
            mock_install.assert_called_once()
            args = mock_install.call_args[0][0]
            assert args.list_only is True


def test_remove_command_all(mock_config_manager):
    """Test 'remove' command without service."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'remove']):
        with patch('csc_service.cli.commands.service_cmd.remove') as mock_remove:
            main()
            mock_remove.assert_called_once()
            args = mock_remove.call_args[0][0]
            assert args.command == 'remove'
            assert args.service == 'all'


def test_remove_command_specific(mock_config_manager):
    """Test 'remove' command for specific service."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'remove', 'test-runner']):
        with patch('csc_service.cli.commands.service_cmd.remove') as mock_remove:
            main()
            mock_remove.assert_called_once()
            args = mock_remove.call_args[0][0]
            assert args.service == 'test-runner'


def test_cycle_command(mock_config_manager):
    """Test 'cycle' command."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'cycle', 'queue-worker']):
        with patch('csc_service.cli.commands.service_cmd.cycle') as mock_cycle:
            main()
            mock_cycle.assert_called_once()
            args = mock_cycle.call_args[0][0]
            assert args.command == 'cycle'
            assert args.service == 'queue-worker'


def test_run_command_alias(mock_config_manager):
    """Test 'run' command as alias for cycle."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'run', 'pm']):
        with patch('csc_service.cli.commands.service_cmd.cycle') as mock_cycle:
            main()
            mock_cycle.assert_called_once()
            args = mock_cycle.call_args[0][0]
            assert args.command == 'run'
            assert args.service == 'pm'


# ============================================================================
# Config Manager Initialization Tests
# ============================================================================

def test_config_manager_default_path(mock_config_manager):
    """Test ConfigManager initialization with default path."""
    mock_cm_class, mock_cm_instance = mock_config_manager
    
    with patch('sys.argv', ['csc-ctl', 'status']):
        with patch('csc_service.cli.commands.status_cmd.status'):
            main()
            # Should be called with None (default)
            mock_cm_class.assert_called_once_with(None)


def test_config_manager_custom_path(mock_config_manager, tmp_path):
    """Test ConfigManager initialization with custom config path."""
    mock_cm_class, mock_cm