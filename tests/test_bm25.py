"""Tests for BM25 FTS5 search (v0.8.0)."""

import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from memorius.meta_store import SQLiteStore
from memorius.models import Memory
from memorius.vector_store_base import VectorStore


class _FakeVectorStore(VectorStore):
    """Minimal vector store that returns pre-configured results."""

    def __init__(self, results: list[Memory] | None = None):
        self._results = results or []

    def add(self, memory: Any) -> None:
        pass

    def delete(self, memory_id: str, vault: str, shelf: str) -> None:
        pass

    def search(
        self,
        query: str,
        vault: str | None = None,
        shelf: str | None = None,
        n_results: int = 10,
        filter_metadata: dict[str, str] | None = None,
    ) -> list[Memory]:
        return self._results[:n_results]

    def get_collections(self) -> list[dict[str, str]]:
        return []

    def count(self, vault: str | None = None, shelf: str | None = None) -> int:
        return 0

    def get_by_ids(
        self,
        ids: list[str],
        vault: str,
        shelf: str,
        include_vectors: bool = True,
    ) -> list[Memory]:
        return []


@pytest.fixture
def store():
    tmp = Path(tempfile.mkdtemp())
    s = SQLiteStore(tmp)
    yield s
    shutil.rmtree(tmp, ignore_errors=True)


def test_fts_table_exists(store):
    """FTS5 virtual table should be created on init."""
    tables = [r[0] for r in store._conn().execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "memory_fts" in tables


def test_fts_populated_on_track(store):
    """FTS index should contain content when a memory is tracked."""
    store.track_memory(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        vault="test", shelf="test", folder="test", note="test",
        content="Python programming language",
    )
    rows = store._conn().execute(
        "SELECT content FROM memory_fts"
    ).fetchall()
    contents = [r[0] for r in rows]
    assert "Python programming language" in contents


def test_bm25_search_finds_keyword(store):
    """bm25_search should find memories by keyword."""
    store.track_memory(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        vault="test", shelf="test", folder="test", note="test",
        content="Python programming language",
    )
    store.track_memory(
        "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
        vault="test", shelf="test", folder="test", note="test",
        content="JavaScript web development",
    )
    results = store.bm25_search("Python")
    assert len(results) >= 1
    assert any("Python" in r["content"] for r in results)


def test_bm25_search_no_results(store):
    """bm25_search should return empty list for unmatched query."""
    store.track_memory(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        vault="test", shelf="test", folder="test", note="test",
        content="Python programming",
    )
    results = store.bm25_search("xyznonexistent")
    assert len(results) == 0


def test_bm25_search_limit(store):
    """bm25_search should respect the limit parameter."""
    for i in range(5):
        store.track_memory(
            f"aaaaaaaa-bbbb-cccc-dddd-{i:012d}",
            vault="test", shelf="test", folder="test", note="test",
            content=f"Python item {i}",
        )
    results = store.bm25_search("Python", limit=3)
    assert len(results) <= 3


def test_bm25_search_returns_id_and_rank(store):
    """bm25_search results should include id, content, and rank."""
    store.track_memory(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        vault="test", shelf="test", folder="test", note="test",
        content="Python programming",
    )
    results = store.bm25_search("Python")
    assert len(results) == 1
    assert "id" in results[0]
    assert "content" in results[0]
    assert "rank" in results[0]


def test_hybrid_search_blends_vector_and_bm25(store):
    """Hybrid search should combine vector and BM25 scores."""
    from memorius.search_module import SearchModule

    store.track_memory(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        vault="test", shelf="test", folder="test", note="test",
        content="Python machine learning",
    )
    store.track_memory(
        "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
        vault="test", shelf="test", folder="test", note="test",
        content="Python web development",
    )
    store.track_memory(
        "cccccccc-dddd-eeee-ffff-000000000000",
        vault="test", shelf="test", folder="test", note="test",
        content="JavaScript frameworks",
    )

    vector_results = [
        Memory(
            id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            vault="test", shelf="test", folder="test", note="",
            content="Python machine learning",
            metadata={"__distance__": 0.2},
        ),
        Memory(
            id="bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
            vault="test", shelf="test", folder="test", note="",
            content="Python web development",
            metadata={"__distance__": 0.4},
        ),
        Memory(
            id="cccccccc-dddd-eeee-ffff-000000000000",
            vault="test", shelf="test", folder="test", note="",
            content="JavaScript frameworks",
            metadata={"__distance__": 0.9},
        ),
    ]

    vector = _FakeVectorStore(vector_results)
    sm = SearchModule(vector, store)
    results = sm.search("Python programming", use_hybrid=True)
    assert len(results) >= 2
    result_ids = [r.id for r in results]
    assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in result_ids
    assert "bbbbbbbb-cccc-dddd-eeee-ffffffffffff" in result_ids
