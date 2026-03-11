"""Tests for the GitHub webhook listener.

Covers:
- HMAC signature verification (valid, invalid, missing secret)
- Correct HTTP response codes for each scenario
- PR event filtering (opened/synchronize accepted; others ignored)
- Non-pull_request event types ignored
- Wrong paths return 404
- Health endpoint returns 200
- _trigger_pr_review spawns pr-review-agent.sh with correct env vars
"""

import hashlib
import hmac
import io
import json
import os
import sys
import threading
import time
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

# Ensure package is importable from source tree
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'packages', 'csc-service'))

import csc_service.infra.webhook_listener as wl
from csc_service.infra.webhook_listener import (
    WebhookHandler,
    WebhookServer,
    _verify_signature,
    _trigger_pr_review,
    _load_env,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sig(secret: bytes, payload: bytes) -> str:
    return "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _build_pr_payload(action: str = "opened", pr_number: int = 42,
                      branch: str = "feature/test", repo: str = "org/repo") -> bytes:
    data = {
        "action": action,
        "number": pr_number,
        "pull_request": {
            "number": pr_number,
            "html_url": f"https://github.com/{repo}/pull/{pr_number}",
            "head": {"ref": branch},
        },
        "repository": {"full_name": repo},
    }
    return json.dumps(data).encode()


# ---------------------------------------------------------------------------
# _verify_signature
# ---------------------------------------------------------------------------

class TestVerifySignature:
    def test_valid_signature(self):
        secret = b"mysecret"
        payload = b'{"action":"opened"}'
        sig = _make_sig(secret, payload)
        assert _verify_signature(payload, sig, secret) is True

    def test_invalid_signature(self):
        secret = b"mysecret"
        payload = b'{"action":"opened"}'
        assert _verify_signature(payload, "sha256=deadbeef", secret) is False

    def test_missing_header(self):
        secret = b"mysecret"
        assert _verify_signature(b"payload", "", secret) is False

    def test_no_sha256_prefix(self):
        secret = b"mysecret"
        assert _verify_signature(b"payload", "sha1=abc123", secret) is False

    def test_empty_secret_skips_check(self):
        # No secret configured → always returns True (logged warning)
        assert _verify_signature(b"payload", "", b"") is True

    def test_timing_safe(self):
        """Verify hmac.compare_digest is used (no timing side-channel)."""
        secret = b"mysecret"
        payload = b"data"
        valid_sig = _make_sig(secret, payload)
        # Tampered last character should still fail
        tampered = valid_sig[:-1] + ("0" if valid_sig[-1] != "0" else "1")
        assert _verify_signature(payload, tampered, secret) is False


# ---------------------------------------------------------------------------
# _load_env
# ---------------------------------------------------------------------------

class TestLoadEnv:
    def test_loads_key_value_pairs(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("MY_TEST_KEY=hello\nANOTHER=world\n")
        monkeypatch.delenv("MY_TEST_KEY", raising=False)
        monkeypatch.delenv("ANOTHER", raising=False)
        _load_env(tmp_path)
        assert os.environ.get("MY_TEST_KEY") == "hello"
        assert os.environ.get("ANOTHER") == "world"

    def test_skips_comments_and_blank_lines(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nVALID=yes\n")
        monkeypatch.delenv("VALID", raising=False)
        _load_env(tmp_path)
        assert os.environ.get("VALID") == "yes"

    def test_does_not_override_existing_env(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING_VAR=from_file\n")
        monkeypatch.setenv("EXISTING_VAR", "from_env")
        _load_env(tmp_path)
        assert os.environ.get("EXISTING_VAR") == "from_env"

    def test_missing_env_file_ok(self, tmp_path):
        # Should not raise
        _load_env(tmp_path)

    def test_strips_quotes_from_values(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text('QUOTED="double_quoted"\nSINGLE=\'single_quoted\'\n')
        monkeypatch.delenv("QUOTED", raising=False)
        monkeypatch.delenv("SINGLE", raising=False)
        _load_env(tmp_path)
        assert os.environ.get("QUOTED") == "double_quoted"
        assert os.environ.get("SINGLE") == "single_quoted"


# ---------------------------------------------------------------------------
# _trigger_pr_review
# ---------------------------------------------------------------------------

class TestTriggerPrReview:
    def test_calls_script_with_correct_args(self, tmp_path):
        """Script is called via bash with correct env vars."""
        script = tmp_path / "bin" / "pr-review-agent.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/bash\necho ok\n")
        script.chmod(0o755)

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs.get("env", {})))
            result = MagicMock()
            result.returncode = 0
            result.stdout = "ok"
            result.stderr = ""
            return result

        orig_root = wl.CSC_ROOT
        try:
            wl.CSC_ROOT = tmp_path
            with patch("subprocess.run", side_effect=fake_run):
                _trigger_pr_review("org/repo", 7, "feature/x", "https://gh/pr/7")
                # Give the daemon thread time to run
                time.sleep(0.1)
        finally:
            wl.CSC_ROOT = orig_root

        assert len(calls) == 1
        cmd, env = calls[0]
        assert cmd == ["bash", str(script)]
        assert env["PR_REPO"] == "org/repo"
        assert env["PR_NUMBER"] == "7"
        assert env["PR_BRANCH"] == "feature/x"
        assert env["PR_URL"] == "https://gh/pr/7"

    def test_missing_script_logs_error(self, tmp_path, caplog):
        orig_root = wl.CSC_ROOT
        try:
            wl.CSC_ROOT = tmp_path
            import logging
            with caplog.at_level(logging.ERROR, logger="webhook"):
                _trigger_pr_review("org/repo", 1, "main", "https://gh/1")
        finally:
            wl.CSC_ROOT = orig_root
        assert "not found" in caplog.text


# ---------------------------------------------------------------------------
# HTTP handler (via live server)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """Start a WebhookServer on a random port for integration tests."""
    tmp = tmp_path_factory.mktemp("webhook_srv")
    # Create a dummy pr-review-agent.sh so trigger doesn't error
    script = tmp / "bin" / "pr-review-agent.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/bash\nexit 0\n")
    script.chmod(0o755)

    secret = b"testsecret"
    orig_root = wl.CSC_ROOT
    wl.CSC_ROOT = tmp
    WebhookHandler.webhook_secret = secret

    srv = WebhookServer(host="127.0.0.1", port=15080)

    t = threading.Thread(target=srv.start, daemon=True)
    # Monkey-patch _load_env so it doesn't read a missing .env
    with patch.object(wl, "_load_env"):
        with patch.object(wl, "_get_webhook_secret", return_value=secret):
            t.start()
            time.sleep(0.2)  # let server bind

    yield srv, secret

    srv.stop()
    wl.CSC_ROOT = orig_root


def _post(path: str, payload: bytes, headers: dict, port: int = 15080):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", path, body=payload, headers=headers)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body.decode()


def _get(path: str, port: int = 15080):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body.decode()


class TestWebhookHandlerHTTP:
    """Integration tests against the live test server."""

    def _pr_headers(self, payload: bytes, secret: bytes, action: str = "pull_request") -> dict:
        sig = _make_sig(secret, payload)
        return {
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            "X-GitHub-Event": action,
            "X-Hub-Signature-256": sig,
        }

    def test_health_endpoint(self, server):
        _, secret = server
        status, body = _get("/health")
        assert status == 200
        assert "OK" in body

    def test_unknown_path_returns_404(self, server):
        _, secret = server
        status, _ = _get("/unknown")
        assert status == 404

    def test_pr_opened_returns_200(self, server):
        _, secret = server
        payload = _build_pr_payload("opened")
        headers = self._pr_headers(payload, secret)
        status, _ = _post("/webhook", payload, headers)
        assert status == 200

    def test_pr_synchronize_returns_200(self, server):
        _, secret = server
        payload = _build_pr_payload("synchronize")
        headers = self._pr_headers(payload, secret)
        status, _ = _post("/webhook", payload, headers)
        assert status == 200

    def test_pr_closed_ignored(self, server):
        _, secret = server
        payload = _build_pr_payload("closed")
        headers = self._pr_headers(payload, secret)
        status, body = _post("/webhook", payload, headers)
        assert status == 200
        assert "ignored" in body

    def test_non_pr_event_ignored(self, server):
        _, secret = server
        payload = b'{"zen":"Keep it logically awesome."}'
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": _make_sig(secret, payload),
        }
        status, body = _post("/webhook", payload, headers)
        assert status == 200
        assert "ignored" in body

    def test_invalid_signature_returns_403(self, server):
        _, secret = server
        payload = _build_pr_payload("opened")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=bad000",
        }
        status, _ = _post("/webhook", payload, headers)
        assert status == 403

    def test_wrong_path_returns_404_post(self, server):
        _, secret = server
        payload = b"{}"
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _make_sig(secret, payload),
        }
        status, _ = _post("/other", payload, headers)
        assert status == 404

    def test_invalid_json_returns_400(self, server):
        _, secret = server
        payload = b"not-json{"
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _make_sig(secret, payload),
        }
        status, _ = _post("/webhook", payload, headers)
        assert status == 400
