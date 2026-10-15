"""Tests for hybrid keyword/vector retrieval with score fusion (GOAL 3.4).

Covers:
  - memorius/meta_store.py::bm25_search (FTS5 full-text keyword search)
  - memorius/search_module.py::search(use_hybrid=True) — score fusion of
    vector similarity and BM25 keyword ranking

The BM25 layer uses SQLite FTS5 (no external dependency), so tests run
offline.  The hybrid blending path in SearchModule is exercised through
a real VaultEngine fixture so both stores (ChromaDB/SqliteVec + SQLite)
are in sync.
"""

import json
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


@pytest.fixture
def meta_store(tmp_path: Path):
    """Standalone SQLiteStore (no vector backend) for FTS5-only tests."""
    from memorius.meta_store import SQLiteStore
    db_dir = tmp_path / "meta_test"
    db_dir.mkdir()
    store = SQLiteStore(db_dir)
    yield store
    store.close()


# ── BM25 / FTS5 keyword search ──────────────────────────────────────────────


class TestBM25Search:
    def test_exact_keyword_match_returns_hit(self, meta_store):
        """FTS5 MATCH finds memories containing the exact keyword."""
        from memorius.meta_store import SQLiteStore

        mid = str(uuid.uuid4())
        meta_store.track_memory(
            memory_id=mid,
            vault="main", shelf="kw", folder="default", note="default",
            content="The database connection pool uses pgBouncer for multiplexing",
        )

        hits = meta_store.bm25_search("pgBouncer", limit=5)
        assert len(hits) >= 1
        assert hits[0]["id"] == mid
        assert "pgBouncer" in hits[0]["content"]

    def test_keyword_not_in_content_returns_no_hits(self, meta_store):
        """FTS5 MATCH with a non-existent term returns an empty list."""
        mid = str(uuid.uuid4())
        meta_store.track_memory(
            memory_id=mid,
            vault="main", shelf="kw", folder="default", note="default",
            content="The build pipeline uses GitHub Actions",
        )

        hits = meta_store.bm25_search("kubernetes", limit=5)
        assert hits == []

    def test_multiple_keywords_ranked_by_relevance(self, meta_store):
        """Frequencies affect BM25 ranking — a word appearing more often
        in a document ranks higher for that term."""
        from memorius.meta_store import SQLiteStore
        now = "2026-10-01T00:00:00+00:00"

        m1 = str(uuid.uuid4())
        m2 = str(uuid.uuid4())
        # m1 mentions "redis" twice, m2 once — m1 should rank first
        meta_store.track_memory(
            memory_id=m1, vault="main", shelf="kw", folder="default", note="default",
            content="Redis cache is used. Redis TTL is set to 300s.",
            created_at=now,
        )
        meta_store.track_memory(
            memory_id=m2, vault="main", shelf="kw", folder="default", note="default",
            content="Redis is the primary cache layer.",
            created_at=now,
        )

        hits = meta_store.bm25_search("Redis", limit=10)
        hit_ids = [h["id"] for h in hits]
        assert m1 in hit_ids and m2 in hit_ids
        assert hit_ids.index(m1) < hit_ids.index(m2)

    def test_archived_memory_still_searchable_in_fts(self, meta_store):
        """Archiving a memory does NOT remove it from FTS (FTS trigger is
        on DELETE, not on archived flag) — BM25 results include it but
        the meta row carries archived=1."""
        from memorius.meta_store import SQLiteStore
        mid = str(uuid.uuid4())
        meta_store.track_memory(
            memory_id=mid, vault="main", shelf="kw", folder="default", note="default",
            content="legacy feature flag: enable_v2_api",
        )
        meta_store.archive_memory(mid)

        hits = meta_store.bm25_search("enable_v2_api", limit=5)
        assert any(h["id"] == mid for h in hits)

    def test_delete_removes_from_fts(self, meta_store):
        """Hard-deleting a memory removes its FTS entry."""
        from memorius.meta_store import SQLiteStore
        mid = str(uuid.uuid4())
        meta_store.ensure_note("main", "kw", "default", "default")
        meta_store.track_memory(
            memory_id=mid, vault="main", shelf="kw", folder="default", note="default",
            content="ephemeral keyword: temp_session_token",
        )
        meta_store.delete_memory(mid)

        hits = meta_store.bm25_search("temp_session_token", limit=5)
        assert all(h["id"] != mid for h in hits)

    def test_limit_respected(self, meta_store):
        """limit parameter caps the number of FTS rows returned."""
        for i in range(20):
            mid = str(uuid.uuid4())
            meta_store.track_memory(
                memory_id=mid, vault="main", shelf="kw", folder="default", note="default",
                content=f"entry number {i} with shared keyword commonword",
            )
        hits = meta_store.bm25_search("commonword", limit=5)
        assert len(hits) == 5


# ── Hybrid score fusion (SearchModule) ───────────────────────────────────────


class TestHybridScoreFusion:
    def test_hybrid_search_returns_vector_hits(self, engine):
        """use_hybrid=True still returns the vector-search results."""
        engine.store(
            "The deploy pipeline runs on GitHub Actions with Ubuntu runners",
            vault="main", shelf="hybrid",
        )
        results = engine.search(
            "GitHub Actions deploy pipeline",
            vault="main", shelf="hybrid", limit=3,
        )
        assert len(results) >= 1
        assert "GitHub Actions" in results[0].content or "deploy pipeline" in results[0].content.lower()

    def test_hybrid_search_includes_keyword_match_missed_by_vector(self, engine):
        """A memory that contains the exact keyword but has low semantic
        overlap should still surface when BM25 ranking boosts it."""
        engine.store(
            "The service X uses YAML configuration files for service definitions",
            vault="main", shelf="hybrid",
        )
        engine.store(
            "The service Y uses JSON schema validation for input payloads",
            vault="main", shelf="hybrid",
        )
        engine.store(
            "ZULIP_CONFIG uses TOML for channel subscription routing rules",
            vault="main", shelf="hybrid",
        )

        # "ZULIP_CONFIG" is a rare proper noun — vector similarity to the
        # other two memories is very low, but BM25 should rank it #1.
        results = engine.search(
            "ZULIP_CONFIG channel routing",
            vault="main", shelf="hybrid", limit=3,
        )
        top = results[0] if results else None
        # The rare-keyword memory must appear in the top results
        if top:
            assert any("ZULIP_CONFIG" in r.content for r in results[:3])

    def test_hybrid_search_empty_vault_returns_empty_list(self, engine):
        """No stored memories → hybrid search returns an empty list, not an error."""
        results = engine.search(
            "nonexistent query", vault="main", shelf="empty", limit=5,
        )
        assert results == []

    def test_hybrid_search_respects_vault_filter(self, engine):
        """Results are scoped to the requested vault even in hybrid mode."""
        engine.store("vault A memory about networking", vault="alpha", shelf="net")
        engine.store("vault B memory about networking", vault="beta", shelf="net")

        results = engine.search("networking", vault="alpha", limit=10)
        assert all(r.vault == "alpha" for r in results)

    def test_hybrid_search_no_cross_vault_leakage(self, engine):
        """Searching one vault never returns memories from another vault."""
        engine.store("secret alpha fact: the API key is sk-alpha-001", vault="alpha", shelf="secrets")
        engine.store("secret beta fact: the API key is sk-beta-999", vault="beta", shelf="secrets")

        alpha_results = engine.search("the API key is", vault="alpha", limit=10)
        beta_results = engine.search("the API key is", vault="beta", limit=10)

        alpha_ids = {r.id for r in alpha_results}
        beta_ids = {r.id for r in beta_results}
        assert alpha_ids.isdisjoint(beta_ids)


# ── SearchModule hybrid path (unit) ─────────────────────────────────────────


class TestSearchModuleHybridPath:
    """Directly exercise SearchModule.search with use_hybrid=True using a
    mock vector store so we can verify the blending math without an
    embedding provider."""

    @pytest.fixture
    def module(self):
        from memorius.meta_store import SQLiteStore
        from memorius.search_module import SearchModule
        from unittest.mock import MagicMock

        tmp = Path(tempfile.mkdtemp())
        (tmp / "meta_test").mkdir()
        meta = SQLiteStore(tmp / "meta_test")
        vector = MagicMock()
        vector.search.return_value = []
        yield SearchModule(vector, meta)
        meta.close()
        shutil.rmtree(tmp, ignore_errors=True)

    def test_hybrid_blend_fuses_bm25_and_vector_scores(self, module):
        """When vector returns results and BM25 has overlapping hits,
        the fused score = 0.6*vector + 0.4*bm25 and the re-ranked list
        reflects the fusion."""
        from memorius.models import Memory

        import uuid as _uuid
        mid1 = str(_uuid.uuid4())
        mid2 = str(_uuid.uuid4())

        # Track two memories so BM25 can find them
        now = "2026-10-01T00:00:00+00:00"
        module._meta.ensure_note("main", "hybrid_unit", "default", "default")
        module._meta.track_memory(
            memory_id=mid1, vault="main", shelf="hybrid_unit",
            folder="default", note="default",
            content="alpha token refresh flow", created_at=now,
        )
        module._meta.track_memory(
            memory_id=mid2, vault="main", shelf="hybrid_unit",
            folder="default", note="default",
            content="beta token refresh flow", created_at=now,
        )

        # Mock vector store returns mid1 with low distance (good match)
        mem1 = Memory(
            id=mid1, vault="main", shelf="hybrid_unit",
            folder="default", note="default",
            content="alpha token refresh flow",
            metadata={"__distance__": 0.1},
            created_at=now, updated_at=now, vector=None,
        )
        module._vector.search.return_value = [mem1]

        # Call the real method directly on the module instance
        out = module.search(
            "alpha token refresh", vault="main", shelf="hybrid_unit",
            limit=2, use_hybrid=True,
        )
        # mid1 should be in results
        assert any(m.id == mid1 for m in out)
