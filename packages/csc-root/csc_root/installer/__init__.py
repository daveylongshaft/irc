"""Installer helpers for CSC package deployment and migration."""

from importlib import import_module

__all__ = [
    "LAYER_PACKAGE_ORDER",
    "LayerPackageSpec",
    "LEGACY_IMPORT_MAP",
    "build_install_commands",
    "build_install_plan",
    "build_uninstall_commands",
    "render_install_plan",
    "resolve_repo_root",
]


def __getattr__(name):
    if name in __all__:
        module = import_module(".layer_packages", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
