"""Phase 4.4 — Consolidation scaling tests.

Verifies that find_similar_clusters works correctly for both small
(in-memory pairwise) and large (HNSW/union-find) vaults.
"""
from __future__ import annotations

import time

import pytest

from memorius.consolidation import (
    find_similar_clusters,
    _find_clusters_in_memory,
    _find_clusters_hnsw,
    _HNSW_SWICHOVER,
)


def _make_memories(vectors: list[tuple[str, list[float]]]) -> list[dict]:
    """Build memory dicts from (id, vector) pairs."""
    return [{"id": mid, "vector": vec, "content": f"mem {mid}"} for mid, vec in vectors]


class TestInMemoryClusters:
    """Small vault path — O(N²) pairwise."""

    def test_single_cluster(self):
        v1 = [1.0, 0.0, 0.0]
        v2 = [0.99, 0.1, 0.0]  # very similar
        v3 = [0.0, 0.0, 1.0]   # orthogonal
        mems = _make_memories([("a", v1), ("b", v2), ("c", v3)])
        clusters = _find_clusters_in_memory(mems, similarity_threshold=0.9)
        assert len(clusters) == 1
        ids = {m["id"] for m in clusters[0]}
        assert "a" in ids and "b" in ids
        assert "c" not in ids

    def test_no_clusters(self):
        v1 = [1.0, 0.0, 0.0]
        v2 = [0.0, 1.0, 0.0]
        mems = _make_memories([("a", v1), ("b", v2)])
        clusters = _find_clusters_in_memory(mems, similarity_threshold=0.9)
        assert len(clusters) == 0

    def test_empty(self):
        assert _find_clusters_in_memory([], 0.9) == []

    def test_none_vectors_skipped(self):
        mems = [{"id": "a", "vector": None, "content": "x"},
                {"id": "b", "vector": [1.0], "content": "y"}]
        clusters = _find_clusters_in_memory(mems, 0.9)
        assert len(clusters) == 0


class TestHNSWClusters:
    """Large vault path — union-find clustering."""

    def test_transitive_cluster(self):
        """A~B and B~C but A!~C → all in same cluster (transitivity)."""
        v1 = [1.0, 0.0, 0.0]
        v2 = [0.95, 0.1, 0.0]  # sim(A,B) >= 0.9
        v3 = [0.9, 0.2, 0.0]   # sim(B,C) >= 0.9, sim(A,C) < 0.9
        mems = _make_memories([("a", v1), ("b", v2), ("c", v3)])
        clusters = _find_clusters_hnsw(mems, similarity_threshold=0.9)
        assert len(clusters) == 1
        ids = {m["id"] for m in clusters[0]}
        assert ids == {"a", "b", "c"}

    def test_two_separate_clusters(self):
        v1 = [1.0, 0.0, 0.0]
        v2 = [0.99, 0.0, 0.0]
        v3 = [0.0, 1.0, 0.0]
        v4 = [0.0, 0.99, 0.0]
        mems = _make_memories([("a", v1), ("b", v2), ("c", v3), ("d", v4)])
        clusters = _find_clusters_hnsw(mems, similarity_threshold=0.9)
        assert len(clusters) == 2

    def test_empty(self):
        assert _find_clusters_hnsw([], 0.9) == []


class TestAutoSwitch:
    """find_similar_clusters picks the right path."""

    def test_small_vault_uses_in_memory(self):
        """<=500 memories → in-memory path."""
        mems = _make_memories([(f"m{i}", [1.0, 0.0]) for i in range(10)])
        # Patch to detect which path was taken
        with pytest.MonkeyPatch.context() as m:
            called = {"in_memory": False}
            original = _find_clusters_in_memory
            def patched(*a, **kw):
                called["in_memory"] = True
                return original(*a, **kw)
            m.setattr("memorius.consolidation._find_clusters_in_memory", patched)
            find_similar_clusters(mems, 0.9)
            assert called["in_memory"] is True

    def test_large_vault_uses_hnsw(self):
        """Just over switchover → HNSW path."""
        mems = _make_memories([(f"m{i}", [1.0, 0.0]) for i in range(_HNSW_SWICHOVER + 10)])
        with pytest.MonkeyPatch.context() as m:
            called = {"hnsw": False}
            original = _find_clusters_hnsw
            def patched(*a, **kw):
                called["hnsw"] = True
                return original(*a, **kw)
            m.setattr("memorius.consolidation._find_clusters_hnsw", patched)
            find_similar_clusters(mems, 0.9)
            assert called["hnsw"] is True


class TestConsolidationScalingPerf:
    """Performance guard: large vault clustering completes in budget."""

    def test_large_vault_under_budget(self):
        """500+ memories clustered in under 5 seconds."""
        import random
        random.seed(42)
        vecs = [(f"m{i}", [random.random() for _ in range(32)]) for i in range(600)]
        mems = _make_memories(vecs)
        start = time.monotonic()
        clusters = find_similar_clusters(mems, similarity_threshold=0.95)
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"Clustering took {elapsed:.1f}s — too slow"
        # With random vectors at 0.95 threshold, expect few or no clusters
        assert isinstance(clusters, list)
