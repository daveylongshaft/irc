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
