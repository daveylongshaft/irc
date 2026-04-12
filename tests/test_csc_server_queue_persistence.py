from __future__ import annotations

import importlib
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = REPO_ROOT / "packages"

for package_dir in PACKAGES_DIR.iterdir():
    if package_dir.is_dir():
        sys.path.insert(0, str(package_dir))


def test_server_command_log_restores_pending_queue(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)

    server_module = importlib.import_module("csc_server.server")
    server_module = importlib.reload(server_module)

    first_server = server_module.Server(host="127.0.0.1", port=0)
    try:
        command_id = first_server.enqueue_client_line("PRIVMSG #general :hello world")
        assert len(first_server.queue) == 1
    finally:
        first_server.sock.close()

    second_server = server_module.Server(host="127.0.0.1", port=0)
    try:
        assert len(second_server.queue) == 1
        pending = second_server.command_store.load_pending()
        assert [item.command_id for item in pending] == [command_id]

        assert second_server.run_once() is True
        assert second_server.state.executed_commands == [command_id]
        assert second_server.command_store.load_pending() == []
    finally:
        second_server.sock.close()
