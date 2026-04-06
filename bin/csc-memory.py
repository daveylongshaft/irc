"""Small CLI for the docs/memory indexed context store."""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for package in ("csc-root", "csc-log", "csc-data"):
    sys.path.insert(0, str(REPO_ROOT / "packages" / package))

from csc_data.memory_store import MemoryStore  # noqa: E402


def main():
    parser = argparse.ArgumentParser(prog="csc-memory", description="Indexed file-backed memory helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List memory entries")
    list_parser.add_argument("--category")
    list_parser.add_argument("--status")
    list_parser.add_argument("--tag")

    show_parser = subparsers.add_parser("show", help="Show one memory entry")
    show_parser.add_argument("slug")

    upsert_parser = subparsers.add_parser("upsert", help="Create or update a memory entry")
    upsert_parser.add_argument("category")
    upsert_parser.add_argument("slug")
    upsert_parser.add_argument("title")
    upsert_parser.add_argument("summary")
    upsert_parser.add_argument("--status", default="reference")
    upsert_parser.add_argument("--tags", default="")
    upsert_parser.add_argument("--related", default="")
    upsert_parser.add_argument("--body", default="")
    upsert_parser.add_argument("--body-file")

    note_parser = subparsers.add_parser("note", help="Append an update note to an entry")
    note_parser.add_argument("slug")
    note_parser.add_argument("text")
    note_parser.add_argument("--status")

    link_parser = subparsers.add_parser("link", help="Link two entries")
    link_parser.add_argument("source")
    link_parser.add_argument("target")
    link_parser.add_argument("--relation", default="related")

    args = parser.parse_args()
    store = MemoryStore()

    if args.command == "list":
        entries = store.list_entries(category=args.category, status=args.status, tag=args.tag)
        for entry in entries:
            print(f"{entry['slug']}\t{entry['status']}\t{entry['category']}\t{entry['title']}")
        return 0

    if args.command == "show":
        entry = store.get_entry(args.slug)
        if not entry:
            print(f"Unknown memory entry: {args.slug}", file=sys.stderr)
            return 1
        print(json.dumps({k: v for k, v in entry.items() if k != "body"}, indent=2))
        print()
        print(entry["body"])
        return 0

    if args.command == "upsert":
        body = args.body
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        metadata = store.upsert_entry(
            slug=args.slug,
            category=args.category,
            title=args.title,
            summary=args.summary,
            body=body,
            status=args.status,
            tags=[item for item in args.tags.split(",") if item],
            related=[item for item in args.related.split(",") if item],
        )
        print(json.dumps(metadata, indent=2))
        return 0

    if args.command == "note":
        print(json.dumps(store.append_note(args.slug, args.text, status=args.status), indent=2))
        return 0

    if args.command == "link":
        store.link_entries(args.source, args.target, relation=args.relation)
        print(f"Linked {args.source} -> {args.target} ({args.relation})")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
