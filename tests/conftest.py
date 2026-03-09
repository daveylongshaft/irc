import pytest
import sys
import os

@pytest.fixture(scope='session', autouse=True)
def add_project_root_to_path():
    """Adds the project root to sys.path for the entire test session."""
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    # Append the 'shared' directory specifically, as some modules might still rely on it
    shared_path = os.path.join(project_root, 'shared')
    if shared_path not in sys.path:
        sys.path.insert(0, shared_path)

    # Append the 'client' directory
    client_path = os.path.join(project_root, 'client')
    if client_path not in sys.path:
        sys.path.insert(0, client_path)

    # Append the 'translator' directory
    translator_path = os.path.join(project_root, 'translator')
    if translator_path not in sys.path:
        sys.path.insert(0, translator_path)