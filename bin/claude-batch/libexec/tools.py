"""Tool implementations for batch API execution."""

import os
import json
import subprocess
from pathlib import Path


def read_file(path: str) -> str:
    """Read file contents."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return f"ERROR: File not found: {path}"
        return p.read_text(encoding='utf-8')
    except Exception as e:
        return f"ERROR reading {path}: {e}"


def write_file(path: str, content: str) -> str:
    """Write/overwrite file."""
    try:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8')
        return f"OK: Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"ERROR writing {path}: {e}"


def delete_file(path: str) -> str:
    """Delete a file."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return f"ERROR: File not found: {path}"
        p.unlink()
        return f"OK: Deleted {path}"
    except Exception as e:
        return f"ERROR deleting {path}: {e}"


def run_command(command: str, cwd: str = None) -> str:
    """Execute shell command."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=300
        )
        output = result.stdout
        if result.stderr:
            output += "\nSTDERR:\n" + result.stderr
        if result.returncode != 0:
            output += f"\nExit code: {result.returncode}"
        return output if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: Command timeout (300s)"
    except Exception as e:
        return f"ERROR running command: {e}"


def list_directory(path: str) -> str:
    """List directory contents."""
    try:
        p = Path(path).resolve()
        if not p.is_dir():
            return f"ERROR: Not a directory: {path}"
        items = sorted(p.iterdir())
        lines = [f"{i.name}{'/' if i.is_dir() else ''}" for i in items]
        return "\n".join(lines) if lines else "(empty directory)"
    except Exception as e:
        return f"ERROR listing {path}: {e}"


def glob_files(pattern: str, base: str = None) -> str:
    """Glob file pattern."""
    try:
        base_path = Path(base or ".").resolve()
        results = list(base_path.glob(pattern))
        lines = [str(p.relative_to(base_path)) for p in sorted(results)]
        return "\n".join(lines) if lines else "(no matches)"
    except Exception as e:
        return f"ERROR in glob: {e}"


def search_files(pattern: str, path: str = None, file_glob: str = "*.py") -> str:
    """Search file contents with regex."""
    try:
        import re
        base_path = Path(path or ".").resolve()
        regex = re.compile(pattern)
        results = []

        for fpath in base_path.glob(f"**/{file_glob}"):
            try:
                content = fpath.read_text(encoding='utf-8', errors='ignore')
                for i, line in enumerate(content.split('\n'), 1):
                    if regex.search(line):
                        rel_path = fpath.relative_to(base_path)
                        results.append(f"{rel_path}:{i}: {line[:100]}")
            except:
                pass

        return "\n".join(results[:100]) if results else "(no matches)"
    except Exception as e:
        return f"ERROR searching: {e}"


def execute_tool(name: str, args: dict) -> str:
    """Execute a tool by name."""
    if name == "read_file":
        return read_file(args.get("path", ""))
    elif name == "write_file":
        return write_file(args.get("path", ""), args.get("content", ""))
    elif name == "delete_file":
        return delete_file(args.get("path", ""))
    elif name == "run_command":
        return run_command(args.get("command", ""), args.get("cwd"))
    elif name == "list_directory":
        return list_directory(args.get("path", ""))
    elif name == "glob_files":
        return glob_files(args.get("pattern", ""), args.get("base"))
    elif name == "search_files":
        return search_files(
            args.get("pattern", ""),
            args.get("path"),
            args.get("file_glob", "*.py")
        )
    else:
        return f"ERROR: Unknown tool: {name}"


TOOL_DEFINITIONS = [
    {
        "name": "read_file",
        "description": "Read file contents. Use absolute paths.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute path"}},
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write/overwrite file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path"},
                "content": {"type": "string", "description": "File content"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "delete_file",
        "description": "Delete a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute path"}},
            "required": ["path"]
        }
    },
    {
        "name": "run_command",
        "description": "Run shell command.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command"},
                "cwd": {"type": "string", "description": "Working directory (default: current)"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "list_directory",
        "description": "List directory contents.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory path"}},
            "required": ["path"]
        }
    },
    {
        "name": "glob_files",
        "description": "Find files by glob pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. **/*.py)"},
                "base": {"type": "string", "description": "Base directory (default: .)"}
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "search_files",
        "description": "Search file contents with regex.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern"},
                "path": {"type": "string", "description": "Base directory"},
                "file_glob": {"type": "string", "description": "File glob (e.g. *.py)"}
            },
            "required": ["pattern"]
        }
    }
]
