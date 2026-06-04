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
    with the memory vault. Runs over stdin/stdout JSON-RPC.
    """

    def __init__(self, engine):
        self._engine = engine

    # ── Tool definitions ──

    TOOLS = [
        {
            "name": "memorius_status",
            "description": "Get memory vault status: vault count, memory count, recent diaries, embedding provider info. Call at session start.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "memorius_store",
            "description": "Store a memory in the vault under a hierarchical path (vault/shelf/folder/note).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The memory content to store"},
                    "vault": {"type": "string", "description": "Vault name (default: main)"},
                    "shelf": {"type": "string", "description": "Shelf name (default: default)"},
                    "folder": {"type": "string", "description": "Folder name (default: default)"},
                    "note": {"type": "string", "description": "Note name (default: default)"},
                },
                "required": ["content"],
            },
        },
        {
            "name": "memorius_search",
            "description": "Semantic search across the vault. Use before answering questions about past work.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                    "n_results": {"type": "number", "description": "Number of results (default: 10)", "default": 10},
                    "vault": {"type": "string", "description": "Filter by vault"},
                    "shelf": {"type": "string", "description": "Filter by shelf"},
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
                    "vault": {"type": "string", "description": "Vault name (default: main)"},
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "memorius_mine",
            "description": "Extract memories from a conversation transcript and store them automatically in the conversations shelf.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "transcript": {"type": "string", "description": "Conversation transcript to mine"},
                    "vault": {"type": "string", "description": "Vault name (default: main)"},
                },
                "required": ["transcript"],
            },
        },
        {
            "name": "memorius_vault_ls",
            "description": "List the hierarchy: vaults, shelves, folders, notes. Explore what's stored where.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "vault": {"type": "string", "description": "Vault to explore (default: main)"},
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
                    "vault": {"type": "string", "description": "Filter by vault"},
                },
            },
        },
    ]

    # ── Tool dispatch ──

    def _get_tool_handler(self, tool_name: str):
        """Resolve a tool name to its handler method or None."""
        return getattr(self, f"tool_{tool_name}", None)

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

        handler = self._get_tool_handler(tool_name)
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
            vault=args.get("vault", "main"),
            shelf=args.get("shelf", "default"),
            folder=args.get("folder", "default"),
            note=args.get("note", "default"),
        )
        return {"id": memory.id, "vault": memory.vault, "path": f"{memory.shelf}/{memory.folder}/{memory.note}"}

    def tool_memorius_search(self, args: dict) -> dict:
        results = self._engine.search(
            query=args["query"],
            vault=args.get("vault"),
            shelf=args.get("shelf"),
            limit=args.get("n_results", 10),
        )
        return {
            "query": args["query"],
            "count": len(results),
            "results": [m.to_dict() for m in results],
        }

    def tool_memorius_diary_write(self, args: dict) -> dict:
        entry = self._engine.write_diary(
            session_id=args["session_id"],
            vault=args.get("vault", "main"),
            title=args.get("title", ""),
            summary=args.get("summary", ""),
            content=args.get("content", ""),
            exchange_count=args.get("exchange_count", 0),
        )
        return {"id": entry["id"], "session_id": entry["session_id"]}

    def tool_memorius_mine(self, args: dict) -> dict:
        memories = self._engine.mine(
            text=args["transcript"],
            vault=args.get("vault", "main"),
        )
        return {"stored": len(memories), "memory_ids": [m.id for m in memories]}

    def tool_memorius_vault_ls(self, args: dict) -> dict:
        vault = args.get("vault", "main")
        hierarchy = self._engine.get_hierarchy(vault)
        return hierarchy

    def tool_memorius_diary_list(self, args: dict) -> dict:
        diaries = self._engine._meta.list_diaries(
            vault=args.get("vault"),
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
