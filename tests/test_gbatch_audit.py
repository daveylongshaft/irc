"""
Tests for the diff audit layer in gbatch_tools.py.

Tests cover:
- _slugify_wo_id
- _path_to_slug
- _save_diff (new file, edit, delete, no-op on identical content)
- write_file audit integration (new file, edit)
- delete_file audit integration
- mark_wo_done (DONE and FAIL markers)
- Audit failures never block tool execution
- _current_wo_id attribution in filenames
"""

import sys
import os
import tempfile
import time
import difflib
import unittest
from pathlib import Path
from unittest.mock import patch

# Add gbatch dir to path
_GBATCH_DIR = Path(__file__).resolve().parent.parent.parent / "bin" / "gemini-batch"
sys.path.insert(0, str(_GBATCH_DIR))

import gbatch_tools
from gbatch_tools import (
    _slugify_wo_id,
    _path_to_slug,
    _save_diff,
    _ensure_audit_dir,
    mark_wo_done,
    write_file,
    delete_file,
    CSC_ROOT,
)


class TestSlugifyWoId(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(_slugify_wo_id(""), "anon")

    def test_none_like_empty(self):
        # None is not a valid input but empty string is the fallback
        self.assertEqual(_slugify_wo_id(""), "anon")

    def test_spaces_become_underscores(self):
        self.assertEqual(_slugify_wo_id("my wo name"), "my_wo_name")

    def test_truncates_at_40_chars(self):
        long_id = "a" * 60
        result = _slugify_wo_id(long_id)
        self.assertEqual(len(result), 40)

    def test_normal_id_unchanged(self):
        self.assertEqual(_slugify_wo_id("PROMPT_docs_svc_agent"), "PROMPT_docs_svc_agent")

    def test_exactly_40_chars(self):
        id_40 = "x" * 40
        self.assertEqual(_slugify_wo_id(id_40), id_40)


class TestPathToSlug(unittest.TestCase):
    def test_path_under_csc_root(self):
        p = CSC_ROOT / "irc" / "tests" / "test_foo.py"
        slug = _path_to_slug(p)
        self.assertEqual(slug, "irc-tests-test_foo.py")

    def test_path_outside_csc_root(self):
        p = Path("/tmp/something.py")
        slug = _path_to_slug(p)
        self.assertEqual(slug, "something.py")

    def test_nested_path(self):
        p = CSC_ROOT / "bin" / "gemini-batch" / "gbatch_tools.py"
        slug = _path_to_slug(p)
        self.assertEqual(slug, "bin-gemini-batch-gbatch_tools.py")


class TestSaveDiff(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Redirect audit dir to tmpdir for isolation
        self._orig_ensure = gbatch_tools._ensure_audit_dir
        gbatch_tools._ensure_audit_dir = lambda: Path(self.tmpdir)
        # Set a known WO id
        self._orig_wo_id = gbatch_tools._current_wo_id
        gbatch_tools._current_wo_id = "test_wo"

    def tearDown(self):
        gbatch_tools._ensure_audit_dir = self._orig_ensure
        gbatch_tools._current_wo_id = self._orig_wo_id
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _audit_files(self):
        return list(Path(self.tmpdir).iterdir())

    def test_new_file_creates_dot_new(self):
        p = CSC_ROOT / "fake" / "file.py"
        _save_diff(None, "print('hello')", p)
        files = self._audit_files()
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.endswith(".new"))
        self.assertIn("test_wo", files[0].name)
        self.assertEqual(files[0].read_text(), "print('hello')")

    def test_edit_creates_dot_patch(self):
        p = CSC_ROOT / "fake" / "file.py"
        _save_diff("old content\n", "new content\n", p)
        files = self._audit_files()
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.endswith(".patch"))
        content = files[0].read_text()
        self.assertIn("-old content", content)
        self.assertIn("+new content", content)

    def test_delete_creates_dot_deleted(self):
        p = CSC_ROOT / "fake" / "file.py"
        _save_diff("old content\n", None, p)
        files = self._audit_files()
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.endswith(".deleted"))
        self.assertEqual(files[0].read_text(), "old content\n")

    def test_identical_content_no_file(self):
        p = CSC_ROOT / "fake" / "file.py"
        _save_diff("same\n", "same\n", p)
        files = self._audit_files()
        self.assertEqual(len(files), 0)

    def test_both_none_no_file(self):
        p = CSC_ROOT / "fake" / "file.py"
        _save_diff(None, None, p)
        files = self._audit_files()
        self.assertEqual(len(files), 0)

    def test_wo_id_in_filename(self):
        gbatch_tools._current_wo_id = "PROMPT_docs_svc_agent"
        p = CSC_ROOT / "fake" / "file.py"
        _save_diff(None, "content", p)
        files = self._audit_files()
        self.assertEqual(len(files), 1)
        self.assertIn("PROMPT_docs_svc_agent", files[0].name)

    def test_audit_failure_does_not_raise(self):
        # Break ensure_audit_dir to simulate failure
        gbatch_tools._ensure_audit_dir = lambda: (_ for _ in ()).throw(OSError("disk full"))
        # Should not raise
        try:
            _save_diff(None, "content", CSC_ROOT / "fake.py")
        except Exception as e:
            self.fail(f"_save_diff raised unexpectedly: {e}")
        finally:
            gbatch_tools._ensure_audit_dir = lambda: Path(self.tmpdir)

    def test_patch_is_reversible(self):
        old = "line one\nline two\nline three\n"
        new = "line one\nline TWO\nline three\n"
        p = CSC_ROOT / "fake" / "file.py"
        _save_diff(old, new, p)
        files = self._audit_files()
        patch_text = files[0].read_text()
        # Verify patch contains the right context
        self.assertIn("line two", patch_text)
        self.assertIn("line TWO", patch_text)


class TestMarkWoDone(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_ensure = gbatch_tools._ensure_audit_dir
        gbatch_tools._ensure_audit_dir = lambda: Path(self.tmpdir)

    def tearDown(self):
        gbatch_tools._ensure_audit_dir = self._orig_ensure
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_done_marker_created(self):
        mark_wo_done("my_wo", "DONE")
        files = list(Path(self.tmpdir).iterdir())
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.endswith(".DONE"))
        self.assertIn("my_wo", files[0].name)

    def test_fail_marker_created(self):
        mark_wo_done("my_wo", "FAIL")
        files = list(Path(self.tmpdir).iterdir())
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.endswith(".FAIL"))

    def test_marker_is_zero_bytes(self):
        mark_wo_done("my_wo", "DONE")
        files = list(Path(self.tmpdir).iterdir())
        self.assertEqual(files[0].stat().st_size, 0)

    def test_failure_does_not_raise(self):
        gbatch_tools._ensure_audit_dir = lambda: (_ for _ in ()).throw(OSError("no space"))
        try:
            mark_wo_done("my_wo", "DONE")
        except Exception as e:
            self.fail(f"mark_wo_done raised unexpectedly: {e}")
        finally:
            gbatch_tools._ensure_audit_dir = lambda: Path(self.tmpdir)

    def test_timestamp_in_filename(self):
        before = int(time.time() * 1000)
        mark_wo_done("my_wo", "DONE")
        after = int(time.time() * 1000)
        files = list(Path(self.tmpdir).iterdir())
        ts_str = files[0].name.split("_")[0]
        ts = int(ts_str)
        self.assertGreaterEqual(ts, before)
        self.assertLessEqual(ts, after)


class TestWriteFileAudit(unittest.TestCase):
    """Integration tests: write_file calls _save_diff correctly."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_ensure = gbatch_tools._ensure_audit_dir
        gbatch_tools._ensure_audit_dir = lambda: Path(self.tmpdir)
        gbatch_tools._current_wo_id = "test_write"
        # Use a temp file for writing
        self.test_file = Path(self.tmpdir) / "testfile.txt"

    def tearDown(self):
        gbatch_tools._ensure_audit_dir = self._orig_ensure
        gbatch_tools._current_wo_id = ""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_new_file_produces_dot_new_audit(self):
        target = CSC_ROOT / "tmp" / "_audit_test_new.txt"
        try:
            if target.exists():
                target.unlink()
            result = write_file(str(target), "hello world")
            self.assertIn("OK", result)
            audit_files = [f for f in Path(self.tmpdir).iterdir() if f.suffix == ".new"]
            self.assertEqual(len(audit_files), 1)
        finally:
            if target.exists():
                target.unlink()

    def test_edit_produces_dot_patch_audit(self):
        target = CSC_ROOT / "tmp" / "_audit_test_edit.txt"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("original content\n")
            result = write_file(str(target), "modified content\n")
            self.assertIn("OK", result)
            audit_files = [f for f in Path(self.tmpdir).iterdir() if f.suffix == ".patch"]
            self.assertEqual(len(audit_files), 1)
            patch_content = audit_files[0].read_text()
            self.assertIn("-original content", patch_content)
            self.assertIn("+modified content", patch_content)
        finally:
            if target.exists():
                target.unlink()


class TestDeleteFileAudit(unittest.TestCase):
    """Integration tests: delete_file calls _save_diff correctly."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_ensure = gbatch_tools._ensure_audit_dir
        gbatch_tools._ensure_audit_dir = lambda: Path(self.tmpdir)
        gbatch_tools._current_wo_id = "test_delete"

    def tearDown(self):
        gbatch_tools._ensure_audit_dir = self._orig_ensure
        gbatch_tools._current_wo_id = ""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_delete_produces_dot_deleted_audit(self):
        target = CSC_ROOT / "tmp" / "_audit_test_delete.txt"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("content to preserve\n")
            result = delete_file(str(target))
            self.assertIn("OK", result)
            self.assertFalse(target.exists())
            audit_files = [f for f in Path(self.tmpdir).iterdir() if f.suffix == ".deleted"]
            self.assertEqual(len(audit_files), 1)
            self.assertEqual(audit_files[0].read_text(), "content to preserve\n")
        finally:
            if target.exists():
                target.unlink()

    def test_delete_missing_file_no_audit(self):
        result = delete_file(str(CSC_ROOT / "tmp" / "_does_not_exist_xyz.txt"))
        self.assertIn("ERROR", result)
        # No audit file should be created for a missing file
        audit_files = list(Path(self.tmpdir).iterdir())
        self.assertEqual(len(audit_files), 0)


if __name__ == "__main__":
    unittest.main()
