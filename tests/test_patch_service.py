```python
"""Tests for the fuzzy patch service.

Tests the core parsing, anchor matching, and hunk application logic
against a copy of the patch_test_dummy_service.py file.
"""

import os
import pytest
from unittest.mock import MagicMock, patch as mock_patch

from csc_service.shared.services.patch_service import patch


# The canonical dummy file content used by all tests.
DUMMY_CONTENT = """\
from service import Service


class patch_test_dummy( Service ):
    \"\"\"A dummy service used exclusively as a patch test target.\"\"\"

    def __init__(self, server_instance):
        super().__init__( server_instance )
        self.name = "patch_test_dummy"

    def hello(self):
        \"\"\"Return a greeting.\"\"\"
        return "Hello from dummy service"

    def add(self, a, b):
        \"\"\"Add two numbers.\"\"\"
        result = int( a ) + int( b )
        return str( result )

    def status(self):
        \"\"\"Return status string.\"\"\"
        return "dummy OK"

    def multiply(self, x, y):
        \"\"\"Multiply two numbers.\"\"\"
        result = int( x ) * int( y )
        return str( result )

    def default(self, *args):
        \"\"\"Fallback handler.\"\"\"
        return f"patch_test_dummy default: {args}"
"""


@pytest.fixture
def dummy_lines():
    """Return the dummy content as a list of lines with newlines."""
    return DUMMY_CONTENT.splitlines(True)


@pytest.fixture
def mock_server():
    """Create a mock server instance."""
    server = MagicMock()
    server.project_root_dir = "/fake/project"
    return server


class TestFindAnchor:
    """Test the fuzzy anchor matcher."""

    def test_exact_hint(self, dummy_lines):
        """Anchor found at exact line hint."""
        # Line 10 (0-based) is '    def hello(self):\n'
        idx = patch._find_anchor(dummy_lines, 10, "def hello")
        assert idx == 10

    def test_fuzzy_offset(self, dummy_lines):
        """Anchor found when hint is off by a few lines."""
        # hello is at line 10, give hint of 14 (off by 4)
        idx = patch._find_anchor(dummy_lines, 14, "def hello")
        assert idx == 10

    def test_fuzzy_large_offset(self, dummy_lines):
        """Anchor found when hint is off by up to SEARCH_WINDOW lines."""
        # multiply is at line 23, give hint of 17 (off by 6, within ±10)
        idx = patch._find_anchor(dummy_lines, 17, "def multiply")
        assert idx == 23

    def test_not_found(self, dummy_lines):
        """Anchor returns None when text doesn't exist."""
        idx = patch._find_anchor(dummy_lines, 5, "def nonexistent_method")
        assert idx is None

    def test_empty_fragment(self, dummy_lines):
        """Empty fragment returns None."""
        idx = patch._find_anchor(dummy_lines, 0, "   ")
        assert idx is None

    def test_prefers_closer_match(self, dummy_lines):
        """When two lines match, the one closer to the hint wins."""
        # 'def add' is at line 14 — hint at 15 is off by 1, should still find it
        idx = patch._find_anchor(dummy_lines, 15, "def add")
        assert idx == 14

    def test_out_of_bounds_hint(self, dummy_lines):
        """Anchor search handles out-of-bounds hints gracefully."""
        idx = patch._find_anchor(dummy_lines, 10000, "def hello")
        assert idx == 10

    def test_negative_line_hint(self, dummy_lines):
        """Anchor search handles negative line hints gracefully."""
        idx = patch._find_anchor(dummy_lines, -5, "def hello")
        assert idx == 10


class TestParseLoosePatch:
    """Test the loose-format parser."""

    def test_single_hunk(self):
        """Parse a single anchor with removes and adds."""
        content = (
            '<patch file=patch_test_dummy>\n'
            '12 def hello\n'
            '- def hello(self):\n'
            '+ def greet(self):\n'
            '</patch>'
        )
        hunks = patch._parse_loose_patch(content)
        assert len(hunks) == 1
        assert hunks[0]["file"] == "patch_test_dummy"
        assert hunks[0]["anchor_line"] == 11  # 12 -> 0-based 11
        assert hunks[0]["anchor_text"] == "def hello"
        assert hunks[0]["removes"] == ['def hello(self):']
        assert hunks[0]["adds"] == ['def greet(self):']

    def test_multiple_hunks(self):
        """Parse two anchors in one patch block."""
        content = (
            '<patch file=patch_test_dummy>\n'
            '12 def hello\n'
            '- def hello(self):\n'
            '+ def greet(self):\n'
            '20 def status\n'
            '- def status(self):\n'
            '+ def get_status(self):\n'
            '</patch>'
        )
        hunks = patch._parse_loose_patch(content)
        assert len(hunks) == 2
        assert hunks[0]["anchor_text"] == "def hello"
        assert hunks[1]["anchor_text"] == "def status"

    def test_add_only(self):
        """Hunk with only add lines (insertion)."""
        content = (
            '<patch file=patch_test_dummy>\n'
            '14 return "Hello\n'
            '+ \n'
            '+     def goodbye(self):\n'
            '+         return "Goodbye"\n'
            '</patch>'
        )
        hunks = patch._parse_loose_patch(content)
        assert len(hunks) == 1
        assert len(hunks[0]["removes"]) == 0
        assert len(hunks[0]["adds"]) == 3

    def test_remove_only(self):
        """Hunk with only remove lines (deletion)."""
        content = (
            '<patch file=patch_test_dummy>\n'
            '12 def hello\n'
            '-     def hello(self):\n'
            '-         """Return a greeting."""\n'
            '-         return "Hello from dummy service"\n'
            '</patch>'
        )
        hunks = patch._parse_loose_patch(content)
        assert len(hunks) == 1
        assert len(hunks[0]["removes"]) == 3
        assert len(hunks[0]["adds"]) == 0

    def test_quoted_file(self):
        """File name can be in quotes."""
        content = (
            '<patch file="patch_test_dummy">\n'
            '12 def hello\n'
            '- def hello(self):\n'
            '+ def greet(self):\n'
            '</patch>'
        )
        hunks = patch._parse_loose_patch(content)
        assert hunks[0]["file"] == "patch_test_dummy"

    def test_single_quoted_file(self):
        """File name can be in single quotes."""
        content = (
            "<patch file='patch_test_dummy'>\n"
            "12 def hello\n"
            "- def hello(self):\n"
            "+ def greet(self):\n"
            "</patch>"
        )
        hunks = patch._parse_loose_patch(content)
        assert hunks[0]["file"] == "patch_test_dummy"

    def test_whitespace_in_anchor_line(self):
        """Anchor line with various whitespace."""
        content = (
            '<patch file=patch_test_dummy>\n'
            '12   def   hello   \n'
            '- def hello(self):\n'
            '+ def greet(self):\n'
            '</patch>'
        )
        hunks = patch._parse_loose_patch(content)
        assert hunks[0]["anchor_text"] == "def   hello"

    def test_preserve_leading_spaces_in_removes(self):
        """Leading spaces in removes should be preserved (after stripping -/+)."""
        content = (
            '<patch file=patch_test_dummy>\n'
            '12 def hello\n'
            '-     indented line\n'
            '</patch>'
        )
        hunks = patch._parse_loose_patch(content)
        assert hunks[0]["removes"] == ['    indented line']

    def test_preserve_leading_spaces_in_adds(self):
        """Leading spaces in adds should be preserved (after stripping -/+)."""
        content = (
            '<patch file=patch_test_dummy>\n'
            '12 def hello\n'
            '+     indented line\n'
            '</patch>'
        )
        hunks = patch._parse_loose_patch(content)
        assert hunks[0]["adds"] == ['    indented line']

    def test_empty_content(self):
        """Empty patch content returns no hunks."""
        content = ""
        hunks = patch._parse_loose_patch(content)
        assert hunks == []

    def test_no_patch_tags(self):
        """Content without patch tags is ignored."""
        content = (
            "12 def hello\n"
            "- def hello(self):\n"
            "+ def greet(self):\n"
        )
        hunks = patch._parse_loose_patch(content)
        assert hunks == []

    def test_unmatched_opening_tag(self):
        """Patch without closing tag stops at EOF."""
        content = (
            '<patch file=patch_test_dummy>\n'
            '12 def hello\n'
            '- def hello(self):\n'
        )
        hunks = patch._parse_loose_patch(content)
        assert len(hunks) == 1


class TestApplyHunks:
    """Test hunk application to lines."""

    def test_single_hunk_replace(self, dummy_lines):
        """Apply a single hunk that replaces a line."""
        hunks = [
            {
                "file": "patch_test_dummy",
                "anchor_line": 10,
                "anchor_text": "def hello",
                "removes": ["    def hello(self):"],
                "adds": ["    def greet(self):"],
            }
        ]
        result, report = patch._apply_hunks(dummy_lines, hunks)
        assert "def greet(self):" in result[10]
        assert "def hello(self):" not in result[10]
        assert "1 applied" in report

    def test_multiple_hunks(self, dummy_lines):
        """Apply multiple hunks in sequence."""
        hunks = [
            {
                "file": "patch_test_dummy",
                "anchor_line": 10,
                "anchor_text": "def hello",
                "removes": ["    def hello(self):"],
                "adds": ["    def greet(self):"],
            },
            {
                "file": "patch_test_dummy",
                "anchor_line": 14,
                "anchor_text": "def add",
                "removes": ["    def add(self, a, b):"],
                "adds": ["    def sum(self, a, b):"],
            },
        ]
        result, report = patch._apply_hunks(dummy_lines, hunks)
        assert "def greet(self):" in result[10]
        assert "def sum(self, a, b):" in result[14]
        assert "2 applied" in report

    def test_hunk_with_insertion(self, dummy_lines):
        """Apply a hunk that inserts new lines."""
        hunks = [
            {
                "file": "patch_test_dummy",
                "anchor_line": 10,
                "anchor_text": "def hello",
                "removes": [],
                "adds": ["    def new_method(self):", "        pass"],
            }
        ]
        result, report = patch._apply_hunks(dummy_lines, hunks)
        assert len(result) > len(dummy_lines)
        assert "def new_method(self):" in "\n".join(result)
        assert "1 applied" in report

    def test_hunk_with_deletion(self, dummy_lines):
        """Apply a hunk that deletes lines."""
        hunks = [
            {
                "file": "patch_test_dummy",
                "anchor_line": 10,
                "anchor_text": "def hello",
                "removes": ["    def hello(self):", "        \"\"\"Return a greeting.\"\"\""],
                "adds": [],
            }
        ]
        result, report = patch._apply_hunks(dummy_lines, hunks)
        assert len(result) < len(dummy_lines)
        assert "1 applied" in report

    def test_anchor_not_found(self, dummy_lines):
        """When anchor is not found, hunk is skipped."""
        hunks = [
            {
                "file": "patch_test_dummy",
                "anchor_line": 0,
                "anchor_text": "nonexistent_method",
                "removes": ["old line"],
                "adds": ["new line"],
            }
        ]
        result, report = patch._apply_hunks(dummy_lines, hunks)
        assert result == dummy_lines
        assert "1 skipped" in report
        assert "SKIP" in report

    def test_remove_mismatch(self, dummy_lines):
        """When remove lines don't match, hunk is skipped."""
        hunks = [
            {
                "file": "patch_test_dummy",
                "anchor_line": 10,
                "anchor_text": "def hello",
                "removes": ["wrong line that doesn't exist"],
                "adds": ["new line"],
            }
        ]
        result, report = patch._apply_hunks(dummy_lines, hunks)
        assert result == dummy_lines
        assert "1 skipped" in report

    def test_empty_hunks_list(self, dummy_lines):
        """Empty hunks list returns unchanged lines."""
        result, report = patch._apply_hunks(dummy_lines, [])
        assert result == dummy_lines
        assert "0 applied" in report

    def test_offset_accumulation(self, dummy_lines):
        """Offset accumulates correctly when hunks add/remove lines."""
        hunks = [
            {
                "file": "patch_test_dummy",
                "anchor_line": 10,
                "anchor_text": "def hello",
                "removes": [],
                "adds": ["    # new comment 1", "    # new comment 2"],
            },
            {
                "file": "patch_test_dummy",
                "anchor_line": 14,
                "anchor_text": "def add",
                "removes": ["    def add(self, a, b):"],
                "adds": ["    def sum(self, a, b):"],
            },
        ]
        result, report = patch._apply_hunks(dummy_lines, hunks)
        # Second hunk should still find its anchor despite offset from first
        assert "2 applied" in report


class TestServiceIntegration:
    """Integration tests for the patch service class."""

    def test_service_initialization(self, tmp_path, mock_server):
        """Service initializes with correct directories."""
        mock_server.project_root_dir = tmp_path
        with mock_patch.object(patch, 'init_data'), \
             mock_patch.object(patch, 'log'):
            service = patch(mock_server)
            assert service.name == "patch"
            assert str(tmp_path) in service.project_root

    def test_service_creates_patches_dir(self, tmp_path, mock_server):
        """Service creates patches directory if it doesn't exist."""
        mock_server.project_root_dir = tmp_path