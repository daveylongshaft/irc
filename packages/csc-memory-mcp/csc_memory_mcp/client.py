"""mTLS HTTP client for csc-memory web service with local cache.

Cache file: docs/memory/remote_cache.md
Format: raw response body from GET /memory.md, which contains:
  line 1: # Remote Memory Index
  line 2: <!-- expires: ISO8601 -->
  ...

Refresh logic:
1. Read remote_cache.md.
   - Missing/unreadable: attempt fetch, write if success, create placeholder on fail.
2. Parse expires from line 2.
3. Not expired: return cache as-is.
4. Expired:
   a. Reset expires = now+1hr in-place (prevents retry storms).
   b. Fire background thread: GET /memory.md.
      - Success: overwrite cache with response (new expires embedded).
      - Failure: log, cache content unchanged (TTL already extended).
5. Return current cache content to caller.

All errors are caught, logged, swallowed. Session never blocks on cache state.
"""

import json
import logging
import os
import re
import ssl
import sys
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("csc_memory_mcp.client")

_BASE_CACHE_CONTENT = """# Remote Memory Index
<!-- expires: {expires} -->

(cache not yet populated -- server may be unreachable)
"""

_BACKGROUND_REFRESH_INTERVAL = 300  # 5 minutes


class memory_client:
    def __init__(self, base_url=None, cert=None, key=None, ca=None, cache_path=None):
        self.base_url = (base_url or "https://127.0.0.1:9532").rstrip("/")
        self.cert = cert or ""
        self.key = key or ""
        self.ca = ca or ""
        self.cache_path = Path(cache_path) if cache_path else self._default_cache_path()
        self._lock = threading.Lock()
        self._bg_thread = None

    @staticmethod
    def _default_cache_path():
        here = Path(__file__).resolve()
        for parent in here.parents:
            candidate = parent / "docs" / "memory" / "remote_cache.md"
            if candidate.parent.exists():
                return candidate
            if (parent / ".irc_root").exists():
                return parent / "docs" / "memory" / "remote_cache.md"
        return Path.home() / "docs" / "memory" / "remote_cache.md"

    def _build_ssl_ctx(self):
        if not (self.cert and self.key and self.ca):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_cert_chain(self.cert, self.key)
        ctx.load_verify_locations(self.ca)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx

    def _fetch_memory_md(self):
        """GET /memory.md from server. Return response body str or None."""
        try:
            ctx = self._build_ssl_ctx()
            url = f"{self.base_url}/memory.md"
            req = urllib.request.Request(url, headers={"Accept": "text/markdown"})
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                return resp.read().decode("utf-8")
        except Exception as exc:
            log.info("memory.md fetch failed: %s", exc)
            return None

    def _fetch_json(self, path):
        """GET a JSON endpoint. Return parsed dict or None."""
        try:
            ctx = self._build_ssl_ctx()
            url = f"{self.base_url}{path}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            log.info("GET %s failed: %s", path, exc)
            return None

    def _post_json(self, path, payload):
        """POST JSON to endpoint. Return parsed response dict or None."""
        try:
            ctx = self._build_ssl_ctx()
            url = f"{self.base_url}{path}"
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=body, method="POST",
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            log.info("POST %s failed: %s", path, exc)
            return None

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_expires(text):
        """Return expires timestamp string from line 2, or None."""
        lines = text.splitlines()
        if len(lines) < 2:
            return None
        match = re.search(r"expires:\s*(\S+)", lines[1])
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _is_expired(expires_str):
        if not expires_str:
            return True
        try:
            expires_ts = time.mktime(time.strptime(expires_str, "%Y-%m-%dT%H:%M:%SZ"))
            return time.time() > expires_ts
        except Exception:
            return True

    @staticmethod
    def _bump_expires(text, new_expires):
        """Replace the expires timestamp in line 2 of cache text."""
        lines = text.splitlines()
        if len(lines) >= 2:
            lines[1] = re.sub(
                r"expires:\s*\S+",
                f"expires: {new_expires}",
                lines[1],
            )
        return "\n".join(lines) + "\n"

    def _write_cache(self, text):
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(text, encoding="utf-8")
        except Exception as exc:
            log.debug("cache write failed: %s", exc)

    def _read_cache(self):
        try:
            if self.cache_path.exists():
                return self.cache_path.read_text(encoding="utf-8")
        except Exception as exc:
            log.debug("cache read failed: %s", exc)
        return None

    def _create_placeholder(self):
        expires = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
        return _BASE_CACHE_CONTENT.format(expires=expires)

    def _background_refresh(self):
        content = self._fetch_memory_md()
        if content:
            with self._lock:
                self._write_cache(content)
            log.info("remote_cache.md refreshed from server")
        else:
            log.debug("background refresh failed, using stale cache")

    def get_cache(self):
        """Return current cache content, triggering background refresh if expired."""
        with self._lock:
            content = self._read_cache()

        if content is None:
            fetched = self._fetch_memory_md()
            if fetched:
                with self._lock:
                    self._write_cache(fetched)
                return fetched
            placeholder = self._create_placeholder()
            with self._lock:
                self._write_cache(placeholder)
            return placeholder

        expires_str = self._parse_expires(content)
        if self._is_expired(expires_str):
            # Bump TTL immediately before firing background refresh
            new_expires = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
            bumped = self._bump_expires(content, new_expires)
            with self._lock:
                self._write_cache(bumped)
            # Fire background refresh
            t = threading.Thread(target=self._background_refresh, daemon=True)
            t.start()
            return bumped

        return content

    def start_background_refresh_loop(self):
        """Start a daemon thread that rechecks cache expiry every 5 minutes."""
        def loop():
            while True:
                time.sleep(_BACKGROUND_REFRESH_INTERVAL)
                try:
                    self.get_cache()
                except Exception as exc:
                    log.debug("background loop error: %s", exc)

        t = threading.Thread(target=loop, daemon=True, name="csc-memory-cache-loop")
        t.start()
        self._bg_thread = t

    # ------------------------------------------------------------------
    # Tool-facing methods
    # ------------------------------------------------------------------

    def list_entries(self, type=None, status=None, tag=None):
        """Return filtered list of entries from cache index. No network call unless expired."""
        cache = self.get_cache()
        # Parse the cache markdown into a list of {slug, status, description, type}
        entries = []
        current_type = None
        for line in cache.splitlines():
            type_match = re.match(r"^## (\w+)\s*$", line)
            if type_match:
                current_type = type_match.group(1)
                continue
            entry_match = re.match(r"^- `([^`]+)` \[([^\]]+)\] -- (.*)$", line)
            if entry_match and current_type:
                entries.append({
                    "slug": entry_match.group(1),
                    "status": entry_match.group(2),
                    "description": entry_match.group(3),
                    "type": current_type,
                })

        if type:
            entries = [e for e in entries if e["type"] == type]
        if status:
            entries = [e for e in entries if e["status"] == status]
        # tag filtering requires full index -- fall back to server
        if tag:
            full = self._fetch_json(f"/memory?tag={tag}")
            if full:
                return full.get("entries", [])
        return entries

    def read_entry(self, slug):
        """GET /memory/<slug> -- full body, not cached."""
        return self._fetch_json(f"/memory/{slug}")

    def write_entry(self, slug, name, description, entry_type, body,
                    status="reference", tags=None, related=None):
        """POST /memory/<slug>. On success, patch cache inline. Return entry or error str."""
        payload = {
            "name": name,
            "description": description,
            "type": entry_type,
            "body": body,
            "status": status,
            "tags": tags or [],
            "related": related or [],
        }
        result = self._post_json(f"/memory/{slug}", payload)
        if result is None:
            return "error: POST /memory/{} failed -- server unreachable or rejected".format(slug)
        self._patch_cache_entry(slug, entry_type, status, description)
        return result

    def search(self, query):
        """Client-side substring search of cache index."""
        query_lower = query.lower()
        all_entries = self.list_entries()
        return [
            e for e in all_entries
            if query_lower in e.get("slug", "").lower()
            or query_lower in e.get("description", "").lower()
            or query_lower in e.get("type", "").lower()
        ]

    def _patch_cache_entry(self, slug, entry_type, status, description):
        """Add/update a one-liner entry in the cached markdown."""
        try:
            with self._lock:
                content = self._read_cache() or self._create_placeholder()

            new_line = f"- `{slug}` [{status}] -- {description}"
            lines = content.splitlines()
            updated = []
            in_section = False
            inserted = False

            for line in lines:
                type_match = re.match(r"^## (\w+)\s*$", line)
                if type_match:
                    in_section = (type_match.group(1) == entry_type)
                    updated.append(line)
                    continue

                if in_section and re.match(rf"^- `{re.escape(slug)}`", line):
                    updated.append(new_line)
                    inserted = True
                    continue

                updated.append(line)

            if not inserted:
                # Find the section and append
                result = []
                in_section = False
                appended = False
                for line in updated:
                    type_match = re.match(r"^## (\w+)\s*$", line)
                    if type_match:
                        if in_section and not appended:
                            result.append(new_line)
                            appended = True
                        in_section = (type_match.group(1) == entry_type)
                    result.append(line)
                if in_section and not appended:
                    result.append(new_line)
                updated = result

            with self._lock:
                self._write_cache("\n".join(updated) + "\n")
        except Exception as exc:
            log.debug("cache patch failed: %s", exc)
