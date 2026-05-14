"""CSC Memory HTTP API -- Flask + waitress on 127.0.0.1:9532.

mTLS is terminated by Apache (ssl_verify_client require). Apache passes the
validated client cert PEM via the SSL_CLIENT_CERT WSGI environ variable and
the CN via SSL_CLIENT_S_DN_CN. Flask trusts these because it only binds on
127.0.0.1 -- external traffic cannot reach it without going through Apache.

For local development without Apache, set CSC_MEMORY_NO_AUTH=1 to bypass cert
checking. All writes will have peer_cn="dev".
"""

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from flask import Flask, g, jsonify, request

from .catalog import ORDERED_TYPES, VALID_STATUSES, VALID_TYPES
from .catalog import load_index, read_entry, soft_delete, write_entry
from .config import memory_config

log = logging.getLogger("csc_memory.web")
app = Flask(__name__)
_cfg = None


def get_config():
    global _cfg
    if _cfg is None:
        _cfg = memory_config()
    return _cfg


# ---------------------------------------------------------------------------
# Auth: extract peer CN from Apache-injected SSL headers
# ---------------------------------------------------------------------------

def _cn_from_environ():
    """Return peer CN from WSGI environ set by Apache mod_ssl, or None."""
    # Apache sets SSL_CLIENT_S_DN_CN directly -- fastest path
    cn = request.environ.get("SSL_CLIENT_S_DN_CN", "").strip()
    if cn:
        return cn

    # Fall back to parsing the full cert PEM from SSL_CLIENT_CERT
    cert_pem = request.environ.get("SSL_CLIENT_CERT", "").strip()
    if not cert_pem:
        # Some Apache configs pass it as an HTTP header
        cert_pem = request.headers.get("X-SSL-Client-Cert", "").strip()
    if not cert_pem:
        return None

    try:
        result = subprocess.run(
            ["openssl", "x509", "-noout", "-subject"],
            input=cert_pem,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        match = re.search(r"CN\s*=\s*([^,/\n]+)", result.stdout)
        if not match:
            return None
        return match.group(1).strip()
    except Exception as exc:
        log.debug("CN extraction failed: %s", exc)
        return None


@app.before_request
def authenticate():
    if request.path == "/health":
        g.peer_cn = "anonymous"
        return None

    if os.environ.get("CSC_MEMORY_NO_AUTH"):
        g.peer_cn = "dev"
        return None

    cn = _cn_from_environ()
    if not cn:
        return jsonify({"error": "client cert required"}), 403
    g.peer_cn = cn
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    cfg = get_config()
    index = load_index(cfg.store_root)
    return jsonify({"status": "ok", "updated_at": index.get("updated_at")})


@app.route("/index.json")
def serve_index_json():
    cfg = get_config()
    index_path = Path(cfg.store_root) / "index.json"
    if not index_path.exists():
        return jsonify({"entries": {}, "updated_at": None})
    return app.response_class(
        index_path.read_text(encoding="utf-8"),
        mimetype="application/json",
    )


@app.route("/memory.md")
def serve_memory_md():
    """Return Claude-ready index with <!-- expires: ISO8601 --> comment on line 2."""
    cfg = get_config()
    index = load_index(cfg.store_root)
    entries = {
        slug: e for slug, e in index.get("entries", {}).items()
        if e.get("status") != "deleted"
    }
    expires = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(time.time() + 3600),
    )
    lines = [
        "# Remote Memory Index",
        f"<!-- expires: {expires} -->",
        "",
    ]
    for entry_type in ORDERED_TYPES:
        type_entries = sorted(
            [e for e in entries.values() if e.get("type") == entry_type],
            key=lambda e: e.get("slug", ""),
        )
        if not type_entries:
            continue
        lines.append(f"## {entry_type}")
        for e in type_entries:
            lines.append(f"- `{e['slug']}` [{e.get('status', 'reference')}] -- {e.get('description', '')}")
        lines.append("")
    return app.response_class("\n".join(lines) + "\n", mimetype="text/markdown")


@app.route("/memory")
def list_memory():
    cfg = get_config()
    index = load_index(cfg.store_root)
    entries = list(index.get("entries", {}).values())

    type_filter = request.args.get("type")
    status_filter = request.args.get("status")
    tag_filter = request.args.get("tag")
    if type_filter:
        entries = [e for e in entries if e.get("type") == type_filter]
    if status_filter:
        entries = [e for e in entries if e.get("status") == status_filter]
    if tag_filter:
        entries = [e for e in entries if tag_filter in (e.get("tags") or [])]

    return jsonify({"updated_at": index.get("updated_at"), "entries": entries})


@app.route("/memory/<slug>")
def get_memory(slug):
    cfg = get_config()
    entry = read_entry(cfg.store_root, slug)
    if not entry:
        return jsonify({"error": "not found"}), 404
    return jsonify(entry)


@app.route("/memory/<slug>", methods=["POST"])
def post_memory(slug):
    cfg = get_config()
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    entry_type = data.get("type", "reference")
    body = (data.get("body") or "").strip()
    status = data.get("status", "reference")
    tags = data.get("tags") or []
    related = data.get("related") or []

    if not name:
        return jsonify({"error": "name is required"}), 400
    if entry_type not in VALID_TYPES:
        return jsonify({"error": f"type must be one of: {', '.join(sorted(VALID_TYPES))}"}), 400
    if status not in VALID_STATUSES:
        return jsonify({"error": f"status must be one of: {', '.join(sorted(VALID_STATUSES))}"}), 400

    entry = write_entry(
        store_root=cfg.store_root,
        slug=slug,
        name=name,
        description=description,
        entry_type=entry_type,
        body=body,
        status=status,
        tags=tags,
        related=related,
        author_cn=g.peer_cn,
    )
    return jsonify(entry), 200


@app.route("/memory/<slug>", methods=["DELETE"])
def delete_memory(slug):
    if request.headers.get("X-Confirm-Delete") != "true":
        return jsonify({"error": "X-Confirm-Delete: true header required"}), 400
    cfg = get_config()
    entry = soft_delete(cfg.store_root, slug)
    if not entry:
        return jsonify({"error": "not found"}), 404
    return jsonify(entry)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = get_config()
    log.info("store_root: %s", cfg.store_root)
    log.info("no-auth mode: %s", bool(os.environ.get("CSC_MEMORY_NO_AUTH")))

    from waitress import serve
    log.info("listening on %s:%d", cfg.host, cfg.port)
    serve(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
