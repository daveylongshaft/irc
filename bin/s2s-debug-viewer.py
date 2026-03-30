#!/usr/bin/env python3
"""S2S Debug Log Viewer — aggregates debug logs from all CSC nodes in one web page.

Usage: python3 s2s-debug-viewer.py [port]
Default port: 8880

Reads /opt/csc/logs/s2s-debug.log locally, and fetches from beacon/well via SSH.
Auto-refreshes every 2 seconds.

Toggle debug on each server: touch /opt/csc/S2S_DEBUG
Toggle debug off: rm /opt/csc/S2S_DEBUG
"""

import http.server
import subprocess
import sys
import html
import time
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8880
LOCAL_LOG = Path("/opt/csc/logs/s2s-debug.log")
TOGGLE_FILE = Path("/opt/csc/S2S_DEBUG")
REMOTE_HOSTS = ["beacon", "well"]
MAX_LINES = 200  # lines to show per server in the viewer


def read_local_log():
    try:
        if LOCAL_LOG.exists():
            lines = LOCAL_LOG.read_text().strip().split("\n")
            return lines[-MAX_LINES:]
    except Exception as e:
        return [f"ERROR reading local: {e}"]
    return []


def read_remote_log(host):
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=no",
             host, f"tail -{MAX_LINES} /opt/csc/logs/s2s-debug.log 2>/dev/null"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")
        return [f"(no log on {host})"]
    except Exception as e:
        return [f"ERROR from {host}: {e}"]


def is_debug_enabled():
    return TOGGLE_FILE.exists()


HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<title>S2S Debug Viewer</title>
<meta http-equiv="refresh" content="2">
<style>
body {{ background: #1a1a2e; color: #e0e0e0; font-family: monospace; font-size: 13px; margin: 10px; }}
h1 {{ color: #00d4ff; font-size: 16px; margin: 5px 0; }}
h2 {{ color: #ffcc00; font-size: 14px; margin: 8px 0 4px 0; border-bottom: 1px solid #333; }}
.status {{ color: #00ff88; font-weight: bold; }}
.status.off {{ color: #ff4444; }}
pre {{ background: #0d0d1a; padding: 8px; border-radius: 4px; overflow-x: auto; max-height: 300px; overflow-y: auto; white-space: pre-wrap; word-wrap: break-word; font-size: 12px; }}
.controls {{ margin: 10px 0; }}
.controls a {{ color: #00d4ff; margin-right: 15px; text-decoration: none; }}
.controls a:hover {{ text-decoration: underline; }}
.tag-DH {{ color: #ff8844; }}
.tag-AUTH {{ color: #44ff88; }}
.tag-CONN {{ color: #4488ff; }}
.tag-READER {{ color: #ff44ff; }}
.tag-LISTEN {{ color: #ffff44; }}
.tag-SLINK {{ color: #44ffff; }}
.tag-LINKER {{ color: #ff8888; }}
</style>
</head>
<body>
<h1>S2S Debug Viewer</h1>
<div>Debug: <span class="status {status_class}">{status}</span> | Refreshed: {timestamp}</div>
<div class="controls">
<a href="/toggle">Toggle Debug</a>
<a href="/toggle-all">Toggle All Servers</a>
<a href="/clear">Clear Local Log</a>
<a href="/clear-all">Clear All Logs</a>
</div>
{sections}
</body>
</html>"""


def colorize_line(line):
    """Add color spans for known tags."""
    escaped = html.escape(line)
    for tag in ["DH", "AUTH", "CONN", "READER", "LISTEN", "SLINK", "LINKER"]:
        escaped = escaped.replace(f"[{tag}]", f'<span class="tag-{tag}">[{tag}]</span>')
    return escaped


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/toggle":
            if TOGGLE_FILE.exists():
                TOGGLE_FILE.unlink()
            else:
                TOGGLE_FILE.touch()
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        if self.path == "/toggle-all":
            on = TOGGLE_FILE.exists()
            for host in REMOTE_HOSTS:
                cmd = "rm -f /opt/csc/S2S_DEBUG" if on else "touch /opt/csc/S2S_DEBUG"
                subprocess.run(["ssh", "-o", "ConnectTimeout=3", host, cmd],
                               capture_output=True, timeout=5)
            if on:
                TOGGLE_FILE.unlink(missing_ok=True)
            else:
                TOGGLE_FILE.touch()
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        if self.path == "/clear":
            LOCAL_LOG.write_text("")
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        if self.path == "/clear-all":
            LOCAL_LOG.write_text("")
            for host in REMOTE_HOSTS:
                subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=3", host,
                     "truncate -s 0 /opt/csc/logs/s2s-debug.log 2>/dev/null"],
                    capture_output=True, timeout=5)
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        # Main page
        debug_on = is_debug_enabled()
        status = "ON" if debug_on else "OFF"
        status_class = "" if debug_on else "off"
        timestamp = time.strftime("%H:%M:%S")

        sections = ""

        # Local (haven)
        local_lines = read_local_log()
        colored = "\n".join(colorize_line(l) for l in local_lines) if local_lines else "(empty)"
        sections += f"<h2>haven (local)</h2><pre>{colored}</pre>"

        # Remote servers
        for host in REMOTE_HOSTS:
            remote_lines = read_remote_log(host)
            colored = "\n".join(colorize_line(l) for l in remote_lines) if remote_lines else "(empty)"
            sections += f"<h2>{host}</h2><pre>{colored}</pre>"

        page = HTML_TEMPLATE.format(
            status=status, status_class=status_class,
            timestamp=timestamp, sections=sections
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(page.encode())

    def log_message(self, format, *args):
        pass  # Suppress access logs


if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"S2S Debug Viewer running on http://0.0.0.0:{PORT}")
    print(f"Debug {'ON' if is_debug_enabled() else 'OFF'} — toggle at /toggle-all")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
