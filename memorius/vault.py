"""Storage engine — ChromaDB vector store + SQLite metadata store.

Hierarchy: Vault > Shelf > Folder > Note
  Vault   — top-level memory vault (replaces "palace")
  Shelf   — broad knowledge area (replaces "wing")
  Folder  — specific subject (replaces "room")
  Note    — individual memory slot (replaces "drawer")
"""

from __future__ import annotations

import atexit
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
from memorius.validation import validate_name as _validate_name

logger = logging.getLogger("memorius")

local = threading.local()


def _close_thread_conn():
    """Close the current thread's SQLite connection if open."""
    if hasattr(local, "memorius_conn") and local.memorius_conn:
        try:
            local.memorius_conn.close()
        except Exception:
            pass
        local.memorius_conn = None


atexit.register(_close_thread_conn)


# ── Data models ──────────────────────────────────────────────────────────────


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

    def add(self, memory: Memory):
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
    ) -> list[Memory]:
        """Search memories by semantic similarity."""
        query_vector = self._embed.embed([query])[0]

        collections_to_search = self._resolve_collections(vault, shelf)
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
                    include=["embeddings", "documents", "metadatas"],
                )
            except Exception:
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
        """Resolve collections to search based on filters.
        
        Loads all collections from ChromaDB if the in-memory cache is empty.
        """
        # Lazy-load all collections from ChromaDB if cache is empty
        if not self._collections:
            self._load_all_collections()

        if vault and shelf:
            name = self._collection_name(vault, shelf)
            if name in self._collections:
                return [name]
            # Collection might exist in ChromaDB but not in cache yet
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
            pass

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


# ── SQLite metadata store ────────────────────────────────────────────────────


class SQLiteStore:
    """Metadata store for vaults, shelves, folders, notes, and diaries."""

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

    # ── Migration helpers ──

    @staticmethod
    def _get_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        """Return column names for a table."""
        # Whitelist valid table names to prevent SQL injection
        _VALID_TABLES = {"diaries", "memories", "hierarchy", "graph_edges", "memory_meta"}
        if table not in _VALID_TABLES:
            raise ValueError(f"Invalid table name: {table}")
        # Use string concatenation (not f-string) — table is validated by whitelist above
        cur = conn.execute("PRAGMA table_info(" + table + ")")
        return {row["name"] for row in cur.fetchall()}

    def _migrate_diaries_table(self, conn: sqlite3.Connection):
        """Rename diaries.palace -> diaries.vault if old schema detected."""
        cols = self._get_columns(conn, "diaries")
        if "palace" in cols and "vault" not in cols:
            logger.warning("Detected old diaries schema (palace column) — migrating...")
            conn.executescript("""
                PRAGMA foreign_keys=OFF;
                CREATE TABLE diaries_new (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    vault TEXT NOT NULL DEFAULT 'main',
                    title TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    exchange_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO diaries_new
                    SELECT id, session_id, palace, title, summary,
                           content, exchange_count, created_at, updated_at
                    FROM diaries;
                DROP TABLE diaries;
                ALTER TABLE diaries_new RENAME TO diaries;
                PRAGMA foreign_keys=ON;
            """)
            conn.commit()
            logger.info("Migrated diaries table: palace -> vault")

    def _migrate_hierarchy(self, conn: sqlite3.Connection):
        """Migrate old palaces/wings/rooms/drawers to vaults/shelves/folders/notes."""
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='palaces'"
        )
        if not cur.fetchone():
            return  # already on new schema or fresh install

        logger.warning("Detected old hierarchy (palaces/wings/rooms/drawers) — migrating...")

        for p in conn.execute("SELECT * FROM palaces"):
            conn.execute(
                "INSERT OR IGNORE INTO vaults (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (p["name"], p["description"], p["created_at"], p["updated_at"]),
            )
            vault_name = p["name"]

            for w in conn.execute("SELECT * FROM wings WHERE palace = ?", (vault_name,)):
                conn.execute(
                    "INSERT OR IGNORE INTO shelves (vault, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (vault_name, w["name"], w["description"], w["created_at"], w["updated_at"]),
                )
                shelf_name = w["name"]

                for r in conn.execute(
                    "SELECT * FROM rooms WHERE palace = ? AND wing = ?",
                    (vault_name, shelf_name),
                ):
                    conn.execute(
                        "INSERT OR IGNORE INTO folders (vault, shelf, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (vault_name, shelf_name, r["name"], r["description"], r["created_at"], r["updated_at"]),
                    )
                    folder_name = r["name"]

                    for d in conn.execute(
                        "SELECT * FROM drawers WHERE palace = ? AND wing = ? AND room = ?",
                        (vault_name, shelf_name, folder_name),
                    ):
                        conn.execute(
                            "INSERT OR IGNORE INTO notes (vault, shelf, folder, name, description, created_at, updated_at, memory_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (vault_name, shelf_name, folder_name, d["name"], d["description"],
                             d["created_at"], d["updated_at"], d["memory_count"]),
                        )

        conn.commit()

        # Drop old tables after successful migration
        try:
            conn.executescript("""
                DROP TABLE IF EXISTS drawers;
                DROP TABLE IF EXISTS rooms;
                DROP TABLE IF EXISTS wings;
                DROP TABLE IF EXISTS palaces;
                DROP INDEX IF EXISTS idx_diaries_palace;
            """)
            conn.commit()
        except Exception as e:
            logger.warning(f"Could not drop old tables: {e}")

        logger.info("Migrated hierarchy: palaces/wings/rooms/drawers -> vaults/shelves/folders/notes")

    def _init_db(self):
        conn = self._conn()
        with self._lock:
            # Step 1: Detect and migrate old diaries schema
            self._migrate_diaries_table(conn)

            # Step 2: Create new tables (no-op if already exist)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS vaults (
                    name TEXT PRIMARY KEY,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS shelves (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vault TEXT NOT NULL REFERENCES vaults(name),
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(vault, name)
                );
                CREATE TABLE IF NOT EXISTS folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vault TEXT NOT NULL,
                    shelf TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(vault, shelf, name)
                );
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vault TEXT NOT NULL,
                    shelf TEXT NOT NULL,
                    folder TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    memory_count INTEGER DEFAULT 0,
                    UNIQUE(vault, shelf, folder, name)
                );
                CREATE TABLE IF NOT EXISTS diaries (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    vault TEXT NOT NULL DEFAULT 'main',
                    title TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    exchange_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_meta (
                    id TEXT PRIMARY KEY,
                    vault TEXT NOT NULL DEFAULT 'main',
                    shelf TEXT DEFAULT 'default',
                    folder TEXT DEFAULT 'default',
                    note TEXT DEFAULT 'default',
                    content TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    last_accessed TEXT,
                    access_count INTEGER DEFAULT 0,
                    archived INTEGER DEFAULT 0,
                    metadata TEXT DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
            """)
            conn.commit()

            # Step 3: Migrate old hierarchy data
            self._migrate_hierarchy(conn)

            # Step 4: Create indexes (safe after migration)
            conn.executescript("""
                CREATE INDEX IF NOT EXISTS idx_diaries_session ON diaries(session_id);
                CREATE INDEX IF NOT EXISTS idx_diaries_vault ON diaries(vault);
                CREATE INDEX IF NOT EXISTS idx_folders_hierarchy ON folders(vault, shelf);
                CREATE INDEX IF NOT EXISTS idx_notes_hierarchy ON notes(vault, shelf, folder);
                CREATE INDEX IF NOT EXISTS idx_memory_meta_vault ON memory_meta(vault);
                CREATE INDEX IF NOT EXISTS idx_memory_meta_archived ON memory_meta(archived);
            """)
            conn.commit()

    def ensure_vault(self, name: str, description: str = "") -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT OR IGNORE INTO vaults (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (name, description, now, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM vaults WHERE name = ?", (name,)).fetchone()
            return dict(row)

    def ensure_shelf(self, vault: str, name: str, description: str = "") -> dict[str, Any]:
        self.ensure_vault(vault)
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT OR IGNORE INTO shelves (vault, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (vault, name, description, now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM shelves WHERE vault = ? AND name = ?", (vault, name)
            ).fetchone()
            return dict(row)

    def ensure_folder(self, vault: str, shelf: str, name: str, description: str = "") -> dict[str, Any]:
        self.ensure_shelf(vault, shelf)
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT OR IGNORE INTO folders (vault, shelf, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (vault, shelf, name, description, now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM folders WHERE vault = ? AND shelf = ? AND name = ?",
                (vault, shelf, name),
            ).fetchone()
            return dict(row)

    def ensure_note(self, vault: str, shelf: str, folder: str, name: str, description: str = "") -> dict[str, Any]:
        self.ensure_folder(vault, shelf, folder)
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT OR IGNORE INTO notes (vault, shelf, folder, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (vault, shelf, folder, name, description, now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM notes WHERE vault = ? AND shelf = ? AND folder = ? AND name = ?",
                (vault, shelf, folder, name),
            ).fetchone()
            return dict(row)

    def list_vaults(self) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute("SELECT * FROM vaults ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def list_shelves(self, vault: str) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM shelves WHERE vault = ? ORDER BY name", (vault,)
        ).fetchall()
        return [dict(r) for r in rows]

    def list_folders(self, vault: str, shelf: str) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM folders WHERE vault = ? AND shelf = ? ORDER BY name",
            (vault, shelf),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_notes(self, vault: str, shelf: str, folder: str) -> list[dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM notes WHERE vault = ? AND shelf = ? AND folder = ? ORDER BY name",
            (vault, shelf, folder),
        ).fetchall()
        return [dict(r) for r in rows]

    def write_diary(self, session_id: str, vault: str, title: str = "",
                    summary: str = "", content: str = "",
                    exchange_count: int = 0) -> dict[str, Any]:
        """Create or update a diary entry."""
        now = datetime.now(timezone.utc).isoformat()
        entry_id = str(uuid.uuid4())
        conn = self._conn()
        with self._lock:
            conn.execute(
                """INSERT INTO diaries (id, session_id, vault, title, summary, content, exchange_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (entry_id, session_id, vault, title, summary, content, exchange_count, now, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM diaries WHERE id = ?", (entry_id,)).fetchone()
            return dict(row)

    def list_diaries(self, vault: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._conn()
        if vault:
            rows = conn.execute(
                "SELECT * FROM diaries WHERE vault = ? ORDER BY created_at DESC LIMIT ?",
                (vault, limit),
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

    def get_hierarchy(self, vault: str) -> dict[str, Any]:
        """Get the full hierarchy tree for a vault."""
        result = {"name": vault, "shelves": []}
        for shelf in self.list_shelves(vault):
            s = {"name": shelf["name"], "description": shelf["description"], "folders": []}
            for folder in self.list_folders(vault, shelf["name"]):
                f = {"name": folder["name"], "description": folder["description"], "notes": []}
                for note in self.list_notes(vault, shelf["name"], folder["name"]):
                    f["notes"].append({
                        "name": note["name"],
                        "description": note["description"],
                        "memory_count": note["memory_count"],
                    })
                s["folders"].append(f)
            result["shelves"].append(s)
        return result

    def increment_note_count(self, vault: str, shelf: str, folder: str, note: str):
        conn = self._conn()
        with self._lock:
            conn.execute(
                "UPDATE notes SET memory_count = memory_count + 1, updated_at = ? WHERE vault = ? AND shelf = ? AND folder = ? AND name = ?",
                (datetime.now(timezone.utc).isoformat(), vault, shelf, folder, note),
            )
            conn.commit()

    # ── Memory meta tracking (temporal, graph, archival) ──

    def track_memory(self, memory_id: str, vault: str, shelf: str, folder: str,
                     note: str, content: str, metadata: dict | None = None):
        """Track a memory in the meta table for temporal/graph features."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT OR REPLACE INTO memory_meta (id, vault, shelf, folder, note, content, created_at, last_accessed, access_count, archived, metadata, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)",
                (memory_id, vault, shelf, folder, note, content, now, now,
                 json.dumps(metadata or {}), now),
            )
            conn.commit()

    def record_access(self, memory_id: str):
        """Record that a memory was accessed (for temporal decay scoring)."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "UPDATE memory_meta SET last_accessed = ?, access_count = access_count + 1, updated_at = ? WHERE id = ?",
                (now, now, memory_id),
            )
            conn.commit()

    def get_memory_meta(self, memory_id: str) -> dict | None:
        """Get metadata for a memory."""
        conn = self._conn()
        row = conn.execute("SELECT * FROM memory_meta WHERE id = ?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def list_memories_meta(self, vault: str | None = None, limit: int = 100,
                           include_archived: bool = False) -> list[dict]:
        """List memory metadata with optional vault filter."""
        conn = self._conn()
        if vault:
            if include_archived:
                rows = conn.execute(
                    "SELECT * FROM memory_meta WHERE vault = ? ORDER BY created_at DESC LIMIT ?",
                    (vault, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memory_meta WHERE vault = ? AND archived = 0 ORDER BY created_at DESC LIMIT ?",
                    (vault, limit),
                ).fetchall()
        else:
            if include_archived:
                rows = conn.execute(
                    "SELECT * FROM memory_meta ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memory_meta WHERE archived = 0 ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def archive_memory(self, memory_id: str):
        """Soft-delete a memory (mark as archived)."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "UPDATE memory_meta SET archived = 1, updated_at = ? WHERE id = ?",
                (now, memory_id),
            )
            conn.commit()

    def get_memory_stats(self) -> dict:
        """Get statistics about tracked memories."""
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) FROM memory_meta").fetchone()[0]
        archived = conn.execute("SELECT COUNT(*) FROM memory_meta WHERE archived = 1").fetchone()[0]
        active = total - archived
        by_vault = conn.execute(
            "SELECT vault, COUNT(*) FROM memory_meta WHERE archived = 0 GROUP BY vault"
        ).fetchall()
        return {
            "total": total,
            "active": active,
            "archived": archived,
            "by_vault": {r[0]: r[1] for r in by_vault},
        }

    def close(self):
        """Close the current thread's connection."""
        _close_thread_conn()


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
        self._vector = None  # release ChromaDB reference

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
        # Validate names to prevent path traversal
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
        # Track in meta table for temporal/graph features
        self._meta.track_memory(
            memory_id=memory.id, vault=vault, shelf=shelf,
            folder=folder, note=note, content=content, metadata=metadata,
        )
        # Auto-link to related memories via embedding proximity
        try:
            from memorius.graph import auto_link_by_proximity, init_graph_schema
            conn = self._meta._conn()
            init_graph_schema(conn)
            # Get recent memories from same vault for proximity linking
            recent = self._meta.list_memories_meta(vault=vault, limit=50)
            auto_link_by_proximity(conn, memory.id, recent)
        except Exception:
            pass  # graph linking is best-effort
        return memory

    def search(self, query: str, vault: str | None = None,
               shelf: str | None = None, limit: int = 10) -> list[Memory]:
        """Search vault contents by semantic similarity with temporal decay ranking."""
        results = self._vector.search(query, vault=vault, shelf=shelf, n_results=limit * 2)
        # Apply temporal decay scoring to re-rank results
        try:
            from memorius.temporal import calculate_decay_score, calculate_search_score
            scored = []
            for mem in results:
                meta = self._meta.get_memory_meta(mem.id)
                decay = 1.0
                access_count = 0
                if meta:
                    decay = calculate_decay_score(
                        created_at=meta.get("created_at", ""),
                        last_accessed=meta.get("last_accessed"),
                        access_count=meta.get("access_count", 0),
                    )
                    access_count = meta.get("access_count", 0)
                # Semantic similarity is approximated by rank position (1.0 for first, decreasing)
                rank_pos = results.index(mem)
                semantic_sim = max(0.1, 1.0 - (rank_pos * 0.05))
                final_score = calculate_search_score(
                    semantic_similarity=semantic_sim,
                    decay_score=decay,
                    access_count=access_count,
                )
                scored.append((mem, final_score))
            # Sort by combined score descending
            scored.sort(key=lambda x: x[1], reverse=True)
            results = [m for m, _ in scored[:limit]]
        except Exception:
            results = results[:limit]
        # Record access for temporal decay scoring
        for mem in results:
            try:
                self._meta.record_access(mem.id)
            except Exception:
                pass
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

    # ── New feature methods (v0.2.0) ──

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
