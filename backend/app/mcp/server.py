"""
ScholarPilot MCP Server

Exposes ScholarPilot capabilities as MCP (Model Context Protocol) tools,
allowing Claude Code and other AI tools to directly invoke academic search.

Run standalone: python -m app.mcp.server
Or via Docker with the 'mcp' profile.

Transport: stdio (default) for local use, or HTTP+SSE for remote.
"""
import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# MCP protocol constants
JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"

# Tool definitions exposed to MCP clients
TOOLS = [
    {
        "name": "scholarly_search",
        "description": "Search academic databases (OpenAlex, arXiv, Crossref, EPO, etc.) for research papers and patents. Returns scored and deduplicated results.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (English or Chinese)"},
                "max_results": {"type": "integer", "description": "Maximum results to return", "default": 10},
                "year_from": {"type": "integer", "description": "Earliest publication year"},
                "year_to": {"type": "integer", "description": "Latest publication year"},
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific data sources to search (e.g. openalex, arxiv, crossref). Leave empty for all available.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_research_profile",
        "description": "Get a user's research profile including preferred keywords, excluded keywords, and source preferences.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "User UUID"},
                "project_id": {"type": "string", "description": "Project UUID"},
            },
            "required": ["user_id", "project_id"],
        },
    },
    {
        "name": "list_projects",
        "description": "List all research projects for a user.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "User UUID"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "get_tool_stats",
        "description": "Get runtime statistics for all registered data source tools (latency, reliability, invocation count).",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


async def handle_tool_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute an MCP tool call and return the result."""

    if name == "scholarly_search":
        return await _scholarly_search(arguments)
    elif name == "get_research_profile":
        return await _get_research_profile(arguments)
    elif name == "list_projects":
        return await _list_projects(arguments)
    elif name == "get_tool_stats":
        return await _get_tool_stats()
    else:
        return {"error": f"Unknown tool: {name}"}


async def _scholarly_search(args: Dict) -> Dict:
    """Execute a search using the harness tool registry."""
    from app.services.fetchers.international import ALL_FETCHERS
    from app.services.fetchers.base import FetcherRegistry
    from app.services.relevance_engine import deduplicate_docs

    query = args["query"]
    max_results = args.get("max_results", 10)
    year_from = args.get("year_from")
    year_to = args.get("year_to")
    sources = args.get("sources") or list(ALL_FETCHERS.keys())

    tasks = []
    for src_id in sources:
        fetcher = ALL_FETCHERS.get(src_id)
        if fetcher:
            tasks.append(fetcher.safe_fetch(
                query=query,
                max_results=max_results,
                year_from=year_from,
                year_to=year_to,
            ))

    if not tasks:
        return {"results": [], "total": 0}

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_docs = []
    for result in results:
        if isinstance(result, tuple):
            _, docs = result
            all_docs.extend(docs)

    all_docs = deduplicate_docs(all_docs)

    # Return top N by citation count (simple ranking for MCP)
    all_docs.sort(key=lambda d: d.get("citation_count", 0), reverse=True)
    top = all_docs[:max_results]

    return {
        "results": [
            {
                "title": d.get("title"),
                "authors": d.get("authors"),
                "source": d.get("source"),
                "year": str(d.get("publication_date", ""))[:4],
                "doi": d.get("doi"),
                "abstract": (d.get("abstract") or "")[:300],
                "url": d.get("url"),
                "citation_count": d.get("citation_count", 0),
            }
            for d in top
        ],
        "total_found": len(all_docs),
    }


async def _get_research_profile(args: Dict) -> Dict:
    """Get user research profile."""
    import uuid
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.config import settings
    from app.services.profile_service import get_or_create_profile

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            profile = await get_or_create_profile(
                uuid.UUID(args["user_id"]),
                uuid.UUID(args["project_id"]),
                db,
            )
            return {
                "preferred_keywords": profile.preferred_keywords or [],
                "excluded_keywords": profile.excluded_keywords or [],
                "preferred_sources": profile.preferred_sources or [],
                "preferred_doc_types": profile.preferred_doc_types or [],
            }
    finally:
        await engine.dispose()


async def _list_projects(args: Dict) -> Dict:
    """List user projects."""
    import uuid
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.project import Project

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            result = await db.execute(
                select(Project).where(Project.user_id == uuid.UUID(args["user_id"]))
            )
            projects = result.scalars().all()
            return {
                "projects": [
                    {
                        "id": str(p.id),
                        "title": p.title,
                        "status": p.status,
                        "current_round": p.current_round,
                        "created_at": str(p.created_at),
                    }
                    for p in projects
                ],
            }
    finally:
        await engine.dispose()


async def _get_tool_stats() -> Dict:
    """Get tool registry statistics."""
    from app.harness.tool_registry import ToolRegistry
    registry = ToolRegistry.get_instance()
    if registry.tool_count == 0:
        from app.harness.tool_registry import init_tool_registry
        init_tool_registry()
        registry = ToolRegistry.get_instance()
    return {
        "tools": registry.get_all_stats(),
        "reliability": registry.get_reliability_report(),
    }


# --- stdio transport (for local Claude Code integration) ---

async def run_stdio_server():
    """Run MCP server over stdio transport."""
    logger.info("[MCP] ScholarPilot MCP server starting (stdio)")

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)

    writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout.buffer
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, asyncio.get_event_loop())

    async def send_response(response: Dict):
        data = json.dumps(response)
        message = f"Content-Length: {len(data)}\r\n\r\n{data}"
        writer.write(message.encode())
        await writer.drain()

    while True:
        try:
            # Read Content-Length header
            header = await reader.readline()
            if not header:
                break
            if header.startswith(b"Content-Length:"):
                length = int(header.split(b":")[1].strip())
                await reader.readline()  # empty line
                data = await reader.readexactly(length)
                request = json.loads(data)
                response = await handle_request(request)
                await send_response(response)
        except (asyncio.IncompleteReadError, ConnectionError):
            break
        except Exception as e:
            logger.error("[MCP] Error: %s", e)


async def handle_request(request: Dict) -> Dict:
    """Handle a single JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": req_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "scholarpilot",
                    "version": "1.0.0",
                },
            },
        }
    elif method == "tools/list":
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": req_id,
            "result": {"tools": TOOLS},
        }
    elif method == "tools/call":
        params = request.get("params", {})
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        result = await handle_tool_call(name, arguments)
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
            },
        }
    elif method == "notifications/initialized":
        return {}  # No response needed for notifications
    else:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_stdio_server())
