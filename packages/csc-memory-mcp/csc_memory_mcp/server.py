"""CSC Memory MCP server -- exposes memory_list, memory_read, memory_write, memory_search."""

import json
import logging
import os
import sys
from pathlib import Path

# Allow running as `python -m csc_memory_mcp.server` from C:/csc/irc
_here = Path(__file__).resolve()
for _pkg_dir in ["csc-memory"]:
    _candidate = _here.parents[2] / "packages" / _pkg_dir
    if _candidate.exists() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

import mcp.server.stdio
from mcp import types
from mcp.server import Server

from .client import memory_client

log = logging.getLogger("csc_memory_mcp.server")
_client = None


def _get_client():
    global _client
    if _client is None:
        cfg_path = _find_csc_service_json()
        cfg = {}
        if cfg_path:
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        mem = cfg.get("memory", {})
        host = mem.get("host", "127.0.0.1")
        port = int(mem.get("port", 9532))
        scheme = "https" if cfg.get("s2s_cert") else "http"
        base_url = f"{scheme}://{host}:{port}"
        cache_path = _find_cache_path()

        _client = memory_client(
            base_url=base_url,
            cert=cfg.get("s2s_cert", ""),
            key=cfg.get("s2s_key", ""),
            ca=cfg.get("s2s_ca", ""),
            cache_path=cache_path,
        )
    return _client


def _find_csc_service_json():
    candidates = []
    for env_var in ("CSC_ETC", "CSC_ROOT"):
        val = os.environ.get(env_var, "")
        if val:
            candidates.append(Path(val) / "etc" / "csc-service.json")
            candidates.append(Path(val) / "csc-service.json")
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / "etc" / "csc-service.json")
        candidates.append(parent / "csc-service.json")
        if (parent / ".irc_root").exists():
            break
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_cache_path():
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "docs" / "memory").exists():
            return parent / "docs" / "memory" / "remote_cache.md"
        if (parent / ".irc_root").exists():
            return parent / "docs" / "memory" / "remote_cache.md"
    return Path.home() / "docs" / "memory" / "remote_cache.md"


# ---------------------------------------------------------------------------
# Build MCP server
# ---------------------------------------------------------------------------

server = Server("csc-memory")


@server.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="memory_list",
            description="List remote memory entries. Filter by type, status, or tag. Uses local 1hr cache.",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "description": "Filter by type: user, feedback, environment, workflow, task, topic, reference",
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by status: reference, active, stashed, blocked, done",
                    },
                    "tag": {
                        "type": "string",
                        "description": "Filter by tag (requires server fetch)",
                    },
                },
            },
        ),
        types.Tool(
            name="memory_read",
            description="Read a single remote memory entry by slug (full body, fetched from server).",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "The entry slug"},
                },
                "required": ["slug"],
            },
        ),
        types.Tool(
            name="memory_write",
            description="Create or update a remote memory entry. Patches local cache on success.",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Unique identifier (kebab-case)"},
                    "name": {"type": "string", "description": "Human-readable title"},
                    "description": {"type": "string", "description": "One-line summary for the index"},
                    "type": {
                        "type": "string",
                        "description": "user | feedback | environment | workflow | task | topic | reference",
                    },
                    "body": {"type": "string", "description": "Full markdown body of the entry"},
                    "status": {
                        "type": "string",
                        "description": "reference | active | stashed | blocked | done",
                        "default": "reference",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tag strings",
                    },
                    "related": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of related entry slugs",
                    },
                },
                "required": ["slug", "name", "description", "type", "body"],
            },
        ),
        types.Tool(
            name="memory_search",
            description="Search remote memory index by substring. Matches slug, description, type. No network call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Substring to search for"},
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    client = _get_client()

    if name == "memory_list":
        entries = client.list_entries(
            type=arguments.get("type"),
            status=arguments.get("status"),
            tag=arguments.get("tag"),
        )
        return [types.TextContent(type="text", text=json.dumps(entries, indent=2))]

    if name == "memory_read":
        slug = arguments.get("slug", "")
        entry = client.read_entry(slug)
        if entry is None:
            return [types.TextContent(type="text", text=f"error: entry '{slug}' not found or server unreachable")]
        return [types.TextContent(type="text", text=json.dumps(entry, indent=2))]

    if name == "memory_write":
        result = client.write_entry(
            slug=arguments["slug"],
            name=arguments["name"],
            description=arguments["description"],
            entry_type=arguments["type"],
            body=arguments["body"],
            status=arguments.get("status", "reference"),
            tags=arguments.get("tags"),
            related=arguments.get("related"),
        )
        if isinstance(result, str) and result.startswith("error:"):
            return [types.TextContent(type="text", text=result)]
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "memory_search":
        query = arguments.get("query", "")
        entries = client.search(query)
        return [types.TextContent(type="text", text=json.dumps(entries, indent=2))]

    return [types.TextContent(type="text", text=f"error: unknown tool '{name}'")]


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def _run():
    client = _get_client()
    # Warm the cache synchronously at startup; errors are swallowed inside get_cache()
    try:
        client.get_cache()
    except Exception as exc:
        log.debug("startup cache warm failed: %s", exc)
    client.start_background_refresh_loop()

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    import asyncio
    asyncio.run(_run())


if __name__ == "__main__":
    main()
