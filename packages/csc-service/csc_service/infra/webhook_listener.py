"""GitHub Webhook Listener for csc-csc-agent PR review automation.

Listens on 127.0.0.1:5000 (configurable via WEBHOOK_PORT env var).
Validates GitHub webhook signatures using GITHUB_WEBHOOK_SECRET from .env.
Triggers bin/pr-review-agent.sh when a PR is opened or synchronized.

Designed to run as a background daemon managed by systemd or csc-service.
"""

import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [webhook] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("webhook")


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
def _find_csc_root() -> Path:
    """Walk up from this file to find the project root (contains CLAUDE.md)."""
    p = Path(__file__).resolve().parent
    for _ in range(10):
        if (p / "CLAUDE.md").exists():
            return p
        if p == p.parent:
            break
        p = p.parent
    return Path(__file__).resolve().parents[5]  # fallback


CSC_ROOT = Path(os.environ.get("CSC_ROOT", str(_find_csc_root())))


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def _load_env(csc_root: Path) -> None:
    """Load .env file from csc_root if it exists (simple KEY=VALUE parser)."""
    env_path = csc_root / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _get_webhook_secret() -> bytes:
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        log.warning(
            "GITHUB_WEBHOOK_SECRET is not set — signature verification disabled"
        )
    return secret.encode()


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------
def _verify_signature(payload: bytes, sig_header: str, secret: bytes) -> bool:
    """Return True if the X-Hub-Signature-256 header matches the payload HMAC."""
    if not secret:
        log.warning("No secret configured; skipping signature check")
        return True
    if not sig_header or not sig_header.startswith("sha256="):
        log.error("Missing or malformed X-Hub-Signature-256 header")
        return False
    expected = "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header)


# ---------------------------------------------------------------------------
# PR trigger
# ---------------------------------------------------------------------------
def _trigger_pr_review(repo: str, pr_number: int, branch: str, pr_url: str) -> None:
    """Spawn bin/pr-review-agent.sh in a background thread."""
    script = CSC_ROOT / "bin" / "pr-review-agent.sh"
    if not script.exists():
        log.error("pr-review-agent.sh not found at %s", script)
        return

    env = os.environ.copy()
    env["PR_REPO"] = repo
    env["PR_NUMBER"] = str(pr_number)
    env["PR_BRANCH"] = branch
    env["PR_URL"] = pr_url

    log.info(
        "Triggering PR review: repo=%s pr=%s branch=%s", repo, pr_number, branch
    )

    def _run():
        try:
            result = subprocess.run(
                ["bash", str(script)],
                cwd=str(CSC_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode == 0:
                log.info("pr-review-agent.sh completed successfully for PR #%s", pr_number)
            else:
                log.warning(
                    "pr-review-agent.sh exited %d for PR #%s: %s",
                    result.returncode,
                    pr_number,
                    result.stderr[:500],
                )
        except subprocess.TimeoutExpired:
            log.error("pr-review-agent.sh timed out for PR #%s", pr_number)
        except Exception as exc:
            log.error("Failed to run pr-review-agent.sh: %s", exc)

    t = threading.Thread(target=_run, daemon=True, name=f"pr-review-{pr_number}")
    t.start()


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class WebhookHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for GitHub webhook deliveries."""

    # Injected by WebhookServer
    webhook_secret: bytes = b""

    def log_message(self, fmt, *args):  # suppress default access log spam
        log.debug("HTTP %s", fmt % args)

    def do_POST(self):
        if self.path != "/webhook":
            self._respond(404, "Not Found")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        payload = self.rfile.read(content_length)

        # Signature check
        sig = self.headers.get("X-Hub-Signature-256", "")
        if not _verify_signature(payload, sig, self.webhook_secret):
            log.warning("Signature verification failed — rejecting delivery")
            self._respond(403, "Forbidden")
            return

        # Parse event type
        event = self.headers.get("X-GitHub-Event", "")
        if event != "pull_request":
            log.debug("Ignoring event type: %s", event)
            self._respond(200, "OK (ignored)")
            return

        # Parse payload
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            log.error("Invalid JSON payload: %s", exc)
            self._respond(400, "Bad Request")
            return

        action = data.get("action", "")
        if action not in ("opened", "synchronize"):
            log.debug("Ignoring PR action: %s", action)
            self._respond(200, "OK (ignored)")
            return

        # Extract key fields
        pr = data.get("pull_request", {})
        pr_number = pr.get("number", 0)
        pr_url = pr.get("html_url", "")
        head = pr.get("head", {})
        branch = head.get("ref", "")
        repo_obj = data.get("repository", {})
        repo = repo_obj.get("full_name", "")

        log.info(
            "pull_request.%s event: repo=%s pr=#%s branch=%s",
            action, repo, pr_number, branch,
        )

        # Fire and forget
        _trigger_pr_review(repo, pr_number, branch, pr_url)

        self._respond(200, "OK")

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, "OK")
        else:
            self._respond(404, "Not Found")

    def _respond(self, code: int, body: str) -> None:
        encoded = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
class WebhookServer:
    """Wraps HTTPServer with config loading and graceful shutdown."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5000):
        self.host = host
        self.port = port
        self._server: HTTPServer | None = None

    def start(self) -> None:
        _load_env(CSC_ROOT)
        secret = _get_webhook_secret()

        # Inject secret into handler class (thread-safe: set before server starts)
        WebhookHandler.webhook_secret = secret

        self._server = HTTPServer((self.host, self.port), WebhookHandler)
        log.info(
            "GitHub webhook listener started on %s:%d (CSC_ROOT=%s)",
            self.host, self.port, CSC_ROOT,
        )
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            log.info("Shutting down webhook listener")
        finally:
            self._server.server_close()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    host = os.environ.get("WEBHOOK_HOST", "127.0.0.1")
    port = int(os.environ.get("WEBHOOK_PORT", "5000"))
    server = WebhookServer(host=host, port=port)
    server.start()


if __name__ == "__main__":
    main()
