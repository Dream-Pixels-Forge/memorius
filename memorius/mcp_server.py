"""MCP protocol server — primary interface for AI agents."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from memorius import __version__ as _memorius_version
from memorius.validation import (
    validate_name as _validate_name,
    MAX_NAME_LENGTH,
    MAX_CONTENT_LENGTH,
    MAX_FIELD_LENGTH,
    MAX_SEARCH_LIMIT,
)

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
            "description": "Semantic search across the vault. Use before answering questions about past work. Set expand_graph=true to also pull in memories linked in the knowledge graph to the primary hits (\"you also worked on X\"). Filter by folder/note/tags to narrow to a specific path or tagged subset.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                    "n_results": {"type": "number", "description": "Number of results (default: 10)", "default": 10},
                    "vault": {"type": "string", "description": "Filter by vault"},
                    "shelf": {"type": "string", "description": "Filter by shelf"},
                    "folder": {"type": "string", "description": "Filter by folder (Chroma metadata)"},
                    "note": {"type": "string", "description": "Filter by note (Chroma metadata)"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Only return memories carrying ALL of these tags (post-filtered in Python)"},
                    "expand_graph": {"type": "boolean", "description": "Also pull in 1-hop graph-linked memories (default: false). Off preserves the original search-only behavior; on augments with related memories.", "default": False},
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
        # ── New v0.2.0 tools ──
        {
            "name": "memorius_consolidate",
            "description": "Consolidate similar memories — merge duplicates, extract insights. Run periodically to keep vault clean.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "vault": {"type": "string", "description": "Filter by vault (default: all)"},
                    "similarity_threshold": {"type": "number", "description": "Similarity threshold 0-1 (default: 0.80)", "default": 0.80},
                    "dry_run": {"type": "boolean", "description": "Preview without changes (default: false)", "default": False},
                },
            },
        },
        {
            "name": "memorius_extract",
            "description": "Extract structured memories from a conversation using LLM. Identifies decisions, preferences, facts, action items.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "conversation": {"type": "string", "description": "Conversation text to extract from"},
                    "vault": {"type": "string", "description": "Target vault (default: main)"},
                    "shelf": {"type": "string", "description": "Target shelf (default: extracted)"},
                },
                "required": ["conversation"],
            },
        },
        {
            "name": "memorius_factcheck",
            "description": "Fact-check a statement against stored memories. Detects contradictions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string", "description": "Statement to verify"},
                    "vault": {"type": "string", "description": "Filter by vault"},
                },
                "required": ["statement"],
            },
        },
        {
            "name": "memorius_context",
            "description": "Get formatted memory context for injection into agent context. Auto-searches and formats relevant memories.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Current topic/context to search for"},
                    "vault": {"type": "string", "description": "Filter by vault"},
                    "max_items": {"type": "number", "description": "Max memories to include (default: 5)", "default": 5},
                },
                "required": ["query"],
            },
        },
        {
            "name": "memorius_session_profile",
            "description": "Build a memory profile for session inheritance. Get context from previous sessions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session identifier"},
                    "vault": {"type": "string", "description": "Vault name (default: main)"},
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "memorius_graph_stats",
            "description": "Get knowledge graph statistics — nodes, edges, relations.",
            "inputSchema": {"type": "object", "properties": {}},
        },
{
            "name": "memorius_memory_stats",
            "description": "Get memory tracking statistics - total, active, archived, by vault.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "memorius_contradictions",
            "description": "Get memories that contradict a given memory (knowledge graph edges with relation='contradicts', created by memorius_factcheck when a statement surfaces both a corroborating and a contradicting memory).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "Memory UUID to inspect"},
                },
                "required": ["memory_id"],
            },
        },
        {
            "name": "memorius_get",
            "description": "Get a single memory by ID. Returns full content and metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "Memory UUID"},
                },
                "required": ["memory_id"],
            },
        },
        {
            "name": "memorius_update",
            "description": "Update a memory's content and/or metadata. Re-embeds if content changes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "Memory UUID"},
                    "content": {"type": "string", "description": "New content (omit to keep existing)"},
                    "metadata": {"type": "object", "description": "Metadata to shallow-merge (omit to keep existing)"},
                },
                "required": ["memory_id"],
            },
        },
        {
            "name": "memorius_delete",
            "description": "Delete a memory by ID from both vector and metadata stores.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "Memory UUID to delete"},
                },
                "required": ["memory_id"],
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
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        try:
            sys.stdin.reconfigure(encoding="utf-8")
        except Exception:
            pass

        consecutive_errors = 0
        max_consecutive_errors = 10

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
                consecutive_errors = 0  # reset on success
            except EOFError:
                break
            except json.JSONDecodeError as e:
                consecutive_errors += 1
                logger.warning("MCP parse error (%d/%d): %s", consecutive_errors, max_consecutive_errors, e)
                self._send_error(-32700, f"Parse error: {e}")
                if consecutive_errors >= max_consecutive_errors:
                    logger.error("Too many consecutive parse errors, shutting down")
                    break
            except Exception as e:
                consecutive_errors += 1
                logger.exception("MCP handler error (%d/%d)", consecutive_errors, max_consecutive_errors)
                # Sanitize error message to avoid leaking internals
                err_msg = str(e)
                if len(err_msg) > 200:
                    err_msg = err_msg[:200] + "..."
                self._send_error(-32603, err_msg)
                if consecutive_errors >= max_consecutive_errors:
                    logger.error("Too many consecutive errors, shutting down")
                    break

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
            return self._make_error(msg_id, -32601, f"Method not found: {method}")

    def _handle_initialize(self, msg_id):
        return self._make_response(msg_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "memorius", "version": _memorius_version},
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
        content = args.get("content", "")
        if not isinstance(content, str) or not content.strip():
            return {"error": "Content must be a non-empty string"}
        if len(content) > MAX_CONTENT_LENGTH:
            return {"error": f"Content too long (max {MAX_CONTENT_LENGTH} chars)"}

        vault = _validate_name(args.get("vault", "main"), "vault")
        shelf = _validate_name(args.get("shelf", "default"), "shelf")
        folder = _validate_name(args.get("folder", "default"), "folder")
        note = _validate_name(args.get("note", "default"), "note")

        memory = self._engine.store(
            content=content,
            vault=vault,
            shelf=shelf,
            folder=folder,
            note=note,
        )
        return {"id": memory.id, "vault": memory.vault, "path": f"{memory.shelf}/{memory.folder}/{memory.note}"}

    def tool_memorius_search(self, args: dict) -> dict:
        query = args.get("query", "")
        if not isinstance(query, str) or not query.strip():
            return {"error": "Query must be a non-empty string"}
        if len(query) > MAX_FIELD_LENGTH:
            return {"error": f"Query too long (max {MAX_FIELD_LENGTH} chars)"}

        n_results = min(args.get("n_results", 10), MAX_SEARCH_LIMIT)
        vault = _validate_name(args.get("vault"), "vault") if args.get("vault") else None
        shelf = _validate_name(args.get("shelf"), "shelf") if args.get("shelf") else None
        folder = _validate_name(args.get("folder"), "folder") if args.get("folder") else None
        note = _validate_name(args.get("note"), "note") if args.get("note") else None
        expand_graph = bool(args.get("expand_graph", False))
        tags_in = args.get("tags")
        tags = [str(t) for t in tags_in] if isinstance(tags_in, list) and tags_in else None

        results = self._engine.search(
            query=query,
            vault=vault,
            shelf=shelf,
            limit=n_results,
            expand_graph=expand_graph,
            folder=folder,
            note=note,
            tags=tags,
        )
        # Exclude vector from response — it's large and not useful to callers
        return {
            "query": query,
            "count": len(results),
            "results": [{k: v for k, v in m.to_dict().items() if k != "vector"} for m in results],
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
        transcript = args.get("transcript", "")
        if not isinstance(transcript, str) or not transcript.strip():
            return {"error": "Transcript must be a non-empty string"}
        if len(transcript) > MAX_CONTENT_LENGTH:
            return {"error": f"Transcript too long (max {MAX_CONTENT_LENGTH} chars)"}

        vault = _validate_name(args.get("vault", "main"), "vault")
        memories = self._engine.mine(
            text=transcript,
            vault=vault,
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

    # ── New v0.2.0 tool handlers ──

    def tool_memorius_consolidate(self, args: dict) -> dict:
        result = self._engine.consolidate(
            vault=args.get("vault"),
            similarity_threshold=args.get("similarity_threshold", 0.80),
            dry_run=args.get("dry_run", False),
        )
        return {
            "clusters_found": result.clusters_found,
            "memories_merged": result.memories_merged,
            "memories_archived": result.memories_archived,
            "details": result.details[:10],
        }

    def tool_memorius_extract(self, args: dict) -> dict:
        memories = self._engine.extract_memories(
            conversation=args["conversation"],
            vault=args.get("vault", "main"),
            shelf=args.get("shelf", "extracted"),
        )
        return {
            "extracted": len(memories),
            "memory_ids": [m.id for m in memories],
            "previews": [m.content[:100] for m in memories[:5]],
        }

    def tool_memorius_factcheck(self, args: dict) -> dict:
        result = self._engine.check_fact(
            statement=args["statement"],
            vault=args.get("vault"),
        )
        return {
            "statement": result.statement,
            "verdict": result.verdict,
            "confidence": result.confidence,
            "explanation": result.explanation,
            "matching_count": len(result.matching_memories),
            "contradicting_count": len(result.contradicting_memories),
        }

    def tool_memorius_context(self, args: dict) -> dict:
        context = self._engine.get_context(
            query=args["query"],
            vault=args.get("vault"),
            max_items=args.get("max_items", 5),
        )
        return {
            "query": args["query"],
            "context": context,
            "has_context": bool(context),
        }

    def tool_memorius_session_profile(self, args: dict) -> dict:
        from memorius.session import format_profile_for_context
        profile = self._engine.get_session_profile(
            session_id=args["session_id"],
            vault=args.get("vault", "main"),
        )
        return {
            "session_id": profile.session_id,
            "summary": profile.summary,
            "key_decisions": profile.key_decisions[:5],
            "ongoing_tasks": profile.ongoing_tasks[:5],
            "recent_topics": profile.recent_topics[:5],
            "formatted": format_profile_for_context(profile),
        }

    def tool_memorius_graph_stats(self, args: dict) -> dict:
        return self._engine.get_graph_stats()

    def tool_memorius_memory_stats(self, args: dict) -> dict:
        return self._engine.get_memory_stats()

    def tool_memorius_contradictions(self, args: dict) -> dict:
        memory_id = args.get("memory_id", "")
        if not memory_id or not isinstance(memory_id, str):
            return {"error": "memory_id is required"}
        contradictions = self._engine.get_contradictions(memory_id)
        return {
            "memory_id": memory_id,
            "count": len(contradictions),
            "contradictions": [
                {k: v for k, v in m.to_dict().items() if k != "vector"}
                for m in contradictions
            ],
        }

    def tool_memorius_get(self, args: dict) -> dict:
        memory_id = args.get("memory_id", "")
        if not memory_id or not isinstance(memory_id, str):
            return {"error": "memory_id is required"}
        mem = self._engine.get_memory(memory_id)
        if mem is None:
            return {"error": "Memory not found", "memory_id": memory_id}
        d = mem.to_dict()
        d.pop("vector", None)
        return d

    def tool_memorius_update(self, args: dict) -> dict:
        memory_id = args.get("memory_id", "")
        if not memory_id or not isinstance(memory_id, str):
            return {"error": "memory_id is required"}
        content = args.get("content")
        if content is not None:
            if not isinstance(content, str) or not content.strip():
                return {"error": "Content must be a non-empty string"}
            if len(content) > MAX_CONTENT_LENGTH:
                return {"error": f"Content too long (max {MAX_CONTENT_LENGTH} chars)"}
        metadata = args.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            return {"error": "Metadata must be a dict"}
        mem = self._engine.update_memory(memory_id, content=content, metadata=metadata)
        if mem is None:
            return {"error": "Memory not found", "memory_id": memory_id}
        d = mem.to_dict()
        d.pop("vector", None)
        return d

    def tool_memorius_delete(self, args: dict) -> dict:
        memory_id = args.get("memory_id", "")
        if not memory_id or not isinstance(memory_id, str):
            return {"error": "memory_id is required"}
        result = self._engine.delete(memory_id)
        return result

    # ── Response helpers ──

    def _make_response(self, msg_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _make_error(self, msg_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    def _send_error(self, code: int, message: str):
        resp = {"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
