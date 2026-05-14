"""CLI for the CSC memory store. HTTP transport only."""

import argparse
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _pkg in ("csc-memory", "csc-memory-mcp"):
    _p = REPO_ROOT / "packages" / _pkg
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from csc_memory_mcp.client import memory_client


def _load_csc_service():
    candidates = []
    for env_var in ("CSC_ETC", "CSC_ROOT"):
        v = os.environ.get(env_var, "")
        if v:
            candidates.append(Path(v) / "etc" / "csc-service.json")
    for parent in REPO_ROOT.parents:
        candidates.append(parent / "etc" / "csc-service.json")
        if (parent / ".irc_root").exists():
            break
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def _make_client():
    cfg = _load_csc_service()
    mem = cfg.get("memory", {})
    host = mem.get("host", "127.0.0.1")
    port = int(mem.get("port", 9532))
    scheme = "https" if cfg.get("s2s_cert") else "http"
    return memory_client(
        base_url=f"{scheme}://{host}:{port}",
        cert=cfg.get("s2s_cert", ""),
        key=cfg.get("s2s_key", ""),
        ca=cfg.get("s2s_ca", ""),
    )


def _query_str(**kwargs):
    return "&".join(f"{k}={v}" for k, v in kwargs.items() if v)


def _parse_frontmatter(text):
    if not text.startswith("---"):
        return {}, text.strip()
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text.strip()
    fm_text = text[3:end].strip()
    body = text[end + 4:].strip()
    meta = {}
    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            meta[key] = [i.strip() for i in inner.split(",")] if inner else []
        else:
            meta[key] = val
    return meta, body


def main():
    parser = argparse.ArgumentParser(prog="csc-memory", description="CSC memory helper")
    sub = parser.add_subparsers(dest="command", required=True)

    r = sub.add_parser("read", help="Read one entry")
    r.add_argument("slug")

    l = sub.add_parser("list", help="List entries")
    l.add_argument("--type")
    l.add_argument("--status")
    l.add_argument("--tag")

    w = sub.add_parser("write", help="Create/update entry from markdown file")
    w.add_argument("slug")
    w.add_argument("file")

    d = sub.add_parser("delete", help="Soft-delete entry")
    d.add_argument("slug")

    s = sub.add_parser("search", help="Search index")
    s.add_argument("pattern")

    sub.add_parser("refresh", help="Force refresh local cache")

    args = parser.parse_args()
    client = _make_client()

    if args.command == "list":
        result = client._fetch_json(f"/memory?{_query_str(type=args.type, status=args.status, tag=args.tag)}")
        if result is None:
            print("error: server unreachable", file=sys.stderr)
            return 1
        for e in result.get("entries", []):
            print(f"{e['slug']}\t{e.get('status','')}\t{e.get('type','')}\t{e.get('description','')}")
        return 0

    if args.command == "read":
        entry = client._fetch_json(f"/memory/{args.slug}")
        if entry is None:
            print("error: server unreachable", file=sys.stderr)
            return 1
        if "error" in entry:
            print(f"error: {entry['error']}", file=sys.stderr)
            return 1
        print(json.dumps({k: v for k, v in entry.items() if k != "body"}, indent=2))
        print()
        print(entry.get("body", ""))
        return 0

    if args.command == "write":
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"file not found: {args.file}", file=sys.stderr)
            return 1
        meta, body = _parse_frontmatter(file_path.read_text(encoding="utf-8"))
        payload = {
            "name": meta.get("name", args.slug),
            "description": meta.get("description", ""),
            "type": meta.get("type", "reference"),
            "body": body,
            "status": meta.get("status", "reference"),
            "tags": meta.get("tags", []),
            "related": meta.get("related", []),
        }
        result = client._post_json(f"/memory/{args.slug}", payload)
        if result is None:
            print("error: server unreachable", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "delete":
        cfg = _load_csc_service()
        mem = cfg.get("memory", {})
        host = mem.get("host", "127.0.0.1")
        port = int(mem.get("port", 9532))
        scheme = "https" if cfg.get("s2s_cert") else "http"
        url = f"{scheme}://{host}:{port}/memory/{args.slug}"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            req = urllib.request.Request(
                url, method="DELETE",
                headers={"X-Confirm-Delete": "true", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                print(json.dumps(json.loads(resp.read()), indent=2))
            return 0
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.command == "search":
        results = client.search(args.pattern)
        for e in results:
            print(f"{e.get('slug','')}\t{e.get('status','')}\t{e.get('description','')}")
        return 0

    if args.command == "refresh":
        content = client._fetch_memory_md()
        if content is None:
            print("error: fetch failed", file=sys.stderr)
            return 1
        client._write_cache(content)
        print("cache refreshed")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
