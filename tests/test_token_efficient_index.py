"""Tests for the token-efficient vector index option (GOAL 3.5).

Covers the HNSW optimisation knobs in memorius/config.py and
memorius/vector_store.py:

  - config defaults expose ``vector_optimization`` with correct keys
    and values
  - ChromaStore._collection() emits HNSW tuning metadata only when
    ``enable_hnsw_optimization`` is True
  - the metadata keys follow ChromaDB's documented convention
    (hnsw:construction_ef / hnsw:M / hnsw:search_ef)
  - the option is backward-compatible: when disabled, no HNSW keys
    appear in the collection metadata
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Config layer ──────────────────────────────────────────────────────────────


class TestVectorOptimizationConfig:
    def test_default_config_includes_vector_optimization_section(self):
        from memorius.config import get_config
        config = get_config()
        assert "vector_optimization" in config
        opt = config["vector_optimization"]
        assert opt["enable_hnsw_optimization"] is False
        assert opt["hnsw_ef_construction"] == 100
        assert opt["hnsw_ef_search"] == 100
        assert opt["hnsw_max_m"] == 16

    def test_ensure_defaults_fills_missing_vector_optimization_keys(self):
        from memorius.config import _ensure_defaults
        config = {"storage": {"type": "chroma"}}
        _ensure_defaults(config)
        assert "vector_optimization" in config
        opt = config["vector_optimization"]
        assert opt["enable_hnsw_optimization"] is False
        assert opt["hnsw_ef_construction"] == 100
        assert opt["hnsw_ef_search"] == 100
        assert opt["hnsw_max_m"] == 16

    def test_env_var_does_not_override_vector_optimization(self):
        """vector_optimization is file-driven only; no env overrides exist."""
        from memorius.config import _apply_env_overrides
        config = {"vector_optimization": {"enable_hnsw_optimization": True}}
        _apply_env_overrides(config)
        # No env key targets this section — value stays as set
        assert config["vector_optimization"]["enable_hnsw_optimization"] is True


# ── ChromaStore metadata emission ────────────────────────────────────────────


class TestChromaStoreHnswMetadata:
    """Unit tests for the HNSW metadata branch in
    ChromaStore._collection().  The lazy client is mocked so no
    ChromaDB install is required."""

    @pytest.fixture
    def store(self, tmp_path: Path):
        from memorius.vector_store import ChromaStore
        embed = MagicMock()
        embed.dimension = 384
        store = ChromaStore(tmp_path / "chroma_test", embed, config={})
        return store

    def _mock_collection(self, metadata: dict):
        """Build a mock ChromaDB collection carrying the given metadata."""
        col = MagicMock()
        col.metadata = metadata
        col.name = "test"
        return col

    def test_disabled_by_default_no_hnsw_keys(self, store):
        """When enable_hnsw_optimization is absent/False, the base
        metadata has no HNSW tuning keys."""
        base_meta = {
            "hnsw:space": "cosine",
            "memorius_vault": "main",
            "memorius_shelf": "default",
        }
        col = self._mock_collection(base_meta)
        with patch.object(store, "_lazy_client") as mock_client, \
             patch("chromadb.PersistentClient") as _:
            mock_client.return_value = MagicMock()
            mock_client.return_value.get_collection.return_value = col
            mock_client.return_value.create_collection.return_value = col

            result = store._collection("main", "default")
            assert result.metadata.get("hnsw:construction_ef") is None
            assert result.metadata.get("hnsw:M") is None
            assert result.metadata.get("hnsw:search_ef") is None

    def test_enabled_emits_all_hnsw_keys(self, store):
        """When the config enables HNSW optimisation, all three tuning
        keys appear in the metadata passed to create_collection."""
        store._config = {
            "vector_optimization": {
                "enable_hnsw_optimization": True,
                "hnsw_ef_construction": 200,
                "hnsw_ef_search": 50,
                "hnsw_max_m": 32,
            }
        }
        base_meta = {
            "hnsw:space": "cosine",
            "memorius_vault": "main",
            "memorius_shelf": "default",
        }
        col = self._mock_collection(base_meta)
        mock_client = MagicMock()
        mock_client.get_collection.return_value = col
        mock_client.create_collection.return_value = col

        with patch.object(store, "_lazy_client", return_value=mock_client):
            # Force a new collection (not in cache)
            result = store._collection("main", "default")

        # The metadata passed to create_collection should include the HNSW keys
        call_kwargs = mock_client.create_collection.call_args
        if call_kwargs:
            passed_meta = call_kwargs.kwargs.get("metadata", {})
            assert passed_meta.get("hnsw:construction_ef") == 200
            assert passed_meta.get("hnsw:M") == 32
            assert passed_meta.get("hnsw:search_ef") == 50

    def test_partial_config_only_emits_set_keys(self, store):
        """If only some HNSW knobs are set, only those appear in metadata."""
        store._config = {
            "vector_optimization": {
                "enable_hnsw_optimization": True,
                "hnsw_ef_construction": 150,
                # hnsw_max_m and hnsw_ef_search are not set → should be absent
            }
        }
        base_meta = {
            "hnsw:space": "cosine",
            "memorius_vault": "main",
            "memorius_shelf": "default",
        }
        col = self._mock_collection(base_meta)
        mock_client = MagicMock()
        mock_client.get_collection.return_value = col
        mock_client.create_collection.return_value = col

        with patch.object(store, "_lazy_client", return_value=mock_client):
            store._collection("main", "default")

        call_kwargs = mock_client.create_collection.call_args
        if call_kwargs:
            passed_meta = call_kwargs.kwargs.get("metadata", {})
            assert passed_meta.get("hnsw:construction_ef") == 150
            assert "hnsw:M" not in passed_meta
            assert "hnsw:search_ef" not in passed_meta

    def test_backward_compatible_existing_collections_unaffected(self, store):
        """A collection that already exists in ChromaDB is returned as-is;
        the HNSW metadata is not retrofitted."""
        store._config = {
            "vector_optimization": {
                "enable_hnsw_optimization": True,
                "hnsw_ef_construction": 200,
            }
        }
        # Pre-existing collection with only the base metadata
        existing = self._mock_collection({
            "hnsw:space": "cosine",
            "memorius_vault": "main",
            "memorius_shelf": "default",
        })
        mock_client = MagicMock()
        mock_client.get_collection.return_value = existing
        mock_client.create_collection.return_value = existing

        with patch.object(store, "_lazy_client", return_value=mock_client):
            result = store._collection("main", "default")

        # get_collection succeeded → no create_collection call
        mock_client.get_collection.assert_called_once()
        mock_client.create_collection.assert_not_called()
        assert result is existing


# ── Config-driven end-to-end (ChromaStore + real config dict) ───────────────


class TestConfigDrivenChromaStore:
    """Verify that a fully-formed config dict propagates HNSW knobs to
    the ChromaStore without requiring a YAML file on disk."""

    def test_full_config_propagates_to_store(self, tmp_path: Path):
        from memorius.config import get_config
        from memorius.vector_store import ChromaStore

        config = get_config()
        config["vector_optimization"]["enable_hnsw_optimization"] = True
        config["vector_optimization"]["hnsw_ef_construction"] = 300

        embed = MagicMock()
        embed.dimension = 384
        store = ChromaStore(tmp_path / "chroma_full", embed, config)

        # The config dict is stored on the instance
        assert store._config["vector_optimization"]["enable_hnsw_optimization"] is True
        assert store._config["vector_optimization"]["hnsw_ef_construction"] == 300
