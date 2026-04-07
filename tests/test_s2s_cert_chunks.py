import os
import sys
import time


_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _pkg in ("csc-server-core", "csc-network", "csc-platform", "csc-data", "csc-log", "csc-root"):
    _p = os.path.join(_REPO, "packages", _pkg)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


class _FakeServer:
    def __init__(self, server_id="haven.test"):
        self.server_id = server_id
        self.startup_time = time.time()

    def log(self, *_args, **_kwargs):
        pass


def test_split_b64_chunks_respects_limit():
    from csc_server_core.server_network import _split_b64_chunks

    payload = "A" * 2500
    chunks = _split_b64_chunks(payload, size=900)

    assert len(chunks) == 3
    assert all(len(chunk) <= 900 for chunk in chunks)
    assert "".join(chunks) == payload


def test_store_cert_chunk_reassembles_out_of_order():
    from csc_server_core.server_network import ServerLink

    link = ServerLink(_FakeServer(), "127.0.0.1", 9520, "pw")
    parts = ["AAA", "BBB", "CCC"]

    cert_b64, error = link._store_cert_chunk("slink", "haven.remote", 123, 2, 3, parts[1])
    assert cert_b64 is None
    assert error is None

    cert_b64, error = link._store_cert_chunk("slink", "haven.remote", 123, 1, 3, parts[0])
    assert cert_b64 is None
    assert error is None

    cert_b64, error = link._store_cert_chunk("slink", "haven.remote", 123, 3, 3, parts[2])
    assert error is None
    assert cert_b64 == "".join(parts)


def test_process_slinkack_certchunk_completes_event(monkeypatch):
    from csc_server_core.server_network import ServerLink

    monkeypatch.setattr(
        "csc_server_core.server_network._verify_cert_pem",
        lambda cert_pem, ca_path: (True, "haven.remote", "ok"),
    )

    link = ServerLink(_FakeServer(), "127.0.0.1", 9520, "pw", ca_path="dummy-ca.pem")
    full_b64 = "A" * 1800
    chunks = [full_b64[:900], full_b64[900:]]

    link._process_slinkack_cert_chunk(["SLINKACK", "CERTCHUNK", "haven.remote", "123", "2", "2", chunks[1]])
    assert not link._slinkack_received.is_set()

    link._process_slinkack_cert_chunk(["SLINKACK", "CERTCHUNK", "haven.remote", "123", "1", "2", chunks[0]])

    assert link._slinkack_received.is_set()
    assert link._slinkack_error is None
    assert link.remote_server_id == "haven.remote"
    assert link.remote_timestamp == 123
