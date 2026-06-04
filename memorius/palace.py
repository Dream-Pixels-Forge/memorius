"""Storage engine — ChromaDB vector store + SQLite metadata store."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memorius.embeddings import EmbeddingFactory, EmbeddingProvider
from memorius.config import load_config

logger = logging.getLogger("memorius")

local = threading.local()


# ── Data models ──────────────────────────────────────────────────────────────


@dataclass
class Memory:
    """A single memory item stored in a drawer."""
    id: str
    palace: str
    wing: str
    room: str
    drawer: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    vector: list[float] | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "palace": self.palace,
            "wing": self.wing,
            "room": self.room,
            "drawer": self.drawer,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ── ChromaDB vector store ────────────────────────────────────────────────────


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

    def _collection_name(self, palace: str, wing: str) -> str:
        """ChromaDB collection per (palace, wing)."""
        return f"{palace}_{wing}".replace("-", "_").replace(" ", "_").lower()

    def _collection(self, palace: str, wing: str):
        """Get or create a collection."""
        name = self._collection_name(palace, wing)
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

    def add(self, memory: Memory):
        """Add or update a memory in vector storage."""        
        collection = self._collection(memory.palace, memory.wing)
        now = datetime.now(timezone.utc).isoformat()
        if not memory.created_at:
            memory.created_at = now
        memory.updated_at = now

        metadata = {
            "palace": memory.palace,
            "wing": memory.wing,
            "room": memory.room,
            "drawer": memory.drawer,
            "content": memory.content[:500],  # preview in metadata
            "created_at": memory.created_at,
            "updated_at": memory.updated_at,
            **memory.metadata,
        }

        # Encode if no vector provided
        if memory.vector is None:
            vectors = self._embed.embed([memory.content])
            memory.vector = vectors[0]

        collection.upsert(
            ids=[memory.id],
            embeddings=[memory.vector],
            metadatas=[metadata],
            documents=[memory.content],
        )

    def delete(self, memory_id: str, palace: str, wing: str):
        """Delete a memory by ID."""
        collection = self._collection(palace, wing)
        collection.delete(ids=[memory_id])

    def search(
        self,
        query: str,
        palace: str | None = None,
        wing: str | None = None,
        n_results: int = 10,
        filter_metadata: dict[str, str] | None = None,
    ) -> list[Memory]:
        """Search memories by semantic similarity."""
        query_vector = self._embed.embed([query])[0]

        collections_to_search = self._resolve_collections(palace, wing)
        results: list[Memory] = []

        for col_name in collections_to_search:
            col = self._collections.get(col_name)
            if col is None:
                continue
            try:
                where = filter_metadata or None
                res = col.query(
                    query_embeddings=[query_vector],
                    n_results=n_results,
                    where=where,
                )
            except Exception:
                continue

            if not res["ids"] or not res["ids"][0]:
                continue

            for i, doc_id in enumerate(res["ids"][0]):
                meta = (res["metadatas"] or [{}])[0][i] if res.get("metadatas") else {}
                results.append(Memory(
                    id=doc_id,
                    palace=meta.get("palace", palace or ""),
                    wing=meta.get("wing", wing or ""),
                    room=meta.get("room", ""),
                    drawer=meta.get("drawer", ""),
                    content=res["documents"][0][i] if res.get("documents") else "",
                    metadata={k: v for k, v in meta.items() if k not in (
                        "palace", "wing", "room", "drawer", "content",
                        "created_at", "updated_at",
                    )},
                    created_at=meta.get("created_at", ""),
                    updated_at=meta.get("updated_at", ""),
                    vector=res["embeddings"][0][i] if res.get("embeddings") else None,
                ))

        return results[:n_results]

    def _resolve_collections(self, palace: str | None, wing: str | None) -> list[str]:
        """Resolve collections to search based on filters."""
        if palace and wing:
            name = self._collection_name(palace, wing)
            if name in self._collections:
                return [name]
            return []
        if palace:
            return [n for n in self._collections if n.startswith(palace + "_")]
        return list(self._collections.keys())

    def get_collections(self) -> list[dict[str, str]]:
        """List all collections (palace_wing combos) with counts."""
        client = self._lazy_client()
        collections = client.list_collections()
        result = []
        for col in collections:
            name = col.name
            count = col.count()
            if "_" in name:
                palace, wing = name.split("_", 1)
                result.append({"palace": palace, "wing": wing, "count": count})
            else:
                result.append({"palace": name, "wing": "", "count": count})
        return result

    def count(self, palace: str | None = None, wing: str | None = None) -> int:
        """Count memories."""
        total = 0
        for col_name in self._resolve_collections(palace, wing):
            col = self._collections.get(col_name)
            if col:
                total += col.count()
        return total


# ── SQLite metadata store ────────────────────────────────────────────────────


class SQLiteStore:
    """Metadata store for palaces, wings, rooms, drawers, and diaries."""

    def __init__(self, path: Path):
        self._db_path = path / "memorius.db"
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        """Thread-local connection."""
        if not hasattr(local, "memorius_conn") or local.memorius_conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            local.memorius_conn = conn
        return local.memorius_conn

    def _init_db(self):
        conn = self._conn()
        with self._lock:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS palaces (
                    name TEXT PRIMARY KEY,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS wings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    palace TEXT NOT NULL REFERENCES palaces(name),
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(palace, name)
                );
                CREATE TABLE IF NOT EXISTS rooms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    palace TEXT NOT NULL,
                    wing TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(palace, wing, name)
                );
                CREATE TABLE IF NOT EXISTS drawers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    palace TEXT NOT NULL,
                    wing TEXT NOT NULL,
                    room TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    memory_count INTEGER DEFAULT 0,
                    UNIQUE(palace, wing, room, name)
                );
                CREATE TABLE IF NOT EXISTS diaries (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    palace TEXT NOT NULL DEFAULT 'main',
                    title TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    exchange_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_diaries_session ON diaries(session_id);
                CREATE INDEX IF NOT EXISTS idx_diaries_palace ON diaries(palace);
                CREATE INDEX IF NOT EXISTS idx_rooms_hierarchy ON rooms(palace, wing);
                CREATE INDEX IF NOT EXISTS idx_drawers_hierarchy ON drawers(palace, wing, room);
            """)
            conn.commit()

    def ensure_palace(self, name: str, description: str = "") -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT OR IGNORE INTO palaces (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (name, description, now, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM palaces WHERE name = ?", (name,)).fetchone()
            return dict(row)

    def ensure_wing(self, palace: str, name: str, description: str = "") -> dict[str, Any]:
        self.ensure_palace(palace)
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT OR IGNORE INTO wings (palace, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (palace, name, description, now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM wings WHERE palace = ? AND name = ?", (palace, name)
            ).fetchone()
            return dict(row)

    def ensure_room(self, palace: str, wing: str, name: str, description: str = "") -> dict[str, Any]:
        self.ensure_wing(palace, wing)
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT OR IGNORE INTO rooms (palace, wing, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (palace, wing, name, description, now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM rooms WHERE palace = ? AND wing = ? AND name = ?",
                (palace, wing, name),
            ).fetchone()
            return dict(row)

    def ensure_drawer(self, palace: str, wing: str, room: str, name: str, description: str = "") -> dict[str, Any]:
        self.ensure_room(palace, wing, room)
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT OR IGNORE INTO drawers (palace, wing, room, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (palace, wing, room, name, description, now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM drawers WHERE palace = ? AND wing = ? AND room = ? AND name = ?",
                (palace, wing, room, name),
            ).fetchone()
            return dict(row)

    def list_palaces(self) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute("SELECT * FROM palaces ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def list_wings(self, palace: str) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM wings WHERE palace = ? ORDER BY name", (palace,)
        ).fetchall()
        return [dict(r) for r in rows]

    def list_rooms(self, palace: str, wing: str) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM rooms WHERE palace = ? AND wing = ? ORDER BY name",
            (palace, wing),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_drawers(self, palace: str, wing: str, room: str) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM drawers WHERE palace = ? AND wing = ? AND room = ? ORDER BY name",
            (palace, wing, room),
        ).fetchall()
        return [dict(r) for r in rows]

    def write_diary(self, session_id: str, palace: str, title: str = "",
                    summary: str = "", content: str = "",
                    exchange_count: int = 0) -> dict[str, Any]:
        """Create or update a diary entry."""
        now = datetime.now(timezone.utc).isoformat()
        entry_id = str(uuid.uuid4())
        conn = self._conn()
        with self._lock:
            conn.execute(
                """INSERT INTO diaries (id, session_id, palace, title, summary, content, exchange_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (entry_id, session_id, palace, title, summary, content, exchange_count, now, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM diaries WHERE id = ?", (entry_id,)).fetchone()
            return dict(row)

    def list_diaries(self, palace: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._conn()
        if palace:
            rows = conn.execute(
                "SELECT * FROM diaries WHERE palace = ? ORDER BY created_at DESC LIMIT ?",
                (palace, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM diaries ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_diary(self, session_id: str) -> dict[str, Any] | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM diaries WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_hierarchy(self, palace: str) -> dict[str, Any]:
        """Get the full hierarchy tree for a palace."""
        result = {"name": palace, "wings": []}
        for wing in self.list_wings(palace):
            w = {"name": wing["name"], "description": wing["description"], "rooms": []}
            for room in self.list_rooms(palace, wing["name"]):
                r = {"name": room["name"], "description": room["description"], "drawers": []}
                for drawer in self.list_drawers(palace, wing["name"], room["name"]):
                    r["drawers"].append({
                        "name": drawer["name"],
                        "description": drawer["description"],
                        "memory_count": drawer["memory_count"],
                    })
                w["rooms"].append(r)
            result["wings"].append(w)
        return result

    def increment_drawer_count(self, palace: str, wing: str, room: str, drawer: str):
        conn = self._conn()
        with self._lock:
            conn.execute(
                "UPDATE drawers SET memory_count = memory_count + 1, updated_at = ? WHERE palace = ? AND wing = ? AND room = ? AND name = ?",
                (datetime.now(timezone.utc).isoformat(), palace, wing, room, drawer),
            )
            conn.commit()

    def close(self):
        if hasattr(local, "memorius_conn") and local.memorius_conn:
            local.memorius_conn.close()
            local.memorius_conn = None


# ── Palace Engine ────────────────────────────────────────────────────────────


class PalaceEngine:
    """High-level palace operations combining vector + metadata stores."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or load_config()
        embed_cfg = self._config.get("embeddings", {})
        storage_cfg = self._config.get("storage", {})

        self._embed = EmbeddingFactory.create(embed_cfg)
        storage_path = Path(storage_cfg.get("path", "~/.memorius/data")).expanduser()
        self._vector = ChromaStore(storage_path / "vectors", self._embed)
        self._meta = SQLiteStore(storage_path)

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

    def store(self, content: str, palace: str = "main", wing: str = "default",
              room: str = "default", drawer: str = "default",
              metadata: dict[str, Any] | None = None) -> Memory:
        """Store a memory in the palace."""
        self._meta.ensure_drawer(palace, wing, room, drawer)
        memory = Memory(
            id=str(uuid.uuid4()),
            palace=palace,
            wing=wing,
            room=room,
            drawer=drawer,
            content=content,
            metadata=metadata or {},
        )
        self._vector.add(memory)
        self._meta.increment_drawer_count(palace, wing, room, drawer)
        return memory

    def search(self, query: str, palace: str | None = None,
               wing: str | None = None, n_results: int = 10) -> list[Memory]:
        """Semantic search across the palace."""
        return self._vector.search(query, palace, wing, n_results)

    def status(self) -> dict[str, Any]:
        """Get status of the palace."""
        palaces = self._meta.list_palaces()
        total_memories = self._vector.count()
        diaries = self._meta.list_diaries(limit=5)
        return {
            "palaces": len(palaces),
            "memories": total_memories,
            "diaries": len(diaries),
            "recent_diaries": diaries,
            "embedding_provider": self._config.get("embeddings", {}).get("provider", "unknown"),
            "embedding_dimension": self._embed.dimension,
        }

    def mine(self, transcript: str, palace: str = "main",
             wing: str = "conversations", room: str = "default",
             min_chunk_size: int = 50) -> list[Memory]:
        """Extract memories from a conversation transcript."""
        chunks = self._chunk_transcript(transcript, min_chunk_size)
        stored = []
        for chunk in chunks:
            memory = self.store(
                content=chunk,
                palace=palace,
                wing=wing,
                room=room,
                drawer="mined",
                metadata={"source": "transcript", "chunk": True},
            )
            stored.append(memory)
        return stored

    def write_diary(self, session_id: str, palace: str = "main",
                    title: str = "", summary: str = "",
                    content: str = "", exchange_count: int = 0) -> dict[str, Any]:
        """Write a diary entry for a session."""
        return self._meta.write_diary(session_id, palace, title, summary, content, exchange_count)

    def _chunk_transcript(self, transcript: str, min_size: int = 50) -> list[str]:
        """Split a transcript into meaningful chunks."""
        lines = transcript.strip().split("\n")
        if len(lines) <= 2:
            return [t.strip() for t in transcript.split("\n\n") if len(t.strip()) >= min_size]

        chunks = []
        current: list[str] = []
        for line in lines:
            current.append(line)
            if len("\n".join(current)) >= 200:
                chunk = "\n".join(current).strip()
                if len(chunk) >= min_size:
                    chunks.append(chunk)
                current = []
        if current:
            chunk = "\n".join(current).strip()
            if len(chunk) >= min_size:
                chunks.append(chunk)
        return chunks or [transcript]

    def hierarchy(self, palace: str) -> dict[str, Any]:
        return self._meta.get_hierarchy(palace)

    def close(self):
        self._meta.close()
