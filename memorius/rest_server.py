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
