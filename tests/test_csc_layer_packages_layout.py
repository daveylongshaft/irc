from pathlib import Path
import importlib.util
import shutil


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_layer_packages_use_package_chain_imports():
    expected_imports = {
        "packages/csc-log/csc_log/log.py": "from csc_root import Root",
        "packages/csc-data/csc_data/old_data/__init__.py": "from csc_log import Log",
        "packages/csc-version/csc_version/version.py": "from csc_data import Data",
        "packages/csc-platform/csc_platform/platform.py": "from csc_version import Version",
        "packages/csc-network/csc_network/network.py": "from csc_platform import Platform",
        "packages/csc-crypto/csc_crypto/crypto.py": "from csc_network import Network",
        "packages/csc-services/csc_services/service.py": "from csc_crypto import Crypto",
        "packages/csc-server/csc_server/server.py": "from csc_services import Service",
    }
    for path, expected in expected_imports.items():
        assert expected in _read(path), path


def test_data_package_has_active_encrypted_impl_and_old_data_backup():
    encrypted_impl = _read("packages/csc-data/csc_data/data/__init__.py")
    old_impl = _read("packages/csc-data/csc_data/old_data/__init__.py")
    assert "from csc_data.old_data import Data as OldData" in encrypted_impl
    assert "class Data(OldData):" in encrypted_impl
    assert "class Data(Log, ServerData):" in old_impl


def test_layer_package_manifests_require_lower_layers():
    expected_dependencies = {
        "packages/csc-root/pyproject.toml": [],
        "packages/csc-log/pyproject.toml": ["csc-root>=0.1.0"],
        "packages/csc-data/pyproject.toml": ["csc-log>=0.1.0", "jsonschema>=4", "enc-ext-vfs @ git+https://github.com/daveylongshaft/enc-ext-vfs.git"],
        "packages/csc-version/pyproject.toml": ["csc-data>=0.1.0"],
        "packages/csc-platform/pyproject.toml": ["csc-version>=0.1.0"],
        "packages/csc-network/pyproject.toml": ["csc-platform>=0.1.0"],
        "packages/csc-crypto/pyproject.toml": ["csc-network>=0.1.0"],
        "packages/csc-services/pyproject.toml": ["csc-crypto>=0.1.0"],
        "packages/csc-server/pyproject.toml": ["csc-services>=0.1.0"],
    }
    for path, dependencies in expected_dependencies.items():
        contents = _read(path)
        for dependency in dependencies:
            assert dependency in contents, path


def test_find_csc_root_walks_up_to_marker_file():
    helper_path = REPO_ROOT / "packages" / "csc-data" / "csc_data" / "_enc_vfs.py"
    spec = importlib.util.spec_from_file_location("csc_data._enc_vfs_test", helper_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    root = REPO_ROOT / "tmp_test_find_csc_root"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    nested = root / "nested" / "deeper"
    nested.mkdir(parents=True, exist_ok=True)
    try:
        (root / ".csc_root").write_text("marker", encoding="utf-8")
        assert module.find_csc_root(nested) == root.resolve()
    finally:
        shutil.rmtree(root, ignore_errors=True)
