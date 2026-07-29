"""SQLite-vec vector store for memorius — single-file alternative to ChromaDB.

Requires ``pip install memorius[single-file]`` (or ``pip install sqlite-vec``).
Activated via ``storage.type: sqlite-vec`` in config.
"""

from __future__ import annotations

import json
import logging
import struct
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memorius.embeddings import EmbeddingProvider
from memorius.vector_store_base import VectorStore

logger = logging.getLogger("memorius.vector.sqlite_vec")


def _vec_to_blob(vec: list[float] | Any) -> bytes:
    """Pack a float vector into a bytes blob for sqlite-vec."""
    if hasattr(vec, "tolist"):
        vec = vec.tolist()
    return struct.pack(f"{len(vec)}f", *vec)


def _blob_to_vec(blob: bytes, dim: int) -> list[float]:
    """Unpack a bytes blob back into a float vector."""
    expected = dim * 4  # 4 bytes per float32
    if len(blob) != expected:
        raise ValueError(
            f"Vector blob length mismatch: expected {expected} bytes "
            f"for dim={dim}, got {len(blob)}"
        )
    return list(struct.unpack(f"{dim}f", blob))


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Compute 1 - cosine_similarity (lower is more similar)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - (dot / (norm_a * norm_b))


class SqliteVecStore(VectorStore):
    """Vector store backed by sqlite-vec (single-file, no ChromaDB dependency)."""

    def __init__(self, path: Path, embedding_provider: EmbeddingProvider):
        self._path = path
        self._embed = embedding_provider
        self._lock = threading.Lock()
        self._local = threading.local()

    def _lazy_conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        import sqlite3
        try:
            import sqlite_vec
        except ImportError:
            raise ImportError(
                "sqlite-vec not installed. "
                "Install: pip install memorius[single-file]"
            )
        self._path.mkdir(parents=True, exist_ok=True)
        db_path = self._path / "vectors.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        # Create tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                vault TEXT NOT NULL,
                shelf TEXT NOT NULL,
                folder TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                vector BLOB,
                metadata TEXT DEFAULT '{}',
                created_at TEXT,
                updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_vault
            ON memories(vault, shelf)
        """)
        conn.commit()
        self._local.conn = conn
        return conn

    def add(self, memory) -> None:
        """Add or update a memory in vector storage."""
        conn = self._lazy_conn()
        now = datetime.now(timezone.utc).isoformat()
        if not memory.created_at:
            memory.created_at = now
        memory.updated_at = now

        meta_clean = {
            k: v for k, v in (memory.metadata or {}).items()
            if k not in ("vault", "shelf", "folder", "note", "content",
                         "created_at", "updated_at")
        }

        if memory.vector is None:
            vectors = self._embed.embed([memory.content])
            memory.vector = vectors[0]

        vector_blob = _vec_to_blob(memory.vector) if memory.vector is not None else None

        with self._lock:
            conn.execute(
                """INSERT OR REPLACE INTO memories
                   (id, vault, shelf, folder, note, content, vector, metadata, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory.id,
                    memory.vault,
                    memory.shelf,
                    memory.folder,
                    memory.note,
                    memory.content,
                    vector_blob,
                    json.dumps(meta_clean),
                    memory.created_at,
                    memory.updated_at,
                ),
            )
            conn.commit()

    def delete(self, memory_id: str, vault: str, shelf: str) -> None:
        """Delete a memory by ID within a vault/shelf."""
        conn = self._lazy_conn()
        with self._lock:
            conn.execute(
                "DELETE FROM memories WHERE id = ? AND vault = ? AND shelf = ?",
                (memory_id, vault, shelf),
            )
            conn.commit()

    def search(
        self,
        query: str,
        vault: str | None = None,
        shelf: str | None = None,
        n_results: int = 10,
        filter_metadata: dict[str, str] | None = None,
    ) -> list:
        """Search memories by semantic similarity.

        Loads all candidate rows and computes cosine distance in Python
        for simplicity.  For large datasets (10k+), consider using
        sqlite-vec's ``vec0`` virtual table for in-database ANN search.
        """
        from memorius.models import Memory

        conn = self._lazy_conn()
        query_vector = self._embed.embed([query])[0]

        # Build WHERE clause
        conditions = []
        params: list = []
        if vault:
            conditions.append("vault = ?")
            params.append(vault)
        if shelf:
            conditions.append("shelf = ?")
            params.append(shelf)
        _ALLOWED_FILTER_COLS = {"folder", "note"}
        if filter_metadata:
            for k, v in filter_metadata.items():
                if k not in _ALLOWED_FILTER_COLS:
                    logger.warning("Ignoring disallowed filter_metadata key: %s", k)
                    continue
                conditions.append(f"{k} = ?")
                params.append(v)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM memories WHERE {where}"
        rows = conn.execute(sql, params).fetchall()

        # Compute distances
        results: list[tuple[float, Memory]] = []
        dim = self._embed.dimension
        for row in rows:
            vec_blob = row["vector"]
            if vec_blob is None:
                continue
            mem_vec = _blob_to_vec(vec_blob, dim)
            dist = _cosine_distance(query_vector, mem_vec)
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            mem = Memory(
                id=row["id"],
                vault=row["vault"],
                shelf=row["shelf"],
                folder=row["folder"],
                note=row["note"],
                content=row["content"],
                metadata=meta,
                created_at=row["created_at"] or "",
                updated_at=row["updated_at"] or "",
                vector=mem_vec,
            )
            mem.metadata["__distance__"] = dist
            results.append((dist, mem))

        results.sort(key=lambda x: x[0])
        return [m for _, m in results[:n_results]]

    def get_collections(self) -> list[dict[str, str]]:
        """List all vault/shelf combos with counts."""
        conn = self._lazy_conn()
        rows = conn.execute(
            "SELECT vault, shelf, COUNT(*) as cnt FROM memories GROUP BY vault, shelf"
        ).fetchall()
        return [{"vault": r["vault"], "shelf": r["shelf"], "count": r["cnt"]} for r in rows]

    def count(self, vault: str | None = None, shelf: str | None = None) -> int:
        """Count memories."""
        conn = self._lazy_conn()
        conditions = []
        params: list = []
        if vault:
            conditions.append("vault = ?")
            params.append(vault)
        if shelf:
            conditions.append("shelf = ?")
            params.append(shelf)
        where = " AND ".join(conditions) if conditions else "1=1"
        row = conn.execute(f"SELECT COUNT(*) as cnt FROM memories WHERE {where}", params).fetchone()
        return row["cnt"] if row else 0

    def get_by_ids(
        self,
        ids: list[str],
        vault: str,
        shelf: str,
        include_vectors: bool = True,
    ) -> list:
        """Fetch memories by id."""
        from memorius.models import Memory

        if not ids:
            return []
        conn = self._lazy_conn()
        placeholders = ",".join("?" * len(ids))
        sql = f"SELECT * FROM memories WHERE id IN ({placeholders})"
        rows = conn.execute(sql, ids).fetchall()

        dim = self._embed.dimension
        out: list[Memory] = []
        for row in rows:
            vec = None
            if include_vectors and row["vector"]:
                vec = _blob_to_vec(row["vector"], dim)
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            out.append(Memory(
                id=row["id"],
                vault=row["vault"],
                shelf=row["shelf"],
                folder=row["folder"],
                note=row["note"],
                content=row["content"],
                metadata=meta,
                created_at=row["created_at"] or "",
                updated_at=row["updated_at"] or "",
                vector=vec,
            ))
        return out
