from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
for package in ("csc-root", "csc-log", "csc-data"):
    sys.path.insert(0, str(REPO_ROOT / "packages" / package))

from csc_data.memory_store import MemoryStore  # noqa: E402


def test_memory_store_indexes_entries_and_status_views(tmp_path):
    store = MemoryStore(root_dir=tmp_path / "memory")

    store.upsert_entry(
        slug="davey-profile",
        category="user",
        title="Davey Profile",
        summary="Key collaboration preferences.",
        body="Prefers work to be stashed with context when interrupted.",
        status="reference",
        tags=["user", "workflow"],
    )
    store.upsert_entry(
        slug="s2s-linking",
        category="tasks",
        title="S2S Linking Investigation",
        summary="Unfinished server-to-server linking work.",
        body="Need to resume after the memory system task.",
        status="stashed",
        tags=["s2s", "networking"],
        related=["davey-profile"],
    )
    store.link_entries("s2s-linking", "davey-profile", relation="informed-by")
    store.append_note("s2s-linking", "Paused to build durable memory support.", status="stashed")

    stashed = store.list_entries(status="stashed")
    assert [entry["slug"] for entry in stashed] == ["s2s-linking"]

    entry = store.get_entry("s2s-linking")
    assert entry["category"] == "tasks"
    assert "Paused to build durable memory support." in entry["body"]

    index = (tmp_path / "memory" / "index.json").read_text(encoding="utf-8")
    assert "davey-profile" in index
    assert "s2s-linking" in index

    xref = (tmp_path / "memory" / "xref.json").read_text(encoding="utf-8")
    assert "informed-by" in xref

    status_md = (tmp_path / "memory" / "STATUS.md").read_text(encoding="utf-8")
    assert "## stashed" in status_md
    assert "`s2s-linking`" in status_md


def test_upsert_updates_existing_entry(tmp_path):
    store = MemoryStore(root_dir=tmp_path / "memory")
    store.upsert_entry(slug="my-entry", category="user", title="Old Title", summary="Old.", body="Old body.", status="reference")
    store.upsert_entry(slug="my-entry", category="user", title="New Title", summary="New.", body="New body.", status="active")

    entry = store.get_entry("my-entry")
    assert entry["title"] == "New Title"
    assert entry["status"] == "active"
    assert "New body." in entry["body"]

    entries = store.list_entries(category="user")
    assert len(entries) == 1, "upsert must not duplicate the entry"


def test_invalid_status_falls_back_to_reference(tmp_path):
    store = MemoryStore(root_dir=tmp_path / "memory")
    store.upsert_entry(slug="test-entry", category="workflow", title="T", summary="S.", body="B.", status="nonsense")
    entry = store.get_entry("test-entry")
    assert entry["status"] == "reference"


def test_append_note_unknown_slug_raises(tmp_path):
    store = MemoryStore(root_dir=tmp_path / "memory")
    try:
        store.append_note("no-such-slug", "some note")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_duplicate_link_not_added_twice(tmp_path):
    store = MemoryStore(root_dir=tmp_path / "memory")
    store.upsert_entry(slug="a", category="tasks", title="A", summary=".", body=".", status="active")
    store.upsert_entry(slug="b", category="tasks", title="B", summary=".", body=".", status="active")
    store.link_entries("a", "b", relation="related")
    store.link_entries("a", "b", relation="related")

    import json
    xref = json.loads((tmp_path / "memory" / "xref.json").read_text(encoding="utf-8"))
    related_links = [lnk for lnk in xref["links"] if lnk["source"] == "a" and lnk["target"] == "b" and lnk["relation"] == "related"]
    assert len(related_links) == 1, "duplicate link must not be stored"
