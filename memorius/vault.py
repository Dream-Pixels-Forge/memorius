"""Vault engine — high-level orchestrator for memorius.

Combines ChromaDB vector store + SQLite metadata store into a unified
interface. The actual store implementations live in:
  - memorius/vector_store.py (ChromaStore)
  - memorius/meta_store.py   (SQLiteStore)

Hierarchy: Vault > Shelf > Folder > Note
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memorius.embeddings import EmbeddingFactory, EmbeddingProvider
from memorius.config import load_config
from memorius.validation import validate_name as _validate_name
from memorius.vector_store import ChromaStore
from memorius.meta_store import SQLiteStore

logger = logging.getLogger("memorius")


# ── Data model ───────────────────────────────────────────────────────────────


@dataclass
class Memory:
    """A single memory item stored in a note."""
    id: str
    vault: str
    shelf: str
    folder: str
    note: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    vector: list[float] | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.id,
            "vault": self.vault,
            "shelf": self.shelf,
            "folder": self.folder,
            "note": self.note,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.vector is not None:
            d["vector"] = self.vector
        return d


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
               shelf: str | None = None, limit: int = 10) -> list[Memory]:
        """Search vault contents by semantic similarity with temporal decay ranking."""
        results = self._vector.search(query, vault=vault, shelf=shelf, n_results=limit * 2)
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
                semantic_sim = max(0.1, 1.0 - (rank_pos * 0.05))
                final_score = calculate_search_score(
                    semantic_similarity=semantic_sim,
                    decay_score=decay,
                    access_count=access_count,
                )
                scored.append((mem, final_score))
            scored.sort(key=lambda x: x[1], reverse=True)
            results = [m for m, _ in scored[:limit]]
        except Exception:
            logger.debug("Temporal decay scoring failed, using rank order")
            results = results[:limit]
        for mem in results:
            try:
                self._meta.record_access(mem.id)
            except Exception:
                logger.debug("Failed to record access for %s", mem.id)
        return results

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
