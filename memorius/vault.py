"""Vault engine — high-level orchestrator for memorius.

Combines ChromaDB vector store + SQLite metadata store into a unified
interface. The actual store implementations live in:
  - memorius/vector_store.py (ChromaStore)
  - memorius/meta_store.py   (SQLiteStore)

Hierarchy: Vault > Shelf > Folder > Note
"""

from __future__ import annotations

import logging
import math
import uuid
from pathlib import Path
from typing import Any

from memorius.embeddings import EmbeddingFactory, EmbeddingProvider
from memorius.config import load_config
from memorius.validation import validate_name as _validate_name, validate_memory_id
from memorius.models import Memory  # noqa: F401
from memorius.vector_store import ChromaStore
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
        self._vector = ChromaStore(storage_path / "vectors", self._embed)
        self._meta = SQLiteStore(storage_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        """Release all resources (DB connections, ChromaDB client)."""
        try:
            self._meta.close()
        except Exception:
            pass
        self._vector = None

    def __del__(self):
        self.close()

    @property
    def embed(self) -> EmbeddingProvider:
        return self._embed

    @property
    def vector(self) -> ChromaStore:
        return self._vector

    @property
    def meta(self) -> SQLiteStore:
        return self._meta

    # ── Memory operations ──

    def store(self, content: str, vault: str = "main", shelf: str = "default",
              folder: str = "default", note: str = "default",
              metadata: dict[str, Any] | None = None) -> Memory:
        """Store a memory in the vault."""
        vault = _validate_name(vault, "vault")
        shelf = _validate_name(shelf, "shelf")
        folder = _validate_name(folder, "folder")
        note = _validate_name(note, "note")

        self._meta.ensure_note(vault, shelf, folder, note)
        memory = Memory(
            id=str(uuid.uuid4()),
            vault=vault,
            shelf=shelf,
            folder=folder,
            note=note,
            content=content,
            metadata=metadata or {},
        )
        self._vector.add(memory)
        self._meta.increment_note_count(vault, shelf, folder, note)
        self._meta.track_memory(
            memory_id=memory.id, vault=vault, shelf=shelf,
            folder=folder, note=note, content=content, metadata=metadata,
        )
        # Auto-link to related memories via content similarity
        try:
            from memorius.graph import auto_link_by_proximity, init_graph_schema
            conn = self._meta._conn()
            init_graph_schema(conn)
            recent = self._meta.list_memories_meta(vault=vault, limit=50)
            auto_link_by_proximity(conn, memory.id, recent)
        except Exception:
            logger.debug("Graph linking failed (best-effort)")
        return memory

    def search(self, query: str, vault: str | None = None,
               shelf: str | None = None, limit: int = 10,
               expand_graph: bool = False, graph_hops: int = 1,
               graph_min_weight: float = 0.3,
               folder: str | None = None, note: str | None = None,
               tags: list[str] | None = None) -> list[Memory]:
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
        filter_metadata: dict[str, str] = {}
        if folder is not None:
            filter_metadata["folder"] = _validate_name(folder, "folder")
        if note is not None:
            filter_metadata["note"] = _validate_name(note, "note")
        # Over-fetch so the post-filter for tags can still return up to
        # `limit` after discarding non-matching memories.
        fetch_n = (limit * 4) if tags else (limit * 2)
        results = self._vector.search(
            query, vault=vault, shelf=shelf, n_results=fetch_n,
            filter_metadata=filter_metadata or None,
        )

        if tags:
            wanted = {str(t) for t in tags}
            filtered: list[Memory] = []
            for mem in results:
                md_tags = (mem.metadata or {}).get("tags") or []
                if isinstance(md_tags, str):
                    try:
                        import json as _json
                        md_tags = _json.loads(md_tags)
                    except Exception:
                        md_tags = [md_tags]
                if wanted.issubset({str(t) for t in (md_tags or [])}):
                    filtered.append(mem)
            results = filtered
        try:
            from memorius.temporal import calculate_decay_score, calculate_search_score
            meta_map = self._meta.get_memory_meta_batch([m.id for m in results])
            scored = []
            for rank_pos, mem in enumerate(results):
                meta = meta_map.get(mem.id)
                decay = 1.0
                access_count = 0
                if meta:
                    decay = calculate_decay_score(
                        created_at=meta.get("created_at", ""),
                        last_accessed=meta.get("last_accessed"),
                        access_count=meta.get("access_count", 0),
                    )
                    access_count = meta.get("access_count", 0)
                distance = float((mem.metadata or {}).get("__distance__", 0.0) or 0.0)
                semantic_sim = max(0.0, min(1.0, 1.0 - distance))
                final_score = calculate_search_score(
                    semantic_similarity=semantic_sim,
                    decay_score=decay,
                    access_count=access_count,
                )
                scored.append((mem, final_score))
            scored.sort(key=lambda x: x[1], reverse=True)
            results = [m for m, _ in scored[:limit]]
            for mem in results:
                if "__distance__" in (mem.metadata or {}):
                    del mem.metadata["__distance__"]
        except Exception:
            logger.debug("Temporal decay scoring failed, using rank order")
            results = results[:limit]

        # ── Graph expansion (opt-in) ────────────────────────────────────────
        # The seed results are the ranked matches above. If asked, walk the
        # knowledge graph from those seeds and bring in linked memories that
        # the vector search wouldn't have surfaced on its own.
        if expand_graph and results:
            expanded = self._expand_from_graph(
                results, vault=vault, hops=graph_hops,
                min_weight=graph_min_weight,
                max_extra=max(0, math.ceil(limit * 1.5) - len(results)),
            )
            if expanded:
                results = results + expanded

        for mem in results:
            try:
                self._meta.record_access(mem.id)
            except Exception:
                logger.debug("Failed to record access for %s", mem.id)
        return results

    def _expand_from_graph(self, seeds: list[Memory], vault: str | None,
                           hops: int, min_weight: float,
                           max_extra: int) -> list[Memory]:
        """Walk the knowledge graph from ``seeds`` and return linked memories
        not already present in ``seeds``. Returns at most ``max_extra``
        memories. Best-effort: any graph failure is swallowed (graph linking
        is a supplement, never a hard requirement)."""
        if max_extra <= 0 or not seeds:
            return []
        try:
            from memorius.graph import expand_graph, init_graph_schema
            conn = self._meta._conn()
            init_graph_schema(conn)
            res = expand_graph(
                conn, [m.id for m in seeds], hops=max(1, hops),
                min_weight=min_weight, max_nodes=max_extra,
            )
            expanded_ids = list(res.expanded_ids)
        except Exception:
            logger.debug("Graph expansion failed (best-effort)")
            return []
        if not expanded_ids:
            return []
        # If the caller scoped to one vault, only add memories in that vault.
        fetched = self.get_memories_by_ids(expanded_ids, with_vectors=False)
        seed_ids = {m.id for m in seeds}
        out: list[Memory] = []
        for mem in fetched:
            if mem.id in seed_ids:
                continue
            if vault is not None and mem.vault != vault:
                continue
            out.append(mem)
            if len(out) >= max_extra:
                break
        return out

    def get_memories_by_ids(self, ids: list[str],
                            with_vectors: bool = True) -> list[Memory]:
        """Fetch memories by exact ID. Vectors are pulled from ChromaDB only
        when ``with_vectors=True``. Memories whose meta row is missing or
        whose vector is unfetchable are skipped."""
        if not ids:
            return []
        metas = self._meta.get_memory_meta_batch(ids)
        if not metas:
            return []
        groups: dict[tuple[str, str], list[str]] = {}
        for mid, meta in metas.items():
            v = meta.get("vault", "")
            s = meta.get("shelf", "")
            groups.setdefault((v, s), []).append(mid)
        out: list[Memory] = []
        for (v, s), group_ids in groups.items():
            fetched = self._vector.get_by_ids(
                group_ids, v, s, include_vectors=with_vectors,
            )
            for m in fetched:
                meta = metas.get(m.id)
                if meta:
                    if not m.created_at:
                        m.created_at = meta.get("created_at", m.created_at)
                    if not m.updated_at:
                        m.updated_at = meta.get("updated_at", m.updated_at)
                out.append(m)
        return out

    def list_memories(self, vault: str | None = None, shelf: str | None = None,
                      limit: int | None = None, with_vectors: bool = True) -> list[Memory]:
        """List memories by metadata (time-recency), optionally filling vectors
        from the ChromaStore. Avoids the misuse of empty-query search as
        \"list all\". Returns Memories ordered by created_at DESC from the meta
        store.
        """
        meta_rows = self._meta.list_memories_meta(
            vault=vault, limit=limit or 10000, include_archived=False,
        )
        if not meta_rows:
            return []

        # Defaults from meta rows (meta is source of truth for temporal order).
        memories: list[Memory] = []

        # Group meta rows by (vault, shelf) so we can batch-fetch from the right
        # Chroma collection.
        groups: dict[tuple[str, str], list[dict]] = {}
        for row in meta_rows:
            groups.setdefault((row.get("vault") or "", row.get("shelf") or ""), []).append(row)

        for (v, s), rows in groups.items():
            if shelf is not None and s != shelf:
                continue
            ids = [r["id"] for r in rows]
            fetched = self._vector.get_by_ids(ids, v, s, include_vectors=with_vectors)

            by_id = {m.id: m for m in fetched}
            for row in rows:
                mem = by_id.get(row["id"])
                if mem is not None:
                    if not mem.created_at:
                        mem.created_at = row.get("created_at", "")
                    if not mem.updated_at:
                        mem.updated_at = row.get("updated_at", "")
                    memories.append(mem)
                else:
                    # Vector missing: fall back to meta-only record.
                    try:
                        md = row.get("metadata") or "{}"
                        if isinstance(md, str):
                            import json as _json
                            md = (_json.loads(md) if md else {})
                    except Exception:
                        md = {}
                    memories.append(Memory(
                        id=row["id"],
                        vault=v,
                        shelf=s,
                        folder=row.get("folder", ""),
                        note=row.get("note", ""),
                        content=row.get("content", ""),
                        metadata=md or {},
                        created_at=row.get("created_at", ""),
                        updated_at=row.get("updated_at", ""),
                        vector=None,
                    ))

        if limit is not None:
            memories = memories[:limit]
        return memories

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
        memory_id = validate_memory_id(memory_id)
        meta = self._meta.get_memory_meta(memory_id)
        result: dict[str, Any] = {
            "found": meta is not None,
            "deleted": False,
            "memory_id": memory_id,
            "vault": None,
            "shelf": None,
            "folder": None,
            "note": None,
            "content": None,
        }
        if meta is None:
            return result

        result.update({
            "vault": meta["vault"],
            "shelf": meta["shelf"],
            "folder": meta["folder"],
            "note": meta["note"],
            "content": meta["content"],
        })

        # Validate optional scope and ensure it matches the memory's location.
        if vault is not None:
            vault = _validate_name(vault, "vault")
            if vault != meta["vault"]:
                raise ValueError(
                    f"memory {memory_id} is in vault {meta['vault']!r}, not {vault!r}"
                )
        if shelf is not None:
            shelf = _validate_name(shelf, "shelf")
            if shelf != meta["shelf"]:
                raise ValueError(
                    f"memory {memory_id} is on shelf {meta['shelf']!r}, not {shelf!r}"
                )

        if dry_run:
            return result

        # Hard delete from both the vector store and metadata store.
        self._vector.delete(memory_id, meta["vault"], meta["shelf"])
        self._meta.delete_memory(memory_id)
        result["deleted"] = True
        return result

    def mine(self, text: str, vault: str = "main", shelf: str = "conversations",
             folder: str = "mined", note: str = "transcript") -> list[Memory]:
        """Extract memories from a transcript by splitting into chunks."""
        import re
        chunks = re.split(r'\n{2,}', text.strip())
        memories = []
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            m = self.store(chunk, vault=vault, shelf=shelf, folder=folder, note=note)
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
        from memorius.graph import get_graph_stats
        return get_graph_stats(self._meta._conn())

    def get_memory_stats(self) -> dict:
        """Get memory tracking statistics."""
        return self._meta.get_memory_stats()
