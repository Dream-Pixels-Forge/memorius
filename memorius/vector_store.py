"""ChromaDB vector store for memorius.

Handles semantic embedding, storage, and similarity search.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memorius.embeddings import EmbeddingProvider

logger = logging.getLogger("memorius.vector")


# ── Retry helpers ────────────────────────────────────────────────────────────

def _retry(fn, max_retries: int = 3, base_delay: float = 0.1, exceptions: tuple = (Exception,)):
    """Retry a function with exponential backoff."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn()
        except exceptions as e:
            last_exc = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.debug("Retry %d/%d after %.1fs: %s", attempt + 1, max_retries, delay, e)
                time.sleep(delay)
    raise last_exc


class ChromaStore:
    """Vector store backed by ChromaDB."""

    def __init__(self, path: Path, embedding_provider: EmbeddingProvider):
        self._path = path
        self._embed = embedding_provider
        self._client = None  # lazy
        self._collections: dict[str, Any] = {}

    def _lazy_client(self):
        if self._client is not None:
            return self._client
        import chromadb
        self._path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self._path),
        )
        return self._client

    def _collection_name(self, vault: str, shelf: str) -> str:
        """ChromaDB collection per (vault, shelf)."""
        return f"{vault}_{shelf}".replace("-", "_").replace(" ", "_").lower()

    def _collection(self, vault: str, shelf: str):
        """Get or create a collection."""
        name = self._collection_name(vault, shelf)
        if name not in self._collections:
            client = self._lazy_client()
            try:
                self._collections[name] = client.get_collection(name)
            except Exception:
                self._collections[name] = client.create_collection(
                    name,
                    get_or_create=True,
                    metadata={"hnsw:space": "cosine"},
                )
        return self._collections[name]

    def add(self, memory):
        """Add or update a memory in vector storage."""
        collection = self._collection(memory.vault, memory.shelf)
        now = datetime.now(timezone.utc).isoformat()
        if not memory.created_at:
            memory.created_at = now
        memory.updated_at = now

        metadata = {
            "vault": memory.vault,
            "shelf": memory.shelf,
            "folder": memory.folder,
            "note": memory.note,
            "content": memory.content[:500],
            "created_at": memory.created_at,
            "updated_at": memory.updated_at,
            **memory.metadata,
        }

        if memory.vector is None:
            vectors = self._embed.embed([memory.content])
            memory.vector = vectors[0]

        def _upsert():
            collection.upsert(
                ids=[memory.id],
                embeddings=[memory.vector],
                metadatas=[metadata],
                documents=[memory.content],
            )

        _retry(_upsert)

    def delete(self, memory_id: str, vault: str, shelf: str):
        """Delete a memory by ID."""
        collection = self._collection(vault, shelf)
        collection.delete(ids=[memory_id])

    def search(
        self,
        query: str,
        vault: str | None = None,
        shelf: str | None = None,
        n_results: int = 10,
        filter_metadata: dict[str, str] | None = None,
    ) -> list:
        """Search memories by semantic similarity."""
        from memorius.vault import Memory

        query_vector = self._embed.embed([query])[0]

        collections_to_search = self._resolve_collections(vault, shelf)
        results: list[Memory] = []

        for col_name in collections_to_search:
            col = self._collections.get(col_name)
            if col is None:
                continue
            try:
                where = filter_metadata or None
                res = _retry(lambda: col.query(
                    query_embeddings=[query_vector],
                    n_results=n_results,
                    where=where,
                    include=["embeddings", "documents", "metadatas"],
                ))
            except Exception:
                logger.debug("ChromaDB query failed for collection %s after retries, skipping", col_name)
                continue

            if not res["ids"] or not res["ids"][0]:
                continue

            for i, doc_id in enumerate(res["ids"][0]):
                meta = (res["metadatas"] or [{}])[0][i] if res.get("metadatas") else {}
                results.append(Memory(
                    id=doc_id,
                    vault=meta.get("vault", vault or ""),
                    shelf=meta.get("shelf", shelf or ""),
                    folder=meta.get("folder", ""),
                    note=meta.get("note", ""),
                    content=res["documents"][0][i] if res.get("documents") else "",
                    metadata={k: v for k, v in meta.items() if k not in (
                        "vault", "shelf", "folder", "note", "content",
                        "created_at", "updated_at",
                    )},
                    created_at=meta.get("created_at", ""),
                    updated_at=meta.get("updated_at", ""),
                    vector=res["embeddings"][0][i] if res.get("embeddings") else None,
                ))

        return results[:n_results]

    def _resolve_collections(self, vault: str | None, shelf: str | None) -> list[str]:
        """Resolve collections to search based on filters."""
        if not self._collections:
            self._load_all_collections()

        if vault and shelf:
            name = self._collection_name(vault, shelf)
            if name in self._collections:
                return [name]
            try:
                client = self._lazy_client()
                client.get_collection(name)
                return [name]
            except Exception:
                return []
        if vault:
            return [n for n in self._collections if n.startswith(vault + "_")]
        return list(self._collections.keys())

    def _load_all_collections(self):
        """Load all collections from ChromaDB into the in-memory cache."""
        try:
            client = self._lazy_client()
            for col in client.list_collections():
                if col.name not in self._collections:
                    self._collections[col.name] = col
        except Exception:
            logger.debug("Failed to load collections from ChromaDB")

    def get_collections(self) -> list[dict[str, str]]:
        """List all collections (vault_shelf combos) with counts."""
        client = self._lazy_client()
        collections = client.list_collections()
        result = []
        for col in collections:
            name = col.name
            count = col.count()
            if "_" in name:
                vault_part, shelf_part = name.split("_", 1)
                result.append({"vault": vault_part, "shelf": shelf_part, "count": count})
            else:
                result.append({"vault": name, "shelf": "", "count": count})
        return result

    def count(self, vault: str | None = None, shelf: str | None = None) -> int:
        """Count memories."""
        total = 0
        for col_name in self._resolve_collections(vault, shelf):
            col = self._collections.get(col_name)
            if col:
                total += col.count()
        return total
