```python
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock


class TestCLIDocumentationCompleteness:
    """Verify that all key CLI command categories are documented in README.md and CLAUDE.md."""

    @pytest.fixture
    def project_root(self, tmp_path):
        """Create a temporary project structure for testing."""
        root = tmp_path / "project"
        root.mkdir()
        return root

    @pytest.fixture
    def readme_path(self, project_root):
        """Create a README.md file."""
        readme = project_root / "README.md"
        return readme

    @pytest.fixture
    def claude_path(self, project_root):
        """Create a CLAUDE.md file."""
        claude = project_root / "CLAUDE.md"
        return claude

    def test_missing_readme(self, project_root, readme_path, claude_path):
        """Test that missing README.md is detected."""
        claude_path.write_text("# CLAUDE\ncsc-ctl\nworkorders\nagent\nAI", encoding="utf-8")
        
        assert not readme_path.exists(), "README.md should not exist"
        with pytest.raises(AssertionError, match="README.md is missing"):
            self._run_documentation_check(readme_path, claude_path)

    def test_missing_claude(self, project_root, readme_path, claude_path):
        """Test that missing CLAUDE.md is detected."""
        readme_path.write_text("# README\ncsc-ctl\nworkorders\nagent\nAI", encoding="utf-8")
        
        assert not claude_path.exists(), "CLAUDE.md should not exist"
        with pytest.raises(AssertionError, match="CLAUDE.md is missing"):
            self._run_documentation_check(readme_path, claude_path)

    def test_cli_documentation_completeness_success(self, project_root, readme_path, claude_path):
        """Verify that all key CLI command categories are documented."""
        # Create content with all required keywords and subcommands
        complete_content = """
# Documentation

## CLI Tools
- csc-ctl: Main control utility
- workorders: Task management system
- agent: Agent management
- AI: Artificial intelligence integration

### csc-ctl subcommands
- status: Get current status
- config: Manage configuration
- install: Install component
- remove: Remove component
- restart: Restart service
- cycle: Cycle service

### workorder/agent subcommands
- status: Check status
- list: List items
- add: Add new item
- assign: Assign item
- move: Move item between states
"""
        readme_path.write_text(complete_content, encoding="utf-8")
        claude_path.write_text(complete_content, encoding="utf-8")

        # Should not raise
        self._run_documentation_check(readme_path, claude_path)

    def test_missing_keyword_in_readme(self, project_root, readme_path, claude_path):
        """Test that missing keyword in README.md is detected."""
        readme_path.write_text("# README\nworkorders\nagent", encoding="utf-8")
        claude_path.write_text("# CLAUDE\ncsc-ctl\nworkorders\nagent\nAI", encoding="utf-8")

        with pytest.raises(AssertionError, match="Keyword 'csc-ctl' missing from README.md"):
            self._run_documentation_check(readme_path, claude_path)

    def test_missing_keyword_in_claude(self, project_root, readme_path, claude_path):
        """Test that missing keyword in CLAUDE.md is detected."""
        readme_path.write_text("# README\ncsc-ctl\nworkorders\nagent\nAI", encoding="utf-8")
        claude_path.write_text("# CLAUDE\nworkorders\nagent", encoding="utf-8")

        with pytest.raises(AssertionError, match="Keyword 'csc-ctl' missing from CLAUDE.md"):
            self._run_documentation_check(readme_path, claude_path)

    def test_missing_csc_ctl_subcommand_in_readme(self, project_root, readme_path, claude_path):
        """Test that missing csc-ctl subcommand in README.md is detected."""
        readme_path.write_text(
            "# README\ncsc-ctl\nworkorders\nagent\nAI\nstatus\nconfig\ninstall",
            encoding="utf-8"
        )
        claude_path.write_text(
            "# CLAUDE\ncsc-ctl\nworkorders\nagent\nAI\nstatus\nconfig\ninstall\nremove\nrestart\ncycle",
            encoding="utf-8"
        )

        with pytest.raises(AssertionError, match="csc-ctl subcommand 'remove' missing from README.md"):
            self._run_documentation_check(readme_path, claude_path)

    def test_missing_csc_ctl_subcommand_in_claude(self, project_root, readme_path, claude_path):
        """Test that missing csc-ctl subcommand in CLAUDE.md is detected."""
        readme_path.write_text(
            "# README\ncsc-ctl\nworkorders\nagent\nAI\nstatus\nconfig\ninstall\nremove\nrestart\ncycle",
            encoding="utf-8"
        )
        claude_path.write_text(
            "# CLAUDE\ncsc-ctl\nworkorders\nagent\nAI\nstatus\nconfig\ninstall",
            encoding="utf-8"
        )

        with pytest.raises(AssertionError, match="csc-ctl subcommand 'remove' missing from CLAUDE.md"):
            self._run_documentation_check(readme_path, claude_path)

    def test_missing_workorder_subcommand_in_readme(self, project_root, readme_path, claude_path):
        """Test that missing workorder subcommand in README.md is detected."""
        readme_path.write_text(
            "# README\ncsc-ctl\nworkorders\nagent\nAI\nstatus\nconfig\ninstall\nremove\nrestart\ncycle\nlist\nadd",
            encoding="utf-8"
        )
        claude_path.write_text(
            "# CLAUDE\ncsc-ctl\nworkorders\nagent\nAI\nstatus\nconfig\ninstall\nremove\nrestart\ncycle\nstatus\nlist\nadd\nassign\nmove",
            encoding="utf-8"
        )

        with pytest.raises(AssertionError, match="workorder subcommand 'assign' missing from README.md"):
            self._run_documentation_check(readme_path, claude_path)

    def test_missing_workorder_subcommand_in_claude(self, project_root, readme_path, claude_path):
        """Test that missing workorder subcommand in CLAUDE.md is detected."""
        readme_path.write_text(
            "# README\ncsc-ctl\nworkorders\nagent\nAI\nstatus\nconfig\ninstall\nremove\nrestart\ncycle\nstatus\nlist\nadd\nassign\nmove",
            encoding="utf-8"
        )
        claude_path.write_text(
            "# CLAUDE\ncsc-ctl\nworkorders\nagent\nAI\nstatus\nconfig\ninstall\nremove\nrestart\ncycle\nlist\nadd",
            encoding="utf-8"
        )

        with pytest.raises(AssertionError, match="workorder subcommand 'assign' missing from CLAUDE.md"):
            self._run_documentation_check(readme_path, claude_path)

    def test_case_sensitive_keyword_matching(self, project_root, readme_path, claude_path):
        """Test that keyword matching is case-sensitive."""
        readme_path.write_text("# README\nCSC-CTL\nworkorders\nagent\nAI", encoding="utf-8")
        claude_path.write_text("# CLAUDE\ncsc-ctl\nworkorders\nagent\nAI", encoding="utf-8")

        with pytest.raises(AssertionError, match="Keyword 'csc-ctl' missing from README.md"):
            self._run_documentation_check(readme_path, claude_path)

    def test_all_required_keywords(self, project_root, readme_path, claude_path):
        """Test that all required keywords are checked."""
        required_keywords = ["csc-ctl", "workorders", "agent", "AI"]
        content = "\n".join(required_keywords)
        
        readme_path.write_text(content, encoding="utf-8")
        claude_path.write_text(content, encoding="utf-8")

        # Should not raise for keywords
        readme_content = readme_path.read_text(encoding="utf-8")
        claude_content = claude_path.read_text(encoding="utf-8")

        for kw in required_keywords:
            assert kw in readme_content
            assert kw in claude_content

    def test_all_csc_ctl_subcommands(self, project_root, readme_path, claude_path):
        """Test that all csc-ctl subcommands are checked."""
        csc_ctl_subcommands = ["status", "config", "install", "remove", "restart", "cycle"]
        content = "csc-ctl\nworkorders\nagent\nAI\n" + "\n".join(csc_ctl_subcommands)
        
        readme_path.write_text(content, encoding="utf-8")
        claude_path.write_text(content, encoding="utf-8")

        readme_content = readme_path.read_text(encoding="utf-8")
        for sub in csc_ctl_subcommands:
            assert sub in readme_content

    def test_all_workorder_subcommands(self, project_root, readme_path, claude_path):
        """Test that all workorder subcommands are checked."""
        wo_subcommands = ["status", "list", "add", "assign", "move"]
        content = "csc-ctl\nworkorders\nagent\nAI\nstatus\nconfig\ninstall\nremove\nrestart\ncycle\n" + "\n".join(wo_subcommands)
        
        readme_path.write_text(content, encoding="utf-8")
        claude_path.write_text(content, encoding="utf-8")

        readme_content = readme_path.read_text(encoding="utf-8")
        for sub in wo_subcommands:
            assert sub in readme_content

    @staticmethod
    def _run_documentation_check(readme_path, claude_path):
        """Run the documentation completeness check."""
        assert readme_path.exists(), "README.md is missing"
        assert claude_path.exists(), "CLAUDE.md is missing"

        readme_content = readme_path.read_text(encoding="utf-8")
        claude_content = claude_path.read_text(encoding="utf-8")

        # Required categories
        required_keywords = [
            "csc-ctl",
            "workorders",
            "agent",
            "AI"
        ]

        for kw in required_keywords:
            assert kw in readme_content, f"Keyword '{kw}' missing from README.md"
            assert kw in claude_content, f"Keyword '{kw}' missing from CLAUDE.md"

        # Specific subcommands for csc-ctl
        csc_ctl_subcommands = ["status", "config", "install", "remove", "restart", "cycle"]
        for sub in csc_ctl_subcommands:
            assert sub in readme_content, f"csc-ctl subcommand '{sub}' missing from README.md"
            assert sub in claude_content, f"csc-ctl subcommand '{sub}' missing from CLAUDE.md"

        # Specific subcommands for workorders/agent
        wo_subcommands = ["status", "list", "add", "assign", "move"]
        for sub in wo_subcommands:
            assert sub in readme_content, f"workorder subcommand '{sub}' missing from README.md"
            assert sub in claude_content, f"workorder subcommand '{sub}' missing from CLAUDE.md"
```