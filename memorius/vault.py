"""Vault engine — high-level orchestrator for memorius.

Combines ChromaDB vector store + SQLite metadata store into a unified
interface. The actual store implementations live in:
  - memorius/vector_store.py (ChromaStore)
  - memorius/meta_store.py   (SQLiteStore)

Hierarchy: Vault > Shelf > Folder > Note
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from memorius.embeddings import EmbeddingFactory, EmbeddingProvider
from memorius.config import load_config
from memorius.validation import validate_memory_id
from memorius.models import Memory  # noqa: F401
from memorius.vector_store import ChromaStore
from memorius.vector_store_base import VectorStore
from memorius.meta_store import SQLiteStore

logger = logging.getLogger("memorius")



# ── Vault Engine ────────────────────────────────────────────────────────────


class VaultEngine:
    """High-level vault operations combining vector + metadata stores.

    Supports use as a context manager for clean resource cleanup:

        with VaultEngine(config) as engine:
            engine.store("hello")
        # connections closed automatically
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or load_config()
        embed_cfg = self._config.get("embeddings", {})
        storage_cfg = self._config.get("storage", {})

        self._embed = EmbeddingFactory.create(embed_cfg)
        storage_path = Path(storage_cfg.get("path", "~/.memorius/data")).expanduser()
        storage_type = storage_cfg.get("type", "chroma")
        if storage_type == "sqlite-vec":
            from memorius.sqlite_vec_store import SqliteVecStore
            self._vector = SqliteVecStore(storage_path / "vectors", self._embed)
        else:
            self._vector = ChromaStore(storage_path / "vectors", self._embed)
        self._meta = SQLiteStore(storage_path)
        self._search_mod = None  # lazy init
        self._store_mod = None  # lazy init

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        """Release all resources (DB connections, ChromaDB client)."""
        try:
            self._meta.close_connection(self._meta._db_path)
        except Exception:  # best-effort: prevent cleanup errors from propagating
            pass
        self._vector = None

    def __del__(self):
        self.close()

    @property
    def embed(self) -> EmbeddingProvider:
        return self._embed

    @property
    def vector(self) -> VectorStore:
        return self._vector

    @property
    def meta(self) -> SQLiteStore:
        return self._meta

    # ── Private helpers ──

    def _get_store_module(self):
        """Lazy-init and return the StoreModule singleton."""
        if self._store_mod is None:
            from memorius.store_module import StoreModule
            self._store_mod = StoreModule(self._vector, self._meta)
        return self._store_mod

    def _get_search_module(self):
        """Lazy-init and return the SearchModule singleton."""
        if self._search_mod is None:
            from memorius.search_module import SearchModule
            self._search_mod = SearchModule(self._vector, self._meta)
        return self._search_mod

    # ── Memory operations ──

    def store(self, content: str, vault: str = "main", shelf: str = "default",
              folder: str = "default", note: str = "default",
              metadata: dict[str, Any] | None = None,
              ttl_days: int | None = None,
              _vector: list[float] | None = None) -> Memory:
        """Store a memory in the vault.

        Args:
            ttl_days: optional time-to-live in days. When set, the memory
                becomes eligible for archival after this many days regardless
                of access count. Stored as ``expires_at`` ISO timestamp in
                metadata.
            _vector: pre-computed embedding vector (internal use for batch ops).
        """
        return self._get_store_module().store(
            content, vault=vault, shelf=shelf, folder=folder, note=note,
            metadata=metadata, ttl_days=ttl_days, _vector=_vector,
        )

    def search(self, query: str, vault: str | None = None,
               shelf: str | None = None, limit: int = 10,
               expand_graph: bool = False, graph_hops: int = 1,
               graph_min_weight: float = 0.3,
               folder: str | None = None, note: str | None = None,
               tags: list[str] | None = None,
               rerank: bool = False) -> list[Memory]:
        """Search vault contents by semantic similarity with temporal decay
        ranking.

        When ``expand_graph=True``, after the primary ranked results are
        selected, walk the knowledge graph up to ``graph_hops`` hops from
        each seed memory and append linked memories (deduped against the
        seeds) so the caller also sees "what's connected to this". The
        total returned size is capped at ``ceil(limit * 1.5)``.

        Optional metadata filters narrow the primary vector matches:

          - ``folder`` / ``note`` restrict to memories stored under that
            folder/note path. ChromaDB surfaces these as ``where`` clauses
            on metadata fields already written by ``ChromaStore.add``.
          - ``tags`` is a list of tags; a memory matches only if it carries
            ALL of them in its metadata ``tags`` list. ChromaDB's ``where``
            cannot test list membership, so tags are post-filtered in
            Python after the vector query (over all ``n_results`` hits, so
            the limit is still honored when the universe shrinks).
        """
        return self._get_search_module().search(
            query, vault=vault, shelf=shelf, limit=limit,
            expand_graph=expand_graph, graph_hops=graph_hops,
            graph_min_weight=graph_min_weight, folder=folder, note=note,
            tags=tags, rerank=rerank,
        )

    def touch(self, memory_id: str) -> None:
        """Explicitly mark a memory as accessed (reinforce it).

        Use when an agent actually reads/uses a memory and you want the
        reinforcement model to credit it. Idempotent: safe to call on
        a missing id (no-op)."""
        self._get_store_module().touch(memory_id)

    def get_memories_by_ids(self, ids: list[str],
                            with_vectors: bool = True) -> list[Memory]:
        """Fetch memories by exact ID. Vectors are pulled from ChromaDB only
        when ``with_vectors=True``. Memories whose meta row is missing or
        whose vector is unfetchable are skipped."""
        return self._get_store_module().get_by_ids(ids, with_vectors=with_vectors)

    def get_contradictions(self, memory_id: str) -> list[Memory]:
        """Return memories that contradict ``memory_id`` in the knowledge
        graph (edges with relation='contradicts', created by `check_fact`
        when a statement surfaces both a corroborating and a contradicting
        memory about the same claim). Returns an empty list when the memory
        is unknown or has no recorded contradictions."""
        try:
            validate_memory_id(memory_id)
            self._meta.init_graph()
            edges = self._meta.get_linked(memory_id, relation="contradicts")
        except Exception:  # best-effort: graph/meta failure should not break contradiction lookup
            logger.debug("get_contradictions(%s) failed (best-effort)", memory_id)
            return []
        contra_ids = [e["target_id"] for e in edges]
        if not contra_ids:
            return []
        return self.get_memories_by_ids(contra_ids, with_vectors=False)

    # ── CRUD: get / update / delete ──

    def get_memory(self, memory_id: str) -> Memory | None:
        """Fetch a single memory by ID. Returns None when the id is invalid
        or the memory does not exist."""
        return self._get_store_module().get(memory_id)

    def update_memory(self, memory_id: str, content: str | None = None,
                      metadata: dict[str, Any] | None = None) -> Memory | None:
        """Update a memory's content and/or metadata.  When ``content``
        changes the vector is re-embedded and upserted into ChromaDB.  When
        ``metadata`` is provided it is shallow-merged with the existing
        metadata dict (new keys overwrite, existing keys without a new
        value are preserved).  Returns the updated Memory or None when the
        id is invalid / not found."""
        return self._get_store_module().update(memory_id, content=content, metadata=metadata)

    def list_memories(self, vault: str | None = None, shelf: str | None = None,
                      limit: int | None = None, with_vectors: bool = True,
                      cursor: str | None = None) -> dict[str, Any]:
        """List memories by metadata (time-recency), optionally filling vectors
        from the ChromaStore. Avoids the misuse of empty-query search as
        "list all". Returns Memories ordered by created_at DESC from the meta
        store.

        Returns a dict with keys:
            - memories: list of Memory objects
            - next_cursor: ISO timestamp of the last memory (use as cursor
              for the next page), or None if no more results
        """
        return self._get_store_module().list_memories(
            vault=vault, shelf=shelf, limit=limit,
            with_vectors=with_vectors, cursor=cursor,
        )

    def list_diaries(self, vault: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """List recent diary entries."""
        return self._meta.list_diaries(vault=vault, limit=limit)

    def delete(self, memory_id: str, vault: str | None = None,
               shelf: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        """Delete a memory by ID, with validation and an optional dry-run.

        Args:
            memory_id: UUID of the memory to delete.
            vault: Optional vault scope. If given, must match the memory's
                actual vault (prevents deleting the wrong memory when IDs
                are scoped to a vault).
            shelf: Optional shelf scope. If given, must match the memory's
                actual shelf.
            dry_run: If True, return what *would* be deleted without deleting.

        Returns:
            dict with keys: found, deleted, memory_id, vault, shelf, folder,
            note, content.

        Raises:
            ValueError: if memory_id is invalid/missing, or if a provided
                vault/shelf does not match the memory's actual location.
        """
        return self._get_store_module().delete(memory_id, vault=vault, shelf=shelf, dry_run=dry_run)

    def mine(self, text: str, vault: str = "main", shelf: str = "conversations",
             folder: str = "mined", note: str = "transcript") -> list[Memory]:
        """Extract memories from a transcript by splitting into chunks.

        Uses batch embedding — all chunks are embedded in a single call
        for better throughput on large transcripts.
        """
        import re
        chunks = [c.strip() for c in re.split(r'\n{2,}', text.strip()) if c.strip()]
        if not chunks:
            return []

        # Batch embed all chunks at once
        vectors = self._embed.embed(chunks)

        memories = []
        for chunk, vec in zip(chunks, vectors):
            m = self.store(chunk, vault=vault, shelf=shelf, folder=folder, note=note,
                          _vector=vec)
            memories.append(m)
        return memories

    def write_diary(self, session_id: str, title: str = "", summary: str = "",
                    content: str = "", vault: str = "main",
                    exchange_count: int = 0) -> dict[str, Any]:
        """Write a diary entry for a session."""
        return self._meta.write_diary(
            session_id=session_id,
            vault=vault,
            title=title,
            summary=summary,
            content=content,
            exchange_count=exchange_count,
        )

    def status(self) -> dict[str, Any]:
        """Return vault status."""
        vaults = self._meta.list_vaults()
        total_memories = self._vector.count()
        return {
            "memories": total_memories,
            "vaults": len(vaults),
            "embedding_provider": type(self._embed).__name__,
            "embedding_dimension": getattr(self._embed, "dimension", 384),
        }

    def get_hierarchy(self, vault: str) -> dict[str, Any]:
        return self._meta.get_hierarchy(vault)

    # ── Feature methods (v0.2.0) ──

    def consolidate(self, vault: str | None = None, similarity_threshold: float = 0.80,
                    dry_run: bool = False):
        """Run memory consolidation — merge duplicates, extract insights."""
        from memorius.consolidation import consolidate as _consolidate
        return _consolidate(self, vault=vault, similarity_threshold=similarity_threshold,
                           dry_run=dry_run)

    def extract_memories(self, conversation: str, backend: str = "auto",
                         vault: str = "main", shelf: str = "extracted"):
        """Extract structured memories from a conversation using LLM."""
        from memorius.llm_extract import extract_memories as _extract, format_for_storage
        extracted = _extract(conversation, backend=backend)
        stored = []
        for item in format_for_storage(extracted):
            mem = self.store(item["content"], vault=vault, shelf=shelf,
                           metadata=item["metadata"])
            stored.append(mem)
        return stored

    def check_fact(self, statement: str, vault: str | None = None):
        """Fact-check a statement against stored memories."""
        from memorius.factcheck import check_statement
        return check_statement(self, statement, vault=vault)

    def get_context(self, query: str, vault: str | None = None,
                    max_items: int = 5) -> str:
        """Get formatted memory context for injection."""
        from memorius.context_inject import ContextInjector
        injector = ContextInjector(self)
        return injector.inject(query, vault=vault, max_items=max_items)

    def get_session_profile(self, session_id: str, vault: str = "main"):
        """Build a session memory profile for inheritance."""
        from memorius.session import build_session_profile
        return build_session_profile(self, session_id, vault)

    def get_graph_stats(self) -> dict:
        """Get knowledge graph statistics."""
        return self._meta.get_graph_stats()

    def get_graph_data(self, vault: str | None = None, shelf: str | None = None,
                       relation: str | None = None, min_weight: float = 0.0,
                       limit: int = 500) -> dict[str, Any]:
        """Fetch complete graph topology (nodes and edges) for visualization."""
        return self._meta.get_graph_data(
            vault=vault, shelf=shelf, relation=relation,
            min_weight=min_weight, limit=limit,
        )

    def export_graph_html(self, dest: str | None = None, vault: str | None = None,
                          shelf: str | None = None, relation: str | None = None,
                          min_weight: float = 0.0, limit: int = 500,
                          title: str = "Memorius Knowledge Graph") -> str:
        """Render graph visualization to an interactive HTML string or file.

        Args:
            dest: Optional file path to save HTML. If omitted, returns HTML string.
            vault: Optional vault filter.
            shelf: Optional shelf filter.
            relation: Optional relation filter.
            min_weight: Minimum edge weight filter.
            limit: Maximum nodes to render.
            title: HTML page title.

        Returns:
            The HTML content string.
        """
        from pathlib import Path
        from memorius.graph_visualizer import render_graph_html

        graph_data = self.get_graph_data(
            vault=vault, shelf=shelf, relation=relation,
            min_weight=min_weight, limit=limit,
        )
        html_content = render_graph_html(graph_data, title=title)
        if dest:
            out_path = Path(dest)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(html_content, encoding="utf-8")
        return html_content

    def get_memory_stats(self) -> dict:
        """Get memory tracking statistics."""
        return self._meta.get_memory_stats()

    def prune(self, threshold: float = 0.1, dry_run: bool = False,
              archive: bool = True) -> dict[str, Any]:
        """Find stale memories and optionally soft-archive them.

        Args:
            threshold: decay-score threshold below which memories are stale.
            dry_run: list candidates without touching them.
            archive: if True (default) soft-archives; if False hard-deletes.

        Returns:
            dict with keys: stale (list of candidates), count,
            dry_run, archived_count.
        """
        stale = self._meta.find_stale_memories(threshold=threshold)
        result: dict[str, Any] = {
            "stale": [
                {"id": s["id"], "content": (s.get("content") or "")[:200],
                 "vault": s["vault"], "shelf": s["shelf"],
                 "decay_score": round(s.get("decay_score", 0.0), 4)}
                for s in stale
            ],
            "count": len(stale),
            "dry_run": dry_run,
            "archived_count": 0,
        }
        if dry_run or not stale:
            return result
        ids = [s["id"] for s in stale]
        if archive:
            self._meta.archive_memories(ids)
            result["archived_count"] = len(ids)
        else:
            for mid in ids:
                self.delete(mid)
            result["archived_count"] = len(ids)
        return result
