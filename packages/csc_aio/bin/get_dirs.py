#!/usr/bin/env python3
"""Export portable CSC AIO path variables."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _bootstrap_imports() -> None:
    aio_root = Path(__file__).resolve().parents[1]
    if str(aio_root) not in sys.path:
        sys.path.insert(0, str(aio_root))


def main(argv: list[str] | None = None) -> int:
    _bootstrap_imports()

    from csc import Platform

    parser = argparse.ArgumentParser(prog="get_dirs")
    parser.add_argument(
        "--shell",
        choices=("auto", "posix", "powershell", "cmd", "json"),
        default="auto",
        help="Output format for environment exports.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Shortcut for --shell json.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Override runtime root. Defaults to the parent of the csc directory.",
    )
    args = parser.parse_args(argv)

    shell = "json" if args.json else args.shell
    platform = Platform(args.root)
    platform.ensure_dirs()
    print(platform.format_exports(shell))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
