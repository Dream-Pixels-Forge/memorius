"""Tests for heat-score functionality (v0.8.0)."""

import datetime
import tempfile
import shutil
from pathlib import Path

import pytest

from memorius.temporal import (
    calculate_heat_score,
    classify_tier,
    calculate_combined_score_with_tier,
)
from memorius.meta_store import SQLiteStore


@pytest.fixture
def store():
    tmp = Path(tempfile.mkdtemp())
    s = SQLiteStore(tmp)
    yield s
    shutil.rmtree(tmp, ignore_errors=True)


def test_calculate_heat_score():
    """Heat score should return value between 0.0 and 1.0."""
    now = datetime.datetime.now(datetime.timezone.utc)
    created = (now - datetime.timedelta(days=7)).isoformat()
    accessed = (now - datetime.timedelta(hours=12)).isoformat()
    score = calculate_heat_score(created, accessed, access_count=5)
    assert 0.0 <= score <= 1.0


def test_calculate_heat_score_higher_when_recent():
    """More recently accessed memory should have higher heat score."""
    now = datetime.datetime.now(datetime.timezone.utc)
    created = (now - datetime.timedelta(days=7)).isoformat()
    recent = (now - datetime.timedelta(hours=1)).isoformat()
    old = (now - datetime.timedelta(days=3)).isoformat()
    score_recent = calculate_heat_score(created, recent, access_count=1)
    score_old = calculate_heat_score(created, old, access_count=1)
    assert score_recent > score_old


def test_classify_tier():
    """classify_tier should map scores to tiers."""
    assert classify_tier(0.8) == "hot"
    assert classify_tier(0.5) == "warm"
    assert classify_tier(0.2) == "cold"
    assert classify_tier(0.05) == "archived"


def test_calculate_combined_score_with_tier():
    """Tier should boost combined search score."""
    base = 0.5
    boosted_hot = calculate_combined_score_with_tier(base, "hot")
    boosted_cold = calculate_combined_score_with_tier(base, "cold")
    assert boosted_hot > base
    assert boosted_cold < base


def test_meta_store_has_heat_score(store):
    """SQLiteStore should support heat_score in memory_meta."""
    mid = store.track_memory(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        vault="test", shelf="test", folder="test", note="test",
        content="test heat score",
    )
    heat = store._conn().execute(
        "SELECT heat_score FROM memory_meta WHERE id=?",
        ("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",),
    ).fetchone()
    assert heat is not None
    assert heat[0] == 0.0


def test_update_heat_score(store):
    """update_heat_score should recalculate and store heat score."""
    import uuid
    mid = str(uuid.uuid4())
    store.track_memory(
        mid,
        vault="test", shelf="test", folder="test", note="test",
        content="test update heat",
    )
    meta = store.get_memory_meta(mid)
    assert meta["heat_score"] == 0.0
    store.update_heat_score(mid)
    meta2 = store.get_memory_meta(mid)
    assert meta2["heat_score"] > 0.0


def test_search_updates_heat_score(store):
    """search should update heat scores for returned memories."""
    from memorius.search_module import SearchModule
    from memorius.models import Memory
    import uuid
    
    # Create a fake vector store that returns a known memory
    class FakeVectorStore:
        def __init__(self, memories):
            self._memories = memories
        def search(self, query, vault=None, shelf=None, n_results=10, filter_metadata=None):
            return self._memories
        def add(self, memory): pass
        def delete(self, memory_id, vault, shelf): pass
        def get_collections(self): return []
        def count(self, vault=None, shelf=None): return 0
        def get_by_ids(self, ids, vault, shelf, include_vectors=True): return []
    
    mid = str(uuid.uuid4())
    # Track memory in meta store with heat_score 0
    store.track_memory(
        mid,
        vault="test", shelf="test", folder="test", note="test",
        content="test search heat",
    )
    # Create a Memory object that will be returned by vector search
    mem = Memory(
        id=mid,
        vault="test", shelf="test", folder="test", note="test",
        content="test search heat",
        metadata={},
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:00:00+00:00",
    )
    vector = FakeVectorStore([mem])
    search = SearchModule(vector, store)
    results = search.search("test query", vault="test")
    assert len(results) == 1
    assert results[0].id == mid
    meta = store.get_memory_meta(mid)
    assert meta["heat_score"] > 0.0


def test_tier_boosted_search(store):
    """Hot memories should rank higher than cold memories with same base score."""
    import uuid
    from memorius.search_module import SearchModule
    from memorius.models import Memory

    mid1 = str(uuid.uuid4())
    mid2 = str(uuid.uuid4())
    now = "2025-08-15T00:00:00+00:00"

    mem1 = Memory(
        id=mid1, vault="test", shelf="test", folder="test", note="test",
        content="hot memory about cats", metadata={"__distance__": 0.2},
        created_at=now, updated_at=now,
    )
    mem2 = Memory(
        id=mid2, vault="test", shelf="test", folder="test", note="test",
        content="cold memory about cats", metadata={"__distance__": 0.2},
        created_at=now, updated_at=now,
    )

    class FakeVectorStore:
        def search(self, query, vault=None, shelf=None, n_results=10, filter_metadata=None):
            return [mem2, mem1]
        def add(self, memory): pass
        def delete(self, memory_id, vault, shelf): pass
        def get_collections(self): return []
        def count(self, vault=None, shelf=None): return 0
        def get_by_ids(self, ids, vault, shelf, include_vectors=True): return []

    store.track_memory(mid1, vault="test", shelf="test", folder="test", note="test", content="hot memory about cats")
    store.track_memory(mid2, vault="test", shelf="test", folder="test", note="test", content="cold memory about cats")
    store._conn().execute("UPDATE memory_meta SET heat_score=0.9 WHERE id=?", (mid1,))
    store._conn().execute("UPDATE memory_meta SET heat_score=0.05 WHERE id=?", (mid2,))
    store._conn().commit()

    vector = FakeVectorStore()
    sm = SearchModule(vector, store)
    results = sm.search("cats")
    ids = [r.id for r in results]
    assert mid1 in ids
    assert mid2 in ids
    assert ids.index(mid1) < ids.index(mid2)
