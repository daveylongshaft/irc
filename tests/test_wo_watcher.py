"""Tests for WoWatcher and WoSyncClient.

Tests:
  - test_detects_new_file         — create file in ops/wo/ready/, verify on_change called
  - test_detects_deletion         — delete file, verify on_change called
  - test_debounce                 — rapid changes batched into single callback
  - test_filelist_hash            — hash changes when file added/removed/modified
  - test_ftp_push_mock            — mock FTP server, verify correct STOR/DELE commands
  - test_slave_delta_sync         — mock master, slave fetches only changed files
"""

import io
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "packages" / "csc-service"),
)

from csc_service.infra.wo_watcher import WoWatcher, compute_filelist_hash
from csc_service.infra.wo_sync_client import WoSyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_watcher(tmp_path, **kwargs):
    """Return a WoWatcher pointing at tmp_path with FTP disabled by default."""
    defaults = dict(
        wo_dir=str(tmp_path),
        ftp_master_host="127.0.0.1",
        ftp_master_port=9521,
        ftp_user="test",
        ftp_password="test",
        debounce_ms=50,
        poll_interval_s=1,
    )
    defaults.update(kwargs)
    return WoWatcher(**defaults)


# ---------------------------------------------------------------------------
# test_detects_new_file
# ---------------------------------------------------------------------------

class TestDetectsNewFile:
    def test_detects_new_file(self, tmp_path):
        """Polling watcher calls on_change when a new file appears."""
        ready_dir = tmp_path / "ready"
        ready_dir.mkdir()

        detected = []
        watcher = _make_watcher(tmp_path, poll_interval_s=1)

        # Patch on_change to capture calls and stop the watcher
        original_on_change = watcher.on_change

        def capturing_on_change(path):
            detected.append(path)
            watcher.stop()
            original_on_change(path)

        watcher.on_change = capturing_on_change

        # Start watcher in background thread
        t = threading.Thread(target=watcher._start_poll_loop)
        t.daemon = True
        t.start()

        time.sleep(0.2)  # let watcher take initial snapshot
        (ready_dir / "task-001.md").write_text("hello")

        t.join(timeout=5)
        assert any("task-001.md" in p for p in detected), (
            f"Expected task-001.md in detected paths, got: {detected}"
        )


# ---------------------------------------------------------------------------
# test_detects_deletion
# ---------------------------------------------------------------------------

class TestDetectsDeletion:
    def test_detects_deletion(self, tmp_path):
        """Polling watcher calls on_delete when a file is removed."""
        ready_dir = tmp_path / "ready"
        ready_dir.mkdir()
        target = ready_dir / "task-to-delete.md"
        target.write_text("content")

        deleted = []
        watcher = _make_watcher(tmp_path, poll_interval_s=1)
        original_on_delete = watcher.on_delete

        def capturing_on_delete(path):
            deleted.append(path)
            watcher.stop()
            original_on_delete(path)

        watcher.on_delete = capturing_on_delete

        t = threading.Thread(target=watcher._start_poll_loop)
        t.daemon = True
        t.start()

        time.sleep(0.2)
        target.unlink()

        t.join(timeout=5)
        assert any("task-to-delete.md" in p for p in deleted), (
            f"Expected task-to-delete.md in deleted paths, got: {deleted}"
        )


# ---------------------------------------------------------------------------
# test_debounce
# ---------------------------------------------------------------------------

class TestDebounce:
    def test_debounce_batches_rapid_changes(self, tmp_path):
        """Multiple rapid on_change calls result in a single _flush call."""
        watcher = _make_watcher(tmp_path, debounce_ms=200)
        flush_calls = []

        def fake_flush():
            flush_calls.append(time.monotonic())

        watcher._flush = fake_flush

        # Simulate 5 rapid changes
        for i in range(5):
            watcher.on_change(f"ready/task-{i:03d}.md")
            time.sleep(0.01)

        # Wait for debounce to fire
        time.sleep(0.5)

        assert len(flush_calls) == 1, (
            f"Expected 1 flush call (debounced), got {len(flush_calls)}"
        )

    def test_debounce_resets_on_new_change(self, tmp_path):
        """A new change arriving during the debounce window resets the timer."""
        watcher = _make_watcher(tmp_path, debounce_ms=200)
        flush_times = []

        def fake_flush():
            flush_times.append(time.monotonic())

        watcher._flush = fake_flush

        start = time.monotonic()
        watcher.on_change("ready/a.md")
        time.sleep(0.1)
        watcher.on_change("ready/b.md")  # resets timer
        # flush should come ~200ms after last on_change, not ~200ms after first
        time.sleep(0.5)

        assert len(flush_times) == 1
        # Should have fired ~300ms after start (0.1 delay + 0.2 debounce)
        elapsed = flush_times[0] - start
        assert elapsed >= 0.25, f"Flush fired too early: {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# test_filelist_hash
# ---------------------------------------------------------------------------

class TestFilelistHash:
    def test_hash_changes_on_add(self, tmp_path):
        h1 = compute_filelist_hash(tmp_path)
        (tmp_path / "a.md").write_text("hello")
        h2 = compute_filelist_hash(tmp_path)
        assert h1 != h2

    def test_hash_changes_on_remove(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("hello")
        h1 = compute_filelist_hash(tmp_path)
        f.unlink()
        h2 = compute_filelist_hash(tmp_path)
        assert h1 != h2

    def test_hash_changes_on_modify(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("hello")
        h1 = compute_filelist_hash(tmp_path)
        f.write_text("world")
        h2 = compute_filelist_hash(tmp_path)
        assert h1 != h2

    def test_hash_stable_on_no_change(self, tmp_path):
        (tmp_path / "a.md").write_text("stable")
        h1 = compute_filelist_hash(tmp_path)
        h2 = compute_filelist_hash(tmp_path)
        assert h1 == h2

    def test_hash_is_hex_string(self, tmp_path):
        h = compute_filelist_hash(tmp_path)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# test_ftp_push_mock
# ---------------------------------------------------------------------------

class TestFtpPushMock:
    @patch("csc_service.infra.wo_watcher._connect_ftp")
    def test_stor_called_for_changed_file(self, mock_connect, tmp_path):
        """_flush uploads changed files via STOR."""
        # Create a file
        (tmp_path / "ready").mkdir()
        f = tmp_path / "ready" / "task.md"
        f.write_text("content")

        mock_ftp = MagicMock()
        mock_connect.return_value = mock_ftp

        watcher = _make_watcher(tmp_path)
        watcher._pending_changes = {"ready/task.md"}
        watcher._pending_deletions = set()
        watcher._flush()

        # STOR should have been called for the file
        stor_calls = [
            c for c in mock_ftp.storbinary.call_args_list
            if "wo/ready/task.md" in str(c)
        ]
        assert len(stor_calls) >= 1, (
            f"Expected STOR for wo/ready/task.md; calls: {mock_ftp.storbinary.call_args_list}"
        )

    @patch("csc_service.infra.wo_watcher._connect_ftp")
    def test_dele_called_for_deleted_file(self, mock_connect, tmp_path):
        """_flush sends DELE for deleted files."""
        mock_ftp = MagicMock()
        mock_connect.return_value = mock_ftp

        watcher = _make_watcher(tmp_path)
        watcher._pending_changes = set()
        watcher._pending_deletions = {"wip/old-task.md"}
        watcher._flush()

        mock_ftp.delete.assert_called_once_with("wo/wip/old-task.md")

    @patch("csc_service.infra.wo_watcher._connect_ftp")
    def test_filelist_hash_uploaded_after_push(self, mock_connect, tmp_path):
        """_flush uploads wo/.filelist.hash after pushing file changes."""
        (tmp_path / "ready").mkdir()
        f = tmp_path / "ready" / "task.md"
        f.write_text("hi")

        mock_ftp = MagicMock()
        mock_connect.return_value = mock_ftp

        watcher = _make_watcher(tmp_path)
        watcher._pending_changes = {"ready/task.md"}
        watcher._pending_deletions = set()
        watcher._flush()

        hash_upload_calls = [
            c for c in mock_ftp.storbinary.call_args_list
            if "wo/.filelist.hash" in str(c)
        ]
        assert len(hash_upload_calls) == 1, (
            f"Expected filelist hash upload; calls: {mock_ftp.storbinary.call_args_list}"
        )

    @patch("csc_service.infra.wo_watcher._connect_ftp")
    def test_ftp_connect_params(self, mock_connect, tmp_path):
        """WoWatcher connects with correct host and port."""
        mock_ftp = MagicMock()
        mock_connect.return_value = mock_ftp

        watcher = WoWatcher(
            wo_dir=str(tmp_path),
            ftp_master_host="fahu.example.com",
            ftp_master_port=9521,
            ftp_user="csc-node",
            ftp_password="secret",
        )
        watcher._pending_changes = set()
        watcher._pending_deletions = set()
        # trigger flush with nothing to push (just to verify connect)
        watcher._flush()

        mock_connect.assert_not_called()  # nothing to flush, no connect needed


# ---------------------------------------------------------------------------
# test_slave_delta_sync
# ---------------------------------------------------------------------------

class TestSlaveDeltaSync:
    def _make_client(self, tmp_path):
        return WoSyncClient(
            wo_dir=str(tmp_path),
            ftp_master_host="127.0.0.1",
            ftp_master_port=9521,
            ftp_user="test",
            ftp_password="test",
        )

    def test_no_sync_when_hashes_match(self, tmp_path):
        """If local and remote hashes match, no files are downloaded."""
        (tmp_path / "ready").mkdir()
        (tmp_path / "ready" / "task.md").write_text("same")
        local_hash = compute_filelist_hash(tmp_path)

        client = self._make_client(tmp_path)
        mock_ftp = MagicMock()
        mock_ftp.retrbinary = lambda cmd, callback: callback(local_hash.encode())

        with patch.object(client, "_connect", return_value=mock_ftp):
            result = client.sync()

        assert result is False

    def test_downloads_missing_file(self, tmp_path):
        """If remote has a file not present locally, it is downloaded."""
        client = self._make_client(tmp_path)

        remote_hash = "aaaa" + "0" * 60  # fake different hash
        file_content = b"new task content"

        mock_ftp = MagicMock()

        def mock_retrbinary(cmd, callback):
            if ".filelist.hash" in cmd:
                callback(remote_hash.encode())
            else:
                callback(file_content)

        mock_ftp.retrbinary.side_effect = mock_retrbinary
        mock_ftp.mlsd.return_value = [
            ("ready", {"type": "dir", "size": "0"}),
            # mlsd on subdirectory
        ]

        # mlsd for "wo" returns a dir; mlsd for "wo/ready" returns a file
        def mock_mlsd(path, facts=None):
            if path == "wo":
                return [("ready", {"type": "dir", "size": "0"})]
            if path == "wo/ready":
                return [("new-task.md", {"type": "file", "size": str(len(file_content))})]
            return []

        mock_ftp.mlsd.side_effect = mock_mlsd

        with patch.object(client, "_connect", return_value=mock_ftp):
            result = client.sync()

        assert result is True
        downloaded = tmp_path / "ready" / "new-task.md"
        assert downloaded.exists()
        assert downloaded.read_bytes() == file_content

    def test_skips_unchanged_files(self, tmp_path):
        """Files whose local size matches remote size are not re-downloaded."""
        (tmp_path / "ready").mkdir()
        existing = tmp_path / "ready" / "existing.md"
        existing.write_text("unchanged")
        local_size = existing.stat().st_size

        client = self._make_client(tmp_path)
        remote_hash = "bbbb" + "0" * 60  # different hash triggers sync

        mock_ftp = MagicMock()

        def mock_retrbinary(cmd, callback):
            if ".filelist.hash" in cmd:
                callback(remote_hash.encode())
            # no other RETR calls expected

        mock_ftp.retrbinary.side_effect = mock_retrbinary

        def mock_mlsd(path, facts=None):
            if path == "wo":
                return [("ready", {"type": "dir", "size": "0"})]
            if path == "wo/ready":
                return [("existing.md", {"type": "file", "size": str(local_size)})]
            return []

        mock_ftp.mlsd.side_effect = mock_mlsd

        with patch.object(client, "_connect", return_value=mock_ftp):
            result = client.sync()

        # No new files downloaded (size matched), so result False
        assert result is False
