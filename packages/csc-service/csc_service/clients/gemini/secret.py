"""
Gemini API secret management and credential handling.

Handles API key loading, operational credentials, and system context.
"""

import os
import json
from pathlib import Path


def get_gemini_api_key() -> str:
    """Get Gemini API key from environment or config.

    Returns:
        str: Gemini API key

    Raises:
        ValueError: If API key not found
    """
    # Try environment variable first
    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        return api_key

    # Try config file
    config_path = Path.home() / ".config" / "csc-gemini" / "secrets.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
                api_key = config.get("api_key")
                if api_key:
                    return api_key
        except Exception:
            pass

    raise ValueError("Gemini API key not found in GOOGLE_API_KEY or ~/.config/csc-gemini/secrets.json")


def get_gemini_oper_credentials() -> dict:
    """Get Gemini operator credentials for IRC authentication.

    Returns:
        dict: Operator credentials with keys: username, password, roles
    """
    # Load from config if available
    config_path = Path.home() / ".config" / "csc-gemini" / "secrets.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
                creds = config.get("oper_credentials", {})
                if creds:
                    return creds
        except Exception:
            pass

    # Default credentials (can be overridden)
    return {
        "username": "gemini",
        "password": os.environ.get("GEMINI_OPER_PASSWORD", ""),
        "roles": ["oper", "ai"]
    }


def load_initial_core_file_context() -> str:
    """Load initial core context files for Gemini system instructions.

    Reads critical project files to provide Gemini with understanding of:
    - Project architecture (.irc_root)
    - Code structure (tools/INDEX.txt, tree.txt)
    - Current state (platform.json, pm_state.json)

    Returns:
        str: Concatenated context from core files
    """
    context_parts = []
   .irc_root = Path(os.environ.get("CSC_ROOT", "/c/csc"))

    # Load .irc_root (project instructions)
    claude_md =.irc_root / ".irc_root"
    if claude_md.exists():
        try:
            context_parts.append(f"=== PROJECT INSTRUCTIONS (.irc_root) ===\n{claude_md.read_text()}")
        except Exception:
            pass

    # Load code map
    code_map =.irc_root / "tools" / "INDEX.txt"
    if code_map.exists():
        try:
            context_parts.append(f"=== CODE MAP (tools/INDEX.txt) ===\n{code_map.read_text()}")
        except Exception:
            pass

    # Load directory tree
    tree =.irc_root / "tree.txt"
    if tree.exists():
        try:
            context_parts.append(f"=== DIRECTORY TREE ===\n{tree.read_text()[:5000]}")  # First 5000 chars
        except Exception:
            pass

    # Load platform inventory
    platform_json =.irc_root / "platform.json"
    if platform_json.exists():
        try:
            context_parts.append(f"=== PLATFORM INVENTORY ===\n{platform_json.read_text()}")
        except Exception:
            pass

    return "\n\n".join(context_parts)


def get_system_instructions() -> str:
    """Get Gemini system instructions and role definition.

    Returns:
        str: System instructions for Gemini model
    """
    return """You are Gemini, an AI agent in the CSC (Client-Server-Commander) autonomous system.

## Your Role

You are a coding agent in a distributed multi-AI orchestration system. You receive work via IRC messages and execute tasks autonomously.

## Instructions

1. **Work Receipt**: Tasks arrive as IRC PRIVMSG to your channel
2. **Work Execution**: Read the workorder/prompt, understand requirements
3. **Tool Use**: You have access to file reading, writing, bash commands
4. **Journaling**: Use `echo >>` to append progress to WIP file (CRITICAL for crash recovery)
5. **Completion**: Write "COMPLETE" as last line when done
6. **Commits**: Make git commits with clear messages describing changes

## Key Principles

- **Autonomy**: Make decisions without human intervention
- **Crash Recovery**: Journal every step - next agent reads WIP and resumes
- **Code Quality**: Follow project patterns in .irc_root
- **Testing**: Don't run tests manually - test runner handles it
- **Commits**: One per logical change, clear messages

## Available Models

You have access to the full CSC architecture:
- IRC Server (UDP port 9525)
- Bridge Proxy (encrypted tunneling)
- Queue-Worker (task assignment)
- PM Agent (orchestration)
- Test Runner (automated validation)
- Shared Library (IRC protocol, platform detection)

## Communication

Send messages to IRC channels you've joined. Queue-worker monitors WIP files for "COMPLETE" marker to know when you're done.

Good luck! The system needs you. 🤖
"""
