"""Feature tests for CRUD operations (Phase 2.1): get, update, delete.

Phase 2.1 completes the basic CRUD surface:
- get_memory(id)   → returns Memory or None
- update_memory(id, content=None, metadata=None) → re-embeds + upserts
- delete(id)       → hard-deletes from both stores (already existed)
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def engine():
    """VaultEngine against an isolated temp store."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.config import load_config
    from memorius.vault import VaultEngine

    config = load_config()
    eng = VaultEngine(config)
    yield eng
    shutil.rmtree(tmp, ignore_errors=True)
    if hasattr(eng, "_vector") and hasattr(eng._vector, "_client"):
        try:
            eng._vector._client = None
        except Exception:
            pass


# ── get_memory ───────────────────────────────────────────────────────────────


def test_get_memory_returns_stored(engine):
    """get_memory returns the exact memory that was stored."""
    m = engine.store("CRUD get test content for retrieval", vault="cr")
    fetched = engine.get_memory(m.id)
    assert fetched is not None
    assert fetched.id == m.id
    assert fetched.content == "CRUD get test content for retrieval"
    assert fetched.vault == "cr"


def test_get_memory_returns_none_for_unknown(engine):
    """get_memory returns None when the ID does not exist."""
    import uuid
    result = engine.get_memory(str(uuid.uuid4()))
    assert result is None


def test_get_memory_returns_none_for_invalid(engine):
    """get_memory returns None for an invalid UUID string."""
    result = engine.get_memory("not-a-uuid")
    assert result is None


# ── update_memory ────────────────────────────────────────────────────────────


def test_update_memory_content(engine):
    """update_memory replaces content and re-embeds the vector."""
    m = engine.store("original content about machine learning", vault="cr")
    updated = engine.update_memory(m.id, content="updated content about deep learning")
    assert updated is not None
    assert updated.id == m.id
    assert updated.content == "updated content about deep learning"
    # The fetched content should match the update.
    fetched = engine.get_memory(m.id)
    assert fetched.content == "updated content about deep learning"


def test_update_memory_metadata_merges(engine):
    """update_memory shallow-merges metadata (does not discard existing keys)."""
    m = engine.store("metadata merge test content", vault="cr", metadata={"a": 1, "b": 2})
    updated = engine.update_memory(m.id, metadata={"b": 99, "c": 3})
    assert updated is not None
    # Metadata should have all three keys with b overwritten.
    assert updated.metadata.get("a") == 1
    assert updated.metadata.get("b") == 99
    assert updated.metadata.get("c") == 3
    # Fetched memory should also reflect the merged metadata.
    fetched = engine.get_memory(m.id)
    assert fetched.metadata.get("a") == 1
    assert fetched.metadata.get("b") == 99
    assert fetched.metadata.get("c") == 3


def test_update_memory_content_and_metadata(engine):
    """update_memory can update both content and metadata in one call."""
    m = engine.store("both fields test original", vault="cr", metadata={"x": 1})
    updated = engine.update_memory(m.id, content="both fields test updated", metadata={"y": 2})
    assert updated.content == "both fields test updated"
    assert updated.metadata.get("x") == 1
    assert updated.metadata.get("y") == 2


def test_update_memory_returns_none_for_unknown(engine):
    """update_memory returns None when the ID does not exist."""
    import uuid
    result = engine.update_memory(str(uuid.uuid4()), content="nope")
    assert result is None


def test_update_memory_meta_row_updated(engine):
    """After update_memory the meta row reflects the new content."""
    m = engine.store("meta row update test content", vault="cr")
    engine.update_memory(m.id, content="meta row updated content")
    meta = engine.meta.get_memory_meta(m.id)
    assert meta["content"] == "meta row updated content"


def test_update_memory_search_finds_new_content(engine):
    """After updating content, a search for the new content finds it."""
    m = engine.store("original searchable content about python", vault="cr")
    engine.update_memory(m.id, content="updated searchable content about rust")
    results = engine.search("rust programming language", vault="cr", limit=5)
    ids = [r.id for r in results]
    assert m.id in ids, f"updated memory should be findable by new content; got {ids}"


# ── delete (via engine) ─────────────────────────────────────────────────────


def test_delete_removes_from_both_stores(engine):
    """engine.delete() removes the memory from both vector and meta stores."""
    m = engine.store("delete test content for both stores", vault="cr")
    result = engine.delete(m.id)
    assert result["deleted"] is True
    # Should no longer be retrievable.
    assert engine.get_memory(m.id) is None
    # Meta row should be gone.
    assert engine.meta.get_memory_meta(m.id) is None


def test_delete_dry_run_does_not_delete(engine):
    """engine.delete with dry_run=True does not actually delete."""
    m = engine.store("dry run delete test content", vault="cr")
    result = engine.delete(m.id, dry_run=True)
    assert result["found"] is True
    assert result["deleted"] is False
    # Memory should still exist.
    assert engine.get_memory(m.id) is not None
