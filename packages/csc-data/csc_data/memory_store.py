"""Indexed file-backed memory store for durable user/project context."""

import json
import time
from pathlib import Path

from .data import Data


class MemoryStore(Data):
    """Persist categorized notes plus lightweight index and cross-reference views."""

    VALID_STATUSES = {"active", "stashed", "done", "blocked", "reference"}

    def __init__(self, root_dir=None):
        super().__init__()
        self.root_dir = Path(root_dir) if root_dir else Path(__file__).resolve().parents[3] / "docs" / "memory"
        self.index_path = self.root_dir / "index.json"
        self.xref_path = self.root_dir / "xref.json"
        self.index_md_path = self.root_dir / "INDEX.md"
        self.xref_md_path = self.root_dir / "XREF.md"
        self.status_md_path = self.root_dir / "STATUS.md"
        self.readme_path = self.root_dir / "README.md"
        self._ensure_layout()

    def _ensure_layout(self):
        self.root_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._write_json_file(self.index_path, {"categories": {}, "entries": {}, "updated_at": None})
        if not self.xref_path.exists():
            self._write_json_file(self.xref_path, {"links": [], "updated_at": None})

    @staticmethod
    def _slugify(value):
        cleaned = []
        for char in (value or "").strip().lower():
            if char.isalnum():
                cleaned.append(char)
            elif char in (" ", "-", "_", ".", "/"):
                cleaned.append("-")
        slug = "".join(cleaned).strip("-")
        while "--" in slug:
            slug = slug.replace("--", "-")
        return slug or "entry"

    @staticmethod
    def _now():
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _load_index(self):
        data = self._read_json_file(self.index_path)
        data.setdefault("categories", {})
        data.setdefault("entries", {})
        data.setdefault("updated_at", None)
        return data

    def _load_xref(self):
        data = self._read_json_file(self.xref_path)
        data.setdefault("links", [])
        data.setdefault("updated_at", None)
        return data

    def _write_views(self, index, xref):
        self._write_text_file(self.index_md_path, self._render_index_md(index))
        self._write_text_file(self.xref_md_path, self._render_xref_md(index, xref))
        self._write_text_file(self.status_md_path, self._render_status_md(index))

    def _save(self, index, xref):
        now = self._now()
        index["updated_at"] = now
        xref["updated_at"] = now
        self._write_json_file(self.index_path, index)
        self._write_json_file(self.xref_path, xref)
        self._write_views(index, xref)

    def list_entries(self, category=None, status=None, tag=None):
        index = self._load_index()
        entries = list(index["entries"].values())
        if category:
            category = self._slugify(category)
            entries = [entry for entry in entries if entry.get("category") == category]
        if status:
            entries = [entry for entry in entries if entry.get("status") == status]
        if tag:
            entries = [entry for entry in entries if tag in entry.get("tags", [])]
        return sorted(entries, key=lambda item: (item.get("status", ""), item.get("title", ""), item.get("slug", "")))

    def get_entry(self, slug):
        slug = self._slugify(slug)
        index = self._load_index()
        entry = index["entries"].get(slug)
        if not entry:
            return None
        result = dict(entry)
        result["body"] = self._read_text_file(self.root_dir / entry["path"])
        return result

    def upsert_entry(self, slug, category, title, summary, body, status="reference", tags=None, related=None):
        slug = self._slugify(slug)
        category = self._slugify(category)
        status = status if status in self.VALID_STATUSES else "reference"
        tags = sorted({self._slugify(tag) for tag in (tags or []) if tag})
        related = sorted({self._slugify(item) for item in (related or []) if item})

        index = self._load_index()
        xref = self._load_xref()
        now = self._now()
        entry = index["entries"].get(slug, {})
        created_at = entry.get("created_at", now)

        category_dir = self.root_dir / category
        category_dir.mkdir(parents=True, exist_ok=True)
        rel_path = f"{category}/{slug}.md"

        metadata = {
            "slug": slug,
            "title": title.strip(),
            "category": category,
            "summary": summary.strip(),
            "status": status,
            "tags": tags,
            "related": related,
            "path": rel_path,
            "created_at": created_at,
            "updated_at": now,
        }
        index["entries"][slug] = metadata

        category_meta = index["categories"].setdefault(category, {"entries": [], "updated_at": now})
        if slug not in category_meta["entries"]:
            category_meta["entries"].append(slug)
            category_meta["entries"].sort()
        category_meta["updated_at"] = now

        self._write_text_file(self.root_dir / rel_path, self._render_entry_md(metadata, body.strip()))

        for target in related:
            self._upsert_link(xref, slug, target, "related")

        self._save(index, xref)
        return metadata

    def append_note(self, slug, note, status=None):
        slug = self._slugify(slug)
        index = self._load_index()
        xref = self._load_xref()
        entry = index["entries"].get(slug)
        if not entry:
            raise KeyError(f"Unknown memory entry: {slug}")

        path = self.root_dir / entry["path"]
        content = self._read_text_file(path).rstrip() + "\n"
        timestamp = self._now()
        if "\n## Updates\n" not in content:
            content += "\n## Updates\n"
        content += f"- {timestamp}: {note.strip()}\n"
        self._write_text_file(path, content)

        entry["updated_at"] = timestamp
        if status in self.VALID_STATUSES:
            entry["status"] = status
        self._save(index, xref)
        return dict(entry)

    def link_entries(self, source_slug, target_slug, relation="related"):
        source_slug = self._slugify(source_slug)
        target_slug = self._slugify(target_slug)
        index = self._load_index()
        xref = self._load_xref()
        if source_slug not in index["entries"] or target_slug not in index["entries"]:
            raise KeyError("Both memory entries must exist before linking them")
        self._upsert_link(xref, source_slug, target_slug, relation)

        source = index["entries"][source_slug]
        related = set(source.get("related", []))
        related.add(target_slug)
        source["related"] = sorted(related)
        source["updated_at"] = self._now()
        self._save(index, xref)
        return True

    @staticmethod
    def _upsert_link(xref, source, target, relation):
        for link in xref["links"]:
            if link["source"] == source and link["target"] == target and link["relation"] == relation:
                return
        xref["links"].append({"source": source, "target": target, "relation": relation})
        xref["links"].sort(key=lambda item: (item["source"], item["relation"], item["target"]))

    @staticmethod
    def _render_entry_md(metadata, body):
        tags = ", ".join(metadata.get("tags", [])) or "none"
        related = ", ".join(metadata.get("related", [])) or "none"
        sections = [
            f"# {metadata['title']}",
            "",
            f"- Slug: `{metadata['slug']}`",
            f"- Category: `{metadata['category']}`",
            f"- Status: `{metadata['status']}`",
            f"- Tags: {tags}",
            f"- Related: {related}",
            f"- Created: {metadata['created_at']}",
            f"- Updated: {metadata['updated_at']}",
            "",
            "## Summary",
            metadata["summary"],
            "",
            "## Details",
            body or "No details recorded yet.",
            "",
        ]
        return "\n".join(sections)

    @staticmethod
    def _render_index_md(index):
        lines = [
            "# Memory Index",
            "",
            "Read this file first. It lists what memory exists so you can open only relevant entries.",
            "",
        ]
        for category in sorted(index["categories"].keys()):
            lines.append(f"## {category}")
            category_entries = [
                index["entries"][slug]
                for slug in index["categories"][category].get("entries", [])
                if slug in index["entries"]
            ]
            for entry in sorted(category_entries, key=lambda item: item["title"]):
                lines.append(
                    f"- `{entry['slug']}` [{entry['status']}] - {entry['title']}: {entry['summary']}"
                )
            if not category_entries:
                lines.append("- none")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _render_xref_md(index, xref):
        lines = [
            "# Memory Cross References",
            "",
            "Use this file when a topic spans multiple entries.",
            "",
        ]
        for link in xref.get("links", []):
            source = index["entries"].get(link["source"], {}).get("title", link["source"])
            target = index["entries"].get(link["target"], {}).get("title", link["target"])
            lines.append(f"- `{link['source']}` ({source}) --{link['relation']}--> `{link['target']}` ({target})")
        if len(lines) == 4:
            lines.append("- none")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _render_status_md(index):
        lines = [
            "# Memory Status",
            "",
            "Use this file to see what is active, stashed, done, blocked, or just reference material.",
            "",
        ]
        for status in ["active", "stashed", "blocked", "done", "reference"]:
            lines.append(f"## {status}")
            items = [entry for entry in index["entries"].values() if entry.get("status") == status]
            for entry in sorted(items, key=lambda item: item["title"]):
                lines.append(f"- `{entry['slug']}` ({entry['category']}): {entry['summary']}")
            if not items:
                lines.append("- none")
            lines.append("")
        return "\n".join(lines)
