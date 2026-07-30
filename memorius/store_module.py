"""StoreModule — memory CRUD operations.

Extracted from VaultEngine to isolate the storage concern:
  - store: create and persist a memory
  - update: modify content/metadata of an existing memory
  - delete: remove a memory from both stores
  - touch: mark a memory as accessed
  - get_by_ids: batch fetch memories
  - get: single memory fetch

The module owns the coordination between VectorStore and MetaStore.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from memorius.models import Memory
from memorius.vector_store_base import VectorStore
from memorius.validation import validate_name, validate_memory_id
from memorius.utils import safe_parse_json

logger = logging.getLogger("memorius.store")


class StoreModule:
    """Memory CRUD — orchestrates VectorStore + MetaStore."""

    def __init__(self, vector: VectorStore, meta: Any):
        self._vector = vector
        self._meta = meta

    def store(
        self,
        content: str,
        vault: str = "main",
        shelf: str = "default",
        folder: str = "default",
        note: str = "default",
        metadata: dict[str, Any] | None = None,
        ttl_days: int | None = None,
        _vector: list[float] | None = None,
    ) -> Memory:
        """Store a memory in the vault.

        Args:
            ttl_days: optional time-to-live in days. When set, the memory
                becomes eligible for archival after this many days regardless
                of access count. Stored as ``expires_at`` ISO timestamp in
                metadata.
            _vector: pre-computed embedding vector (internal use for batch ops).
        """
        vault = validate_name(vault, "vault")
        shelf = validate_name(shelf, "shelf")
        folder = validate_name(folder, "folder")
        note = validate_name(note, "note")

        merged_metadata = dict(metadata or {})
        if ttl_days is not None and ttl_days >= 0:
            expires_at = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()
            merged_metadata["expires_at"] = expires_at
            merged_metadata["ttl_days"] = ttl_days

        self._meta.ensure_note(vault, shelf, folder, note)
        memory = Memory(
            id=str(uuid.uuid4()),
            vault=vault,
            shelf=shelf,
            folder=folder,
            note=note,
            content=content,
            metadata=merged_metadata,
            vector=_vector,
        )
        self._vector.add(memory)
        self._meta.increment_note_count(vault, shelf, folder, note)
        self._meta.track_memory(
            memory_id=memory.id, vault=vault, shelf=shelf,
            folder=folder, note=note, content=content, metadata=merged_metadata,
            created_at=memory.created_at,
        )
        # Auto-link to related memories via content similarity
        try:
            self._meta.init_graph()
            recent = self._meta.list_memories_meta(vault=vault, limit=50)
            self._meta.auto_link_by_proximity(memory.id, recent)
        except Exception:  # best-effort: graph linking failure should not prevent memory storage
            logger.debug("Graph linking failed (best-effort)")
        return memory

    def touch(self, memory_id: str) -> None:
        """Explicitly mark a memory as accessed (reinforce it).

        Use when an agent actually reads/uses a memory and you want the
        reinforcement model to credit it. Idempotent: safe to call on
        a missing id (no-op)."""
        try:
            validate_memory_id(memory_id)
            self._meta.record_access(memory_id)
        except Exception:  # best-effort: touch failure is non-critical (reinforcement only)
            logger.debug("touch(%s) failed (best-effort)", memory_id)

    def get_by_ids(
        self, ids: list[str], with_vectors: bool = True
    ) -> list[Memory]:
        """Fetch memories by exact ID. Vectors are pulled only when
        ``with_vectors=True``. Memories whose meta row is missing or
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

    def get(self, memory_id: str) -> Memory | None:
        """Fetch a single memory by ID. Returns None when the id is invalid
        or the memory does not exist."""
        try:
            memory_id = validate_memory_id(memory_id)
        except (ValueError, TypeError):
            return None
        results = self.get_by_ids([memory_id], with_vectors=True)
        return results[0] if results else None

    def update(
        self,
        memory_id: str,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Memory | None:
        """Update a memory's content and/or metadata. When ``content``
        changes the vector is re-embedded and upserted. When ``metadata``
        is provided it is shallow-merged with the existing metadata dict
        (new keys overwrite, existing keys without a new value are preserved).
        Returns the updated Memory or None when the id is invalid / not found."""
        try:
            memory_id = validate_memory_id(memory_id)
        except (ValueError, TypeError):
            return None
        meta = self._meta.get_memory_meta(memory_id)
        if meta is None:
            return None
        # Update meta row first.
        self._meta.update_memory_meta(memory_id, content=content, metadata=metadata)
        # Re-fetch the (possibly updated) memory from meta + vector.
        updated_metas = self._meta.get_memory_meta_batch([memory_id])
        updated_meta = updated_metas.get(memory_id, meta)
        # Build the Memory object to upsert into vector store.
        new_content = content if content is not None else updated_meta.get("content", meta["content"])
        merged_metadata = safe_parse_json(updated_meta.get("metadata", ""))
        if metadata is not None:
            merged_metadata.update(metadata)
        mem = Memory(
            id=memory_id,
            vault=updated_meta["vault"],
            shelf=updated_meta["shelf"],
            folder=updated_meta.get("folder", "default"),
            note=updated_meta.get("note", "default"),
            content=new_content,
            metadata=merged_metadata,
            created_at=updated_meta.get("created_at", ""),
            updated_at=updated_meta.get("updated_at", ""),
        )
        # Re-embed + upsert.
        self._vector.add(mem)
        return mem

    def delete(
        self,
        memory_id: str,
        vault: str | None = None,
        shelf: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
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
            vault = validate_name(vault, "vault")
            if vault != meta["vault"]:
                raise ValueError(
                    f"memory {memory_id} is in vault {meta['vault']!r}, not {vault!r}"
                )
        if shelf is not None:
            shelf = validate_name(shelf, "shelf")
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

    def list_memories(
        self,
        vault: str | None = None,
        shelf: str | None = None,
        limit: int | None = None,
        with_vectors: bool = True,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List memories by metadata (time-recency), optionally filling vectors
        from the VectorStore. Avoids the misuse of empty-query search as
        "list all". Returns Memories ordered by created_at DESC from the meta
        store.

        Returns a dict with keys:
            - memories: list of Memory objects
            - next_cursor: ISO timestamp of the last memory (use as cursor
              for the next page), or None if no more results
        """
        fetch_limit = (limit or 10000) + 1  # fetch one extra to detect next page
        meta_rows = self._meta.list_memories_meta(
            vault=vault, limit=fetch_limit, include_archived=False, cursor=cursor,
        )
        if not meta_rows:
            return {"memories": [], "next_cursor": None}

        # Check if there are more results
        has_more = len(meta_rows) > (limit or 10000)
        if has_more:
            meta_rows = meta_rows[:limit or 10000]

        # Defaults from meta rows (meta is source of truth for temporal order).
        memories: list[Memory] = []

        # Group meta rows by (vault, shelf) so we can batch-fetch from the right
        # collection.
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
                    md = safe_parse_json(row.get("metadata", ""))
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

        # Compute next_cursor as composite "created_at|id" to break ties
        # when multiple memories share the same timestamp.
        next_cursor = None
        if has_more and memories:
            last = memories[-1]
            ts = last.created_at or last.updated_at
            next_cursor = f"{ts}~{last.id}"

        return {"memories": memories, "next_cursor": next_cursor}
