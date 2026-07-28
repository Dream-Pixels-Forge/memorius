"""Tests for Phase 5.3 — SQLite-vec fallback vector store."""
import json
from pathlib import Path

import pytest

from memorius.config import load_config
from memorius.sqlite_vec_store import SqliteVecStore, _cosine_distance


@pytest.fixture
def engine(tmp_path):
    """Engine with sqlite-vec storage backend."""
    config = load_config()
    config["storage"]["path"] = str(tmp_path / "data")
    config["storage"]["type"] = "sqlite-vec"
    from memorius.vault import VaultEngine
    return VaultEngine(config)


@pytest.fixture
def store(tmp_path):
    """Raw SqliteVecStore for unit tests."""
    from memorius.embeddings import EmbeddingFactory
    embed = EmbeddingFactory.create({"provider": "chroma-default"})
    return SqliteVecStore(tmp_path / "vectors", embed)


class TestCosineDistance:
    def test_identical_vectors(self):
        """Identical vectors have distance 0."""
        assert _cosine_distance([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)

    def test_orthogonal_vectors(self):
        """Orthogonal vectors have distance 1."""
        assert _cosine_distance([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)

    def test_opposite_vectors(self):
        """Opposite vectors have distance 2."""
        assert _cosine_distance([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(2.0)

    def test_zero_vector(self):
        """Zero vector returns distance 1."""
        assert _cosine_distance([0.0, 0.0], [1.0, 0.0]) == 1.0


class TestSqliteVecStore:
    def test_add_and_search(self, store):
        """Add a memory and search for it."""
        from memorius.models import Memory
        mem = Memory(
            id="m1", vault="test", shelf="main",
            folder="default", note="default",
            content="Python is a programming language",
        )
        store.add(mem)
        results = store.search("programming", vault="test", n_results=5)
        assert len(results) >= 1
        assert results[0].id == "m1"

    def test_add_updates_on_same_id(self, store):
        """Adding with same ID updates the existing record."""
        from memorius.models import Memory
        mem1 = Memory(id="m1", vault="test", shelf="main",
                       folder="default", note="default", content="Python is great")
        store.add(mem1)
        mem2 = Memory(id="m1", vault="test", shelf="main",
                       folder="default", note="default", content="Java is great")
        store.add(mem2)
        results = store.search("Java", vault="test", n_results=5)
        assert len(results) >= 1
        assert results[0].id == "m1"
        assert "Java" in results[0].content

    def test_delete(self, store):
        """Deleted memory no longer appears in search."""
        from memorius.models import Memory
        mem = Memory(id="m1", vault="test", shelf="main",
                      folder="default", note="default", content="Hello world")
        store.add(mem)
        store.delete("m1", "test", "main")
        results = store.search("Hello", vault="test", n_results=5)
        assert len(results) == 0

    def test_count(self, store):
        """count() returns correct number."""
        from memorius.models import Memory
        for i in range(3):
            mem = Memory(id=f"m{i}", vault="test", shelf="main",
                          folder="default", note="default", content=f"Memory {i}")
            store.add(mem)
        assert store.count("test", "main") == 3

    def test_get_by_ids(self, store):
        """get_by_ids returns correct memories."""
        from memorius.models import Memory
        mem = Memory(id="m1", vault="test", shelf="main",
                      folder="default", note="default", content="Test content")
        store.add(mem)
        results = store.get_by_ids(["m1"], "test", "main")
        assert len(results) == 1
        assert results[0].id == "m1"
        assert results[0].content == "Test content"

    def test_get_by_ids_empty(self, store):
        """get_by_ids with empty list returns empty."""
        assert store.get_by_ids([], "test", "main") == []

    def test_get_collections(self, store):
        """get_collections returns vault/shelf combos."""
        from memorius.models import Memory
        mem = Memory(id="m1", vault="test", shelf="main",
                      folder="default", note="default", content="Test")
        store.add(mem)
        cols = store.get_collections()
        assert len(cols) == 1
        assert cols[0]["vault"] == "test"
        assert cols[0]["shelf"] == "main"
        assert cols[0]["count"] == 1

    def test_search_vault_filter(self, store):
        """search filters by vault."""
        from memorius.models import Memory
        mem1 = Memory(id="m1", vault="v1", shelf="main",
                       folder="default", note="default", content="Python code")
        mem2 = Memory(id="m2", vault="v2", shelf="main",
                       folder="default", note="default", content="Python code")
        store.add(mem1)
        store.add(mem2)
        results = store.search("Python", vault="v1", n_results=5)
        assert len(results) == 1
        assert results[0].vault == "v1"


class TestEngineSqliteVec:
    def test_engine_store_and_search(self, engine):
        """Full engine with sqlite-vec backend stores and searches."""
        engine.store("Rust is a systems language", vault="test", shelf="main")
        results = engine.search("systems language", vault="test", limit=5)
        assert len(results) >= 1

    def test_engine_status(self, engine):
        """status() works with sqlite-vec backend."""
        status = engine.status()
        assert "memories" in status

    def test_engine_list_memories(self, engine):
        """list_memories works with sqlite-vec backend."""
        engine.store("Test memory", vault="test", shelf="main")
        page = engine.list_memories(vault="test", limit=5)
        assert len(page["memories"]) >= 1

    def test_engine_delete(self, engine):
        """delete works with sqlite-vec backend."""
        mem = engine.store("Delete me", vault="test", shelf="main")
        engine.delete(mem.id, dry_run=False)
        results = engine.search("Delete me", vault="test", limit=5)
        assert len(results) == 0
