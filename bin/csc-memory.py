"""CLI for the CSC memory store.

Defaults to HTTP transport (csc-memory web service at 127.0.0.1:9532).
Falls back to direct MemoryStore filesystem access when server is unreachable.

Subcommands:
  read <slug>                     GET /memory/<slug>, pretty-print
  list [--type X] [--status X] [--tag X]  GET /memory
  write <slug> <file.md>          POST /memory/<slug> from file
  delete <slug>                   DELETE /memory/<slug>
  search <pattern>                filter index by name/description/tags
  refresh                         force GET /memory.md, write local cache
  # legacy filesystem subcommands still work when server is unreachable
  upsert <category> <slug> <title> <summary> ...
  note <slug> <text>
  link <source> <target>
"""

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _pkg in ("csc-root", "csc-log", "csc-data", "csc-memory", "csc-memory-mcp"):
    _p = REPO_ROOT / "packages" / _pkg
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


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


def _make_http_client():
    try:
        from csc_memory_mcp.client import memory_client
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
    except Exception as exc:
        print(f"[warn] HTTP client unavailable: {exc}", file=sys.stderr)
        return None


def _check_server(client):
    """Return True if server is reachable."""
    try:
        result = client._fetch_json("/health")
        return result is not None
    except Exception:
        return False


def _fallback_store():
    from csc_data.memory_store import MemoryStore
    return MemoryStore()


def main():
    parser = argparse.ArgumentParser(prog="csc-memory", description="CSC memory helper")
    parser.add_argument("--local", action="store_true", help="Force filesystem backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # HTTP-first subcommands
    read_p = subparsers.add_parser("read", help="Read one entry (full body)")
    read_p.add_argument("slug")

    list_p = subparsers.add_parser("list", help="List entries")
    list_p.add_argument("--type")
    list_p.add_argument("--status")
    list_p.add_argument("--tag")

    write_p = subparsers.add_parser("write", help="Create/update entry from markdown file")
    write_p.add_argument("slug")
    write_p.add_argument("file", help="Markdown file with YAML frontmatter")

    delete_p = subparsers.add_parser("delete", help="Soft-delete entry")
    delete_p.add_argument("slug")

    search_p = subparsers.add_parser("search", help="Search index")
    search_p.add_argument("pattern")

    subparsers.add_parser("refresh", help="Force refresh local cache from server")

    # Legacy filesystem subcommands
    show_p = subparsers.add_parser("show", help="[legacy] Show entry (filesystem)")
    show_p.add_argument("slug")

    upsert_p = subparsers.add_parser("upsert", help="[legacy] Upsert entry (filesystem)")
    upsert_p.add_argument("category")
    upsert_p.add_argument("slug")
    upsert_p.add_argument("title")
    upsert_p.add_argument("summary")
    upsert_p.add_argument("--status", default="reference")
    upsert_p.add_argument("--tags", default="")
    upsert_p.add_argument("--related", default="")
    upsert_p.add_argument("--body", default="")
    upsert_p.add_argument("--body-file")

    note_p = subparsers.add_parser("note", help="[legacy] Append note (filesystem)")
    note_p.add_argument("slug")
    note_p.add_argument("text")
    note_p.add_argument("--status")

    link_p = subparsers.add_parser("link", help="[legacy] Link entries (filesystem)")
    link_p.add_argument("source")
    link_p.add_argument("target")
    link_p.add_argument("--relation", default="related")

    args = parser.parse_args()

    # Legacy filesystem-only commands
    if args.command in ("show", "upsert", "note", "link") or args.local:
        store = _fallback_store()
        return _run_legacy(args, store)

    # HTTP-first commands
    client = None if args.local else _make_http_client()
    use_server = client is not None and _check_server(client)

    if args.command == "list":
        if use_server:
            result = client._fetch_json(
                f"/memory?{_query_str(type=args.type, status=args.status, tag=args.tag)}"
            )
            if result:
                for e in result.get("entries", []):
                    print(f"{e['slug']}\t{e.get('status','')}\t{e.get('type','')}\t{e.get('description','')}")
                return 0
        # fallback
        store = _fallback_store()
        for e in store.list_entries(category=args.type, status=args.status, tag=args.tag):
            print(f"{e['slug']}\t{e.get('status','')}\t{e.get('category','')}\t{e.get('title','')}")
        return 0

    if args.command == "read":
        if use_server:
            entry = client._fetch_json(f"/memory/{args.slug}")
            if entry and "error" not in entry:
                print(json.dumps({k: v for k, v in entry.items() if k != "body"}, indent=2))
                print()
                print(entry.get("body", ""))
                return 0
            elif entry:
                print(f"error: {entry['error']}", file=sys.stderr)
                return 1
        # fallback
        store = _fallback_store()
        entry = store.get_entry(args.slug)
        if not entry:
            print(f"Unknown entry: {args.slug}", file=sys.stderr)
            return 1
        print(json.dumps({k: v for k, v in entry.items() if k != "body"}, indent=2))
        print()
        print(entry["body"])
        return 0

    if args.command == "write":
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"File not found: {args.file}", file=sys.stderr)
            return 1
        text = file_path.read_text(encoding="utf-8")
        # Parse frontmatter
        meta, body = _parse_frontmatter(text)
        payload = {
            "name": meta.get("name", args.slug),
            "description": meta.get("description", ""),
            "type": meta.get("type", "reference"),
            "body": body,
            "status": meta.get("status", "reference"),
            "tags": meta.get("tags", []),
            "related": meta.get("related", []),
        }
        if use_server:
            result = client._post_json(f"/memory/{args.slug}", payload)
            if result:
                print(json.dumps(result, indent=2))
                return 0
        print("error: server unreachable and write requires HTTP transport", file=sys.stderr)
        return 1

    if args.command == "delete":
        if use_server:
            import urllib.request, urllib.error
            try:
                cfg = _load_csc_service()
                mem = cfg.get("memory", {})
                host = mem.get("host", "127.0.0.1")
                port = int(mem.get("port", 9532))
                scheme = "https" if cfg.get("s2s_cert") else "http"
                url = f"{scheme}://{host}:{port}/memory/{args.slug}"
                import ssl as _ssl
                ctx = _ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = _ssl.CERT_NONE
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
        print("error: delete requires HTTP transport", file=sys.stderr)
        return 1

    if args.command == "search":
        if use_server:
            results = client.search(args.pattern)
        else:
            results = []
            store = _fallback_store()
            q = args.pattern.lower()
            for e in store.list_entries():
                if (q in e.get("slug", "").lower() or
                        q in e.get("title", "").lower() or
                        q in e.get("summary", "").lower()):
                    results.append(e)
        for e in results:
            print(f"{e.get('slug','')}\t{e.get('status','')}\t{e.get('description', e.get('summary',''))}")
        return 0

    if args.command == "refresh":
        if not use_server:
            print("error: server unreachable", file=sys.stderr)
            return 1
        content = client._fetch_memory_md()
        if content:
            client._write_cache(content)
            print("cache refreshed")
            return 0
        print("error: fetch failed", file=sys.stderr)
        return 1

    return 1


def _run_legacy(args, store):
    if args.command == "show":
        entry = store.get_entry(args.slug)
        if not entry:
            print(f"Unknown entry: {args.slug}", file=sys.stderr)
            return 1
        print(json.dumps({k: v for k, v in entry.items() if k != "body"}, indent=2))
        print()
        print(entry["body"])
        return 0
    if args.command == "upsert":
        body = args.body
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        meta = store.upsert_entry(
            slug=args.slug,
            category=args.category,
            title=args.title,
            summary=args.summary,
            body=body,
            status=args.status,
            tags=[t for t in args.tags.split(",") if t],
            related=[r for r in args.related.split(",") if r],
        )
        print(json.dumps(meta, indent=2))
        return 0
    if args.command == "note":
        print(json.dumps(store.append_note(args.slug, args.text, status=args.status), indent=2))
        return 0
    if args.command == "link":
        store.link_entries(args.source, args.target, relation=args.relation)
        print(f"Linked {args.source} -> {args.target} ({args.relation})")
        return 0
    return 1


def _query_str(**kwargs):
    parts = [f"{k}={v}" for k, v in kwargs.items() if v]
    return "&".join(parts)


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
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            meta[key] = [item.strip() for item in inner.split(",")] if inner else []
        else:
            meta[key] = val
    return meta, body


if __name__ == "__main__":
    raise SystemExit(main())
