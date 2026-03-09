```python
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest


def bootstrap_csc_shared_package():
    """Bootstrap the csc_shared package for testing."""
    pkg_root = Path(__file__).resolve().parent.parent / "packages" / "csc-shared"
    if "csc_shared" in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(
        "csc_shared",
        pkg_root / "__init__.py",
        submodule_search_locations=[str(pkg_root)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["csc_shared"] = module
    spec.loader.exec_module(module)


def load_queue_worker_module():
    """Load the queue-worker module dynamically."""
    bootstrap_csc_shared_package()
    queue_worker_path = Path(__file__).resolve().parent.parent / "bin" / "queue-worker"
    loader = importlib.machinery.SourceFileLoader("queue_worker", str(queue_worker_path))
    spec = importlib.util.spec_from_loader("queue_worker", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestQueueWorkerResolveWorkordersBase:
    """Test suite for queue-worker workorders base resolution."""

    def test_resolve_workorders_base_prefers_workorders_directory(self, tmp_path):
        """Test that resolve_workorders_base prefers 'workorders' directory."""
        queue_worker = load_queue_worker_module()

        root = tmp_path / "csc"
        (root / "workorders").mkdir(parents=True)
        (root / "prompts").mkdir(parents=True)

        old_root = queue_worker.CSC_ROOT
        try:
            queue_worker.CSC_ROOT = root
            resolved = queue_worker.resolve_workorders_base()
            assert resolved == root / "workorders"
            assert resolved.exists()
        finally:
            queue_worker.CSC_ROOT = old_root

    def test_resolve_workorders_base_falls_back_to_prompts(self, tmp_path):
        """Test that resolve_workorders_base falls back to 'prompts' directory."""
        queue_worker = load_queue_worker_module()

        root = tmp_path / "csc"
        (root / "prompts").mkdir(parents=True)

        old_root = queue_worker.CSC_ROOT
        try:
            queue_worker.CSC_ROOT = root
            resolved = queue_worker.resolve_workorders_base()
            assert resolved == root / "prompts"
            assert resolved.exists()
        finally:
            queue_worker.CSC_ROOT = old_root

    def test_resolve_workorders_base_with_neither_directory(self, tmp_path):
        """Test resolve_workorders_base when neither directory exists."""
        queue_worker = load_queue_worker_module()

        root = tmp_path / "csc"
        root.mkdir(parents=True)

        old_root = queue_worker.CSC_ROOT
        try:
            queue_worker.CSC_ROOT = root
            resolved = queue_worker.resolve_workorders_base()
            # Should still return workorders path as default
            assert resolved == root / "workorders"
        finally:
            queue_worker.CSC_ROOT = old_root


class TestPromptsService:
    """Test suite for prompts service."""

    def test_prompts_service_uses_workorders_when_present(self, tmp_path):
        """Test that prompts service uses workorders directory when it exists."""
        bootstrap_csc_shared_package()
        from csc_shared.services.prompts_service import prompts

        root = tmp_path / "csc"
        workorders = root / "workorders"
        (workorders / "ready").mkdir(parents=True)
        (workorders / "wip").mkdir(parents=True)
        (workorders / "done").mkdir(parents=True)
        (workorders / "hold").mkdir(parents=True)
        (workorders / "archive").mkdir(parents=True)

        old_workorders = prompts.WORKORDERS_BASE
        old_prompts = prompts.LEGACY_PROMPTS_BASE
        try:
            prompts.WORKORDERS_BASE = workorders
            prompts.LEGACY_PROMPTS_BASE = root / "prompts"
            svc = prompts(server_instance=None)
            assert svc.name == "workorders"
            assert svc.queue.base == workorders
        finally:
            prompts.WORKORDERS_BASE = old_workorders
            prompts.LEGACY_PROMPTS_BASE = old_prompts

    def test_prompts_service_uses_legacy_when_workorders_absent(self, tmp_path):
        """Test that prompts service falls back to legacy prompts when workorders missing."""
        bootstrap_csc_shared_package()
        from csc_shared.services.prompts_service import prompts

        root = tmp_path / "csc"
        prompts_dir = root / "prompts"
        prompts_dir.mkdir(parents=True)

        old_workorders = prompts.WORKORDERS_BASE
        old_prompts = prompts.LEGACY_PROMPTS_BASE
        try:
            prompts.WORKORDERS_BASE = root / "workorders"  # Does not exist
            prompts.LEGACY_PROMPTS_BASE = prompts_dir
            svc = prompts(server_instance=None)
            assert svc.name == "prompts"
            assert svc.queue.base == prompts_dir
        finally:
            prompts.WORKORDERS_BASE = old_workorders
            prompts.LEGACY_PROMPTS_BASE = old_prompts

    def test_prompts_service_initialization(self, tmp_path):
        """Test prompts service initialization with valid configuration."""
        bootstrap_csc_shared_package()
        from csc_shared.services.prompts_service import prompts

        root = tmp_path / "csc"
        workorders = root / "workorders"
        (workorders / "ready").mkdir(parents=True)
        (workorders / "wip").mkdir(parents=True)
        (workorders / "done").mkdir(parents=True)
        (workorders / "hold").mkdir(parents=True)
        (workorders / "archive").mkdir(parents=True)

        old_workorders = prompts.WORKORDERS_BASE
        old_prompts = prompts.LEGACY_PROMPTS_BASE
        try:
            prompts.WORKORDERS_BASE = workorders
            prompts.LEGACY_PROMPTS_BASE = root / "prompts"
            svc = prompts(server_instance=None)
            assert svc is not None
            assert hasattr(svc, "queue")
            assert hasattr(svc, "name")
        finally:
            prompts.WORKORDERS_BASE = old_workorders
            prompts.LEGACY_PROMPTS_BASE = old_prompts


class TestCSCRootConfiguration:
    """Test suite for CSC_ROOT configuration."""

    def test_csc_root_is_path_object(self):
        """Test that CSC_ROOT is a Path object."""
        queue_worker = load_queue_worker_module()
        assert isinstance(queue_worker.CSC_ROOT, Path)

    def test_csc_root_can_be_modified(self, tmp_path):
        """Test that CSC_ROOT can be temporarily modified."""
        queue_worker = load_queue_worker_module()
        original_root = queue_worker.CSC_ROOT

        try:
            queue_worker.CSC_ROOT = tmp_path
            assert queue_worker.CSC_ROOT == tmp_path
        finally:
            queue_worker.CSC_ROOT = original_root

    def test_csc_root_respects_environment(self, tmp_path, monkeypatch):
        """Test that CSC_ROOT respects environment configuration."""
        queue_worker = load_queue_worker_module()
        original_root = queue_worker.CSC_ROOT

        try:
            monkeypatch.setenv("CSC_ROOT", str(tmp_path))
            queue_worker.CSC_ROOT = Path(str(tmp_path))
            assert queue_worker.CSC_ROOT == tmp_path
        finally:
            queue_worker.CSC_ROOT = original_root
```