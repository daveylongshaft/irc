from pathlib import Path
import sys
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
for package in (
    "csc-root",
    "csc-log",
    "csc-data",
    "csc-platform",
    "csc-network",
    "csc-services",
    "csc-clients",
    "csc-server-core",
):
    sys.path.insert(0, str(REPO_ROOT / "packages" / package))

from csc_clients.client.ftp_dcc_utils import (  # noqa: E402
    normalize_ftp_path,
    parse_dcc_send,
    resolve_ftp_upload_target,
)
from csc_server_core.handlers.ftp import FTPMixin  # noqa: E402


class _DummyHandler(FTPMixin):
    def __init__(self, server):
        self.server = server
        self._ftp_cwd = {}
        self._ftp_rnfr = {}
        self._ftp_config_cache = None
        self._ftp_index_cache = None


def test_normalize_ftp_path_resolves_relative_segments():
    assert normalize_ftp_path("ftp:/ops/wo") == "/ops/wo"
    assert normalize_ftp_path("ready/task.md", cwd="/ops/wo") == "/ops/wo/ready/task.md"
    assert normalize_ftp_path("../done", cwd="/ops/wo/ready") == "/ops/wo/done"


def test_resolve_ftp_upload_target_appends_filename_for_directory_target():
    assert resolve_ftp_upload_target(r"C:\tmp\file.txt", "ftp:/incoming/", cwd="/") == "/incoming/file.txt"
    assert resolve_ftp_upload_target("report.txt", "ftp:.", cwd="/ops/releases") == "/ops/releases/report.txt"


def test_parse_dcc_send_supports_quoted_filename():
    parsed = parse_dcc_send('DCC SEND "build 01.zip" 2130706433 5000 42')
    assert parsed["filename"] == "build 01.zip"
    assert parsed["ip"] == "127.0.0.1"
    assert parsed["port"] == 5000
    assert parsed["size"] == 42


def test_ftp_handler_requires_oper():
    handler = _DummyHandler(server=SimpleNamespace(opers={"davey": True}))
    assert handler._ftp_is_allowed("davey") is True
    assert handler._ftp_is_allowed("guest") is False


def test_ftp_local_path_stays_inside_root(tmp_path):
    handler = _DummyHandler(server=SimpleNamespace(opers={}))
    handler._ftp_config_cache = SimpleNamespace(serve_root=str(tmp_path), role="slave")

    local = handler._ftp_local_path("/ops/wo/task.md")
    assert local == tmp_path / "ops" / "wo" / "task.md"
