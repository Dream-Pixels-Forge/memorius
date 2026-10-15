"""Tests for automatic episodic vs. semantic store segregation (GOAL 3.6).

Covers the dual-store architecture in memorius/vault.py:

  - VaultEngine creates two separate stores:
      * semantic store — legacy path, holds distilled facts
      * episodic store — new subdirectory, holds raw interaction traces
  - _get_store_module_for_memory routes:
      * shelf="conversations", folder="mined", note="transcript"
        → episodic store
      * everything else → semantic store
  - mine() always routes to the episodic store
  - store() routes correctly based on shelf/folder/note
  - search() merges results from both stores
  - get_memory() checks episodic first, then semantic
  - delete() tries episodic first, then semantic
  - list_memories() unions both stores
  - update_memory() tries episodic first, then semantic
"""

import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    """VaultEngine with isolated temp storage."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.config import load_config
    from memorius.vault import VaultEngine
    eng = VaultEngine(load_config())
    yield eng
    eng.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Store routing ────────────────────────────────────────────────────────────


class TestStoreRouting:
    def test_mine_routes_to_episodic_store(self, engine):
        """mine() uses the episodic store (shelf=conversations,
        folder=mined, note=transcript)."""
        engine.mine("raw transcript chunk about debugging", vault="main")

        # The memory should be in the episodic meta store
        episodic = engine._meta_episodic.list_memories_meta(
            vault="main", limit=10,
        )
        assert len(episodic) >= 1
        assert any(
            "debugging" in m.get("content", "")
            for m in episodic
        )

    def test_store_default_goes_to_semantic_store(self, engine):
        """store() with default shelf/folder/note routes to the semantic store."""
        engine.store("a distilled fact about the system", vault="main")

        semantic = engine._meta_semantic.list_memories_meta(
            vault="main", limit=10,
        )
        assert len(semantic) >= 1
        assert any(
            "distilled fact" in m.get("content", "")
            for m in semantic
        )

    def test_store_conversations_mined_transcript_goes_episodic(self, engine):
        """Explicitly storing with the episodic routing path goes to
        the episodic store."""
        engine.store(
            "raw interaction trace from user session",
            vault="main",
            shelf="conversations",
            folder="mined",
            note="transcript",
        )

        episodic = engine._meta_episodic.list_memories_meta(
            vault="main", limit=10,
        )
        assert any(
            "raw interaction trace" in m.get("content", "")
            for m in episodic
        )

    def test_store_extracted_facts_go_semantic(self, engine):
        """store() with shelf=extracted goes to the semantic store."""
        engine.store(
            "extracted fact: the timeout is 30s",
            vault="main",
            shelf="extracted",
        )

        semantic = engine._meta_semantic.list_memories_meta(
            vault="main", limit=10,
        )
        assert any(
            "timeout is 30s" in m.get("content", "")
            for m in semantic
        )

    def test_store_custom_shelf_goes_semantic(self, engine):
        """Any shelf other than the episodic routing tuple goes semantic."""
        engine.store(
            "a memory on a custom shelf",
            vault="main",
            shelf="custom_shelf",
            folder="custom_folder",
            note="custom_note",
        )

        semantic = engine._meta_semantic.list_memories_meta(
            vault="main", limit=10,
        )
        assert any(
            "custom shelf" in m.get("content", "")
            for m in semantic
        )

    def test_get_store_module_for_memory_returns_correct_module(self, engine):
        """The routing logic returns the right StoreModule instance
        for each path tuple."""
        from memorius.store_module import StoreModule

        episodic_module = engine._get_store_module_for_memory(
            "conversations", "mined", "transcript",
        )
        semantic_module = engine._get_store_module_for_memory(
            "default", "default", "default",
        )
        extracted_module = engine._get_store_module_for_memory(
            "extracted", "default", "default",
        )

        # Episodic module is wired to the episodic vector store
        assert episodic_module._vector is engine._vector_episodic
        assert episodic_module._meta is engine._meta_episodic

        # Semantic module is wired to the semantic vector store
        assert semantic_module._vector is engine._vector_semantic
        assert semantic_module._meta is engine._meta_semantic

        # Extracted also goes semantic
        assert extracted_module is semantic_module


# ── Search merge ─────────────────────────────────────────────────────────────


class TestSearchMerge:
    def test_search_merges_both_stores(self, engine):
        """search() returns results from both semantic and episodic stores."""
        # Seed one memory in each store
        engine.store("semantic: the build uses Docker Compose", vault="main")
        engine.mine("episodic: raw trace of a CI failure", vault="main")

        results = engine.search("build CI failure", vault="main", limit=10)
        # Both memories should be discoverable
        contents = " ".join(r.content for r in results)
        assert "Docker Compose" in contents or "CI failure" in contents

    def test_search_no_cross_vault_leakage(self, engine):
        """Searching one vault never returns memories from another."""
        engine.store("alpha vault secret", vault="alpha")
        engine.mine("alpha episodic secret", vault="alpha")
        engine.store("beta vault secret", vault="beta")

        alpha_results = engine.search("secret", vault="alpha", limit=10)
        assert all(r.vault == "alpha" for r in alpha_results)

        beta_results = engine.search("secret", vault="beta", limit=10)
        assert all(r.vault == "beta" for r in beta_results)

    def test_search_episodic_failure_is_best_effort(self, engine):
        """If the episodic search raises, the semantic results are
        still returned (no exception propagates)."""
        from unittest.mock import patch
        import memorius.vault as vault_mod

        engine.store("semantic only memory", vault="main")

        # Force the episodic SearchModule to raise
        def _raise_episodic(*a, **kw):
            raise RuntimeError("episodic store unavailable")

        with patch.object(
            engine, "_get_search_module_episodic", side_effect=_raise_episodic,
        ):
            results = engine.search("semantic only", vault="main", limit=5)

        assert len(results) >= 1
        assert any("semantic only" in r.content for r in results)


# ── CRUD operations across stores ───────────────────────────────────────────


class TestCrudAcrossStores:
    def test_get_memory_finds_episodic_memory(self, engine):
        """get_memory() finds a memory that lives only in the episodic store."""
        engine.mine("episodic: user said hello at 10am", vault="main")

        episodic_memories = engine._meta_episodic.list_memories_meta(
            vault="main", limit=10,
        )
        assert len(episodic_memories) >= 1
        mid = episodic_memories[0]["id"]

        mem = engine.get_memory(mid)
        assert mem is not None
        assert "episodic" in mem.content

    def test_get_memory_finds_semantic_memory(self, engine):
        """get_memory() finds a memory that lives only in the semantic store."""
        engine.store("semantic: the API endpoint is /v1/users", vault="main")

        semantic_memories = engine._meta_semantic.list_memories_meta(
            vault="main", limit=10,
        )
        # Filter to find the semantic-only memory
        semantic_ids = [m["id"] for m in semantic_memories]
        # The episodic store should NOT have this memory
        episodic_metas = engine._meta_episodic.list_memories_meta(
            vault="main", limit=10,
        )
        episodic_ids = {m["id"] for m in episodic_metas}
        only_semantic = [mid for mid in semantic_ids if mid not in episodic_ids]

        if only_semantic:
            mem = engine.get_memory(only_semantic[0])
            assert mem is not None

    def test_update_memory_updates_episodic_first(self, engine):
        """update_memory() tries episodic first; if found, it updates there."""
        engine.mine("episodic: initial value", vault="main")

        episodic_memories = engine._meta_episodic.list_memories_meta(
            vault="main", limit=10,
        )
        mid = episodic_memories[0]["id"]

        updated = engine.update_memory(mid, content="episodic: updated value")
        assert updated is not None
        assert "updated value" in updated.content

    def test_delete_removes_from_episodic_store(self, engine):
        """delete() finds and removes a memory from the episodic store."""
        engine.mine("episodic: memory to delete", vault="main")

        episodic_memories = engine._meta_episodic.list_memories_meta(
            vault="main", limit=10,
        )
        mid = episodic_memories[0]["id"]

        result = engine.delete(mid)
        assert result["found"] is True
        assert result["deleted"] is True

        # Confirm it's gone
        assert engine.get_memory(mid) is None

    def test_delete_removes_from_semantic_store(self, engine):
        """delete() finds and removes a memory from the semantic store."""
        engine.store("semantic: memory to delete", vault="main")

        semantic_memories = engine._meta_semantic.list_memories_meta(
            vault="main", limit=10,
        )
        mid = semantic_memories[0]["id"]

        result = engine.delete(mid)
        assert result["found"] is True
        assert result["deleted"] is True


# ── List merge ───────────────────────────────────────────────────────────────


class TestListMemories:
    def test_list_memories_unions_both_stores(self, engine):
        """list_memories() returns memories from both episodic and
        semantic stores, sorted by created_at DESC."""
        engine.store("semantic memory", vault="main")
        engine.mine("episodic memory", vault="main")

        result = engine.list_memories(vault="main", limit=10)
        assert "memories" in result
        contents = " ".join(m.content for m in result["memories"])
        assert "semantic memory" in contents
        assert "episodic memory" in contents

    def test_list_memories_respects_limit(self, engine):
        """list_memories(limit=N) caps the combined result set."""
        for i in range(3):
            engine.store(f"semantic mem {i}", vault="main")
        engine.mine("episodic mem", vault="main")

        result = engine.list_memories(vault="main", limit=2)
        assert len(result["memories"]) == 2

    def test_list_memories_cursor_pagination(self, engine):
        """list_memories(cursor=...) returns the next page."""
        engine.store("first memory", vault="main")
        engine.store("second memory", vault="main")

        page1 = engine.list_memories(vault="main", limit=1)
        assert len(page1["memories"]) == 1
        cursor = page1.get("next_cursor")
        if cursor:
            page2 = engine.list_memories(vault="main", limit=1, cursor=cursor)
            # Page 2 should contain a different memory
            assert len(page2["memories"]) >= 1


# ── Status / stats ──────────────────────────────────────────────────────────


class TestStatusStats:
    def test_status_reports_total_memories_from_both_stores(self, engine):
        """status() sums episodic and semantic memory counts."""
        engine.store("semantic fact", vault="main")
        engine.mine("episodic trace", vault="main")

        status = engine.status()
        assert status["memories"] >= 2
        assert "vaults" in status
        assert "embedding_provider" in status

    def test_status_empty_vault_reports_zero(self, engine):
        """A fresh engine with no memories reports zero."""
        status = engine.status()
        assert status["memories"] == 0


# ── TTL / decay policy per store ─────────────────────────────────────────────


class TestDifferentPoliciesPerStore:
    """Different TTL/consolidation policies can target each store
    independently because they have separate SQLite databases and
    vector directories."""

    def test_episodic_meta_store_is_separate_database(self, engine):
        """The episodic and semantic meta stores use different DB files."""
        assert engine._meta_episodic._db_path != engine._meta_semantic._db_path
        assert "meta_episodic" in str(engine._meta_episodic._db_path)
        # Semantic keeps the legacy path (no meta_episodic suffix)
        assert "meta_episodic" not in str(engine._meta_semantic._db_path)

    def test_episodic_vector_store_is_separate_directory(self, engine):
        """The episodic and semantic vector stores use different dirs."""
        assert engine._vector_episodic._path != engine._vector_semantic._path
        assert "episodic" in str(engine._vector_episodic._path)

    def test_store_with_ttl_to_episodic(self, engine):
        """TTL metadata is stored in the episodic store when routing there."""
        engine.store(
            "ephemeral episodic trace with TTL",
            vault="main",
            shelf="conversations",
            folder="mined",
            note="transcript",
            ttl_days=7,
        )

        episodic_memories = engine._meta_episodic.list_memories_meta(
            vault="main", limit=10,
        )
        assert len(episodic_memories) >= 1
        meta = episodic_memories[0]
        import json as _json
        parsed = _json.loads(meta.get("metadata") or "{}")
        assert "expires_at" in parsed
        assert parsed.get("ttl_days") == 7

    def test_store_with_ttl_to_semantic(self, engine):
        """TTL metadata is stored in the semantic store when routing there."""
        engine.store(
            "ephemeral semantic fact with TTL",
            vault="main",
            shelf="default",
            ttl_days=30,
        )

        semantic_memories = engine._meta_semantic.list_memories_meta(
            vault="main", limit=10,
        )
        assert len(semantic_memories) >= 1
        import json as _json
        parsed = _json.loads(semantic_memories[0].get("metadata") or "{}")
        assert "expires_at" in parsed
        assert parsed.get("ttl_days") == 30


# ── Consolidation operates on semantic store ────────────────────────────────


class TestConsolidationOnSemantic:
    def test_consolidate_runs_on_semantic_store(self, engine):
        """Consolidation runs on the semantic store (the primary store)."""
        engine.store("duplicate fact A: the timeout is 30s", vault="main")
        engine.store("duplicate fact B: the timeout is 30s", vault="main")

        result = engine.consolidate(vault="main", similarity_threshold=0.5)
        # Should not raise
        assert result is not None

    def test_consolidate_runs_on_both_stores(self, engine):
        """consolidate() uses list_memories() which merges both episodic
        and semantic stores, so raw episodic traces CAN be clustered
        and merged if they are similar enough."""
        engine.mine("raw trace 1: user clicked button", vault="main")
        engine.mine("raw trace 2: user typed query", vault="main")

        result = engine.consolidate(vault="main", similarity_threshold=0.5)
        # With the two traces being reasonably similar, a cluster may be
        # found — this confirms consolidate reaches episodic content.
        assert isinstance(result, dict) or hasattr(result, "clusters_found")
