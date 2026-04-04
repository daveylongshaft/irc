"""Tests for queue_worker target_repo support.

Tests the new functionality that allows workorders to specify which repository
to clone (csc/irc.git or facingaddictionwithhope.git) via the target_repo
frontmatter field.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add packages to path for test imports
TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "packages" / "csc-loop"))

from csc_loop.infra.queue_worker import (
    parse_workorder_frontmatter,
    _get_target_repo_remote,
)


class TestParseWorkorderFrontmatter:
    """Tests for parsing YAML-like front-matter from workorder files."""

    def test_parse_target_repo_csc(self):
        """Parse workorder with target_repo: csc."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("""---
urgency: P1
requires: [python, fastapi]
target_repo: csc
---
## Task description
Some work to do.
""")
            f.flush()
            path = Path(f.name)

        try:
            result = parse_workorder_frontmatter(path)
            assert result.get("target_repo") == "csc"
            assert result.get("urgency") == "P1"
            assert result.get("requires") == ["python", "fastapi"]
        finally:
            path.unlink()

    def test_parse_target_repo_fahu(self):
        """Parse workorder with target_repo: fahu."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("""---
urgency: P0
target_repo: fahu
---
## OAuth Implementation
Add Google/Facebook/Twitter/Bing logins.
""")
            f.flush()
            path = Path(f.name)

        try:
            result = parse_workorder_frontmatter(path)
            assert result.get("target_repo") == "fahu"
            assert result.get("urgency") == "P0"
        finally:
            path.unlink()

    def test_parse_no_frontmatter(self):
        """Parse workorder without front-matter (legacy)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("""## Task
No front-matter here.
""")
            f.flush()
            path = Path(f.name)

        try:
            result = parse_workorder_frontmatter(path)
            assert result == {}
        finally:
            path.unlink()

    def test_parse_incomplete_frontmatter(self):
        """Handle incomplete front-matter gracefully."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("""---
urgency: P1
Some incomplete line
---
Content here.
""")
            f.flush()
            path = Path(f.name)

        try:
            result = parse_workorder_frontmatter(path)
            assert result.get("urgency") == "P1"
            # Incomplete lines without ':' are skipped
        finally:
            path.unlink()

    def test_parse_list_values(self):
        """Parse list values in front-matter."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("""---
requires: [docker, git, python3]
platform: [linux, macos]
---
Task.
""")
            f.flush()
            path = Path(f.name)

        try:
            result = parse_workorder_frontmatter(path)
            assert result.get("requires") == ["docker", "git", "python3"]
            assert result.get("platform") == ["linux", "macos"]
        finally:
            path.unlink()

    def test_parse_missing_file(self):
        """Handle missing file gracefully."""
        nonexistent = Path("/tmp/nonexistent_file_12345.md")
        result = parse_workorder_frontmatter(nonexistent)
        assert result == {}


class TestGetTargetRepoRemote:
    """Tests for deriving git remote URLs based on target_repo."""

    @patch('subprocess.run')
    def test_get_irc_remote_from_csc_origin(self, mock_run):
        """Derive irc.git URL by replacing /csc.git with /irc.git."""
        # Mock git remote get-url origin -> returns csc.git origin
        mock_run.return_value = Mock(
            returncode=0,
            stdout="https://github.com/daveylongshaft/csc.git\n"
        )

        url = _get_target_repo_remote("csc")
        assert "/irc.git" in url
        assert "github.com/daveylongshaft" in url

    @patch('subprocess.run')
    def test_get_fahu_remote_from_csc_origin(self, mock_run):
        """Derive facingaddictionwithhope.git URL by replacing /csc.git."""
        # Mock git remote get-url origin -> returns csc.git origin
        mock_run.return_value = Mock(
            returncode=0,
            stdout="https://github.com/daveylongshaft/csc.git\n"
        )

        url = _get_target_repo_remote("fahu")
        assert "facingaddictionwithhope.git" in url
        assert "github.com/daveylongshaft" in url

    @patch('subprocess.run')
    def test_get_fahu_remote_fallback(self, mock_run):
        """Fall back to hardcoded fahu URL if git command fails."""
        # Mock git command failure
        mock_run.return_value = Mock(returncode=1, stdout="")

        url = _get_target_repo_remote("fahu")
        assert url == "https://github.com/daveylongshaft/facingaddictionwithhope.git"

    @patch('subprocess.run')
    def test_get_csc_remote_none_defaults_to_irc(self, mock_run):
        """Default to irc.git when target_repo is None."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="https://github.com/daveylongshaft/csc.git\n"
        )

        url = _get_target_repo_remote(None)
        assert "/irc.git" in url

    @patch('subprocess.run')
    def test_get_csc_remote_string_defaults_to_irc(self, mock_run):
        """Default to irc.git when target_repo is 'csc'."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="https://github.com/daveylongshaft/csc.git\n"
        )

        url = _get_target_repo_remote("csc")
        assert "/irc.git" in url


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
