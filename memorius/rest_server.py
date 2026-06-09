"""REST API server for memorius — alternative interface to the MCP server."""

from __future__ import annotations

import logging
import os
from typing import Any

from memorius import __version__ as _memorius_version
from .utils import validate_name as _validate_name, MAX_NAME_LENGTH

logger = logging.getLogger("memorius.rest")

# Input validation constants
MAX_CONTENT_LENGTH = 100_000  # 100KB
MAX_FIELD_LENGTH = 1_000
MAX_SEARCH_LIMIT = 100
MAX_DIARY_CONTENT = 50_000


def _validate_content(content: str) -> str:
    """Validate content field. Raises ValueError if invalid."""
    if not isinstance(content, str):
        raise ValueError("Content must be a string")
    if not content.strip():
        raise ValueError("Content cannot be empty")
    if len(content) > MAX_CONTENT_LENGTH:
        raise ValueError(f"Content too long (max {MAX_CONTENT_LENGTH} chars)")
    return content


def run_rest_server(engine, host: str = "127.0.0.1", port: int = 8912):
    """Start the FastAPI REST server."""
    try:
        from fastapi import FastAPI, Request, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        import uvicorn
    except ImportError:
        print("Error: REST server requires extra dependencies. Install: pip install memorius[rest]")
        return

    app = FastAPI(title="Memorius API", version=_memorius_version)

    # CORS — restrictive by default
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1", "http://localhost"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # API key authentication
    api_key = os.environ.get("MEMORIUS_API_KEY")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        # Skip auth for health check
        if request.url.path == "/health":
            return await call_next(request)
        # Skip auth if no API key configured (backwards compatible)
        if api_key:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer ") or auth_header[7:] != api_key:
                raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return await call_next(request)

    # Request body size limit middleware
    @app.middleware("http")
    async def size_limit_middleware(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_CONTENT_LENGTH:
                    raise HTTPException(status_code=413, detail="Request body too large")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid Content-Length header")
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "memorius"}

    @app.post("/store")
    async def store(payload: dict[str, Any]):
        content = _validate_content(payload.get("content", ""))
        vault = _validate_name(payload.get("vault", "main"), "vault")
        shelf = _validate_name(payload.get("shelf", "default"), "shelf")
        folder = _validate_name(payload.get("folder", "default"), "folder")
        note = _validate_name(payload.get("note", "default"), "note")

        memory = engine.store(
            content=content,
            vault=vault,
            shelf=shelf,
            folder=folder,
            note=note,
            metadata=payload.get("metadata"),
        )
        return memory.to_dict()

    @app.post("/search")
    async def search(payload: dict[str, Any]):
        query = payload.get("query", "")
        if not query or not isinstance(query, str):
            raise HTTPException(status_code=400, detail="Query is required")
        if len(query) > MAX_FIELD_LENGTH:
            raise HTTPException(status_code=400, detail="Query too long")

        limit = min(payload.get("limit", 10), MAX_SEARCH_LIMIT)
        vault = _validate_name(payload.get("vault"), "vault") if payload.get("vault") else None
        shelf = _validate_name(payload.get("shelf"), "shelf") if payload.get("shelf") else None

        results = engine.search(query=query, vault=vault, shelf=shelf, limit=limit)
        return {"query": query, "count": len(results), "results": [m.to_dict() for m in results]}

    @app.post("/mine")
    async def mine(payload: dict[str, Any]):
        text = payload.get("text", "")
        if not text or not isinstance(text, str):
            raise HTTPException(status_code=400, detail="Text is required")
        if len(text) > MAX_CONTENT_LENGTH:
            raise HTTPException(status_code=400, detail="Text too long")

        vault = _validate_name(payload.get("vault", "main"), "vault")
        memories = engine.mine(text=text, vault=vault)
        return {"stored": len(memories), "memory_ids": [m.id for m in memories]}

    @app.get("/status")
    async def status():
        return engine.status()

    @app.post("/diary")
    async def diary(payload: dict[str, Any]):
        session_id = payload.get("session_id", "")
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")

        vault = _validate_name(payload.get("vault", "main"), "vault")
        content = payload.get("content", "")
        if content and len(content) > MAX_DIARY_CONTENT:
            raise HTTPException(status_code=400, detail="Diary content too long")

        entry = engine.write_diary(
            session_id=session_id,
            vault=vault,
            title=payload.get("title", ""),
            summary=payload.get("summary", ""),
            content=content,
            exchange_count=payload.get("exchange_count", 0),
        )
        return entry

    @app.get("/vault")
    async def ls(vault: str = "main"):
        vault = _validate_name(vault, "vault")
        return engine.get_hierarchy(vault)

    @app.get("/diaries")
    async def diaries(vault: str | None = None, limit: int = 10):
        if vault:
            vault = _validate_name(vault, "vault")
        limit = min(limit, MAX_SEARCH_LIMIT)
        return engine._meta.list_diaries(vault=vault, limit=limit)

    # ── New v0.2.0 endpoints ──

    @app.post("/consolidate")
    async def consolidate(payload: dict[str, Any]):
        vault = _validate_name(payload.get("vault"), "vault") if payload.get("vault") else None
        threshold = min(max(payload.get("threshold", 0.80), 0.0), 1.0)
        dry_run = payload.get("dry_run", False)

        result = engine.consolidate(
            vault=vault,
            similarity_threshold=threshold,
            dry_run=dry_run,
        )
        return {
            "clusters_found": result.clusters_found,
            "memories_merged": result.memories_merged,
            "memories_archived": result.memories_archived,
            "details": result.details[:10] if result.details else [],
        }

    @app.post("/extract")
    async def extract(payload: dict[str, Any]):
        text = payload.get("text", "")
        if not text or not isinstance(text, str):
            raise HTTPException(status_code=400, detail="Text is required")
        if len(text) > MAX_CONTENT_LENGTH:
            raise HTTPException(status_code=400, detail="Text too long")

        vault = _validate_name(payload.get("vault", "main"), "vault")
        shelf = _validate_name(payload.get("shelf", "extracted"), "shelf")
        backend = payload.get("backend", "auto")

        memories = engine.extract_memories(
            conversation=text,
            backend=backend,
            vault=vault,
            shelf=shelf,
        )
        return {
            "extracted": len(memories),
            "memories": [
                {
                    "id": m.id,
                    "content": m.content[:300],
                    "category": m.metadata.get("category", "unknown"),
                    "confidence": m.metadata.get("confidence", 0),
                }
                for m in memories
            ],
        }

    @app.post("/factcheck")
    async def factcheck(payload: dict[str, Any]):
        statement = payload.get("statement", "")
        if not statement or not isinstance(statement, str):
            raise HTTPException(status_code=400, detail="Statement is required")

        vault = _validate_name(payload.get("vault"), "vault") if payload.get("vault") else None
        result = engine.check_fact(statement, vault=vault)
        return {
            "verdict": result.verdict,
            "statement": result.statement,
            "confidence": result.confidence,
            "explanation": result.explanation,
            "matching_memories": result.matching_memories,
            "contradicting_memories": result.contradicting_memories,
        }

    @app.post("/context")
    async def context(payload: dict[str, Any]):
        query = payload.get("query", "")
        if not query or not isinstance(query, str):
            raise HTTPException(status_code=400, detail="Query is required")

        vault = _validate_name(payload.get("vault"), "vault") if payload.get("vault") else None
        max_items = min(payload.get("max_items", 5), MAX_SEARCH_LIMIT)
        context_text = engine.get_context(query=query, vault=vault, max_items=max_items)
        return {"context": context_text, "query": query}

    @app.get("/obsidian")
    async def obsidian_list(vault: str | None = None):
        """List notes in an Obsidian vault."""
        from memorius.cli.obsidian import _resolve_vault_path, _scan_vault
        path = _resolve_vault_path(vault)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Vault not found: {path}")
        notes = _scan_vault(path)
        return {"vault": str(path), "count": len(notes), "notes": notes}

    @app.post("/obsidian/import")
    async def obsidian_import(payload: dict[str, Any]):
        """Import Obsidian notes as memories."""
        from memorius.cli.obsidian import _resolve_vault_path, _scan_vault, _parse_note
        vault_path = _resolve_vault_path(payload.get("vault"))
        if not vault_path.exists():
            raise HTTPException(status_code=404, detail=f"Vault not found: {vault_path}")

        target_vault = _validate_name(payload.get("target_vault", "main"), "vault")
        target_shelf = _validate_name(payload.get("target_shelf", "obsidian"), "shelf")
        dry_run = payload.get("dry_run", False)
        tag_filter = payload.get("tag")

        notes = _scan_vault(vault_path)
        imported = 0
        skipped = 0
        for note in notes:
            if tag_filter and tag_filter not in note.get("tags", []):
                skipped += 1
                continue
            if not dry_run:
                body = _parse_note(note["path"])
                engine.store(
                    content=body,
                    vault=target_vault,
                    shelf=target_shelf,
                    folder=note.get("folder", "default"),
                    note=note["name"],
                    metadata={"source": "obsidian", "tags": note.get("tags", [])},
                )
            imported += 1

        return {"imported": imported, "skipped": skipped, "dry_run": dry_run}

    @app.post("/obsidian/export")
    async def obsidian_export(payload: dict[str, Any]):
        """Export memorius memories as Obsidian notes."""
        from memorius.cli.obsidian import _resolve_vault_path
        vault_path = _resolve_vault_path(payload.get("vault"))
        source_vault = _validate_name(payload.get("source_vault", "main"), "vault")
        source_shelf = payload.get("source_shelf")
        dry_run = payload.get("dry_run", False)

        # Get memories from vault
        results = engine.search(query="", vault=source_vault, shelf=source_shelf, limit=1000)
        exported = 0
        for mem in results:
            note_path = vault_path / mem.vault / mem.shelf / mem.folder / f"{mem.note}.md"
            if not dry_run:
                note_path.parent.mkdir(parents=True, exist_ok=True)
                note_path.write_text(mem.content)
            exported += 1

        return {"exported": exported, "dry_run": dry_run, "vault": str(vault_path)}

    @app.get("/stats")
    async def stats():
        status = engine.status()
        meta_stats = engine.get_memory_stats()
        graph_stats = engine.get_graph_stats()
        return {
            "vault": status,
            "memory_tracking": meta_stats,
            "knowledge_graph": graph_stats,
        }

    print(f"Memorius REST API running on http://{host}:{port}")
    if api_key:
        print("  API key authentication: enabled")
    else:
        print("  API key authentication: disabled (set MEMORIUS_API_KEY to enable)")
    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    except KeyboardInterrupt:
        logger.info("Shutting down REST server")
    finally:
        engine.close()
