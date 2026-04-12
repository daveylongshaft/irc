from __future__ import annotations

import importlib
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = REPO_ROOT / "packages"

for package_dir in PACKAGES_DIR.iterdir():
    if package_dir.is_dir():
        sys.path.insert(0, str(package_dir))


def _reload_server_module():
    server_module = importlib.import_module("csc_server.server")
    return importlib.reload(server_module)


def test_server_executes_service_command_from_queued_privmsg(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    server = server_module.Server(host="127.0.0.1", port=0)
    try:
        command_id = server.enqueue_client_line(
            f"PRIVMSG #general :{server.name} AI token builtin echo hello queue",
            metadata={"source_nick": "alice", "source_is_oper": True},
        )
        assert server.run_once() is True
        assert server.state.executed_commands == [command_id]
        assert server.state.service_results == [
            {
                "command_id": command_id,
                "class_name": "builtin",
                "method_name": "echo",
                "result": "Echo: hello queue",
            }
        ]
        assert server.state.skipped_service_commands == []
    finally:
        server.sock.close()


def test_server_does_not_execute_untargeted_service_command(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    server = server_module.Server(host="127.0.0.1", port=0)
    try:
        command_id = server.enqueue_client_line("PRIVMSG #general :AI token builtin echo hello queue")
        assert server.run_once() is True
        assert server.state.executed_commands == [command_id]
        assert server.state.service_results == []
        assert server.state.skipped_service_commands == []
        assert server.state.protocol_events == [
            {
                "command_id": command_id,
                "event": "privmsg",
                "detail": {"text": "AI token builtin echo hello queue", "service_command": False},
            }
        ]
    finally:
        server.sock.close()


def test_server_does_not_execute_service_command_for_other_target(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    server = server_module.Server(host="127.0.0.1", port=0)
    try:
        command_id = server.enqueue_client_line(
            "PRIVMSG #general :other.0001 AI token builtin echo hello queue",
            metadata={"source_nick": "alice", "source_is_oper": True},
        )
        assert server.run_once() is True
        assert server.state.executed_commands == [command_id]
        assert server.state.service_results == []
        assert server.state.skipped_service_commands == [
            {
                "command_id": command_id,
                "target": "other.0001",
                "reason": "target_mismatch",
            }
        ]
    finally:
        server.sock.close()


def test_server_requires_queued_sender_authorization_for_local_target(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    server = server_module.Server(host="127.0.0.1", port=0)
    try:
        command_id = server.enqueue_client_line(
            f"PRIVMSG #general :{server.name} AI token builtin echo hello queue",
            metadata={"source_nick": "alice"},
        )
        assert server.run_once() is True
        assert server.state.executed_commands == [command_id]
        assert server.state.service_results == []
        assert server.state.skipped_service_commands == [
            {
                "command_id": command_id,
                "target": server.name,
                "reason": "not_authorized",
                "detail": {
                    "source_nick": "alice",
                    "channel": "#general",
                    "source_is_oper": False,
                    "source_is_channel_op": False,
                },
            }
        ]
    finally:
        server.sock.close()


def test_server_responds_to_ping_from_queued_command(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    server = server_module.Server(host="127.0.0.1", port=0)
    try:
        command_id = server.enqueue_client_line("PING :12345")
        assert server.run_once() is True
        assert server.state.executed_commands == [command_id]
        expected = f":{server.name} PONG :12345"
        assert server.state.outbound_messages == [expected]
        assert server.state.protocol_events == [
            {
                "command_id": command_id,
                "event": "ping",
                "detail": {"token": "12345", "response": expected},
            }
        ]
    finally:
        server.sock.close()


def test_server_completes_registration_from_nick_and_user(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    server = server_module.Server(host="127.0.0.1", port=0)
    try:
        server.enqueue_client_line("NICK alice", source_session="session-1")
        server.enqueue_client_line("USER alice 0 * :Alice Example", source_session="session-1")

        assert server.run_once() is True
        assert server.run_once() is True

        session = server.state.get_session("session-1")
        assert session["state"] == "registered"
        assert session["nick"] == "alice"
        assert session["user"] == "alice"
        assert session["realname"] == "Alice Example"
        assert "#general" in session["channels"]
        assert server.state.is_channel_member("#general", "alice") is True
        assert any(
            event["event"] == "registration_complete" and event["detail"]["nick"] == "alice"
            for event in server.state.protocol_events
        )
        assert [event["session_id"] for event in server.state.outbound_events] == ["session-1"] * 9
        assert server.state.outbound_messages[0].startswith(f":{server.name} 001 alice :Welcome to")
        assert server.state.outbound_messages[3].startswith(f":{server.name} 004 alice ")
        assert server.state.outbound_messages[4].startswith(f":{server.name} 005 alice ")
        assert any(f" JOIN #general" in line for line in server.state.outbound_messages)
    finally:
        server.sock.close()


def test_server_rejects_oper_before_registration(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    server = server_module.Server(host="127.0.0.1", port=0)
    try:
        server.enqueue_client_line("OPER admin changeme", source_session="session-1")
        assert server.run_once() is True
        assert server.state.outbound_messages == [f":{server.name} 451 * :You have not registered"]
    finally:
        server.sock.close()


def test_server_oper_auth_updates_session_context(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    server = server_module.Server(host="127.0.0.1", port=0)
    try:
        server.enqueue_client_line("NICK alice", source_session="session-1")
        server.enqueue_client_line("USER alice 0 * :Alice Example", source_session="session-1")
        server.enqueue_client_line("OPER admin changeme", source_session="session-1")

        assert server.run_once() is True
        assert server.run_once() is True
        assert server.run_once() is True

        session = server.state.get_session("session-1")
        assert session["oper_account"] == "admin"
        assert session["oper_flags"] == "aol"
        context = server.state.get_session_context("session-1")
        assert context["source_nick"] == "alice"
        assert context["source_is_oper"] is True
        assert server.get_oper_flags("alice") == "aol"
        assert server.state.outbound_messages[-1] == f":{server.name} 381 alice :You are now an IRC operator"
    finally:
        server.sock.close()


def test_server_enriches_queue_metadata_from_session_context(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    server = server_module.Server(host="127.0.0.1", port=0)
    try:
        server.update_session_context(
            "session-1",
            source_nick="alice",
            source_is_oper=False,
            channel_ops={"#general"},
        )
        command_id = server.enqueue_client_line(
            f"PRIVMSG #general :{server.name} AI token builtin echo hello queue",
            source_session="session-1",
        )

        pending = server.command_store.load_pending()
        assert [item.command_id for item in pending] == [command_id]
        assert pending[0].payload["source_nick"] == "alice"
        assert pending[0].payload["source_is_channel_op"] is True
        assert pending[0].payload.get("source_is_oper", False) is False

        assert server.run_once() is True
        assert server.state.service_results == [
            {
                "command_id": command_id,
                "class_name": "builtin",
                "method_name": "echo",
                "result": "Echo: hello queue",
            }
        ]
    finally:
        server.sock.close()


def test_server_uses_registered_oper_context_for_later_service_command(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    server = server_module.Server(host="127.0.0.1", port=0)
    try:
        server.enqueue_client_line("NICK alice", source_session="session-1")
        server.enqueue_client_line("USER alice 0 * :Alice Example", source_session="session-1")
        server.enqueue_client_line("OPER admin changeme", source_session="session-1")
        for _ in range(3):
            assert server.run_once() is True

        command_id = server.enqueue_client_line(
            f"PRIVMSG #general :{server.name} AI token builtin echo hello queue",
            source_session="session-1",
        )
        pending = server.command_store.load_pending()
        assert pending[-1].payload["source_nick"] == "alice"
        assert pending[-1].payload["source_is_oper"] is True

        assert server.run_once() is True
        assert server.state.service_results[-1] == {
            "command_id": command_id,
            "class_name": "builtin",
            "method_name": "echo",
            "result": "Echo: hello queue",
        }
    finally:
        server.sock.close()


def test_server_broadcasts_channel_privmsg_after_join(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    server = server_module.Server(host="127.0.0.1", port=0)
    try:
        server.enqueue_client_line("NICK alice", source_session="session-a")
        server.enqueue_client_line("USER alice 0 * :Alice Example", source_session="session-a")
        server.enqueue_client_line("NICK bob", source_session="session-b")
        server.enqueue_client_line("USER bob 0 * :Bob Example", source_session="session-b")
        for _ in range(4):
            assert server.run_once() is True

        before = len(server.state.outbound_events)
        server.enqueue_client_line("PRIVMSG #general :hello channel", source_session="session-a")
        assert server.run_once() is True

        new_events = server.state.outbound_events[before:]
        assert [event["session_id"] for event in new_events] == ["session-a", "session-b"]
        assert all(event["line"] == ":alice!alice@" + server.name + " PRIVMSG #general :hello channel" for event in new_events)
    finally:
        server.sock.close()


def test_server_supports_names_and_list(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    server = server_module.Server(host="127.0.0.1", port=0)
    try:
        server.enqueue_client_line("NICK alice", source_session="session-a")
        server.enqueue_client_line("USER alice 0 * :Alice Example", source_session="session-a")
        server.enqueue_client_line("NICK bob", source_session="session-b")
        server.enqueue_client_line("USER bob 0 * :Bob Example", source_session="session-b")
        for _ in range(4):
            assert server.run_once() is True

        before = len(server.state.outbound_events)
        server.enqueue_client_line("NAMES #general", source_session="session-a")
        server.enqueue_client_line("LIST", source_session="session-a")
        assert server.run_once() is True
        assert server.run_once() is True

        lines = [event["line"] for event in server.state.outbound_events[before:] if event["session_id"] == "session-a"]
        assert any(f":{server.name} 353 alice = #general :@alice bob" == line for line in lines)
        assert any(f":{server.name} 322 alice #general 2 :" == line for line in lines)
        assert any(f":{server.name} 323 alice :End of /LIST" == line for line in lines)
    finally:
        server.sock.close()


def test_server_quit_removes_session_from_channels(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    server = server_module.Server(host="127.0.0.1", port=0)
    try:
        server.enqueue_client_line("NICK alice", source_session="session-a")
        server.enqueue_client_line("USER alice 0 * :Alice Example", source_session="session-a")
        server.enqueue_client_line("NICK bob", source_session="session-b")
        server.enqueue_client_line("USER bob 0 * :Bob Example", source_session="session-b")
        for _ in range(4):
            assert server.run_once() is True

        before = len(server.state.outbound_events)
        server.enqueue_client_line("QUIT :bye", source_session="session-a")
        assert server.run_once() is True

        session = server.state.get_session("session-a")
        assert session is None
        assert server.state.is_channel_member("#general", "alice") is False
        new_events = server.state.outbound_events[before:]
        assert new_events == [{"session_id": "session-b", "line": f":alice!alice@{server.name} QUIT :bye"}]
    finally:
        server.sock.close()


def test_sync_mesh_receive_preserves_auth_metadata_for_remote_execution(tmp_path, monkeypatch):
    from csc_platform import Platform

    monkeypatch.setattr(Platform, "PROJECT_ROOT", tmp_path)
    server_module = _reload_server_module()

    source_server = server_module.Server(host="127.0.0.1", port=0)
    target_server = server_module.Server(host="127.0.0.1", port=0)
    try:
        source_server.update_session_context(
            "uplink-1",
            source_nick="alice",
            source_is_oper=True,
        )
        outbound = source_server.ingress.accept_client_line(
            f"PRIVMSG #general :{target_server.name} AI token builtin echo relayed command",
            source_session="uplink-1",
        )

        wire_payload = source_server.sync_mesh.encode_command_line(outbound)
        relayed = target_server.sync_mesh.receive_command_line(wire_payload)

        assert relayed.command_id == outbound.command_id
        assert relayed.origin_server == outbound.origin_server
        assert relayed.replicate is False
        assert relayed.payload["source_nick"] == "alice"
        assert relayed.payload["source_is_oper"] is True

        assert target_server.run_once() is True
        assert target_server.state.service_results == [
            {
                "command_id": outbound.command_id,
                "class_name": "builtin",
                "method_name": "echo",
                "result": "Echo: relayed command",
            }
        ]
    finally:
        source_server.sock.close()
        target_server.sock.close()


def test_sync_mesh_stub_methods_announce_loudly():
    from csc_server.queue.command import CommandEnvelope
    from csc_server.sync.mesh import SyncMesh

    log_messages = []

    class DummyServer:
        def debug(self, _message: str) -> None:
            return None

    mesh = SyncMesh(server=DummyServer(), logger=log_messages.append)
    envelope = CommandEnvelope(
        kind="PRIVMSG",
        payload={"line": "PRIVMSG #general :hello"},
        source_session="alice",
        origin_server="local.0001",
    )

    mesh.start()
    mesh.sync_command(envelope)
    mesh.stop()

    assert any(
        "[STUB] SyncMesh.start called: mesh transport is not running a real network listener."
        in message
        for message in log_messages
    )
    assert any(
        "[STUB] SyncMesh.sync_command called: no peers configured, command relay skipped."
        in message
        for message in log_messages
    )
    assert any(
        "[STUB] SyncMesh.stop called: no peers configured, relay was inactive."
        in message
        for message in log_messages
    )
