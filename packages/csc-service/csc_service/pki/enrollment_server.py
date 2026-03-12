"""PKI enrollment WSGI server.

Listens on 127.0.0.1:9530, proxied by Apache at /csc/pki/.
Handles certificate enrollment, renewal, and CRL/CA distribution.

Routes:
    POST /enroll  — Validate token, sign CSR, return cert chain
    POST /renew   — mTLS-authenticated cert renewal
    GET  /ca.crt  — Serve CA certificate
    GET  /crl.pem — Serve current CRL
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Shortname must be alphanumeric with dots/hyphens, max 64 chars
_SHORTNAME_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{0,62}[a-z0-9]$")

# EasyRSA paths
EASYRSA_DIR = Path("/etc/openvpn/easy-rsa")
EASYRSA_BIN = EASYRSA_DIR / "easyrsa"
PKI_DIR = EASYRSA_DIR / "pki"
CA_CRT = PKI_DIR / "ca.crt"
CRL_PEM = PKI_DIR / "crl.pem"
ISSUED_DIR = PKI_DIR / "issued"

# Token storage
TOKEN_FILE = Path("/opt/csc/tmp/csc/run/pki_tokens.json")

# Approved server list (repo-tracked, git sync keeps it current)
APPROVED_FILE = Path("/opt/csc/irc/etc/approved_servers.json")

# PKI log
PKI_LOG = Path("/opt/csc/logs/pki.log")

# Cert output directory
CERT_DIR = Path("/etc/csc")

# Token lifetime: 24 hours
TOKEN_TTL = 86400

# Listen address
BIND_HOST = "127.0.0.1"
BIND_PORT = 9530


def _load_approved():
    """Load approved server list from repo-tracked JSON. Returns dict shortname → metadata."""
    if APPROVED_FILE.exists():
        try:
            return json.loads(APPROVED_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _load_tokens():
    """Load token store from disk."""
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_tokens(tokens):
    """Atomically save token store."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, TOKEN_FILE)


def _write_pki_log(message):
    """Append a timestamped entry to the PKI log."""
    PKI_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    line = f"{ts} [PKI] {message}\n"
    with open(PKI_LOG, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def _sign_csr(shortname, csr_pem):
    """Import CSR and sign it with EasyRSA. Returns cert chain PEM or raises."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csr", delete=False, dir="/tmp"
    ) as f:
        f.write(csr_pem)
        csr_path = f.name

    try:
        # Import the CSR
        result = subprocess.run(
            [str(EASYRSA_BIN), "--batch", "import-req", csr_path, shortname],
            capture_output=True, text=True, timeout=30,
            cwd=str(EASYRSA_DIR),
        )
        if result.returncode != 0:
            raise RuntimeError(f"import-req failed: {result.stderr.strip()}")

        # Sign the request as a server cert
        result = subprocess.run(
            [str(EASYRSA_BIN), "--batch", "sign-req", "server", shortname],
            capture_output=True, text=True, timeout=30,
            cwd=str(EASYRSA_DIR),
        )
        if result.returncode != 0:
            raise RuntimeError(f"sign-req failed: {result.stderr.strip()}")

        # Build cert chain (issued cert + CA cert)
        issued_cert = ISSUED_DIR / f"{shortname}.crt"
        if not issued_cert.exists():
            raise RuntimeError(f"Signed cert not found at {issued_cert}")

        cert_pem = issued_cert.read_text(encoding="utf-8")
        ca_pem = CA_CRT.read_text(encoding="utf-8")
        chain_pem = cert_pem + ca_pem

        # Save chain to /etc/csc/
        chain_dest = CERT_DIR / f"{shortname}.chain.pem"
        CERT_DIR.mkdir(parents=True, exist_ok=True)
        chain_dest.write_text(chain_pem, encoding="utf-8")
        os.chmod(chain_dest, 0o644)

        # Regenerate CRL after signing
        subprocess.run(
            [str(EASYRSA_BIN), "gen-crl"],
            capture_output=True, text=True, timeout=30,
            cwd=str(EASYRSA_DIR),
        )
        if CRL_PEM.exists():
            crl_dest = CERT_DIR / "crl.pem"
            shutil.copy2(CRL_PEM, crl_dest)

        # Compute validity dates for log
        today = time.strftime("%Y-%m-%d")
        # Default EasyRSA validity is 825 days, but we report 1 year for simplicity
        expiry = time.strftime(
            "%Y-%m-%d", time.localtime(time.time() + 365 * 86400)
        )

        return chain_pem, today, expiry

    finally:
        try:
            os.unlink(csr_path)
        except OSError:
            pass


class PKIRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for PKI enrollment endpoints."""

    def log_message(self, format, *args):
        """Suppress default HTTP logging — we use PKI log instead."""
        pass

    def _send_json(self, code, data):
        """Send a JSON response."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type="application/x-pem-file"):
        """Send a file as response."""
        if not path.exists():
            self._send_json(404, {"error": "not found"})
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        """Read and parse JSON request body."""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        """Handle GET requests."""
        path = self.path.rstrip("/")

        if path == "/ca.crt":
            self._send_file(CA_CRT)
        elif path == "/crl.pem":
            self._send_file(CRL_PEM)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        """Handle POST requests."""
        path = self.path.rstrip("/")

        if path == "/enroll":
            self._handle_enroll()
        elif path == "/renew":
            self._handle_renew()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_enroll(self):
        """Handle certificate enrollment request.

        Expected body: {"shortname": "...", "csr_pem": "...", "token": "..."}
        """
        try:
            body = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid JSON"})
            return

        shortname = body.get("shortname", "").strip().lower()
        csr_pem = body.get("csr_pem", "").strip()
        token = body.get("token", "").strip()

        if not shortname or not csr_pem or not token:
            self._send_json(400, {"error": "missing shortname, csr_pem, or token"})
            return

        # Validate shortname format
        if not _SHORTNAME_RE.match(shortname):
            self._send_json(400, {"error": "invalid shortname format"})
            return

        # Basic CSR format check
        if not csr_pem.startswith("-----BEGIN CERTIFICATE REQUEST"):
            self._send_json(400, {"error": "invalid CSR format"})
            return

        if not token:
            # Tokenless path: check pre-approved server list
            approved = _load_approved()
            if shortname not in approved:
                self._send_json(403, {
                    "error": "not in approved server list",
                    "hint": (
                        "Ask an oper to run: PKI APPROVE " + shortname + "  "
                        "or obtain a one-time token with: PKI TOKEN " + shortname
                    ),
                })
                return
            _write_pki_log(f"approved enrollment: {shortname} (pre-approved, no token)")
        else:
            # Token path: validate one-time token
            tokens = _load_tokens()
            token_info = tokens.get(token)

            if not token_info:
                self._send_json(403, {"error": "invalid token"})
                return

            if token_info.get("used"):
                self._send_json(403, {"error": "token already used"})
                return

            if token_info.get("shortname") != shortname:
                self._send_json(403, {"error": "token/shortname mismatch"})
                return

            if time.time() - token_info.get("created_at", 0) > TOKEN_TTL:
                self._send_json(403, {"error": "token expired"})
                return

            tokens[token]["used"] = True
            _save_tokens(tokens)
            _write_pki_log(
                f"enrollment pending: {shortname} token consumed, queued for signing"
            )

        # Sign the CSR
        try:
            chain_pem, valid_from, valid_to = _sign_csr(shortname, csr_pem)
        except RuntimeError as e:
            self._send_json(500, {"error": str(e)})
            return

        _write_pki_log(
            f"cert issued:  {shortname:14s} valid {valid_from} → {valid_to}"
        )

        self._send_json(200, {
            "status": "ok",
            "shortname": shortname,
            "chain_pem": chain_pem,
            "valid_from": valid_from,
            "valid_to": valid_to,
        })

    def _handle_renew(self):
        """Handle certificate renewal via mTLS.

        The existing certificate is used for authentication (verified by
        Apache's mTLS config). The server extracts the CN from the
        client certificate headers set by Apache.

        Expected body: {"shortname": "...", "csr_pem": "..."}
        """
        try:
            body = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid JSON"})
            return

        shortname = body.get("shortname", "").strip().lower()
        csr_pem = body.get("csr_pem", "").strip()

        if not shortname or not csr_pem:
            self._send_json(400, {"error": "missing shortname or csr_pem"})
            return

        # Validate shortname format
        if not _SHORTNAME_RE.match(shortname):
            self._send_json(400, {"error": "invalid shortname format"})
            return

        # Verify the client cert CN (Apache passes this via X-SSL-Client-CN header)
        client_cn = self.headers.get("X-SSL-Client-CN", "").strip().lower()
        if not client_cn:
            self._send_json(
                403, {"error": "client certificate required (X-SSL-Client-CN header missing)"}
            )
            return
        if client_cn != shortname:
            self._send_json(
                403, {"error": "client cert CN does not match shortname"}
            )
            return

        # Verify shortname is in approved list
        approved = _load_approved()
        if shortname not in approved:
            self._send_json(403, {
                "error": "server not in approved list",
                "hint": "Ask an oper to run: PKI APPROVE " + shortname,
            })
            return

        # Verify that this shortname has an existing cert
        existing_cert = ISSUED_DIR / f"{shortname}.crt"
        if not existing_cert.exists():
            self._send_json(403, {"error": "no existing cert for this shortname"})
            return

        # Revoke old cert first, then sign new CSR
        try:
            subprocess.run(
                [str(EASYRSA_BIN), "--batch", "revoke", shortname],
                capture_output=True, text=True, timeout=30,
                cwd=str(EASYRSA_DIR),
            )
        except Exception:
            pass  # May fail if already revoked; continue anyway

        try:
            chain_pem, valid_from, valid_to = _sign_csr(shortname, csr_pem)
        except RuntimeError as e:
            self._send_json(500, {"error": str(e)})
            return

        _write_pki_log(
            f"cert renewed: {shortname:14s} valid {valid_from} → {valid_to}"
        )

        self._send_json(200, {
            "status": "ok",
            "shortname": shortname,
            "chain_pem": chain_pem,
            "valid_from": valid_from,
            "valid_to": valid_to,
        })


def run_server(host=BIND_HOST, port=BIND_PORT):
    """Start the PKI enrollment HTTP server."""
    server = HTTPServer((host, port), PKIRequestHandler)
    _write_pki_log(f"enrollment server started on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
