"""SQLite metadata store for memorius.

Handles vault hierarchy, diaries, memory tracking, and temporal metadata.
"""

from __future__ import annotations

import atexit
import json
import logging
import sqlite3
import threading
import uuid
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
        except Exception:
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

    # ── Migration helpers ──

    @staticmethod
    def _get_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        """Return column names for a table."""
        _VALID_TABLES = {"diaries", "memories", "hierarchy", "graph_edges", "memory_meta"}
        if table not in _VALID_TABLES:
            raise ValueError(f"Invalid table name: {table}")
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
        except Exception as e:
            logger.warning(f"Could not drop old tables: {e}")

        logger.info("Migrated hierarchy: palaces/wings/rooms/drawers -> vaults/shelves/folders/notes")

    def _init_db(self):
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
            """)
            conn.commit()

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

    def increment_note_count(self, vault: str, shelf: str, folder: str, note: str):
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

    def update_memory_meta(self, memory_id: str, content: str | None = None,
                           metadata: dict | None = None) -> bool:
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

    def get_memory_meta(self, memory_id: str) -> dict | None:
        """Get metadata for a memory."""
        conn = self._conn()
        row = conn.execute("SELECT * FROM memory_meta WHERE id = ?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def get_memory_meta_batch(self, memory_ids: list[str]) -> dict[str, dict]:
        """Get metadata for multiple memories in a single query."""
        if not memory_ids:
            return {}
        conn = self._conn()
        # Validate all IDs are non-empty strings to prevent injection
        safe_ids = [str(mid) for mid in memory_ids if mid]
        if not safe_ids:
            return {}
        placeholders = ",".join("?" * len(safe_ids))
        rows = conn.execute(
            "SELECT * FROM memory_meta WHERE id IN (" + placeholders + ")",
            safe_ids,
        ).fetchall()
        return {row["id"]: dict(row) for row in rows}

    def list_memories_meta(self, vault: str | None = None, limit: int = 100,
                           include_archived: bool = False,
                           cursor: str | None = None) -> list[dict]:
        """List memory metadata with optional vault filter and cursor pagination.

        Args:
            cursor: ISO timestamp of the last item from the previous page.
                When set, returns items created *before* this timestamp.
        """
        conn = self._conn()
        if vault:
            if include_archived:
                if cursor:
                    rows = conn.execute(
                        "SELECT * FROM memory_meta WHERE vault = ? AND created_at < ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (vault, cursor, limit),
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
                        "AND created_at < ? ORDER BY created_at DESC LIMIT ?",
                        (vault, cursor, limit),
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
                        "SELECT * FROM memory_meta WHERE created_at < ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (cursor, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM memory_meta ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
            else:
                if cursor:
                    rows = conn.execute(
                        "SELECT * FROM memory_meta WHERE archived = 0 AND created_at < ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (cursor, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM memory_meta WHERE archived = 0 "
                        "ORDER BY created_at DESC LIMIT ?",
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

    def delete_memory(self, memory_id: str) -> dict | None:
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
