"""SQLite metadata store for memorius.

Handles vault hierarchy, diaries, memory tracking, and temporal metadata.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import sqlite3
import threading
import uuid
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("memorius.meta")

local = threading.local()


def _close_thread_conn():
    """Close ALL of the current thread's SQLite connections if open."""
    conns = getattr(local, "memorius_conns", None)
    if not conns:
        return
    for conn in conns.values():
        try:
            conn.close()
        except Exception:  # best-effort: prevent atexit handler from raising during shutdown
            pass
    local.memorius_conns = {}


atexit.register(_close_thread_conn)


class SQLiteStore:
    """Metadata store for vaults, shelves, folders, notes, and diaries."""

    def __init__(self, path: Path):
        self._db_path = path / "memorius.db"
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        """Thread-local, per-db-path connection."""
        conns = getattr(local, "memorius_conns", None)
        if conns is None:
            conns = {}
            local.memorius_conns = conns
        key = str(self._db_path)
        conn = conns.get(key)
        if conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conns[key] = conn
        return conn

    # ── Public query API ──

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a single SQL statement and commit.

        Use for INSERT, UPDATE, DELETE, or DDL. Returns the cursor so the
        caller can inspect ``lastrowid`` or ``rowcount`` if needed.
        """
        conn = self._conn()
        with self._lock:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur

    def execute_many(self, sql: str, params_seq: list[tuple]) -> sqlite3.Cursor:
        """Execute a SQL statement against every parameter set and commit."""
        conn = self._conn()
        with self._lock:
            cur = conn.executemany(sql, params_seq)
            conn.commit()
            return cur

    def executescript(self, script: str) -> None:
        """Execute a multi-statement SQL script and commit."""
        conn = self._conn()
        with self._lock:
            conn.executescript(script)
            conn.commit()

    def fetchone(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        """Execute a SELECT and return a single row as a dict (or None)."""
        conn = self._conn()
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetchall(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute a SELECT and return all rows as a list of dicts."""
        conn = self._conn()
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    @contextlib.contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager that wraps a block in a single transaction.

        Commits on clean exit, rolls back on exception.  The connection
        object is yielded but callers should prefer ``execute()`` /
        ``fetchone()`` / ``fetchall()`` over raw ``conn`` calls for
        forward-compatibility.

        Usage::

            with meta.transaction() as conn:
                conn.execute("INSERT INTO ...", (...))
                # auto-committed unless an exception propagates
        """
        conn = self._conn()
        with self._lock:
            try:
                conn.execute("BEGIN")
                yield conn
                conn.commit()
            except Exception:  # transaction rollback-and-raise pattern
                conn.rollback()
                raise

    # ── Migration helpers ──

    @staticmethod
    def _get_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        """Return column names for a table.

        Table names are validated against a fixed allowlist before being
        interpolated into the PRAGMA statement.  SQLite PRAGMA does not
        support parameterized table names, so the whitelist is the
        security boundary here.
        """
        _VALID_TABLES = frozenset({"diaries", "memories", "hierarchy", "graph_edges", "memory_meta"})
        if table not in _VALID_TABLES:
            raise ValueError(f"Invalid table name: {table}")
        cur = conn.execute(f"PRAGMA table_info({table})")
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
            return

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

        try:
            conn.executescript("""
                DROP TABLE IF EXISTS drawers;
                DROP TABLE IF EXISTS rooms;
                DROP TABLE IF EXISTS wings;
                DROP TABLE IF EXISTS palaces;
                DROP INDEX IF EXISTS idx_diaries_palace;
            """)
            conn.commit()
        except Exception as e:  # best-effort: old table drop failure is non-critical
            logger.warning("Could not drop old tables: %s", e)

        logger.info("Migrated hierarchy: palaces/wings/rooms/drawers -> vaults/shelves/folders/notes")

    def _init_db(self) -> None:
        conn = self._conn()
        with self._lock:
            self._migrate_diaries_table(conn)

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

            self._migrate_hierarchy(conn)

            conn.executescript("""
                CREATE INDEX IF NOT EXISTS idx_diaries_session ON diaries(session_id);
                CREATE INDEX IF NOT EXISTS idx_diaries_vault ON diaries(vault);
                CREATE INDEX IF NOT EXISTS idx_folders_hierarchy ON folders(vault, shelf);
                CREATE INDEX IF NOT EXISTS idx_notes_hierarchy ON notes(vault, shelf, folder);
                CREATE INDEX IF NOT EXISTS idx_memory_meta_vault ON memory_meta(vault);
                CREATE INDEX IF NOT EXISTS idx_memory_meta_archived ON memory_meta(archived);
                CREATE INDEX IF NOT EXISTS idx_memory_meta_cursor ON memory_meta(created_at, id);
            """)
            conn.commit()

    # ── Graph adapter ──

    def init_graph(self) -> None:
        """Ensure the knowledge graph schema exists."""
        from memorius.graph import init_graph_schema
        init_graph_schema(self._conn())

    def link_memories(self, source_id: str, target_id: str,
                      weight: float = 1.0, relation: str = "related") -> None:
        """Create a bidirectional link between two memories."""
        from memorius.graph import link_memories
        link_memories(self._conn(), source_id, target_id, weight, relation)

    def get_linked(self, memory_id: str, relation: str | None = None,
                   min_weight: float = 0.0) -> list[dict[str, Any]]:
        """Get all memories linked to a given memory."""
        from memorius.graph import get_linked
        return get_linked(self._conn(), memory_id, relation, min_weight)

    def auto_link_by_proximity(self, memory_id: str,
                               all_memories: list[dict[str, Any]],
                               threshold: float = 0.3, max_links: int = 10) -> None:
        """Create links based on content similarity."""
        from memorius.graph import auto_link_by_proximity
        auto_link_by_proximity(self._conn(), memory_id, all_memories, threshold, max_links)

    def get_graph_stats(self) -> dict[str, Any]:
        """Get knowledge graph statistics."""
        from memorius.graph import get_graph_stats
        return get_graph_stats(self._conn())

    def get_graph_data(self, vault: str | None = None, shelf: str | None = None,
                       relation: str | None = None, min_weight: float = 0.0,
                       limit: int = 500) -> dict[str, Any]:
        """Get complete graph topology (nodes and edges) for visualization."""
        from memorius.graph import get_graph_data
        return get_graph_data(
            self._conn(), vault=vault, shelf=shelf, relation=relation,
            min_weight=min_weight, limit=limit,
        )

    def expand_graph(self, seed_ids: list[str], hops: int = 1,
                     min_weight: float = 0.3, max_nodes: int = 50) -> dict[str, Any]:
        """Expand from seed IDs through the graph."""
        from memorius.graph import expand_graph
        return expand_graph(self._conn(), seed_ids, hops, min_weight, max_nodes)

    # ── Temporal adapter ──

    def archive_memories(self, memory_ids: list[str]) -> None:
        """Mark memories as archived (soft delete)."""
        from memorius.temporal import archive_memories
        archive_memories(self._conn(), memory_ids)

    def find_stale_memories(self, threshold: float = 0.1,
                            limit: int = 100) -> list[dict[str, Any]]:
        """Find memories below the decay threshold."""
        from memorius.temporal import find_stale_memories
        return find_stale_memories(self._conn(), threshold, limit)

    # ── Hierarchy operations ──

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

    def increment_note_count(self, vault: str, shelf: str, folder: str, note: str) -> None:
        conn = self._conn()
        with self._lock:
            conn.execute(
                "UPDATE notes SET memory_count = memory_count + 1, updated_at = ? WHERE vault = ? AND shelf = ? AND folder = ? AND name = ?",
                (datetime.now(timezone.utc).isoformat(), vault, shelf, folder, note),
            )
            conn.commit()

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

    # ── Diary operations ──

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

    # ── Memory meta tracking ──

    def track_memory(self, memory_id: str, vault: str, shelf: str, folder: str,
                     note: str, content: str, metadata: dict[str, Any] | None = None,
                     created_at: str | None = None) -> None:
        """Track a memory in the meta table for temporal/graph features."""
        now = created_at or datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT OR REPLACE INTO memory_meta (id, vault, shelf, folder, note, content, created_at, last_accessed, access_count, archived, metadata, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)",
                (memory_id, vault, shelf, folder, note, content, now, now,
                 json.dumps(metadata or {}), now),
            )
            conn.commit()

    def record_access(self, memory_id: str) -> None:
        """Record that a memory was accessed (for temporal decay scoring)."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "UPDATE memory_meta SET last_accessed = ?, access_count = access_count + 1, updated_at = ? WHERE id = ?",
                (now, now, memory_id),
            )
            conn.commit()

    def update_memory_meta(self, memory_id: str, content: str | None = None,
                           metadata: dict[str, Any] | None = None) -> bool:
        """Update content and/or metadata for an existing memory.

        Returns True if the row was updated, False if the memory was not found.
        Metadata is shallow-merged: existing keys are kept unless overwritten
        by the new dict.  ``updated_at`` is always refreshed.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            row = conn.execute(
                "SELECT * FROM memory_meta WHERE id = ?", (memory_id,)
            ).fetchone()
            if not row:
                return False
            cur_meta = json.loads(row["metadata"]) if row["metadata"] else {}
            if metadata is not None:
                cur_meta.update(metadata)
            if content is not None:
                conn.execute(
                    "UPDATE memory_meta SET content = ?, metadata = ?, updated_at = ? WHERE id = ?",
                    (content, json.dumps(cur_meta), now, memory_id),
                )
            else:
                conn.execute(
                    "UPDATE memory_meta SET metadata = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(cur_meta), now, memory_id),
                )
            conn.commit()
        return True

    def get_memory_meta(self, memory_id: str) -> dict[str, Any] | None:
        """Get metadata for a memory."""
        conn = self._conn()
        row = conn.execute("SELECT * FROM memory_meta WHERE id = ?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def get_memory_meta_batch(self, memory_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Get metadata for multiple memories in a single query.

        Each ID is validated as a UUID to prevent SQL injection via the
        ``WHERE IN`` clause.  Invalid IDs are silently skipped.
        """
        if not memory_ids:
            return {}
        conn = self._conn()
        safe_ids = []
        for mid in memory_ids:
            if not mid:
                continue
            try:
                import uuid as _uuid
                _uuid.UUID(str(mid))
                safe_ids.append(str(mid))
            except (ValueError, TypeError, AttributeError):
                continue
        if not safe_ids:
            return {}
        placeholders = ",".join("?" for _ in safe_ids)
        rows = conn.execute(
            "SELECT * FROM memory_meta WHERE id IN (" + placeholders + ")",
            safe_ids,
        ).fetchall()
        return {row["id"]: dict(row) for row in rows}

    def list_memories_meta(self, vault: str | None = None, limit: int = 100,
                           include_archived: bool = False,
                           cursor: str | None = None) -> list[dict[str, Any]]:
        """List memory metadata with optional vault filter and cursor pagination.

        Args:
            cursor: Composite cursor ``"timestamp~memory_id"`` from the
                previous page.  When set, returns items created *before*
                the cursor, breaking ties by id.
        """
        conn = self._conn()

        # Parse composite cursor into (timestamp, id).
        cursor_ts: str | None = None
        cursor_id: str | None = None
        if cursor:
            if "~" in cursor:
                cursor_ts, cursor_id = cursor.split("~", 1)
            else:
                # Legacy cursor (pre-0.9.0): bare timestamp without id.
                cursor_ts = cursor
                cursor_id = ""

        if vault:
            if include_archived:
                if cursor:
                    rows = conn.execute(
                        "SELECT * FROM memory_meta WHERE vault = ? "
                        "AND (created_at, id) < (?, ?) "
                        "ORDER BY created_at DESC LIMIT ?",
                        (vault, cursor_ts, cursor_id, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM memory_meta WHERE vault = ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (vault, limit),
                    ).fetchall()
            else:
                if cursor:
                    rows = conn.execute(
                        "SELECT * FROM memory_meta WHERE vault = ? AND archived = 0 "
                        "AND (created_at, id) < (?, ?) "
                        "ORDER BY created_at DESC LIMIT ?",
                        (vault, cursor_ts, cursor_id, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM memory_meta WHERE vault = ? AND archived = 0 "
                        "ORDER BY created_at DESC LIMIT ?",
                        (vault, limit),
                    ).fetchall()
        else:
            if include_archived:
                if cursor:
                    rows = conn.execute(
                        "SELECT * FROM memory_meta "
                        "WHERE (created_at, id) < (?, ?) "
                        "ORDER BY created_at DESC LIMIT ?",
                        (cursor_ts, cursor_id, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM memory_meta ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
            else:
                if cursor:
                    rows = conn.execute(
                        "SELECT * FROM memory_meta WHERE archived = 0 "
                        "AND (created_at, id) < (?, ?) "
                        "ORDER BY created_at DESC LIMIT ?",
                        (cursor_ts, cursor_id, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM memory_meta WHERE archived = 0 "
                        "ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
        return [dict(r) for r in rows]

    def archive_memory(self, memory_id: str) -> None:
        """Soft-delete a memory (mark as archived)."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        with self._lock:
            conn.execute(
                "UPDATE memory_meta SET archived = 1, updated_at = ? WHERE id = ?",
                (now, memory_id),
            )
            conn.commit()

    def delete_memory(self, memory_id: str) -> dict[str, Any] | None:
        """Hard-delete a memory and clean up its graph edges + note count.

        Returns the deleted memory's metadata, or None if it didn't exist
        (so callers can distinguish 'not found' from 'deleted').
        """
        conn = self._conn()
        meta = self.get_memory_meta(memory_id)
        if not meta:
            return None
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            # Remove graph edges referencing this memory (both directions).
            try:
                conn.execute(
                    "DELETE FROM memory_graph WHERE source_id = ? OR target_id = ?",
                    (memory_id, memory_id),
                )
            except sqlite3.OperationalError:
                pass  # graph table may not exist if no links were ever created
            # Decrement the owning note's memory count (floor at 0).
            conn.execute(
                "UPDATE notes SET memory_count = MAX(0, memory_count - 1), updated_at = ? "
                "WHERE vault = ? AND shelf = ? AND folder = ? AND name = ?",
                (now, meta["vault"], meta["shelf"], meta["folder"], meta["note"]),
            )
            # Hard-delete the memory row.
            conn.execute("DELETE FROM memory_meta WHERE id = ?", (memory_id,))
            conn.commit()
        return dict(meta)

    def get_memory_stats(self) -> dict[str, Any]:
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

    # ── Batch export (backup) ──

    def export_hierarchy(self) -> dict[str, Any]:
        """Export all hierarchy tables for backup."""
        return {
            "vaults": self.fetchall("SELECT name, description, created_at, updated_at FROM vaults"),
            "shelves": self.fetchall("SELECT vault, name, description, created_at, updated_at FROM shelves"),
            "folders": self.fetchall("SELECT vault, shelf, name, description, created_at, updated_at FROM folders"),
            "notes": self.fetchall("SELECT vault, shelf, folder, name, description, memory_count, created_at, updated_at FROM notes"),
        }

    def export_memories_meta(self) -> list[dict[str, Any]]:
        """Export all memory metadata for backup."""
        return self.fetchall(
            "SELECT id, vault, shelf, folder, note, content, metadata, "
            "access_count, last_accessed, created_at, updated_at FROM memory_meta"
        )

    def export_diaries(self) -> list[dict[str, Any]]:
        """Export all diaries for backup."""
        return self.fetchall(
            "SELECT id, session_id, vault, title, summary, content, "
            "exchange_count, created_at, updated_at FROM diaries"
        )

    def export_graph_edges(self) -> list[dict[str, Any]]:
        """Export all graph edges for backup."""
        try:
            return self.fetchall(
                "SELECT source_id, target_id, weight, relation, created_at FROM memory_graph"
            )
        except Exception:  # best-effort: graph table may not exist — return empty list
            return []

    def import_hierarchy(self, vaults: list[dict[str, Any]], shelves: list[dict[str, Any]],
                         folders: list[dict[str, Any]], notes: list[dict[str, Any]]) -> None:
        """Import hierarchy tables from a backup."""
        now = datetime.now(timezone.utc).isoformat()
        for v in vaults:
            self.execute(
                "INSERT OR IGNORE INTO vaults (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (v["name"], v.get("description", ""), v.get("created_at", now), v.get("updated_at", now)),
            )
        for s in shelves:
            self.execute(
                "INSERT OR IGNORE INTO shelves (vault, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (s["vault"], s["name"], s.get("description", ""), s.get("created_at", now), s.get("updated_at", now)),
            )
        for f in folders:
            self.execute(
                "INSERT OR IGNORE INTO folders (vault, shelf, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (f["vault"], f["shelf"], f["name"], f.get("description", ""), f.get("created_at", now), f.get("updated_at", now)),
            )
        for n in notes:
            self.execute(
                "INSERT OR IGNORE INTO notes (vault, shelf, folder, name, description, memory_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (n["vault"], n["shelf"], n["folder"], n["name"],
                 n.get("description", ""), n.get("memory_count", 0),
                 n.get("created_at", now), n.get("updated_at", now)),
            )

    def import_memory_meta(self, memory_data: dict[str, Any], *, merge: bool = True) -> bool:
        """Import a single memory metadata row. Returns True if imported."""
        mid = memory_data["id"]
        now = datetime.now(timezone.utc).isoformat()
        existing = self.fetchone("SELECT id FROM memory_meta WHERE id = ?", (mid,))
        if existing:
            if not merge:
                self.execute(
                    "UPDATE memory_meta SET vault=?, shelf=?, folder=?, note=?, "
                    "content=?, metadata=?, access_count=?, last_accessed=?, "
                    "created_at=?, updated_at=? WHERE id=?",
                    (memory_data["vault"], memory_data["shelf"], memory_data["folder"],
                     memory_data["note"], memory_data["content"],
                     memory_data.get("metadata", "{}"), memory_data.get("access_count", 0),
                     memory_data.get("last_accessed"), memory_data.get("created_at", now),
                     memory_data.get("updated_at", now), mid),
                )
                return True
            return False
        self.execute(
            "INSERT INTO memory_meta (id, vault, shelf, folder, note, content, "
            "metadata, access_count, last_accessed, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, memory_data["vault"], memory_data["shelf"], memory_data["folder"],
             memory_data["note"], memory_data["content"],
             memory_data.get("metadata", "{}"), memory_data.get("access_count", 0),
             memory_data.get("last_accessed"), memory_data.get("created_at", now),
             memory_data.get("updated_at", now)),
        )
        return True

    def import_diary(self, diary_data: dict[str, Any], *, merge: bool = True) -> bool:
        """Import a single diary entry. Returns True if imported."""
        did = diary_data["id"]
        now = datetime.now(timezone.utc).isoformat()
        existing = self.fetchone("SELECT id FROM diaries WHERE id = ?", (did,))
        if existing:
            if not merge:
                self.execute(
                    "UPDATE diaries SET session_id=?, vault=?, title=?, summary=?, "
                    "content=?, exchange_count=?, created_at=?, updated_at=? WHERE id=?",
                    (diary_data["session_id"], diary_data["vault"], diary_data.get("title", ""),
                     diary_data.get("summary", ""), diary_data.get("content", ""),
                     diary_data.get("exchange_count", 0),
                     diary_data.get("created_at", now), diary_data.get("updated_at", now), did),
                )
                return True
            return False
        self.execute(
            "INSERT INTO diaries (id, session_id, vault, title, summary, content, "
            "exchange_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (did, diary_data["session_id"], diary_data["vault"], diary_data.get("title", ""),
             diary_data.get("summary", ""), diary_data.get("content", ""),
             diary_data.get("exchange_count", 0),
             diary_data.get("created_at", now), diary_data.get("updated_at", now)),
        )
        return True

    def import_graph_edges(self, edges: list[dict[str, Any]]) -> int:
        """Import graph edges from a backup. Returns count imported."""
        self.init_graph()
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for e in edges:
            try:
                self.execute(
                    "INSERT OR IGNORE INTO memory_graph (source_id, target_id, weight, relation, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (e["source_id"], e["target_id"], e.get("weight", 1.0),
                     e.get("relation", "related"), e.get("created_at", now)),
                )
                count += 1
            except Exception:  # best-effort: skip corrupted edge, continue with rest
                pass
        return count

    def count_meta_rows(self) -> int:
        """Count rows in memory_meta."""
        return self.fetchone("SELECT COUNT(*) as c FROM memory_meta")["c"]

    def count_graph_edges(self) -> int:
        """Count rows in memory_graph."""
        try:
            return self.fetchone("SELECT COUNT(*) as c FROM memory_graph")["c"]
        except Exception:  # best-effort: graph table may not exist yet — return 0
            return 0

    def close(self) -> None:
        """Close the current thread's connection."""
        _close_thread_conn()

    def close_connection(self, db_path: Path) -> None:
        """Close only the connection for this specific db_path on the current thread.

        Unlike ``close()`` which closes *all* memorius connections for the
        thread, this method scopes cleanup to this instance's database file,
        leaving other VaultEngine instances untouched.
        """
        conns = getattr(local, "memorius_conns", None)
        if not conns:
            return
        key = str(db_path)
        conn = conns.pop(key, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # best-effort: prevent close errors during cleanup
                pass
