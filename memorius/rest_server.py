"""REST API server for memorius — alternative interface to the MCP server."""

from __future__ import annotations

import hmac
import logging
import os
import time
from pathlib import Path
from typing import Any

from memorius import __version__ as _memorius_version
from memorius.validation import (
    validate_name as _validate_name,
    validate_session_id as _validate_session_id,
    validate_content as _validate_content,
    MAX_CONTENT_LENGTH,
    MAX_FIELD_LENGTH,
    MAX_SEARCH_LIMIT,
    MAX_DIARY_CONTENT,
)

# Prometheus metrics
try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
    from fastapi import Response
    from fastapi.responses import PlainTextResponse, JSONResponse
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

logger = logging.getLogger("memorius.rest")

# Prometheus metrics objects
if PROMETHEUS_AVAILABLE:
    # Recall latency histogram
    MEMORIUS_RECALL_LATENCY_SECONDS = Histogram(  # pyright: ignore[reportPossiblyUnboundVariable]
        'memorius_recall_latency_seconds',
        'Time spent recalling memories',
        buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
    )
    
    # Consolidation queue size gauge
    MEMORIUS_CONSOLIDATION_QUEUE_SIZE = Gauge(  # pyright: ignore[reportPossiblyUnboundVariable]
        'memorius_consolidation_queue_size',
        'Number of memories pending consolidation'
    )
    
    # Memory utilization score gauge
    MEMORIUS_MEMORY_UTILIZATION_SCORE = Gauge(  # pyright: ignore[reportPossiblyUnboundVariable]
        'memorius_memory_utilization_score',
        'Memory utilization score (0.0 to 1.0)'
    )
    
    # Total memories counter
    MEMORIUS_TOTAL_MEMORIES = Gauge(  # pyright: ignore[reportPossiblyUnboundVariable]
        'memorius_total_memories',
        'Total number of memories in the vault'
    )
    
    # Store operation counter
    MEMORIUS_STORE_OPERATIONS_TOTAL = Counter(  # pyright: ignore[reportPossiblyUnboundVariable]
        'memorius_store_operations_total',
        'Total number of store operations',
        ['result']  # success or failure
    )
    
    # Search operation counter
    MEMORIUS_SEARCH_OPERATIONS_TOTAL = Counter(  # pyright: ignore[reportPossiblyUnboundVariable]
        'memorius_search_operations_total',
        'Total number of search operations',
        ['result']  # success or failure
    )
    
    # Mine operation counter
    MEMORIUS_MINE_OPERATIONS_TOTAL = Counter(  # pyright: ignore[reportPossiblyUnboundVariable]
        'memorius_mine_operations_total',
        'Total number of mine operations',
        ['result']  # success or failure
    )


class MemoriusAPI:
    """FastAPI application with all route handlers as methods.

    This makes routes testable without starting the server.

    Note on rate limiting:
        The in-memory sliding-window rate limiter resets on process restart.
        When using multiple uvicorn workers (``--workers N``), each worker
        has its own counter, so the effective limit is ``N × rate_limit_max``.
        For persistent rate limiting across restarts or workers, use an external
        reverse proxy (nginx, Caddy) or a shared store (Redis).
    """

    def __init__(self, engine):
        self._engine = engine
        self._request_counts: dict[str, list[float]] = {}  # IP -> [timestamps]
        self._rate_limit_max = 500  # requests per minute
        self._rate_limit_window = 60  # seconds
        self._rate_limit_sweep_counter = 0  # periodic cleanup counter
        self._rate_limit_max_ips = 10_000  # max unique IPs tracked before force sweep

    def create_app(self):
        """Build and return the FastAPI app with all routes registered."""
        try:
            from fastapi import FastAPI, Request
            from fastapi.middleware.cors import CORSMiddleware
            from fastapi.responses import JSONResponse
        except ImportError:
            raise ImportError(
                "REST server requires extra dependencies. Install: pip install memorius"
            )

        app = FastAPI(title="Memorius API", version=_memorius_version, debug=False)

        # Configure JSON logging for memorius
        import logging
        import json

        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_record = {
                    "timestamp": self.formatTime(record, self.datefmt),
                    "level": record.levelname,
                    "message": record.getMessage(),
                    "logger": record.name,
                }
                if record.exc_info:
                    log_record["exc_info"] = self.formatException(record.exc_info)
                return json.dumps(log_record)

        # Get the memorius logger
        memorius_logger = logging.getLogger("memorius")
        memorius_logger.setLevel(logging.INFO)
        # Clear existing handlers to avoid duplicate logs
        memorius_logger.handlers.clear()
        # Add stream handler with our formatter
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        memorius_logger.addHandler(handler)

        # CORS — restrictive by default; regex covers dynamic ports
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["app://obsidian.md"],
            allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Global exception handler to catch unexpected errors and return sanitized response
        @app.exception_handler(Exception)
        async def global_exception_handler(request: Request, exc: Exception):
            memorius_logger.exception("Unhandled exception")
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
            )

        # API key authentication
        api_key = os.environ.get("MEMORIUS_API_KEY")
        if api_key and len(api_key) < 16:
            logger.warning(
                "MEMORIUS_API_KEY is shorter than 16 characters — use a longer, randomly generated key."
            )

        @app.middleware("http")
        async def auth_middleware(request: Request, call_next):
            if request.url.path == "/health":
                return await call_next(request)
            if api_key:
                auth_header = request.headers.get("Authorization", "")
                token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
                # Use compare_digest to prevent timing-based key enumeration
                if not hmac.compare_digest(token.encode(), api_key.encode()):
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
            elif request.method in ("POST", "PUT", "PATCH"):
                # Chunked transfer encoding: stream and enforce limit
                chunks: list[bytes] = []
                total = 0
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > MAX_CONTENT_LENGTH:
                        return JSONResponse(status_code=413, content={"detail": "Request body too large"})
                    chunks.append(chunk)
                body = b"".join(chunks)

                async def _receive():
                    return {"type": "http.request", "body": body, "more_body": False}

                request._receive = _receive
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
            # Clean old entries for this IP
            if client_ip in rate_store:
                rate_store[client_ip] = [t for t in rate_store[client_ip] if now - t < rate_window]
            else:
                rate_store[client_ip] = []
            if len(rate_store[client_ip]) >= rate_max:
                return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
            rate_store[client_ip].append(now)
            # Periodic sweep: every 200 requests OR when IP count exceeds limit,
            # evict fully-expired IP entries to prevent unbounded dict growth.
            self._rate_limit_sweep_counter += 1
            force_sweep = len(rate_store) > self._rate_limit_max_ips
            if self._rate_limit_sweep_counter >= 200 or force_sweep:
                self._rate_limit_sweep_counter = 0
                expired_ips = [
                    ip for ip, ts in rate_store.items()
                    if not ts or (now - ts[-1]) > rate_window
                ]
                for ip in expired_ips:
                    del rate_store[ip]
            return await call_next(request)

        # Register all routes
        self._register_routes(app)
        return app

    def _register_routes(self, app):
        """Register all route handlers on the app."""
        from fastapi import HTTPException
        engine = self._engine

        @app.get("/health/live")
        async def health_live():
            """Liveness probe - checks if the process is running."""
            return {"status": "alive", "service": "memorius"}

        @app.get("/health/ready")
        async def health_ready():
            """Readiness probe - checks if dependencies are healthy."""
            try:
                # Check if we can access the database/status
                status = engine.status()
                # Basic check: if we can get status without error, we're ready
                # In a more sophisticated implementation, we'd check DB connections, etc.
                return {
                    "status": "ready", 
                    "service": "memorius",
                    "checks": {
                        "status": "ok",
                        "memories": status.get("memories", 0),
                        "vaults": status.get("vaults", 0)
                    }
                }
            except Exception as e:
                logger.error(f"Readiness check failed: {e}")
                return JSONResponse(  # pyright: ignore[reportPossiblyUnboundVariable]
                    status_code=503,
                    content={"status": "not ready", "service": "memorius", "error": str(e)}
                )

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
            
            # Start timing for operation
            start_time = time.time()
            try:
                memory = engine.store(
                    content=content, vault=vault, shelf=shelf,
                    folder=folder, note=note, metadata=payload.get("metadata"),
                    ttl_days=ttl_days,
                )
                # Record successful store
                if PROMETHEUS_AVAILABLE:
                    MEMORIUS_STORE_OPERATIONS_TOTAL.labels(result="success").inc()
                d = memory.to_dict()
                d.pop("vector", None)
                return d
            except Exception as e:
                # Record failed store
                if PROMETHEUS_AVAILABLE:
                    MEMORIUS_STORE_OPERATIONS_TOTAL.labels(result="failure").inc()
                raise e
            finally:
                # For store operations, we might want to track latency too
                # But the recall latency is specifically for recall operations
                pass

        @app.post("/search")
        async def search(payload: dict[str, Any]):
            query = payload.get("query", "")
            if not query or not isinstance(query, str):
                raise HTTPException(status_code=400, detail="Query is required")
            if len(query) > MAX_FIELD_LENGTH:
                raise HTTPException(status_code=400, detail="Query too long")
            limit = min(payload.get("limit", 10), MAX_SEARCH_LIMIT)
            raw_vault = payload.get("vault")
            vault = _validate_name(raw_vault, "vault") if raw_vault else None
            raw_shelf = payload.get("shelf")
            shelf = _validate_name(raw_shelf, "shelf") if raw_shelf else None
            raw_folder = payload.get("folder")
            folder = _validate_name(raw_folder, "folder") if raw_folder else None
            raw_note = payload.get("note")
            note = _validate_name(raw_note, "note") if raw_note else None
            expand_graph = bool(payload.get("expand_graph", False))
            rerank = bool(payload.get("rerank", False))
            tags_in = payload.get("tags")
            tags = [str(t) for t in tags_in] if isinstance(tags_in, list) and tags_in else None
            
            # Start timing for recall latency metric
            start_time = time.time()
            try:
                results = engine.search(
                    query=query, vault=vault, shelf=shelf, limit=limit,
                    expand_graph=expand_graph, folder=folder, note=note, tags=tags,
                    rerank=rerank,
                )
                # Record successful search
                if PROMETHEUS_AVAILABLE:
                    MEMORIUS_SEARCH_OPERATIONS_TOTAL.labels(result="success").inc()
                out = []
                for m in results:
                    d = m.to_dict()
                    d.pop("vector", None)
                    out.append(d)
                return {"query": query, "count": len(results), "results": out}
            except Exception as e:
                # Record failed search
                if PROMETHEUS_AVAILABLE:
                    MEMORIUS_SEARCH_OPERATIONS_TOTAL.labels(result="failure").inc()
                raise e
            finally:
                # Record recall latency
                if PROMETHEUS_AVAILABLE:
                    MEMORIUS_RECALL_LATENCY_SECONDS.observe(time.time() - start_time)

        @app.post("/mine")
        async def mine(payload: dict[str, Any]):
            text = payload.get("text", "")
            if not text or not isinstance(text, str):
                raise HTTPException(status_code=400, detail="Text is required")
            if len(text) > MAX_CONTENT_LENGTH:
                raise HTTPException(status_code=400, detail="Text too long")
            vault = _validate_name(payload.get("vault", "main"), "vault")
            
            # Start timing for operation
            start_time = time.time()
            try:
                memories = engine.mine(text=text, vault=vault)
                # Record successful mine
                if PROMETHEUS_AVAILABLE:
                    MEMORIUS_MINE_OPERATIONS_TOTAL.labels(result="success").inc()
                return {"stored": len(memories), "memory_ids": [m.id for m in memories]}
            except Exception as e:
                # Record failed mine
                if PROMETHEUS_AVAILABLE:
                    MEMORIUS_MINE_OPERATIONS_TOTAL.labels(result="failure").inc()
                raise e
            finally:
                # Record recall latency for mine operations too (since it involves recall/search)
                if PROMETHEUS_AVAILABLE:
                    MEMORIUS_RECALL_LATENCY_SECONDS.observe(time.time() - start_time)

        @app.get("/status")
        async def status():
            return engine.status()

        @app.post("/diary")
        async def diary(payload: dict[str, Any]):
            try:
                session_id = _validate_session_id(payload.get("session_id", ""))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            vault = _validate_name(payload.get("vault", "main"), "vault")
            content = payload.get("content", "")
            if content and len(content) > MAX_DIARY_CONTENT:
                raise HTTPException(status_code=400, detail="Diary content too long")
            
            # Start timing for operation
            start_time = time.time()
            try:
                entry = engine.write_diary(
                    session_id=session_id, vault=vault,
                    title=payload.get("title", ""), summary=payload.get("summary", ""),
                    content=content, exchange_count=payload.get("exchange_count", 0),
                )
                # Record successful diary write (as a store operation)
                if PROMETHEUS_AVAILABLE:
                    MEMORIUS_STORE_OPERATIONS_TOTAL.labels(result="success").inc()
                return entry
            except Exception as e:
                # Record failed diary write
                if PROMETHEUS_AVAILABLE:
                    MEMORIUS_STORE_OPERATIONS_TOTAL.labels(result="failure").inc()
                raise e
            finally:
                pass

        @app.get("/vault")
        async def ls(vault: str = "main"):
            vault = _validate_name(vault, "vault")
            return engine.get_hierarchy(vault)

        @app.get("/vaults")
        async def vaults():
            """Enumerate vault names with memory counts (powers the bookcase)."""
            return {"vaults": engine.list_vaults()}

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
            raw_vault = payload.get("vault")
            vault = _validate_name(raw_vault, "vault") if raw_vault else None
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
            raw_vault = payload.get("vault")
            vault = _validate_name(raw_vault, "vault") if raw_vault else None
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
            raw_vault = payload.get("vault")
            vault = _validate_name(raw_vault, "vault") if raw_vault else None
            max_items = min(payload.get("max_items", 5), MAX_SEARCH_LIMIT)
            context_text = engine.get_context(query=query, vault=vault, max_items=max_items)
            return {"context": context_text, "query": query}

        @app.get("/obsidian")
        async def obsidian_list(vault: str | None = None):
            from memorius.obsidian import resolve_vault_path, scan_vault
            path = resolve_vault_path(vault)
            home = Path.home().resolve()
            if not str(path).startswith(str(home)):
                raise HTTPException(status_code=400, detail="Vault path must be within the home directory")
            if not path.exists():
                raise HTTPException(status_code=404, detail=f"Vault not found: {path}")
            notes = scan_vault(path)
            return {"vault": str(path), "count": len(notes), "notes": notes}

        @app.post("/obsidian/import")
        async def obsidian_import(payload: dict[str, Any]):
            if not payload.get("confirm", False) and not payload.get("dry_run", False):
                raise HTTPException(status_code=400, detail="Import requires confirm=true or dry_run=true")
            from memorius.obsidian import resolve_vault_path, scan_vault, parse_note
            vault_path = resolve_vault_path(payload.get("vault"))
            home = Path.home().resolve()
            if not str(vault_path).startswith(str(home)):
                raise HTTPException(status_code=400, detail="Vault path must be within the home directory")
            if not vault_path.exists():
                raise HTTPException(status_code=404, detail=f"Vault not found: {vault_path}")
            target_vault = _validate_name(payload.get("target_vault", "main"), "vault")
            target_shelf = _validate_name(payload.get("target_shelf", "obsidian"), "shelf")
            dry_run = payload.get("dry_run", False)
            tag_filter = payload.get("tag")
            notes = scan_vault(vault_path)
            imported = skipped = 0
            for note in notes:
                if tag_filter and tag_filter not in note.get("tags", []):
                    skipped += 1
                    continue
                if not dry_run:
                    body = parse_note(note["path"])
                    engine.store(content=body, vault=target_vault, shelf=target_shelf,
                                 folder=note.get("folder", "default"), note=note["name"],
                                 metadata={"source": "obsidian", "tags": note.get("tags", [])})
                imported += 1
            return {"imported": imported, "skipped": skipped, "dry_run": dry_run}

        @app.post("/obsidian/export")
        async def obsidian_export(payload: dict[str, Any]):
            from memorius.obsidian import resolve_vault_path
            vault_path = resolve_vault_path(payload.get("vault")).resolve()
            home = Path.home().resolve()
            if not str(vault_path).startswith(str(home)):
                raise HTTPException(status_code=400, detail="Vault path must be within the home directory")
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
            
            # Start timing for recall latency
            start_time = time.time()
            try:
                mem = engine.get_memory(memory_id)
                if mem is None:
                    raise HTTPException(status_code=404, detail="Memory not found")
                d = mem.to_dict()
                d.pop("vector", None)
                return d
            except Exception as e:
                raise e
            finally:
                # Record recall latency
                if PROMETHEUS_AVAILABLE:
                    MEMORIUS_RECALL_LATENCY_SECONDS.observe(time.time() - start_time)

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
            
            # Start timing for operation
            start_time = time.time()
            try:
                result = engine.delete(memory_id)
                if not result.get("found", False):
                    raise HTTPException(status_code=404, detail="Memory not found")
                # Record successful delete (as a store operation)
                if PROMETHEUS_AVAILABLE:
                    MEMORIUS_STORE_OPERATIONS_TOTAL.labels(result="success").inc()
                return result
            except Exception as e:
                # Record failed delete
                if PROMETHEUS_AVAILABLE:
                    MEMORIUS_STORE_OPERATIONS_TOTAL.labels(result="failure").inc()
                raise e
            finally:
                pass

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

        @app.get("/graph/data")
        async def graph_data(vault: str | None = None, shelf: str | None = None,
                             relation: str | None = None, min_weight: float = 0.0,
                             limit: int = 500):
            if vault:
                vault = _validate_name(vault, "vault")
            if shelf:
                shelf = _validate_name(shelf, "shelf")
            limit = min(limit, 2000)
            return engine.get_graph_data(
                vault=vault, shelf=shelf, relation=relation,
                min_weight=min_weight, limit=limit,
            )

        @app.get("/graph/view")
        @app.get("/visualize")
        async def graph_view(vault: str | None = None, shelf: str | None = None,
                             relation: str | None = None, min_weight: float = 0.0,
                             limit: int = 500):
            from fastapi.responses import HTMLResponse
            if vault:
                vault = _validate_name(vault, "vault")
            if shelf:
                shelf = _validate_name(shelf, "shelf")
            limit = min(limit, 2000)
            html = engine.export_graph_html(
                vault=vault, shelf=shelf, relation=relation,
                min_weight=min_weight, limit=limit,
            )
            return HTMLResponse(content=html)

        @app.get("/doctor")
        async def doctor():
            from memorius.doctor import run_checks
            return run_checks(engine=engine)

        @app.get("/memories")
        async def list_memories(vault: str | None = None, limit: int = 10, cursor: str | None = None):
            result = engine.list_memories(
                vault=vault, limit=min(limit, 100), with_vectors=False, cursor=cursor,
            )
            memories = result["memories"]
            next_cursor = result["next_cursor"]
            out = []
            for m in memories:
                d = m.to_dict()
                d.pop("vector", None)
                out.append(d)
            return {"count": len(out), "next_cursor": next_cursor, "memories": out}

        @app.get("/metrics")
        async def metrics():
            """Prometheus metrics endpoint."""
            if not PROMETHEUS_AVAILABLE:
                return PlainTextResponse(  # pyright: ignore[reportPossiblyUnboundVariable]
                    "Prometheus client not available. Install: pip install prometheus-client",
                    status_code=503
                )
            
            # Update metrics before serving
            try:
                # Update total memories count
                status = engine.status()
                MEMORIUS_TOTAL_MEMORIES.set(status.get("memories", 0))
                
                # Try to get memory utilization score from engine if available
                memory_utilization = 0.5  # Default placeholder
                if hasattr(engine, 'get_memory_utilization_score'):
                    memory_utilization = engine.get_memory_utilization_score()
                elif hasattr(engine, 'get_memory_stats'):
                    stats = engine.get_memory_stats()
                    # Calculate utilization based on stats if available
                    # This is a placeholder - actual implementation would depend on what stats are available
                    memory_utilization = min(stats.get('total_memories', 0) / 10000.0, 1.0)  # Assume 10k is full
                
                MEMORIUS_MEMORY_UTILIZATION_SCORE.set(memory_utilization)
                
                # Try to get consolidation queue size from engine if available
                consolidation_queue_size = 0  # Default
                if hasattr(engine, 'get_consolidation_queue_size'):
                    consolidation_queue_size = engine.get_consolidation_queue_size()
                elif hasattr(engine, 'consolidation_daemon') and engine.consolidation_daemon:
                    # If we have access to the consolidation daemon
                    if hasattr(engine.consolidation_daemon, 'get_queue_size'):
                        consolidation_queue_size = engine.consolidation_daemon.get_queue_size()
                
                MEMORIUS_CONSOLIDATION_QUEUE_SIZE.set(consolidation_queue_size)
                
            except Exception:
                # If we can't update metrics, still serve what we have
                pass
            
            return Response(  # pyright: ignore[reportPossiblyUnboundVariable]
                content=generate_latest(),  # pyright: ignore[reportPossiblyUnboundVariable]
                media_type=CONTENT_TYPE_LATEST  # pyright: ignore[reportPossiblyUnboundVariable]
            )


def run_rest_server(engine, host: str = "127.0.0.1", port: int = 8912,
                    tls_cert: str | None = None, tls_key: str | None = None):
    """Start the FastAPI REST server.

    Args:
        host: Bind address (default 127.0.0.1).
        port: Listen port (default 8912).
        tls_cert: Optional path to TLS certificate file for HTTPS.
        tls_key: Optional path to TLS private key file for HTTPS.
    """
    try:
        import uvicorn
    except ImportError:
        print("Error: REST server requires uvicorn. Install: pip install memorius")
        return

    api = MemoriusAPI(engine)
    app = api.create_app()

    api_key = os.environ.get("MEMORIUS_API_KEY")
    print(f"Memorius REST API running on http://{host}:{port}")
    if api_key:
        print("  API key authentication: enabled")
    else:
        print("  API key authentication: disabled (set MEMORIUS_API_KEY to enable)")
        if host not in ("127.0.0.1", "localhost", "::1"):
            logger.warning(
                "REST server bound to %s without API key auth — "
                "any LAN-reachable client can access the vault. "
                "Set MEMORIUS_API_KEY or bind to 127.0.0.1.",
                host,
            )
            print("  WARNING: binding to non-localhost without auth — see logs for details")

    ssl_certfile = tls_cert
    ssl_keyfile = tls_key
    if tls_cert and tls_key:
        print("  TLS: enabled")
    elif tls_cert or tls_key:
        print("  WARNING: both --tls-cert and --tls-key required for TLS — running without TLS")

    try:
        uvicorn.run(
            app, host=host, port=port, log_level="info",
            ssl_certfile=ssl_certfile, ssl_keyfile=ssl_keyfile,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down REST server")
    finally:
        engine.close()
