"""Tests for StoreModule — semantic dedup and store operations."""

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def store():
    """Create a StoreModule with isolated temp stores."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.config import load_config
    from memorius.vault import VaultEngine

    config = load_config()
    eng = VaultEngine(config)
    yield eng._get_store_module()
    eng.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _get_metadata(meta_row):
    return json.loads(meta_row.get("metadata", "{}")) if meta_row else {}


def test_store_detects_semantic_duplicate(store):
    """Storing near-identical content should flag as duplicate."""
    mid1 = store.store("The quick brown fox jumps over the lazy dog", shelf="test", folder="test")
    mid2 = store.store("The quick brown fox leaps over the lazy dog", shelf="test", folder="test")
    meta = store._meta.get_memory_meta(mid2.id)
    assert meta is not None
    assert _get_metadata(meta).get("duplicate_of") == mid1.id


def test_store_no_duplicate_for_distinct_content(store):
    """Storing completely different content should not flag as duplicate."""
    store.store("The quick brown fox jumps over the lazy dog", shelf="test", folder="test")
    mid2 = store.store("Python is a popular programming language", shelf="test", folder="test")
    meta = store._meta.get_memory_meta(mid2.id)
    assert meta is not None
    assert _get_metadata(meta).get("duplicate_of") is None


def test_store_duplicate_flagged_in_returned_memory(store):
    """The returned Memory should have duplicate_of in its metadata."""
    mid1 = store.store("The quick brown fox jumps over the lazy dog", shelf="test", folder="test")
    mid2 = store.store("The quick brown fox leaps over the lazy dog", shelf="test", folder="test")
    assert mid2.metadata.get("duplicate_of") == mid1.id
