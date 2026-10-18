"""Vault engine — high-level orchestrator for memorius.

Combines ChromaDB vector store + SQLite metadata store into a unified
interface. The actual store implementations live in:
  - memorius/vector_store.py (ChromaStore)
  - memorius/meta_store.py   (SQLiteStore)

Hierarchy: Vault > Shelf > Folder > Note
"""

from __future__ import annotations

import json
import logging
import math
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
        
        # Create separate stores for episodic and semantic memories.
        # The semantic (primary) store keeps its LEGACY location so existing
        # vaults — and any tool that opens <storage>/memorius.db or the
        # "vectors" directory directly — keep working; only the episodic
        # store gets new subdirectories.
        if storage_type == "sqlite-vec":
            from memorius.sqlite_vec_store import SqliteVecStore
            self._vector_episodic = SqliteVecStore(storage_path / "vectors_episodic", self._embed)
            self._vector_semantic = SqliteVecStore(storage_path / "vectors", self._embed)
        else:
            self._vector_episodic = ChromaStore(storage_path / "vectors_episodic", self._embed, self._config)
            self._vector_semantic = ChromaStore(storage_path / "vectors", self._embed, self._config)

        # Separate metadata stores (legacy path for semantic →
        # <storage>/memorius.db, same as the pre-split single store)
        self._meta_episodic = SQLiteStore(storage_path / "meta_episodic")
        self._meta_semantic = SQLiteStore(storage_path)
        
        self._search_mod = None  # lazy init (semantic SearchModule)
        self._search_mod_episodic = None  # lazy init (episodic SearchModule)
        self._store_mod = None  # lazy init
        self._store_mod_episodic = None  # lazy init for episodic store
        self._store_mod_semantic = None  # lazy init for semantic store

        # Backward-compatible aliases — the semantic store is the primary
        # store. Internal features (knowledge graph, learning, backup,
        # doctor, consolidation, prune, diaries), the public `vector`/`meta`
        # properties, and StoreModule/SearchModule wiring all operate on the
        # semantic store; the episodic store only holds raw interaction
        # traces routed from `mine()`.
        self._meta = self._meta_semantic
        self._vector = self._vector_semantic

        cons_cfg = self._config.get("consolidation", {})
        if cons_cfg.get("enabled", False):
            from memorius.consolidation import ConsolidationDaemon
            self._consolidation_daemon = ConsolidationDaemon(
                meta_store=self._meta,
                vector_store=self._vector,
                config=self._config,
            )
            self._consolidation_daemon.start()
        else:
            self._consolidation_daemon = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        """Release all resources (DB connections, ChromaDB client)."""
        if self._consolidation_daemon is not None:
            self._consolidation_daemon.stop()
            self._consolidation_daemon.join(timeout=2)
            self._consolidation_daemon = None
        try:
            self._meta.close_connection(self._meta._db_path)
        except Exception:  # best-effort: prevent cleanup errors from propagating
            pass
        try:
            self._meta_episodic.close_connection(self._meta_episodic._db_path)
        except Exception:  # best-effort: prevent cleanup errors from propagating
            pass
        self._vector = None
        self._vector_episodic = None
        self._vector_semantic = None

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

    def _get_store_module_for_memory(self, shelf: str, folder: str, note: str):
        """Get the appropriate store module based on memory origin.
        
        Raw interaction traces (from mine) go to episodic store:
          - shelf="conversations", folder="mined", note="transcript"
          
        Distilled facts (from extract or manual storage) go to semantic store:
          - Everything else
        """
        # Check if this is a raw interaction trace from the mine method
        if (shelf == "conversations" and folder == "mined" and note == "transcript"):
            if self._store_mod_episodic is None:
                from memorius.store_module import StoreModule
                self._store_mod_episodic = StoreModule(self._vector_episodic, self._meta_episodic)
            return self._store_mod_episodic
        else:
            # Everything else goes to semantic store
            if self._store_mod_semantic is None:
                from memorius.store_module import StoreModule
                self._store_mod_semantic = StoreModule(self._vector_semantic, self._meta_semantic)
            return self._store_mod_semantic
    
    def _get_search_module(self):
        """Lazy-init and return the SearchModule singleton.
        
        For search, we need to query both stores and merge results.
        """
        if self._search_mod is None:
            from memorius.search_module import SearchModule
            self._search_mod = SearchModule(self._vector_semantic, self._meta_semantic)
        return self._search_mod

    def _get_search_module_episodic(self):
        """Lazy-init and return the episodic SearchModule."""
        if self._search_mod_episodic is None:
            from memorius.search_module import SearchModule
            self._search_mod_episodic = SearchModule(self._vector_episodic, self._meta_episodic)
        return self._search_mod_episodic

    def _get_store_module_episodic(self):
        """Lazy-init and return the episodic StoreModule (raw traces)."""
        if self._store_mod_episodic is None:
            from memorius.store_module import StoreModule
            self._store_mod_episodic = StoreModule(self._vector_episodic, self._meta_episodic)
        return self._store_mod_episodic

    def _get_store_module_semantic(self):
        """Lazy-init and return the semantic StoreModule (distilled facts)."""
        if self._store_mod_semantic is None:
            from memorius.store_module import StoreModule
            self._store_mod_semantic = StoreModule(self._vector_semantic, self._meta_semantic)
        return self._store_mod_semantic

    def _get_store_module(self):
        """Lazy-init and return the primary (semantic) StoreModule.

        Backward-compatible accessor: callers that predate the episodic/
        semantic split expect a single store module wired to the default
        store.
        """
        return self._get_store_module_semantic()

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
        # Route to appropriate store based on memory origin
        store_module = self._get_store_module_for_memory(shelf, folder, note)
        return store_module.store(
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
        # Search both stores: semantic is primary and keeps its internal
        # ranking (temporal decay + optional graph expansion appended at the
        # end by SearchModule); episodic hits are merged in afterwards.
        semantic_results = self._get_search_module().search(
            query, vault=vault, shelf=shelf, limit=limit,
            expand_graph=expand_graph, graph_hops=graph_hops,
            graph_min_weight=graph_min_weight, folder=folder, note=note,
            tags=tags, rerank=rerank,
        )
        try:
            episodic_results = self._get_search_module_episodic().search(
                query, vault=vault, shelf=shelf, limit=limit,
                expand_graph=expand_graph, graph_hops=graph_hops,
                graph_min_weight=graph_min_weight, folder=folder, note=note,
                tags=tags, rerank=rerank,
            )
        except Exception:  # best-effort: episodic search failure must not break search
            logger.debug("Episodic search failed (best-effort)")
            episodic_results = []

        def _dist(m: Memory) -> float:
            d = (m.metadata or {}).get("__distance__")
            try:
                return float(d) if d is not None else 1.0
            except (TypeError, ValueError):
                return 1.0

        # Merge: semantic results keep their ranked order; unseen episodic
        # hits are appended by ascending cosine distance.
        seen_ids = {m.id for m in semantic_results}
        merged = list(semantic_results)
        merged.extend(
            m for m in sorted(episodic_results, key=_dist)
            if m.id not in seen_ids
        )

        cap = math.ceil(limit * 1.5) if expand_graph else limit
        return merged[:cap]

    def touch(self, memory_id: str) -> None:
        """Explicitly mark a memory as accessed (reinforce it).

        Use when an agent actually reads/uses a memory and you want the
        reinforcement model to credit it. Idempotent: safe to call on
        a missing id (no-op)."""
        # Try episodic store first
        episodic_module = self._get_store_module_episodic()
        episodic_module.touch(memory_id)
        # Also try semantic store (idempotent, so safe to call even if not there)
        semantic_module = self._get_store_module_semantic()
        semantic_module.touch(memory_id)

    def get_memories_by_ids(self, ids: list[str],
                            with_vectors: bool = True) -> list[Memory]:
        """Fetch memories by exact ID. Vectors are pulled from ChromaDB only
        when ``with_vectors=True``. Memories whose meta row is missing or
        whose vector is unfetchable are skipped."""
        # Check both episodic and semantic stores
        episodic_module = self._get_store_module_episodic()
        semantic_module = self._get_store_module_semantic()
        
        episodic_results = episodic_module.get_by_ids(ids, with_vectors=with_vectors)
        semantic_results = semantic_module.get_by_ids(ids, with_vectors=with_vectors)
        
        # Combine results, preferring semantic if duplicate IDs exist (semantic is more authoritative)
        seen_ids = set()
        combined_results = []
        
        # Add semantic results first
        for mem in semantic_results:
            if mem.id not in seen_ids:
                seen_ids.add(mem.id)
                combined_results.append(mem)
        
        # Add episodic results that aren't already in semantic
        for mem in episodic_results:
            if mem.id not in seen_ids:
                seen_ids.add(mem.id)
                combined_results.append(mem)
                
        return combined_results

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
        # Check episodic store first, then semantic
        episodic_module = self._get_store_module_episodic()
        mem = episodic_module.get(memory_id)
        if mem is not None:
            return mem
            
        semantic_module = self._get_store_module_semantic()
        return semantic_module.get(memory_id)

    def update_memory(self, memory_id: str, content: str | None = None,
                      metadata: dict[str, Any] | None = None) -> Memory | None:
        """Update a memory's content and/or metadata.  When ``content``
        changes the vector is re-embedded and upserted into ChromaDB.  When
        ``metadata`` is provided it is shallow-merged with the existing
        metadata dict (new keys overwrite, existing keys without a new
        value are preserved).  Returns the updated Memory or None when the
        id is invalid / not found."""
        # Try episodic store first
        episodic_module = self._get_store_module_episodic()
        result = episodic_module.update(memory_id, content=content, metadata=metadata)
        if result is not None:
            return result
            
        # If not found in episodic, try semantic store
        semantic_module = self._get_store_module_semantic()
        return semantic_module.update(memory_id, content=content, metadata=metadata)

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
        # Get results from both stores
        episodic_module = self._get_store_module_episodic()
        semantic_module = self._get_store_module_semantic()
        
        episodic_result = episodic_module.list_memories(
            vault=vault, shelf=shelf, limit=limit,
            with_vectors=with_vectors, cursor=cursor,
        )
        semantic_result = semantic_module.list_memories(
            vault=vault, shelf=shelf, limit=limit,
            with_vectors=with_vectors, cursor=cursor,
        )
        
        # Combine and sort by created_at DESC
        episodic_memories = episodic_result.get("memories", [])
        semantic_memories = semantic_result.get("memories", [])
        all_memories = episodic_memories + semantic_memories
        
        # Sort by created_at DESC (most recent first)
        all_memories.sort(key=lambda m: m.created_at or "", reverse=True)
        
        # Apply limit if specified
        if limit is not None:
            all_memories = all_memories[:limit]
            
        # For simplicity, we'll use the semantic store's next_cursor
        # In a more sophisticated implementation, we'd need to merge cursors properly
        return {
            "memories": all_memories,
            "next_cursor": semantic_result.get("next_cursor"),
        }

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
        # Try episodic store first
        episodic_module = self._get_store_module_episodic()
        result = episodic_module.delete(memory_id, vault=vault, shelf=shelf, dry_run=dry_run)
        if result.get("found", False):
            return result
            
        # If not found in episodic, try semantic store
        semantic_module = self._get_store_module_semantic()
        return semantic_module.delete(memory_id, vault=vault, shelf=shelf, dry_run=dry_run)

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
        return self._meta_semantic.write_diary(
            session_id=session_id,
            vault=vault,
            title=title,
            summary=summary,
            content=content,
            exchange_count=exchange_count,
        )

    def status(self) -> dict[str, Any]:
        """Return vault status."""
        # Get vaults from both stores and take union (list_vaults returns
        # a list of dicts — extract the names for the set union).
        episodic_vaults = {v["name"] for v in self._meta_episodic.list_vaults()}
        semantic_vaults = {v["name"] for v in self._meta_semantic.list_vaults()}
        all_vaults = episodic_vaults.union(semantic_vaults)
        # Get total memories from both stores
        episodic_count = self._vector_episodic.count()
        semantic_count = self._vector_semantic.count()
        total_memories = episodic_count + semantic_count
        return {
            "memories": total_memories,
            "vaults": len(all_vaults),
            "embedding_provider": type(self._embed).__name__,
            "embedding_dimension": getattr(self._embed, "dimension", 384),
        }

    def list_vaults(self) -> list[dict[str, Any]]:
        """Enumerate vault names with per-vault memory counts.

        Mirrors status()' vault-union logic (union of both meta stores) and
        adds the vector-store memory count per vault. Powers GET /vaults.
        """
        episodic_vaults = {v["name"] for v in self._meta_episodic.list_vaults()}
        semantic_vaults = {v["name"] for v in self._meta_semantic.list_vaults()}
        out: list[dict[str, Any]] = []
        for name in sorted(episodic_vaults.union(semantic_vaults)):
            count = (
                self._vector_episodic.count(vault=name)
                + self._vector_semantic.count(vault=name)
            )
            out.append({"name": name, "memories": count})
        return out

    def get_hierarchy(self, vault: str) -> dict[str, Any]:
        """Get hierarchy for a vault, checking semantic store first then episodic."""
        try:
            return self._meta_semantic.get_hierarchy(vault)
        except Exception:
            # Fall back to episodic store
            return self._meta_episodic.get_hierarchy(vault)

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
                Must be within the configured export directory or storage path
                to prevent path traversal.
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
            out_path = Path(dest).resolve()
            # Path traversal guard: dest must be within the storage directory
            storage_cfg = self._config.get("storage", {})
            storage_path = Path(storage_cfg.get("path", "~/.memorius/data")).expanduser().resolve()
            safe_parent = out_path.parent if out_path.suffix else out_path
            if not str(safe_parent).startswith(str(storage_path)) and not str(out_path).startswith(str(storage_path)):
                raise ValueError(
                    f"Export path must be under the storage directory ({storage_path}). "
                    f"Refusing to write to: {out_path}"
                )
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

    def repair(self, vault: str | None = None, reindex: bool = False,
               dry_run: bool = False) -> dict[str, Any]:
        """Reconcile the vector store with the authoritative metadata store.

        Drift between the two stores has two shapes:

        * **Orphaned vectors** — a Chroma record with no matching
          ``memory_meta`` row. These inflate vector counts and can surface in
          search even though the memory is gone.
        * **Missing vectors** — a ``memory_meta`` row whose embedding is
          absent from Chroma, so the memory is invisible to search.

        This method:
        - always detects orphaned vectors and removes them (unless
          ``dry_run=True``);
        - when ``reindex=True``, re-embeds the content of every metadata row
          whose vector is missing;
        - returns a structured report.

        The metadata store is treated as the source of truth: orphaned
        vectors are dropped and missing vectors are restored from metadata.
        This is the inverse of a store rebuild — it only fixes *drift*, not
        wholesale reindexing of healthy data.

        Args:
            vault: restrict the reconciliation to a single vault.
            reindex: re-embed content for metadata rows missing a vector.
            dry_run: report what would change without mutating the vector store.

        Returns:
            dict with keys: orphans_found, orphans_removed, missing_found,
            missing_reindexed, in_sync, dry_run, meta_count, vector_count,
            orphans (list of {id, vault, shelf}).
        """
        from memorius.models import Memory

        meta_rows = self._meta.list_memory_meta(vault=vault)
        meta_by_id = {row["id"]: row for row in meta_rows}

        # Enumerate all vector IDs across Chroma collections.
        client = self._vector._lazy_client()
        all_vector_ids: list[str] = []
        for col in client.list_collections():
            try:
                ids = col.get(include=[])["ids"] or []
            except Exception:  # best-effort: unreadable collection — skip
                logger.debug("repair: could not read collection %s", col.name)
                ids = []
            all_vector_ids.extend(ids)

        orphan_ids = sorted({vid for vid in all_vector_ids if vid not in meta_by_id})
        missing_ids = sorted({mid for mid in meta_by_id
                              if mid not in set(all_vector_ids)})

        orphans_removed = 0
        orphan_set = set(orphan_ids)
        if orphan_ids and not dry_run:
            # Delete orphans per-collection so each delete targets the right
            # ChromaDB collection (delete is scoped to the collection's rows).
            for col in self._vector._lazy_client().list_collections():
                try:
                    col_ids = col.get(include=[])["ids"] or []
                except Exception:  # best-effort: unreadable collection — skip
                    continue
                col_orphans = [vid for vid in col_ids if vid in orphan_set]
                if col_orphans:
                    col.delete(ids=col_orphans)
                    orphans_removed += len(col_orphans)

        missing_reindexed = 0
        if reindex and missing_ids and not dry_run:
            # Re-embed content and upsert into the vector store.
            for mid in missing_ids:
                row = meta_by_id[mid]
                content = row.get("content") or ""
                if not content:
                    continue
                memory = Memory(
                    id=mid,
                    vault=row.get("vault", "main"),
                    shelf=row.get("shelf", "default"),
                    folder=row.get("folder", "default"),
                    note=row.get("note", "default"),
                    content=content,
                    metadata=json.loads(row["metadata"] or "{}") if row.get("metadata") else {},
                    created_at=row.get("created_at", ""),
                    updated_at=row.get("updated_at", ""),
                    vector=None,
                )
                try:
                    self._vector.add(memory)
                    missing_reindexed += 1
                except Exception:  # best-effort: reindex failure is logged, not fatal
                    logger.warning("repair: reindex failed for %s", mid)

        # Re-count after mutations to report the resulting state.
        meta_count = len(meta_by_id)
        if not dry_run:
            client = self._vector._lazy_client()
            vector_count = 0
            for col in client.list_collections():
                try:
                    vector_count += col.count()
                except Exception:
                    pass
        else:
            vector_count = len(all_vector_ids)

        # After a non-dry-run repair, the store is in sync iff no orphans
        # remain AND no missing vectors were left behind (reindex was on).
        if dry_run:
            in_sync = False
        else:
            unresolved_orphans = len(orphan_ids) - orphans_removed
            unresolved_missing = (len(missing_ids) - missing_reindexed) if reindex else len(missing_ids)
            in_sync = unresolved_orphans == 0 and unresolved_missing == 0

        return {
            "orphans_found": len(orphan_ids),
            "orphans_removed": orphans_removed,
            "missing_found": len(missing_ids),
            "missing_reindexed": missing_reindexed,
            "in_sync": in_sync,
            "dry_run": dry_run,
            "meta_count": meta_count,
            "vector_count": vector_count,
            "orphans": [
                {"id": oid, "vault": meta_by_id.get(oid, {}).get("vault", "?"),
                 "shelf": meta_by_id.get(oid, {}).get("shelf", "?")}
                for oid in orphan_ids
            ],
        }

    # ── Learning methods (v0.8.2) ──

    def store_learning(
        self,
        content: str,
        category: str,
        context: str = "",
        solution: str = "",
        tags: list[str] | None = None,
        vault: str = "main",
        confidence: float = 1.0,
    ) -> Memory:
        """Store an agent learning with structured metadata.

        Learnings are stored in a dedicated 'learnings' shelf with rich
        metadata for efficient retrieval and categorization.

        Args:
            content: The learning to store.
            category: Learning category (bug_fix, strategy, pattern,
                self_improvement, tool_usage, code_snippet, workflow).
            context: What was the situation/problem.
            solution: How it was solved.
            tags: Additional tags for categorization.
            vault: Target vault.
            confidence: Confidence score (0-1).

        Returns:
            The stored Memory object.
        """
        from memorius.learning import validate_category, LEARNINGS_SHELF

        category = validate_category(category)
        folder = category
        note = "default"

        metadata = {
            "category": category,
            "context": context,
            "solution": solution,
            "confidence": max(0.0, min(1.0, confidence)),
            "applied_count": 0,
            "last_applied": None,
            "learning": True,
        }

        # Only include tags if non-empty (ChromaDB rejects empty lists)
        if tags:
            metadata["tags"] = tags

        return self.store(
            content=content,
            vault=vault,
            shelf=LEARNINGS_SHELF,
            folder=folder,
            note=note,
            metadata=metadata,
        )

    def recall_learnings(
        self,
        query: str,
        category: str | None = None,
        tags: list[str] | None = None,
        vault: str | None = None,
        limit: int = 10,
    ) -> list[Memory]:
        """Search past learnings by semantic similarity.

        Args:
            query: What to search for.
            category: Filter by category.
            tags: Filter by tags (must match ALL).
            vault: Filter by vault.
            limit: Max results.

        Returns:
            List of matching Memory objects.
        """
        from memorius.learning import LEARNINGS_SHELF

        shelf_filter = LEARNINGS_SHELF
        folder_filter = category if category else None

        results = self.search(
            query=query,
            vault=vault,
            shelf=shelf_filter,
            folder=folder_filter,
            limit=limit,
            tags=tags,
        )

        # Filter to only learning memories (in case shelf has non-learning content)
        return [m for m in results if m.metadata.get("learning") is True]

    def list_learnings(
        self,
        category: str | None = None,
        vault: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List all learnings with statistics.

        Args:
            category: Filter by category.
            vault: Filter by vault.
            limit: Max results.

        Returns:
            Dict with learnings list and summary statistics.
        """
        from memorius.learning import (
            LEARNINGS_SHELF,
            Learning,
            format_learnings_summary,
        )

        # List memories from learnings shelf
        result = self.list_memories(
            vault=vault,
            shelf=LEARNINGS_SHELF,
            limit=limit,
            with_vectors=False,
        )

        learnings = []
        for mem in result["memories"]:
            if mem.metadata.get("learning") is True:
                if category and mem.metadata.get("category") != category:
                    continue
                learnings.append(Learning(
                    id=mem.id,
                    content=mem.content,
                    category=mem.metadata.get("category", "strategy"),
                    context=mem.metadata.get("context", ""),
                    solution=mem.metadata.get("solution", ""),
                    tags=mem.metadata.get("tags") or [],
                    confidence=float(mem.metadata.get("confidence", 1.0)),
                    applied_count=int(mem.metadata.get("applied_count", 0)),
                    last_applied=mem.metadata.get("last_applied"),
                    created_at=mem.created_at,
                    vault=mem.vault,
                ))

        summary = format_learnings_summary(learnings)
        return {
            "learnings": [l.to_dict() for l in learnings],
            "summary": summary,
        }

    def apply_learning(self, learning_id: str) -> Memory | None:
        """Mark a learning as applied (increment counter).

        Args:
            learning_id: UUID of the learning to mark as applied.

        Returns:
            Updated Memory or None if not found.
        """
        from datetime import datetime, timezone

        mem = self.get_memory(learning_id)
        if mem is None:
            return None

        current_count = int(mem.metadata.get("applied_count", 0))
        return self.update_memory(
            learning_id,
            metadata={
                "applied_count": current_count + 1,
                "last_applied": datetime.now(timezone.utc).isoformat(),
            },
        )

    def get_learning_stats(self, vault: str | None = None) -> dict[str, Any]:
        """Get statistics about agent learnings.

        Args:
            vault: Filter by vault.

        Returns:
            Dict with learning statistics.
        """
        from memorius.learning import LEARNINGS_SHELF

        result = self.list_learnings(vault=vault, limit=1000)
        summary = result["summary"]

        # Calculate additional stats
        learnings = result["learnings"]
        if learnings:
            avg_confidence = sum(l["confidence"] for l in learnings) / len(learnings)
            most_applied = max(learnings, key=lambda l: l["applied_count"])
        else:
            avg_confidence = 0.0
            most_applied = None

        return {
            "total": summary["total"],
            "by_category": summary["by_category"],
            "total_applied": summary["total_applied"],
            "avg_confidence": round(avg_confidence, 3),
            "most_applied": {
                "id": most_applied["id"],
                "content": most_applied["content"][:100],
                "category": most_applied["category"],
                "applied_count": most_applied["applied_count"],
            } if most_applied else None,
        }
