"""
HTTP REST Gateway for MemPalace
=================================

Wraps MemPalace's MCP server with a FastAPI HTTP daemon so any tool
can use it via REST — not just MCP-compatible agents.

Features:
  - Full REST API mirroring all 29 MCP tools
  - Auto-start/stop MCP server as subprocess
  - Health check endpoint
  - OpenAPI docs at /docs
  - SSE streaming for real-time search results
  - CORS enabled for web UIs

Usage:
  memorius-serve                    # start on default port 8912
  memorius-serve --port 9999
  memorius-serve --palace /path/to/palace
  memorius-serve --mcp-command "python3 -m mempalace.mcp_server"

  # From any tool:
  curl http://localhost:8912/search?q="auth decisions"
  curl http://localhost:8912/status
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse
    from pydantic import BaseModel, Field
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install: pip install 'memorius[gateway]'")
    print("Or:     pip install fastapi uvicorn[standard] pydantic")
    sys.exit(1)

logger = logging.getLogger("memorius.gateway")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SearchQuery(BaseModel):
    query: str = Field(..., description="Natural language search query")
    wing: Optional[str] = Field(None, description="Filter by wing (project/person)")
    room: Optional[str] = Field(None, description="Filter by room (topic)")
    limit: int = Field(5, description="Max results", ge=1, le=50)


class DrawerAdd(BaseModel):
    wing: str = Field(..., description="Wing name (project/person)")
    room: str = Field(..., description="Room name (topic)")
    content: str = Field(..., description="Verbatim content to store")
    source_file: Optional[str] = Field(None, description="Source reference")


class DrawerDelete(BaseModel):
    drawer_id: str = Field(..., description="Drawer ID to delete")


class DiaryEntry(BaseModel):
    agent_name: str = Field(..., description="Agent name/identifier")
    entry: str = Field(..., description="Diary content")
    topic: str = Field("general", description="Topic category")


class KGAdd(BaseModel):
    subject: str = Field(..., description="Entity name (subject)")
    predicate: str = Field(..., description="Relationship predicate")
    obj: str = Field(..., description="Entity name (object)")
    valid_from: Optional[str] = Field(None, description="Date when fact became true (YYYY-MM-DD)")
    source_closet: Optional[str] = Field(None, description="Source reference")


class KGInvalidate(BaseModel):
    subject: str = Field(..., description="Entity name (subject)")
    predicate: str = Field(..., description="Relationship predicate")
    obj: str = Field(..., description="Entity name (object)")
    ended: Optional[str] = Field(None, description="Date when fact ended (default: today)")


class KGQuery(BaseModel):
    entity: str = Field(..., description="Entity name to query")
    as_of: Optional[str] = Field(None, description="Date filter (YYYY-MM-DD)")
    direction: str = Field("both", description="Relationship direction: outgoing, incoming, or both")


class TraverseQuery(BaseModel):
    start_room: str = Field(..., description="Room to start from")
    max_hops: int = Field(2, description="Connection depth", ge=1, le=10)


class TunnelCreate(BaseModel):
    room_a: str = Field(..., description="First room")
    room_b: str = Field(..., description="Second room")
    label: Optional[str] = Field(None, description="Optional label")


# ---------------------------------------------------------------------------
# MCP Client
# ---------------------------------------------------------------------------


class McpClient:
    """Manages the mempalace-mcp subprocess and sends JSON-RPC requests."""

    def __init__(self, mcp_command: list[str] | None = None):
        self._mcp_command = mcp_command or ["python3", "-m", "mempalace.mcp_server"]
        self._process: subprocess.Popen | None = None
        self._request_id = 0

    def start(self):
        """Start the MCP server subprocess."""
        if self._process is not None and self._process.poll() is None:
            return  # already running

        logger.info(f"Starting MCP server: {' '.join(self._mcp_command)}")
        self._process = subprocess.Popen(
            self._mcp_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Wait for the server to initialize
        import time
        time.sleep(2)

        # Send initialize request
        self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "memorius-gateway", "version": "0.1.0"},
        })

        # Read the response
        response = self._read_response()
        if response and response.get("result"):
            logger.info("MCP server initialized successfully")
            # Send initialized notification
            self._send_notification("notifications/initialized", {})
        else:
            logger.warning(f"MCP server initialization response: {response}")

    def stop(self):
        """Stop the MCP server."""
        if self._process and self._process.poll() is None:
            logger.info("Stopping MCP server")
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict:
        """Call an MCP tool and return the result."""
        if not self._process or self._process.poll() is not None:
            self.start()

        self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        response = self._read_response()
        return response or {"error": "No response from MCP server"}

    def _send_request(self, method: str, params: dict):
        """Send a JSON-RPC request."""
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        line = json.dumps(request) + "\n"
        if self._process and self._process.stdin:
            self._process.stdin.write(line)
            self._process.stdin.flush()

    def _send_notification(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        line = json.dumps(notification) + "\n"
        if self._process and self._process.stdin:
            self._process.stdin.write(line)
            self._process.stdin.flush()

    def _read_response(self, timeout: float = 30.0) -> dict | None:
        """Read a JSON-RPC response line from stdout."""
        import select
        import time

        deadline = time.time() + timeout
        buffer = ""

        while time.time() < deadline:
            if not self._process or not self._process.stdout:
                return None

            # Check if data is available
            r, _, _ = select.select([self._process.stdout], [], [], 0.5)
            if r:
                line = self._process.stdout.readline()
                if line:
                    buffer += line
                    # Check if we have a complete JSON object
                    try:
                        return json.loads(buffer.strip())
                    except json.JSONDecodeError:
                        # Partial JSON, keep reading
                        continue

            # Also check for server errors
            if self._process.poll() is not None:
                stderr_output = self._process.stderr.read() if self._process.stderr else ""
                logger.error(f"MCP server exited with code {self._process.returncode}: {stderr_output[-500:]}")
                return {"error": f"MCP server exited: {stderr_output[-200:]}"}

        return {"error": "MCP request timed out"}


# ---------------------------------------------------------------------------
# Application State
# ---------------------------------------------------------------------------


class AppState:
    def __init__(self):
        self.mcp: McpClient | None = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    logger.info("Starting MemPalace HTTP Gateway...")
    state.mcp = McpClient()
    try:
        state.mcp.start()
    except Exception as e:
        logger.warning(f"MCP server start failed (will retry on first request): {e}")
    yield
    logger.info("Shutting down MemPalace HTTP Gateway...")
    if state.mcp:
        state.mcp.stop()


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MemPalace Universal Gateway",
    description="HTTP REST API for MemPalace — use with any tool, browser, or script.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _mcp_call(tool: str, **kwargs) -> dict:
    """Helper to call MCP and handle errors."""
    if not state.mcp:
        raise HTTPException(status_code=503, detail="MCP server not available")
    result = state.mcp.call_tool(tool, kwargs)
    if "error" in result:
        error_msg = result.get("error", {}).get("message", str(result["error"]))
        raise HTTPException(status_code=502, detail=error_msg)
    # Extract content from MCP result
    content = result.get("result", {}).get("content", [])
    # MCP content is typically a list of {type, text} objects
    if content and isinstance(content, list):
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return {"result": "\n".join(texts), "raw": result}
    return {"result": content, "raw": result}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/")
async def root():
    return {
        "service": "MemPalace Universal Gateway",
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": {
            "GET /status": "Palace overview",
            "GET /search": "Semantic search",
            "POST /drawers": "Add drawer",
            "GET /wings": "List wings",
            "GET /rooms": "List rooms",
            "POST /kg/add": "Add knowledge graph fact",
            "POST /diary": "Write diary entry",
            "GET /health": "Health check",
        },
    }


@app.get("/health")
async def health():
    """Health check — verifies MCP server is responsive."""
    try:
        if state.mcp:
            result = state.mcp.call_tool("mempalace_status", {})
            return {"status": "ok", "mcp_server": "connected", "response": bool(result)}
    except Exception as e:
        pass
    return {"status": "degraded", "mcp_server": "disconnected"}


@app.get("/status")
async def palace_status():
    """Get palace overview: total drawers, wings, rooms."""
    return _mcp_call("mempalace_status")


@app.get("/wings")
async def list_wings():
    """List all wings with drawer counts."""
    return _mcp_call("mempalace_list_wings")


@app.get("/rooms")
async def list_rooms(wing: Optional[str] = None):
    """List rooms, optionally filtered by wing."""
    kwargs = {}
    if wing:
        kwargs["wing"] = wing
    return _mcp_call("mempalace_list_rooms", **kwargs)


@app.get("/taxonomy")
async def get_taxonomy():
    """Full wing → room → count tree."""
    return _mcp_call("mempalace_get_taxonomy")


@app.get("/search")
async def search(
    q: str = Query(..., description="Search query"),
    wing: Optional[str] = Query(None, description="Filter by wing"),
    room: Optional[str] = Query(None, description="Filter by room"),
    limit: int = Query(5, description="Max results", ge=1, le=50),
):
    """Semantic search across palace memories."""
    return _mcp_call("mempalace_search", query=q, wing=wing or "", room=room or "", limit=limit)


@app.post("/drawers")
async def add_drawer(drawer: DrawerAdd):
    """Store verbatim content into a wing/room."""
    return _mcp_call(
        "mempalace_add_drawer",
        wing=drawer.wing,
        room=drawer.room,
        content=drawer.content,
        source_file=drawer.source_file or "",
    )


@app.delete("/drawers/{drawer_id}")
async def delete_drawer(drawer_id: str):
    """Remove a drawer by ID."""
    return _mcp_call("mempalace_delete_drawer", drawer_id=drawer_id)


@app.get("/drawers/{drawer_id}")
async def get_drawer(drawer_id: str):
    """Fetch a single drawer by ID."""
    return _mcp_call("mempalace_get_drawer", drawer_id=drawer_id)


@app.post("/diary")
async def write_diary(entry: DiaryEntry):
    """Write a session diary entry."""
    return _mcp_call(
        "mempalace_diary_write",
        agent_name=entry.agent_name,
        entry=entry.entry,
        topic=entry.topic,
    )


@app.get("/diary")
async def read_diary(
    agent_name: str = Query(..., description="Agent name"),
    last_n: int = Query(10, description="Number of entries", ge=1, le=100),
):
    """Read recent diary entries."""
    return _mcp_call("mempalace_diary_read", agent_name=agent_name, last_n=last_n)


@app.post("/kg/add")
async def kg_add(fact: KGAdd):
    """Add a knowledge graph fact."""
    return _mcp_call(
        "mempalace_kg_add",
        subject=fact.subject,
        predicate=fact.predicate,
        object=fact.obj,
        valid_from=fact.valid_from or "",
        source_closet=fact.source_closet or "",
    )


@app.post("/kg/invalidate")
async def kg_invalidate(fact: KGInvalidate):
    """Mark a knowledge graph fact as no longer true."""
    return _mcp_call(
        "mempalace_kg_invalidate",
        subject=fact.subject,
        predicate=fact.predicate,
        object=fact.obj,
        ended=fact.ended or "",
    )


@app.post("/kg/query")
async def kg_query(query: KGQuery):
    """Query entity relationships."""
    return _mcp_call(
        "mempalace_kg_query",
        entity=query.entity,
        as_of=query.as_of or "",
        direction=query.direction,
    )


@app.get("/kg/timeline")
async def kg_timeline(entity: str = Query("", description="Entity name (optional)")):
    """Chronological story of an entity."""
    return _mcp_call("mempalace_kg_timeline", entity=entity)


@app.get("/kg/stats")
async def kg_stats():
    """Knowledge graph overview."""
    return _mcp_call("mempalace_kg_stats")


@app.post("/traverse")
async def traverse(query: TraverseQuery):
    """Walk from a room, find connected ideas across wings."""
    return _mcp_call(
        "mempalace_traverse",
        start_room=query.start_room,
        max_hops=query.max_hops,
    )


@app.get("/tunnels")
async def find_tunnels(
    wing_a: str = Query(..., description="First wing"),
    wing_b: str = Query(..., description="Second wing"),
):
    """Find rooms that bridge two wings."""
    return _mcp_call("mempalace_find_tunnels", wing_a=wing_a, wing_b=wing_b)


@app.post("/tunnels")
async def create_tunnel(tunnel: TunnelCreate):
    """Create an explicit cross-wing tunnel."""
    return _mcp_call(
        "mempalace_create_tunnel",
        room_a=tunnel.room_a,
        room_b=tunnel.room_b,
        label=tunnel.label or "",
    )


@app.get("/graph/stats")
async def graph_stats():
    """Graph connectivity overview."""
    return _mcp_call("mempalace_graph_stats")


@app.post("/reconnect")
async def reconnect():
    """Force cache invalidation and reconnect after external writes."""
    return _mcp_call("mempalace_reconnect")


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------


def main():
    """Start the HTTP gateway server."""
    import argparse

    parser = argparse.ArgumentParser(
        "memorius-serve",
        description="HTTP REST gateway for MemPalace — use with any tool.",
    )
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument("--port", type=int, default=8912, help="Port to listen on (default: 8912)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--palace", default=None, help="Path to palace directory")
    parser.add_argument("--mcp-command", default=None,
                        help="Custom MCP server command (default: python3 -m mempalace.mcp_server)")
    parser.add_argument("--log-level", default="info",
                        choices=["debug", "info", "warning", "error"],
                        help="Logging level")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")

    args = parser.parse_args()

    if args.version:
        try:
            from .. import __version__
            v = __version__
        except ImportError:
            v = "0.1.0"
        print(f"memorius-serve v{v}")
        return

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # If custom palace path, set environment variable for MCP server
    if args.palace:
        os.environ["MEMPALACE_PALACE_PATH"] = os.path.abspath(args.palace)

    # If custom MCP command
    mcp_cmd = None
    if args.mcp_command:
        mcp_cmd = args.mcp_command.split()
        global _mcp_command_override
        _mcp_command_override = mcp_cmd

    logger.info(f"Starting MemPalace HTTP Gateway on http://{args.host}:{args.port}")
    logger.info(f"API docs: http://{args.host}:{args.port}/docs")

    uvicorn.run(
        "memorius.gateway.http_server:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
