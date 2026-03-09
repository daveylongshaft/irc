```python
"""Tests for capability-tagged prompt parsing and matching."""

import pytest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
import tempfile
import os

# Mock the module path setup that would normally happen
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from csc_shared.services.agent_service import agent as AgentService


class TestFrontMatterParsing:
    """Test YAML front-matter parsing from prompt files."""

    def test_no_front_matter(self, tmp_path):
        """File without front-matter returns empty dict."""
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("# Just a prompt\nDo something.")
        tags = AgentService._parse_front_matter(str(prompt_file))
        assert tags == {}

    def test_basic_front_matter(self, tmp_path):
        """Parse basic front-matter with requires list."""
        prompt_file = tmp_path / "prompt.md"
        content = "---\nrequires: [docker, git, python3]\n---\n# Prompt content\n"
        prompt_file.write_text(content)
        tags = AgentService._parse_front_matter(str(prompt_file))
        assert tags["requires"] == ["docker", "git", "python3"]

    def test_platform_tag(self, tmp_path):
        """Parse platform tag."""
        prompt_file = tmp_path / "prompt.md"
        content = "---\nplatform: [linux]\n---\nContent.\n"
        prompt_file.write_text(content)
        tags = AgentService._parse_front_matter(str(prompt_file))
        assert tags["platform"] == ["linux"]

    def test_min_ram_tag(self, tmp_path):
        """Parse min_ram tag."""
        prompt_file = tmp_path / "prompt.md"
        content = "---\nmin_ram: 2GB\n---\nContent.\n"
        prompt_file.write_text(content)
        tags = AgentService._parse_front_matter(str(prompt_file))
        assert tags["min_ram"] == "2GB"

    def test_multiple_tags(self, tmp_path):
        """Parse multiple tags at once."""
        prompt_file = tmp_path / "prompt.md"
        content = (
            "---\nrequires: [docker, git]\n"
            "platform: [linux, windows]\n"
            "min_ram: 4GB\n---\nContent.\n"
        )
        prompt_file.write_text(content)
        tags = AgentService._parse_front_matter(str(prompt_file))
        assert tags["requires"] == ["docker", "git"]
        assert tags["platform"] == ["linux", "windows"]
        assert tags["min_ram"] == "4GB"

    def test_single_value_requires(self, tmp_path):
        """Single value without brackets."""
        prompt_file = tmp_path / "prompt.md"
        content = "---\nrequires: git\n---\nContent.\n"
        prompt_file.write_text(content)
        tags = AgentService._parse_front_matter(str(prompt_file))
        assert tags["requires"] == "git"

    def test_missing_closing_delimiter(self, tmp_path):
        """No closing --- returns empty dict."""
        prompt_file = tmp_path / "prompt.md"
        content = "---\nrequires: [docker]\n# No closing delimiter\n"
        prompt_file.write_text(content)
        tags = AgentService._parse_front_matter(str(prompt_file))
        assert tags == {}

    def test_empty_front_matter(self, tmp_path):
        """Empty front-matter returns empty dict."""
        prompt_file = tmp_path / "prompt.md"
        content = "---\n---\nContent.\n"
        prompt_file.write_text(content)
        tags = AgentService._parse_front_matter(str(prompt_file))
        assert tags == {}

    def test_comments_in_front_matter(self, tmp_path):
        """Comments are ignored."""
        prompt_file = tmp_path / "prompt.md"
        content = "---\n# This is a comment\nrequires: [git]\n---\nContent.\n"
        prompt_file.write_text(content)
        tags = AgentService._parse_front_matter(str(prompt_file))
        assert tags["requires"] == ["git"]

    def test_nonexistent_file(self):
        """Nonexistent file returns empty dict."""
        tags = AgentService._parse_front_matter("/nonexistent/path/prompt_xyz.md")
        assert tags == {}

    def test_malformed_yaml(self, tmp_path):
        """Malformed YAML in front-matter returns empty dict."""
        prompt_file = tmp_path / "prompt.md"
        content = "---\nrequires: [docker\n---\nContent.\n"
        prompt_file.write_text(content)
        tags = AgentService._parse_front_matter(str(prompt_file))
        assert tags == {}


class TestCapabilityChecking:
    """Test capability checking against platform data."""

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")
    def test_no_tags_always_passes(self, mock_load, tmp_path):
        """Prompt without tags should always be assignable."""
        mock_load.return_value = {}
        svc = AgentService.__new__(AgentService)
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("# Simple prompt\nDo this.")
        can_run, reasons, tags = svc._check_prompt_capabilities(str(prompt_file))
        assert can_run is True
        assert reasons == []
        assert tags == {}

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")
    def test_requires_satisfied(self, mock_load, tmp_path):
        """Prompt requiring installed tool should pass."""
        mock_load.return_value = {
            "software": {"git": {"installed": True, "version": "git 2.x"}},
            "ai_agents": {},
        }
        svc = AgentService.__new__(AgentService)
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("---\nrequires: [git]\n---\nContent.\n")
        can_run, reasons, tags = svc._check_prompt_capabilities(str(prompt_file))
        assert can_run is True
        assert reasons == []

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")
    def test_requires_missing_tool(self, mock_load, tmp_path):
        """Prompt requiring missing tool should fail."""
        mock_load.return_value = {
            "software": {"git": {"installed": False}},
            "ai_agents": {},
        }
        svc = AgentService.__new__(AgentService)
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("---\nrequires: [git]\n---\nContent.\n")
        can_run, reasons, tags = svc._check_prompt_capabilities(str(prompt_file))
        assert can_run is False
        assert any("git" in reason for reason in reasons)

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")
    def test_requires_multiple_tools_partial_missing(self, mock_load, tmp_path):
        """Some required tools missing should fail."""
        mock_load.return_value = {
            "software": {
                "git": {"installed": True},
                "docker": {"installed": False},
            },
            "ai_agents": {},
        }
        svc = AgentService.__new__(AgentService)
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("---\nrequires: [git, docker]\n---\nContent.\n")
        can_run, reasons, tags = svc._check_prompt_capabilities(str(prompt_file))
        assert can_run is False
        assert any("docker" in reason for reason in reasons)

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")
    def test_platform_matching_linux(self, mock_load, tmp_path):
        """Prompt specifying linux platform on linux system."""
        mock_load.return_value = {
            "platform": {"os": "linux"},
            "software": {},
            "ai_agents": {},
        }
        svc = AgentService.__new__(AgentService)
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("---\nplatform: [linux]\n---\nContent.\n")
        can_run, reasons, tags = svc._check_prompt_capabilities(str(prompt_file))
        assert can_run is True

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")
    def test_platform_mismatch(self, mock_load, tmp_path):
        """Prompt requiring windows on linux system should fail."""
        mock_load.return_value = {
            "platform": {"os": "linux"},
            "software": {},
            "ai_agents": {},
        }
        svc = AgentService.__new__(AgentService)
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("---\nplatform: [windows]\n---\nContent.\n")
        can_run, reasons, tags = svc._check_prompt_capabilities(str(prompt_file))
        assert can_run is False
        assert any("platform" in reason.lower() for reason in reasons)

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")
    def test_min_ram_sufficient(self, mock_load, tmp_path):
        """System with sufficient RAM should pass."""
        mock_load.return_value = {
            "hardware": {"memory_gb": 8},
            "software": {},
            "ai_agents": {},
        }
        svc = AgentService.__new__(AgentService)
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("---\nmin_ram: 4GB\n---\nContent.\n")
        can_run, reasons, tags = svc._check_prompt_capabilities(str(prompt_file))
        assert can_run is True

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")
    def test_min_ram_insufficient(self, mock_load, tmp_path):
        """System with insufficient RAM should fail."""
        mock_load.return_value = {
            "hardware": {"memory_gb": 2},
            "software": {},
            "ai_agents": {},
        }
        svc = AgentService.__new__(AgentService)
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("---\nmin_ram: 4GB\n---\nContent.\n")
        can_run, reasons, tags = svc._check_prompt_capabilities(str(prompt_file))
        assert can_run is False
        assert any("ram" in reason.lower() or "memory" in reason.lower() for reason in reasons)

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")
    def test_combined_checks_all_pass(self, mock_load, tmp_path):
        """All capability checks pass together."""
        mock_load.return_value = {
            "platform": {"os": "linux"},
            "hardware": {"memory_gb": 8},
            "software": {
                "git": {"installed": True},
                "docker": {"installed": True},
            },
            "ai_agents": {},
        }
        svc = AgentService.__new__(AgentService)
        prompt_file = tmp_path / "prompt.md"
        content = (
            "---\nplatform: [linux]\n"
            "requires: [git, docker]\n"
            "min_ram: 4GB\n---\nContent.\n"
        )
        prompt_file.write_text(content)
        can_run, reasons, tags = svc._check_prompt_capabilities(str(prompt_file))
        assert can_run is True
        assert reasons == []

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")
    def test_combined_checks_some_fail(self, mock_load, tmp_path):
        """Multiple capability checks with some failures."""
        mock_load.return_value = {
            "platform": {"os": "linux"},
            "hardware": {"memory_gb": 2},
            "software": {
                "git": {"installed": True},
                "docker": {"installed": False},
            },
            "ai_agents": {},
        }
        svc = AgentService.__new__(AgentService)
        prompt_file = tmp_path / "prompt.md"
        content = (
            "---\nplatform: [linux]\n"
            "requires: [git, docker]\n"
            "min_ram: 4GB\n---\nContent.\n"
        )
        prompt_file.write_text(content)
        can_run, reasons, tags = svc._check_prompt_capabilities(str(prompt_file))
        assert can_run is False
        assert len(reasons) > 0

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")
    def test_tags_returned_on_success(self, mock_load, tmp_path):
        """Tags should be returned even on success."""
        mock_load.return_value = {
            "platform": {"os": "linux"},
            "software": {"git": {"installed": True}},
            "ai_agents": {},
        }
        svc = AgentService.__new__(AgentService)
        prompt_file = tmp_path / "prompt.md"
        content = "---\nrequires: [git]\nplatform: [linux]\n---\nContent.\n"
        prompt_file.write_text(content)
        can_run, reasons, tags = svc._check_prompt_capabilities(str(prompt_file))
        assert can_run is True
        assert "requires" in tags
        assert "platform" in tags

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")
    def test_tags_returned_on_failure(self, mock_load, tmp_path):
        """Tags should be returned even on failure."""
        mock_load.return_value = {
            "platform": {"os": "windows"},
            "software": {},
            "ai_agents": {},
        }
        svc = AgentService.__new__(AgentService)
        prompt_file = tmp_path / "prompt.md"
        content = "---\nplatform: [linux]\n---\nContent.\n"
        prompt_file.write_text(content)
        can_run, reasons, tags = svc._check_prompt_capabilities(str(prompt_file))
        assert can_run is False
        assert "platform" in tags
        assert tags["platform"] == ["linux"]


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")
    def test_missing_platform_data(self, mock_load, tmp_path):
        """Handle missing platform data gracefully."""
        mock_load.return_value = {}
        svc = AgentService.__new__(AgentService)
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("---\nplatform: [linux]\n---\nContent.\n")
        can_run, reasons, tags = svc._check_prompt_capabilities(str(prompt_file))
        # Should handle gracefully, may fail or pass depending on implementation
        assert isinstance(can_run, bool)

    @patch("csc_shared.services.agent_service.Platform.load_platform_json")