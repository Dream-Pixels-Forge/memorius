"""REST API server for memorius — alternative interface to the MCP server."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("memorius.rest")


def create_app(engine):
    """Create a FastAPI application wrapping the palace engine."""
    try:
        from fastapi import FastAPI, HTTPException
        from pydantic import BaseModel
    except ImportError:
        raise ImportError(
            "fastapi not installed. Install: pip install memorius[rest]"
        )

    app = FastAPI(
        title="Memorius",
        description="Memory palace REST API — store, search, and manage memories for any AI agent.",
        version="0.1.0",
    )

    # ── Request models ──

    class StoreRequest(BaseModel):
        content: str
        palace: str = "main"
        wing: str = "default"
        room: str = "default"
        drawer: str = "default"
        metadata: dict[str, Any] = {}

    class SearchRequest(BaseModel):
        query: str
        n_results: int = 10
        palace: str | None = None
        wing: str | None = None

    class MineRequest(BaseModel):
        transcript: str
        palace: str = "main"

    class DiaryRequest(BaseModel):
        session_id: str
        title: str = ""
        summary: str = ""
        content: str = ""
        exchange_count: int = 0
        palace: str = "main"

    # ── Endpoints ──

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/status")
    def status():
        return engine.status()

    @app.post("/store")
    def store(req: StoreRequest):
        memory = engine.store(
            content=req.content,
            palace=req.palace,
            wing=req.wing,
            room=req.room,
            drawer=req.drawer,
            metadata=req.metadata,
        )
        return {"id": memory.id, "path": f"{memory.wing}/{memory.room}/{memory.drawer}"}

    @app.post("/search")
    def search(req: SearchRequest):
        results = engine.search(
            query=req.query,
            palace=req.palace,
            wing=req.wing,
            n_results=req.n_results,
        )
        return {
            "query": req.query,
            "count": len(results),
            "results": [m.to_dict() for m in results],
        }

    @app.post("/mine")
    def mine(req: MineRequest):
        memories = engine.mine(
            transcript=req.transcript,
            palace=req.palace,
        )
        return {"stored": len(memories), "memory_ids": [m.id for m in memories]}

    @app.get("/palace")
    def list_palaces():
        return {"palaces": engine._meta.list_palaces()}

    @app.get("/palace/{name}")
    def get_palace(name: str):
        return engine.hierarchy(name)

    @app.get("/palace/{name}/wings")
    def list_wings(name: str):
        return {"wings": engine._meta.list_wings(name)}

    @app.get("/palace/{palace}/{wing}/rooms")
    def list_rooms(palace: str, wing: str):
        return {"rooms": engine._meta.list_rooms(palace, wing)}

    @app.get("/palace/{palace}/{wing}/{room}/drawers")
    def list_drawers(palace: str, wing: str, room: str):
        return {"drawers": engine._meta.list_drawers(palace, wing, room)}

    @app.post("/diary")
    def write_diary(req: DiaryRequest):
        entry = engine.write_diary(
            session_id=req.session_id,
            palace=req.palace,
            title=req.title,
            summary=req.summary,
            content=req.content,
            exchange_count=req.exchange_count,
        )
        return {"id": entry["id"], "session_id": entry["session_id"]}

    @app.get("/diaries")
    def list_diaries(limit: int = 10, palace: str | None = None):
        diaries = engine._meta.list_diaries(palace=palace, limit=limit)
        return {"count": len(diaries), "diaries": diaries}

    return app


def run_rest_server(engine, host: str = "127.0.0.1", port: int = 8912):
    """Run the REST API server."""
    import uvicorn
    app = create_app(engine)
    logger.info(f"REST server starting on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
