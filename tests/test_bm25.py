"""Tests for BM25 FTS5 search (v0.8.0)."""

import shutil
import tempfile
from pathlib import Path

import pytest

from memorius.meta_store import SQLiteStore


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
