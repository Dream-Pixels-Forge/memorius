"""REST API server for memorius — alternative interface to the MCP server."""

from __future__ import annotations

import logging
import os
from typing import Any

from memorius import __version__ as _memorius_version
from memorius.validation import (
    validate_name as _validate_name,
    validate_content as _validate_content,
    MAX_CONTENT_LENGTH,
    MAX_FIELD_LENGTH,
    MAX_SEARCH_LIMIT,
    MAX_DIARY_CONTENT,
)

logger = logging.getLogger("memorius.rest")


class MemoriusAPI:
    """FastAPI application with all route handlers as methods.

    This makes routes testable without starting the server.
    """

    def __init__(self, engine):
        self._engine = engine
        self._request_counts: dict[str, list[float]] = {}  # IP -> [timestamps]
        self._rate_limit_max = 500  # requests per minute
        self._rate_limit_window = 60  # seconds

    def create_app(self):
        """Build and return the FastAPI app with all routes registered."""
        try:
            from fastapi import FastAPI, Request, HTTPException
            from fastapi.middleware.cors import CORSMiddleware
            from fastapi.responses import JSONResponse
        except ImportError:
            raise ImportError(
                "REST server requires extra dependencies. Install: pip install memorius[rest]"
            )

        app = FastAPI(title="Memorius API", version=_memorius_version)

        # CORS — restrictive by default; regex covers dynamic ports
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["app://obsidian.md"],
            allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # API key authentication
        api_key = os.environ.get("MEMORIUS_API_KEY")

        @app.middleware("http")
        async def auth_middleware(request: Request, call_next):
            if request.url.path == "/health":
                return await call_next(request)
            if api_key:
                auth_header = request.headers.get("Authorization", "")
                if not auth_header.startswith("Bearer ") or auth_header[7:] != api_key:
                    return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
            return await call_next(request)

        @app.middleware("http")
        async def size_limit_middleware(request: Request, call_next):
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > MAX_CONTENT_LENGTH:
                        return JSONResponse(status_code=413, content={"detail": "Request body too large"})
                except ValueError:
                    return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header"})
            return await call_next(request)

        # Rate limiting middleware
        import time as _time
        rate_store = self._request_counts
        rate_max = self._rate_limit_max
        rate_window = self._rate_limit_window

        @app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next):
            # Skip rate limiting for health check
            if request.url.path == "/health":
                return await call_next(request)
            client_ip = request.client.host if request.client else "unknown"
            now = _time.time()
            # Clean old entries
            if client_ip in rate_store:
                rate_store[client_ip] = [t for t in rate_store[client_ip] if now - t < rate_window]
            else:
                rate_store[client_ip] = []
            if len(rate_store[client_ip]) >= rate_max:
                return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
            rate_store[client_ip].append(now)
            return await call_next(request)

        # Register all routes
        self._register_routes(app)
        return app

    def _register_routes(self, app):
        """Register all route handlers on the app."""
        engine = self._engine

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
            ttl_days = payload.get("ttl_days")
            memory = engine.store(
                content=content, vault=vault, shelf=shelf,
                folder=folder, note=note, metadata=payload.get("metadata"),
                ttl_days=ttl_days,
            )
            d = memory.to_dict()
            d.pop("vector", None)
            return d

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
            folder = _validate_name(payload.get("folder"), "folder") if payload.get("folder") else None
            note = _validate_name(payload.get("note"), "note") if payload.get("note") else None
            expand_graph = bool(payload.get("expand_graph", False))
            tags_in = payload.get("tags")
            tags = [str(t) for t in tags_in] if isinstance(tags_in, list) and tags_in else None
            results = engine.search(
                query=query, vault=vault, shelf=shelf, limit=limit,
                expand_graph=expand_graph, folder=folder, note=note, tags=tags,
            )
            out = []
            for m in results:
                d = m.to_dict()
                d.pop("vector", None)
                out.append(d)
            return {"query": query, "count": len(results), "results": out}

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
                session_id=session_id, vault=vault,
                title=payload.get("title", ""), summary=payload.get("summary", ""),
                content=content, exchange_count=payload.get("exchange_count", 0),
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

        @app.post("/consolidate")
        async def consolidate(payload: dict[str, Any]):
            if not payload.get("confirm", False):
                raise HTTPException(status_code=400, detail="Destructive operation requires confirm=true")
            vault = _validate_name(payload.get("vault"), "vault") if payload.get("vault") else None
            threshold = min(max(payload.get("threshold", 0.80), 0.0), 1.0)
            dry_run = payload.get("dry_run", False)
            result = engine.consolidate(vault=vault, similarity_threshold=threshold, dry_run=dry_run)
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
            memories = engine.extract_memories(conversation=text, backend=backend, vault=vault, shelf=shelf)
            return {
                "extracted": len(memories),
                "memories": [{"id": m.id, "content": m.content[:300],
                              "category": m.metadata.get("category", "unknown"),
                              "confidence": m.metadata.get("confidence", 0)} for m in memories],
            }

        @app.post("/factcheck")
        async def factcheck(payload: dict[str, Any]):
            statement = payload.get("statement", "")
            if not statement or not isinstance(statement, str):
                raise HTTPException(status_code=400, detail="Statement is required")
            vault = _validate_name(payload.get("vault"), "vault") if payload.get("vault") else None
            result = engine.check_fact(statement, vault=vault)
            return {
                "verdict": result.verdict, "statement": result.statement,
                "confidence": result.confidence, "explanation": result.explanation,
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
            from memorius.cli.obsidian import _resolve_vault_path, _scan_vault
            path = _resolve_vault_path(vault)
            if not path.exists():
                raise HTTPException(status_code=404, detail=f"Vault not found: {path}")
            notes = _scan_vault(path)
            return {"vault": str(path), "count": len(notes), "notes": notes}

        @app.post("/obsidian/import")
        async def obsidian_import(payload: dict[str, Any]):
            if not payload.get("confirm", False) and not payload.get("dry_run", False):
                raise HTTPException(status_code=400, detail="Import requires confirm=true or dry_run=true")
            from memorius.cli.obsidian import _resolve_vault_path, _scan_vault, _parse_note
            vault_path = _resolve_vault_path(payload.get("vault"))
            if not vault_path.exists():
                raise HTTPException(status_code=404, detail=f"Vault not found: {vault_path}")
            target_vault = _validate_name(payload.get("target_vault", "main"), "vault")
            target_shelf = _validate_name(payload.get("target_shelf", "obsidian"), "shelf")
            dry_run = payload.get("dry_run", False)
            tag_filter = payload.get("tag")
            notes = _scan_vault(vault_path)
            imported = skipped = 0
            for note in notes:
                if tag_filter and tag_filter not in note.get("tags", []):
                    skipped += 1
                    continue
                if not dry_run:
                    body = _parse_note(note["path"])
                    engine.store(content=body, vault=target_vault, shelf=target_shelf,
                                 folder=note.get("folder", "default"), note=note["name"],
                                 metadata={"source": "obsidian", "tags": note.get("tags", [])})
                imported += 1
            return {"imported": imported, "skipped": skipped, "dry_run": dry_run}

        @app.post("/obsidian/export")
        async def obsidian_export(payload: dict[str, Any]):
            from memorius.cli.obsidian import _resolve_vault_path
            vault_path = _resolve_vault_path(payload.get("vault")).resolve()
            source_vault = _validate_name(payload.get("source_vault", "main"), "vault")
            source_shelf = payload.get("source_shelf")
            dry_run = payload.get("dry_run", False)
            results = engine._meta.list_memories_meta(vault=source_vault, limit=100000)
            exported = 0
            for mem in results:
                if source_shelf and mem.get("shelf") != source_shelf:
                    continue
                note_path = (vault_path / mem["vault"] / mem["shelf"] / mem["folder"] / f"{mem['note']}.md").resolve()
                if not str(note_path).startswith(str(vault_path)):
                    raise HTTPException(status_code=400, detail="Path traversal detected")
                if not dry_run:
                    note_path.parent.mkdir(parents=True, exist_ok=True)
                    note_path.write_text(mem["content"])
                exported += 1
            return {"exported": exported, "dry_run": dry_run, "vault": str(vault_path)}

        @app.get("/contradictions/{memory_id}")
        async def contradictions(memory_id: str):
            from memorius.validation import validate_memory_id as _vid
            try:
                memory_id = _vid(memory_id)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            contradictions = engine.get_contradictions(memory_id)
            out = []
            for m in contradictions:
                d = m.to_dict()
                d.pop("vector", None)
                out.append(d)
            return {
                "memory_id": memory_id,
                "count": len(contradictions),
                "contradictions": out,
            }

        @app.get("/memory/{memory_id}")
        async def get_memory(memory_id: str):
            from memorius.validation import validate_memory_id as _vid
            try:
                memory_id = _vid(memory_id)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            mem = engine.get_memory(memory_id)
            if mem is None:
                raise HTTPException(status_code=404, detail="Memory not found")
            d = mem.to_dict()
            d.pop("vector", None)
            return d

        @app.patch("/memory/{memory_id}")
        async def update_memory(memory_id: str, payload: dict[str, Any]):
            from memorius.validation import validate_memory_id as _vid
            try:
                memory_id = _vid(memory_id)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            content = payload.get("content")
            if content is not None:
                if not isinstance(content, str) or not content.strip():
                    raise HTTPException(status_code=400, detail="Content must be a non-empty string")
                if len(content) > MAX_CONTENT_LENGTH:
                    raise HTTPException(status_code=400, detail="Content too long")
            metadata = payload.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                raise HTTPException(status_code=400, detail="Metadata must be an object")
            mem = engine.update_memory(memory_id, content=content, metadata=metadata)
            if mem is None:
                raise HTTPException(status_code=404, detail="Memory not found")
            d = mem.to_dict()
            d.pop("vector", None)
            return d

        @app.delete("/memory/{memory_id}")
        async def delete_memory(memory_id: str):
            from memorius.validation import validate_memory_id as _vid
            try:
                memory_id = _vid(memory_id)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            result = engine.delete(memory_id)
            if not result.get("found", False):
                raise HTTPException(status_code=404, detail="Memory not found")
            return result

        @app.post("/prune")
        async def prune(payload: dict[str, Any]):
            threshold = float(payload.get("threshold", 0.1))
            dry_run = bool(payload.get("dry_run", True))
            archive = bool(payload.get("archive", True))
            return engine.prune(threshold=threshold, dry_run=dry_run, archive=archive)

        @app.get("/stats")
        async def stats():
            status = engine.status()
            meta_stats = engine.get_memory_stats()
            graph_stats = engine.get_graph_stats()
            return {"vault": status, "memory_tracking": meta_stats, "knowledge_graph": graph_stats}

        @app.get("/doctor")
        async def doctor():
            from memorius.doctor import run_checks
            return run_checks(engine=engine)


def run_rest_server(engine, host: str = "127.0.0.1", port: int = 8912):
    """Start the FastAPI REST server."""
    try:
        import uvicorn
    except ImportError:
        print("Error: REST server requires extra dependencies. Install: pip install memorius[rest]")
        return

    api = MemoriusAPI(engine)
    app = api.create_app()

    api_key = os.environ.get("MEMORIUS_API_KEY")
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
