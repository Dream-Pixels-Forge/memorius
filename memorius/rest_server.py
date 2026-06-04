"""REST API server for memorius — alternative interface to the MCP server."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("memorius.rest")


def run_rest_server(engine, host: str = "127.0.0.1", port: int = 8912):
    """Start the FastAPI REST server."""
    try:
        from fastapi import FastAPI
        import uvicorn
    except ImportError:
        print("Error: REST server requires extra dependencies. Install: pip install memorius[rest]")
        return

    app = FastAPI(title="Memorius API", version="0.1.0")

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "memorius"}

    @app.post("/store")
    async def store(payload: dict[str, Any]):
        memory = engine.store(
            content=payload["content"],
            vault=payload.get("vault", "main"),
            shelf=payload.get("shelf", "default"),
            folder=payload.get("folder", "default"),
            note=payload.get("note", "default"),
            metadata=payload.get("metadata"),
        )
        return memory.to_dict()

    @app.post("/search")
    async def search(payload: dict[str, Any]):
        results = engine.search(
            query=payload["query"],
            vault=payload.get("vault"),
            shelf=payload.get("shelf"),
            limit=payload.get("limit", 10),
        )
        return {"query": payload["query"], "count": len(results), "results": [m.to_dict() for m in results]}

    @app.post("/mine")
    async def mine(payload: dict[str, Any]):
        memories = engine.mine(
            text=payload["text"],
            vault=payload.get("vault", "main"),
        )
        return {"stored": len(memories), "memory_ids": [m.id for m in memories]}

    @app.get("/status")
    async def status():
        return engine.status()

    @app.post("/diary")
    async def diary(payload: dict[str, Any]):
        entry = engine.write_diary(
            session_id=payload["session_id"],
            vault=payload.get("vault", "main"),
            title=payload.get("title", ""),
            summary=payload.get("summary", ""),
            content=payload.get("content", ""),
            exchange_count=payload.get("exchange_count", 0),
        )
        return entry

    @app.get("/vault")
    async def ls(vault: str = "main"):
        return engine.get_hierarchy(vault)

    @app.get("/diaries")
    async def diaries(vault: str | None = None, limit: int = 10):
        return engine._meta.list_diaries(vault=vault, limit=limit)

    print(f"Memorius REST API running on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
