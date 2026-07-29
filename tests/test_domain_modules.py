"""Unit tests for SearchModule and StoreModule — the domain-layer modules
extracted from VaultEngine."""

import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from memorius.models import Memory


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    """Create a VaultEngine with isolated temp storage per test."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.vault import VaultEngine
    from memorius.config import load_config

    config = load_config()
    eng = VaultEngine(config)
    yield eng
    eng.close()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def store(engine):
    """Return a StoreModule wired to the engine's vector + meta stores."""
    from memorius.store_module import StoreModule

    return StoreModule(engine._vector, engine._meta)


@pytest.fixture
def search(engine):
    """Return a SearchModule wired to the engine's vector + meta stores."""
    from memorius.search_module import SearchModule

    return SearchModule(engine._vector, engine._meta)


# ── SearchModule tests ───────────────────────────────────────────────────────


class TestSearchModule:
    def test_search_basic_query_returns_results(self, engine, store, search):
        """A basic semantic query finds a previously stored memory."""
        store.store("Python is a programming language", vault="search-test")
        store.store("The weather is sunny today", vault="search-test")

        results = search.search("programming language", vault="search-test")
        assert len(results) >= 1
        assert any("Python" in m.content for m in results)

    def test_search_folder_filter(self, store, search):
        """Filtering by folder restricts results to that folder."""
        store.store("alpha", vault="vf", folder="docs", note="n1")
        store.store("beta", vault="vf", folder="logs", note="n2")

        results = search.search("text", vault="vf", folder="docs")
        assert all(m.folder == "docs" for m in results)

    def test_search_note_filter(self, store, search):
        """Filtering by note restricts results to that note."""
        store.store("gamma", vault="vf", folder="f1", note="note-a")
        store.store("delta", vault="vf", folder="f1", note="note-b")

        results = search.search("content", vault="vf", note="note-a")
        assert all(m.note == "note-a" for m in results)

    def test_search_tags_filter(self, store, search):
        """Post-filter by tags keeps only memories carrying all specified tags."""
        store.store(
            "tagged memory", vault="tf", metadata={"tags": ["python", "tdd"]}
        )
        store.store(
            "untagged memory", vault="tf", metadata={"tags": ["other"]}
        )

        results = search.search("memory", vault="tf", tags=["python", "tdd"])
        assert len(results) >= 1
        assert all(
            set(["python", "tdd"]).issubset(
                set(m.metadata.get("tags", []))
            )
            for m in results
        )

    def test_search_expand_graph_false_no_expansion(self, store, search):
        """expand_graph=False returns only vector results."""
        store.store("alpha graph seed", vault="ge")
        store.store("beta graph connected", vault="ge")

        results = search.search("graph", vault="ge", expand_graph=False)
        # Just verify it returns results and doesn't crash.
        assert isinstance(results, list)

    def test_search_expand_graph_true(self, engine, store, search):
        """expand_graph=True appends graph-linked memories (best-effort)."""
        # Store several memories so there's data to link.
        for i in range(5):
            store.store(f"graph expansion test item {i}", vault="ge2")

        results_no_graph = search.search(
            "graph expansion", vault="ge2", expand_graph=False, limit=5
        )
        results_with_graph = search.search(
            "graph expansion", vault="ge2", expand_graph=True, limit=5
        )
        # Graph expansion is best-effort; at minimum it doesn't shrink results.
        assert len(results_with_graph) >= len(results_no_graph)

    def test_search_invalid_folder_raises(self, store, search):
        """Invalid folder name raises ValueError from validation."""
        with pytest.raises(ValueError, match="folder"):
            search.search("query", vault="x", folder="has spaces!")


# ── StoreModule tests ────────────────────────────────────────────────────────


class TestStoreModule:
    def test_store_returns_memory_object(self, store):
        """store() creates and returns a Memory with a valid UUID."""
        m = store.store("hello world", vault="sm-test")
        assert isinstance(m, Memory)
        assert m.id
        # Validate it's a real UUID
        uuid.UUID(m.id)
        assert m.vault == "sm-test"
        assert m.content == "hello world"

    def test_store_with_ttl_sets_expires_at(self, store):
        """store() with ttl_days populates expires_at in metadata."""
        m = store.store("ttl test", vault="sm-ttl", ttl_days=7)
        assert "expires_at" in m.metadata
        assert "ttl_days" in m.metadata
        assert m.metadata["ttl_days"] == 7

    def test_store_without_ttl_no_expires(self, store):
        """store() without ttl_days does not set expires_at."""
        m = store.store("no ttl", vault="sm-notl")
        assert "expires_at" not in m.metadata

    def test_touch_records_access(self, store):
        """touch() records an access on the memory (best-effort, no crash)."""
        m = store.store("touch me", vault="sm-touch")
        # touch should not raise
        store.touch(m.id)
        # Call again — idempotent
        store.touch(m.id)

    def test_touch_invalid_id_no_crash(self, store):
        """touch() with an invalid ID is a no-op."""
        store.touch("not-a-uuid")  # should not raise

    def test_get_returns_memory_by_id(self, store):
        """get() fetches a stored memory by its ID."""
        m = store.store("fetch me", vault="sm-get")
        fetched = store.get(m.id)
        assert fetched is not None
        assert fetched.id == m.id
        assert fetched.content == "fetch me"

    def test_get_returns_none_for_invalid_id(self, store):
        """get() returns None for a nonexistent or invalid ID."""
        assert store.get("00000000-0000-0000-0000-000000000000") is None
        assert store.get("garbage") is None

    def test_get_by_ids_batch(self, store):
        """get_by_ids() fetches multiple memories in one call."""
        m1 = store.store("batch one", vault="sm-ids")
        m2 = store.store("batch two", vault="sm-ids")
        results = store.get_by_ids([m1.id, m2.id])
        assert len(results) == 2
        ids = {r.id for r in results}
        assert m1.id in ids
        assert m2.id in ids

    def test_get_by_ids_empty_returns_empty(self, store):
        """get_by_ids([]) returns an empty list."""
        assert store.get_by_ids([]) == []

    def test_update_changes_content(self, store):
        """update() changes the content of an existing memory."""
        m = store.store("original content", vault="sm-upd")
        updated = store.update(m.id, content="updated content")
        assert updated is not None
        assert updated.content == "updated content"

    def test_update_merges_metadata(self, store):
        """update() merges new metadata with existing."""
        m = store.store(
            "meta merge", vault="sm-merge", metadata={"key1": "val1"}
        )
        updated = store.update(m.id, metadata={"key2": "val2"})
        assert updated is not None
        assert updated.metadata.get("key1") == "val1"
        assert updated.metadata.get("key2") == "val2"

    def test_update_returns_none_for_invalid_id(self, store):
        """update() returns None when the memory ID doesn't exist."""
        result = store.update(
            "00000000-0000-0000-0000-000000000000", content="nope"
        )
        assert result is None

    def test_delete_removes_from_both_stores(self, store):
        """delete() removes the memory from vector and meta stores."""
        m = store.store("delete me", vault="sm-del")
        result = store.delete(m.id)
        assert result["deleted"] is True
        assert result["found"] is True
        # Confirm it's gone
        assert store.get(m.id) is None

    def test_delete_dry_run_does_not_delete(self, store):
        """delete(dry_run=True) reports what would be deleted but keeps it."""
        m = store.store("dry run target", vault="sm-dry")
        result = store.delete(m.id, dry_run=True)
        assert result["deleted"] is False
        assert result["found"] is True
        # Memory still exists
        assert store.get(m.id) is not None

    def test_delete_with_mismatched_vault_raises(self, store):
        """delete() with a vault that doesn't match raises ValueError."""
        m = store.store("vault mismatch", vault="sm-v1")
        with pytest.raises(ValueError, match="vault"):
            store.delete(m.id, vault="wrong-vault")

    def test_delete_not_found(self, store):
        """delete() on a nonexistent ID returns found=False."""
        result = store.delete(
            "00000000-0000-0000-0000-000000000000", vault="x"
        )
        assert result["found"] is False
        assert result["deleted"] is False

    def test_list_memories_returns_results(self, store):
        """list_memories() returns stored memories."""
        store.store("list one", vault="sm-list")
        store.store("list two", vault="sm-list")
        result = store.list_memories(vault="sm-list")
        assert "memories" in result
        assert "next_cursor" in result
        assert len(result["memories"]) >= 2

    def test_list_memories_pagination(self, store):
        """list_memories() with limit returns a page and next_cursor."""
        for i in range(5):
            store.store(f"page item {i}", vault="sm-page")
        page1 = store.list_memories(vault="sm-page", limit=2)
        assert len(page1["memories"]) <= 2
        if page1["next_cursor"] is not None:
            page2 = store.list_memories(
                vault="sm-page", limit=2, cursor=page1["next_cursor"]
            )
            assert len(page2["memories"]) >= 1
            # No overlap between pages
            p1_ids = {m.id for m in page1["memories"]}
            p2_ids = {m.id for m in page2["memories"]}
            assert p1_ids.isdisjoint(p2_ids)

    def test_list_memories_empty_vault(self, store):
        """list_memories() on an empty vault returns empty list."""
        result = store.list_memories(vault="empty-vault-xyz")
        assert result["memories"] == []
        assert result["next_cursor"] is None
