from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "csc-service"))

from csc_service.installer.layer_packages import (  # noqa: E402
    LEGACY_IMPORT_MAP,
    LAYER_PACKAGE_ORDER,
    build_install_commands,
    build_uninstall_commands,
)


EXPECTED_ORDER = [
    "csc-root",
    "csc-log",
    "csc-data",
    "csc-version",
    "csc-platform",
    "csc-network",
    "csc-service-base",
    "csc-server-core",
]


def test_layer_package_order_matches_dependency_chain():
    assert [spec.distribution for spec in LAYER_PACKAGE_ORDER] == EXPECTED_ORDER


def test_install_commands_follow_order_and_paths_exist():
    repo_root = Path(__file__).resolve().parents[1]
    commands = build_install_commands(repo_root=repo_root, python_executable="python3")
    assert len(commands) == len(EXPECTED_ORDER)
    for spec, command in zip(LAYER_PACKAGE_ORDER, commands):
        assert spec.distribution.replace("-", "_") not in command
        assert str((repo_root / spec.relative_dir).resolve()) in command


def test_uninstall_commands_are_reverse_order():
    commands = build_uninstall_commands(python_executable="python3")
    assert commands[0].endswith("csc-server-core")
    assert commands[-1].endswith("csc-root")


def test_legacy_import_map_covers_core_layers():
    assert LEGACY_IMPORT_MAP["from csc_service.shared.data import Data"] == "from csc_data import Data"
    assert LEGACY_IMPORT_MAP["from csc_service.shared.platform import Platform"] == "from csc_platform import Platform"
    assert LEGACY_IMPORT_MAP["from csc_service.server.service import Service"] == "from csc_service_base import Service"
