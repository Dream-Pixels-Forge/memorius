"""ChromaDB vector store for memorius.

Handles semantic embedding, storage, and similarity search.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memorius.embeddings import EmbeddingProvider

logger = logging.getLogger("memorius.vector")


_ALLOWED_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _is_new_scheme(name: str) -> bool:
    """True iff `name` follows the v<N>_<vault>_s<N>_<shelf> scheme."""
    if not name or name[0] != "v":
        return False
    rest = name[1:]
    i = 0
    while i < len(rest) and rest[i].isdigit():
        i += 1
    if i == 0 or i >= len(rest) or rest[i] != "_":
        return False
    return True


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
        try:
            self._migrate_legacy_collections(self._client)
        except Exception:
            logger.debug("Legacy collection migration failed (best-effort)")
        return self._client

    def _collection_name(self, vault: str, shelf: str) -> str:
        """Bijective, length-safe ChromaDB collection name for (vault, shelf)."""
        name = f"v{len(vault):03d}_{vault}_s{len(shelf):03d}_{shelf}"
        if len(name) > 63 or not _ALLOWED_NAME_RE.match(name):
            name = f"ms_{hashlib.sha1(f'{vault}|{shelf}'.encode()).hexdigest()[:20]}"
        return name

    def _collection(self, vault: str, shelf: str, create: bool = True):
        """Get or create a collection."""
        name = self._collection_name(vault, shelf)
        col = self._collections.get(name)
        if col is not None:
            return col
        client = self._lazy_client()
        try:
            col = client.get_collection(name)
        except Exception:
            if not create:
                return None
            col = client.create_collection(
                name,
                get_or_create=True,
                metadata={
                    "hnsw:space": "cosine",
                    "memorius_vault": vault,
                    "memorius_shelf": shelf,
                },
            )
        self._collections[name] = col
        return col

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
        from memorius.models import Memory

        query_vector = self._embed.embed([query])[0]

        collections_to_search = self._resolve_collections(vault, shelf)
        results: list[Memory] = []
        distances: list[float] = []

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
                    include=["embeddings", "documents", "metadatas", "distances"],
                ))
            except Exception:
                logger.debug("ChromaDB query failed for collection %s after retries, skipping", col_name)
                continue

            if not res["ids"] or not res["ids"][0]:
                continue

            dist_list = (res.get("distances") or [[None] * len(res["ids"][0])])[0]
            for i, doc_id in enumerate(res["ids"][0]):
                meta = (res["metadatas"] or [{}])[0][i] if res.get("metadatas") else {}
                mem = Memory(
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
                )
                raw_dist = dist_list[i] if i < len(dist_list) else None
                if raw_dist is None:
                    raw_dist = 0.0
                mem.metadata["__distance__"] = float(raw_dist)
                results.append(mem)
                distances.append(float(raw_dist))

        if not results:
            return results
        # Merge across collections by ascending cosine distance, then truncate.
        paired = sorted(zip(distances, results), key=lambda x: x[0])
        return [m for _, m in paired[:n_results]]

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
            prefix = f"v{len(vault):03d}_{vault}_s"
            return [n for n in self._collections if n.startswith(prefix)]
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
            meta = col.metadata or {}
            vault = meta.get("memorius_vault")
            shelf = meta.get("memorius_shelf")
            if vault is None or shelf is None:
                # Legacy best-effort split for unmigrated collections.
                if "_" in name:
                    vault_part, shelf_part = name.split("_", 1)
                    vault, shelf = vault_part, shelf_part
                else:
                    vault, shelf = name, ""
            result.append({"vault": vault, "shelf": shelf, "count": count})
        return result

    def count(self, vault: str | None = None, shelf: str | None = None) -> int:
        """Count memories."""
        total = 0
        for col_name in self._resolve_collections(vault, shelf):
            col = self._collections.get(col_name)
            if col:
                total += col.count()
        return total

    def get_by_ids(
        self,
        ids: list[str],
        vault: str,
        shelf: str,
        include_vectors: bool = True,
    ) -> list:
        """Fetch memories by id from a specific (vault, shelf) collection."""
        from memorius.models import Memory

        if not ids:
            return []
        col = self._collection(vault, shelf, create=False)
        if col is None:
            return []
        include = ["documents", "metadatas"]
        if include_vectors:
            include.append("embeddings")
        try:
            res = _retry(lambda: col.get(ids=ids, include=include))
        except Exception:
            logger.debug("ChromaDB get_by_ids failed for (%s,%s)", vault, shelf)
            return []
        out: list[Memory] = []
        ids_out = res.get("ids") or []
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        embs = res.get("embeddings")
        if embs is None:
            embs = []
        for i, doc_id in enumerate(ids_out):
            meta = metas[i] if i < len(metas) else {}
            doc = docs[i] if i < len(docs) else ""
            vec = embs[i] if (include_vectors and i < len(embs)) else None
            out.append(Memory(
                id=doc_id,
                vault=meta.get("vault", vault),
                shelf=meta.get("shelf", shelf),
                folder=meta.get("folder", ""),
                note=meta.get("note", ""),
                content=doc,
                metadata={k: v for k, v in meta.items() if k not in (
                    "vault", "shelf", "folder", "note", "content",
                    "created_at", "updated_at",
                )},
                created_at=meta.get("created_at", ""),
                updated_at=meta.get("updated_at", ""),
                vector=vec,
            ))
        return out

    def _migrate_legacy_collections(self, client):
        """One-time, idempotent migration of legacy collection names to the
        new length-safe scheme. Recovers (vault, shelf) from the first
        record's metadata when possible; leaves unrecoverable legacy
        collections untouched.
        """
        migrated = 0
        skipped = 0
        for col in list(client.list_collections()):
            name = col.name
            meta = col.metadata or {}
            if _is_new_scheme(name) or "memorius_vault" in meta:
                continue
            try:
                count = col.count()
            except Exception:
                skipped += 1
                continue
            if count <= 0:
                skipped += 1
                continue
            try:
                probe = col.get(limit=1, include=["metadatas"])
                probe_metas = probe.get("metadatas") or []
                if not probe_metas:
                    skipped += 1
                    continue
                first_meta = probe_metas[0] or {}
                vault = first_meta.get("vault")
                shelf = first_meta.get("shelf")
                if not vault or not shelf:
                    skipped += 1
                    continue
            except Exception:
                skipped += 1
                continue
            new_name = self._collection_name(vault, shelf)
            if new_name == name:
                continue
            try:
                client.get_collection(new_name)
                skipped += 1
                continue
            except Exception:
                pass
            try:
                new_col = client.create_collection(
                    new_name,
                    get_or_create=True,
                    metadata={
                        "hnsw:space": "cosine",
                        "memorius_vault": vault,
                        "memorius_shelf": shelf,
                    },
                )
                payload = _retry(lambda: col.get(
                    limit=count,
                    include=["embeddings", "documents", "metadatas"],
                ))
                ids = payload.get("ids") or []
                if not ids:
                    skipped += 1
                    continue
                embs_in = payload.get("embeddings")
                if embs_in is None:
                    embs_in = []
                docs_in = payload.get("documents")
                if docs_in is None:
                    docs_in = []
                metas_in = payload.get("metadatas")
                if metas_in is None:
                    metas_in = []
                new_col.upsert(
                    ids=ids,
                    embeddings=embs_in,
                    documents=docs_in,
                    metadatas=metas_in,
                )
                client.delete_collection(name)
                self._collections.pop(name, None)
                self._collections[new_name] = new_col
                migrated += 1
            except Exception as e:
                logger.debug("Legacy collection migration failed for %s: %s", name, e)
                skipped += 1
        if migrated or skipped:
            logger.debug(
                "Legacy collection migration: %d migrated, %d skipped",
                migrated, skipped,
            )
