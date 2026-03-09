```python
"""Tests for prompts service legacy compatibility wrapper."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


def test_prompts_import():
    """Test that prompts can be imported from prompts_service."""
    from csc_service.shared.services.prompts_service import prompts
    assert prompts is not None


def test_workorders_import():
    """Test that workorders can be imported from prompts_service."""
    from csc_service.shared.services.prompts_service import workorders
    assert workorders is not None


def test_prompts_is_workorders_alias():
    """Test that prompts is an alias for workorders."""
    from csc_service.shared.services.prompts_service import prompts, workorders
    assert prompts is workorders


def test_module_all_exports():
    """Test that __all__ exports are correct."""
    from csc_service.shared.services import prompts_service
    assert "prompts" in prompts_service.__all__
    assert "workorders" in prompts_service.__all__


def test_prompts_service_module_docstring():
    """Test that module has appropriate docstring."""
    from csc_service.shared.services import prompts_service
    assert prompts_service.__doc__ is not None
    assert "Legacy" in prompts_service.__doc__ or "legacy" in prompts_service.__doc__


@patch('csc_service.shared.services.workorders_service.workorders')
def test_prompts_delegates_to_workorders(mock_workorders):
    """Test that prompts service delegates to workorders."""
    from csc_service.shared.services.prompts_service import prompts
    
    # Verify that prompts points to workorders
    assert prompts is not None


def test_prompts_callable():
    """Test that prompts is callable (it's a class/factory)."""
    from csc_service.shared.services.prompts_service import prompts
    assert callable(prompts)


def test_workorders_callable():
    """Test that workorders is callable (it's a class/factory)."""
    from csc_service.shared.services.prompts_service import workorders
    assert callable(workorders)


@patch('csc_service.shared.services.workorders_service.workorders')
def test_prompts_instantiation_with_mock_server(mock_workorders_class):
    """Test that prompts can be instantiated with a mock server."""
    from csc_service.shared.services.prompts_service import prompts
    
    mock_server = MagicMock()
    mock_instance = MagicMock()
    mock_workorders_class.return_value = mock_instance
    
    # Should be able to call prompts as a factory
    instance = prompts(mock_server)
    
    # Verify it returns something
    assert instance is not None


def test_prompts_and_workorders_are_same_class():
    """Test that prompts and workorders reference the same class."""
    from csc_service.shared.services.prompts_service import prompts, workorders
    
    # They should be the exact same object (alias)
    assert prompts is workorders
    assert id(prompts) == id(workorders)


def test_legacy_import_path():
    """Test that legacy import path works for backwards compatibility."""
    # This should not raise ImportError
    from csc_service.shared.services.prompts_service import prompts
    assert prompts is not None


def test_new_import_path():
    """Test that new import path works."""
    # This should not raise ImportError
    from csc_service.shared.services.workorders_service import workorders
    assert workorders is not None


def test_both_import_paths_resolve_same_class():
    """Test that both import paths resolve to the same class."""
    from csc_service.shared.services.prompts_service import prompts as legacy_prompts
    from csc_service.shared.services.workorders_service import workorders
    
    assert legacy_prompts is workorders


def test_prompts_service_no_additional_logic():
    """Test that prompts_service module adds no additional logic beyond aliasing."""
    import csc_service.shared.services.prompts_service as prompts_module
    from csc_service.shared.services.workorders_service import workorders
    
    # Verify the prompts in the module is the workorders class
    assert prompts_module.prompts is workorders


@patch('csc_service.shared.services.workorders_service.workorders')
def test_prompts_instance_methods_available(mock_workorders_class):
    """Test that prompts instances have expected workorders methods."""
    from csc_service.shared.services.prompts_service import prompts
    
    mock_server = MagicMock()
    mock_instance = MagicMock()
    mock_instance.add = MagicMock(return_value="Created")
    mock_instance.list = MagicMock(return_value="Files")
    mock_instance.read = MagicMock(return_value="Content")
    mock_instance.delete = MagicMock(return_value="Deleted")
    mock_workorders_class.return_value = mock_instance
    
    instance = prompts(mock_server)
    
    # Methods should be callable
    assert callable(instance.add)
    assert callable(instance.list)
    assert callable(instance.read)
    assert callable(instance.delete)
```