"""MCP protocol server — primary interface for AI agents."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

logger = logging.getLogger("memorius.mcp")


class McpServer:
    """MCP protocol server over stdio.

    Implements the Model Context Protocol for AI agents to interact
    with the memory palace. Runs over stdin/stdout JSON-RPC.
    """

    def __init__(self, engine):
        self._engine = engine

    # ── Tool definitions ──

    TOOLS = [
        {
            "name": "memorius_status",
            "description": "Get memory palace status: palace count, memory count, recent diaries, embedding provider info. Call at session start.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "memorius_store",
            "description": "Store a memory in the palace under a hierarchical path.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The memory content to store"},
                    "palace": {"type": "string", "description": "Palace name (default: main)"},
                    "wing": {"type": "string", "description": "Wing name (default: default)"},
                    "room": {"type": "string", "description": "Room name (default: default)"},
                    "drawer": {"type": "string", "description": "Drawer name (default: default)"},
                },
                "required": ["content"],
            },
        },
        {
            "name": "memorius_search",
            "description": "Semantic search across the palace. Use before answering questions about past work.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                    "n_results": {"type": "number", "description": "Number of results (default: 10)", "default": 10},
                    "palace": {"type": "string", "description": "Filter by palace"},
                    "wing": {"type": "string", "description": "Filter by wing"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "memorius_diary_write",
            "description": "Write a diary entry for the current session. Call at session end.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session identifier"},
                    "title": {"type": "string", "description": "Diary title"},
                    "summary": {"type": "string", "description": "One-paragraph summary of what happened"},
                    "content": {"type": "string", "description": "Detailed diary content or transcript"},
                    "exchange_count": {"type": "number", "description": "Number of exchanges in the session"},
                    "palace": {"type": "string", "description": "Palace name (default: main)"},
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "memorius_mine",
            "description": "Extract memories from a conversation transcript and store them automatically in the conversations wing.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "transcript": {"type": "string", "description": "Conversation transcript to mine"},
                    "palace": {"type": "string", "description": "Palace name (default: main)"},
                },
                "required": ["transcript"],
            },
        },
        {
            "name": "memorius_palace_ls",
            "description": "List the hierarchy: palaces, wings, rooms, drawers. Explore what's stored where.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "palace": {"type": "string", "description": "Palace to explore (default: main)"},
                },
            },
        },
        {
            "name": "memorius_diary_list",
            "description": "List recent diary entries across sessions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "number", "description": "Max entries (default: 10)", "default": 10},
                    "palace": {"type": "string", "description": "Filter by palace"},
                },
            },
        },
    ]

    def __getattr__(self, name):
        """Forward memorius_* methods to engine with attribute fallback."""
        raise AttributeError(f"Unknown tool: {name}")

    def run(self):
        """Run the MCP server over stdio (JSON-RPC)."""
        logger.info("MCP server starting (stdio)")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")

        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                response = self._handle_request(json.loads(line))
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
            except EOFError:
                break
            except json.JSONDecodeError:
                self._send_error(-32700, "Parse error")
            except Exception as e:
                logger.exception("MCP handler error")
                self._send_error(-32603, str(e))

    def _handle_request(self, msg: dict) -> dict | None:
        """Handle a single JSON-RPC message."""
        msg_id = msg.get("id")
        method = msg.get("method", "")

        if method == "initialize":
            return self._handle_initialize(msg_id)
        elif method == "notifications/initialized":
            return None
        elif method == "tools/list":
            return self._handle_list_tools(msg_id)
        elif method == "tools/call":
            return self._handle_call_tool(msg_id, msg.get("params", {}))
        else:
            return self._make_response(msg_id, {})

    def _handle_initialize(self, msg_id):
        return self._make_response(msg_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "memorius", "version": "0.1.0"},
        })

    def _handle_list_tools(self, msg_id):
        return self._make_response(msg_id, {"tools": self.TOOLS})

    def _handle_call_tool(self, msg_id, params: dict):
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        handler = getattr(self, f"tool_{tool_name}", None)
        if handler is None:
            return self._make_error(msg_id, -32601, f"Unknown tool: {tool_name}")

        result = handler(arguments)
        return self._make_response(msg_id, {
            "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
        })

    # ── Tool handlers ──

    def tool_memorius_status(self, args: dict) -> dict:
        return self._engine.status()

    def tool_memorius_store(self, args: dict) -> dict:
        content = args["content"]
        memory = self._engine.store(
            content=content,
            palace=args.get("palace", "main"),
            wing=args.get("wing", "default"),
            room=args.get("room", "default"),
            drawer=args.get("drawer", "default"),
        )
        return {"id": memory.id, "palace": memory.palace, "path": f"{memory.wing}/{memory.room}/{memory.drawer}"}

    def tool_memorius_search(self, args: dict) -> dict:
        results = self._engine.search(
            query=args["query"],
            palace=args.get("palace"),
            wing=args.get("wing"),
            n_results=args.get("n_results", 10),
        )
        return {
            "query": args["query"],
            "count": len(results),
            "results": [m.to_dict() for m in results],
        }

    def tool_memorius_diary_write(self, args: dict) -> dict:
        entry = self._engine.write_diary(
            session_id=args["session_id"],
            palace=args.get("palace", "main"),
            title=args.get("title", ""),
            summary=args.get("summary", ""),
            content=args.get("content", ""),
            exchange_count=args.get("exchange_count", 0),
        )
        return {"id": entry["id"], "session_id": entry["session_id"]}

    def tool_memorius_mine(self, args: dict) -> dict:
        memories = self._engine.mine(
            transcript=args["transcript"],
            palace=args.get("palace", "main"),
        )
        return {"stored": len(memories), "memory_ids": [m.id for m in memories]}

    def tool_memorius_palace_ls(self, args: dict) -> dict:
        palace = args.get("palace", "main")
        hierarchy = self._engine.hierarchy(palace)
        return hierarchy

    def tool_memorius_diary_list(self, args: dict) -> dict:
        diaries = self._engine._meta.list_diaries(
            palace=args.get("palace"),
            limit=args.get("limit", 10),
        )
        return {"count": len(diaries), "diaries": diaries}

    # ── Response helpers ──

    def _make_response(self, msg_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _make_error(self, msg_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    def _send_error(self, code: int, message: str):
        resp = {"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
