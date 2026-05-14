"""Read/write YAML-frontmatter memory files and maintain index.json + markdown views.

This module works directly with the on-disk schema (name/type/description/updated)
and never calls MemoryStore, which uses a different internal schema (title/category/
summary) and would overwrite frontmatter on upsert.
"""

import json
import os
import re
import tempfile
import time
from pathlib import Path


VALID_TYPES = {"user", "feedback", "environment", "workflow", "task", "topic", "reference"}
VALID_STATUSES = {"reference", "active", "stashed", "blocked", "done", "deleted"}
ORDERED_TYPES = ["user", "feedback", "environment", "workflow", "task", "topic", "reference"]


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_frontmatter(text):
    """Return (meta_dict, body_str) from YAML-frontmatter markdown."""
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
            if inner:
                meta[key] = [item.strip() for item in inner.split(",")]
            else:
                meta[key] = []
        else:
            meta[key] = val
    return meta, body


def _render_frontmatter(meta, body):
    lines = ["---"]
    for key in ("slug", "name", "description", "type", "status", "tags", "related", "updated"):
        val = meta.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            if val:
                lines.append(f"{key}: [{', '.join(val)}]")
            else:
                lines.append(f"{key}: []")
        else:
            lines.append(f"{key}: {val}")
    for key, val in meta.items():
        if key not in ("slug", "name", "description", "type", "status", "tags", "related", "updated"):
            if isinstance(val, list):
                lines.append(f"{key}: [{', '.join(val)}]")
            else:
                lines.append(f"{key}: {val}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    return "\n".join(lines) + "\n"


def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def read_entry(store_root, slug):
    """Return dict with all frontmatter fields + body, or None if not found."""
    store_root = Path(store_root)
    index = load_index(store_root)
    entry = index.get("entries", {}).get(slug)
    if not entry:
        return None
    file_path = store_root / entry["path"]
    if not file_path.exists():
        return None
    text = file_path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    result = dict(entry)
    result["body"] = body
    result.update({k: v for k, v in meta.items() if k not in result})
    return result


def write_entry(store_root, slug, name, description, entry_type, body,
                status="reference", tags=None, related=None, author_cn=None):
    """Write YAML-frontmatter .md file and rebuild catalog. Return entry dict."""
    store_root = Path(store_root)
    entry_type = entry_type if entry_type in VALID_TYPES else "reference"
    status = status if status in VALID_STATUSES else "reference"
    tags = sorted(set(tags or []))
    related = sorted(set(related or []))
    now = _now()

    rel_path = f"{entry_type}/{slug}.md"
    meta = {
        "slug": slug,
        "name": name,
        "description": description,
        "type": entry_type,
        "status": status,
        "tags": tags,
        "related": related,
        "updated": now,
    }
    if author_cn:
        meta["author_cn"] = author_cn

    _atomic_write(store_root / rel_path, _render_frontmatter(meta, body))
    rebuild_index(store_root)

    entry = dict(meta)
    entry["path"] = rel_path
    return entry


def soft_delete(store_root, slug):
    """Set status=deleted in frontmatter. Rebuild catalog. Return entry dict."""
    store_root = Path(store_root)
    entry = read_entry(store_root, slug)
    if not entry:
        return None
    body = entry.pop("body", "")
    entry["status"] = "deleted"
    entry["updated"] = _now()
    rel_path = entry["path"]
    meta = {k: v for k, v in entry.items() if k != "path"}
    _atomic_write(store_root / rel_path, _render_frontmatter(meta, body))
    rebuild_index(store_root)
    return entry


def scan_entries(store_root):
    """Scan all .md files in type subdirs. Return list of entry dicts (no body)."""
    store_root = Path(store_root)
    entries = []
    for type_dir in store_root.iterdir():
        if not type_dir.is_dir() or type_dir.name.startswith("."):
            continue
        for md_file in sorted(type_dir.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                meta, _ = _parse_frontmatter(text)
                if not meta.get("slug"):
                    meta["slug"] = md_file.stem
                meta["path"] = f"{type_dir.name}/{md_file.name}"
                entries.append(meta)
            except Exception:
                pass
    return entries


def load_index(store_root):
    """Load index.json. Return dict with 'entries' keyed by slug."""
    index_path = Path(store_root) / "index.json"
    if not index_path.exists():
        return {"entries": {}, "updated_at": None}
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {"entries": {}, "updated_at": None}


def rebuild_index(store_root):
    """Scan all .md files, rebuild index.json + INDEX.md + STATUS.md."""
    store_root = Path(store_root)
    entries_list = scan_entries(store_root)

    entries_dict = {}
    for e in entries_list:
        slug = e.get("slug", "")
        if not slug:
            continue
        entries_dict[slug] = {
            "slug": slug,
            "name": e.get("name", slug),
            "description": e.get("description", ""),
            "type": e.get("type", "reference"),
            "status": e.get("status", "reference"),
            "tags": e.get("tags", []),
            "related": e.get("related", []),
            "path": e.get("path", ""),
            "updated": e.get("updated", ""),
        }

    index = {
        "updated_at": _now(),
        "schema": "slug, name, description, type, status, tags, related, path, updated -- mirrored from file frontmatter. index.json is the fast-load catalog; open individual files only when needed.",
        "entries": entries_dict,
    }
    _atomic_write(store_root / "index.json", json.dumps(index, indent=2, ensure_ascii=True) + "\n")
    _atomic_write(store_root / "INDEX.md", _render_index_md(entries_dict))
    _atomic_write(store_root / "STATUS.md", _render_status_md(entries_dict))


def _render_index_md(entries_dict):
    lines = [
        "# Memory Index",
        "",
        "Read this file first. Each entry is one line -- enough to decide if you need to open the file.",
        "For cross-topic relationships see XREF.md. For status overview see STATUS.md.",
        "Machine-readable version: index.json (same data; YAML frontmatter in each file is source of truth).",
    ]
    for entry_type in ORDERED_TYPES:
        type_entries = sorted(
            [e for e in entries_dict.values()
             if e.get("type") == entry_type and e.get("status") != "deleted"],
            key=lambda e: e.get("slug", "")
        )
        if not type_entries:
            continue
        lines.append("")
        lines.append(f"## {entry_type}")
        for e in type_entries:
            lines.append(f"- `{e['slug']}` [{e.get('status', 'reference')}] -- {e.get('description', '')}")
    lines.append("")
    return "\n".join(lines)


def _render_status_md(entries_dict):
    lines = [
        "# Memory Status",
        "",
        "Use this file to see what is active, stashed, done, blocked, or just reference material.",
    ]
    for status in ("active", "stashed", "blocked", "done", "reference"):
        items = sorted(
            [e for e in entries_dict.values() if e.get("status") == status],
            key=lambda e: e.get("slug", "")
        )
        lines.append("")
        lines.append(f"## {status}")
        if items:
            for e in items:
                lines.append(f"- `{e['slug']}` ({e.get('type', '')}): {e.get('description', '')}")
        else:
            lines.append("- none")
    lines.append("")
    return "\n".join(lines)
