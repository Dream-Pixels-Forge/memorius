"""Feature tests for memorius prune (Phase 2.2).

Prune exposes the existing stale-archive machinery via engine, CLI, MCP
and REST.  These tests verify engine.prune() logic, including dry-run,
soft-archive, and hard-delete paths.
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def engine():
    """VaultEngine against an isolated temp store."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.config import load_config
    from memorius.vault import VaultEngine

    config = load_config()
    eng = VaultEngine(config)
    yield eng
    shutil.rmtree(tmp, ignore_errors=True)
    if hasattr(eng, "_vector") and hasattr(eng._vector, "_client"):
        try:
            eng._vector._client = None
        except Exception:
            pass


def test_prune_dry_run_does_not_archive(engine):
    """prune(dry_run=True) returns stale candidates but does not archive them."""
    m = engine.store("prune dry run test memory content", vault="p")
    # Patch decay score to 0.0 so the memory is below any threshold.
    with patch("memorius.temporal.calculate_decay_score", return_value=0.0):
        result = engine.prune(threshold=0.5, dry_run=True)
    assert result["dry_run"] is True
    assert result["archived_count"] == 0
    assert result["count"] >= 1
    stale_ids = [s["id"] for s in result["stale"]]
    assert m.id in stale_ids
    # Memory should still be active.
    meta = engine.meta.get_memory_meta(m.id)
    assert meta["archived"] == 0


def test_prune_soft_archive(engine):
    """prune(archive=True) soft-archives stale memories (archived=1)."""
    m = engine.store("prune soft archive test memory content", vault="p")
    with patch("memorius.temporal.calculate_decay_score", return_value=0.0):
        result = engine.prune(threshold=0.5, dry_run=False, archive=True)
    assert result["archived_count"] >= 1
    meta = engine.meta.get_memory_meta(m.id)
    assert meta["archived"] == 1, f"expected archived=1, got {meta['archived']}"


def test_prune_hard_delete(engine):
    """prune(archive=False) hard-deletes stale memories."""
    m = engine.store("prune hard delete test memory content", vault="p")
    with patch("memorius.temporal.calculate_decay_score", return_value=0.0):
        result = engine.prune(threshold=0.5, dry_run=False, archive=False)
    assert result["archived_count"] >= 1
    # Memory should be fully gone.
    assert engine.get_memory(m.id) is None
    assert engine.meta.get_memory_meta(m.id) is None


def test_prune_no_stale_memories(engine):
    """When all memories are above threshold, prune returns count=0."""
    m = engine.store("healthy memory content here", vault="p")
    with patch("memorius.temporal.calculate_decay_score", return_value=1.0):
        result = engine.prune(threshold=0.5, dry_run=True)
    assert result["count"] == 0
    assert result["archived_count"] == 0


def test_prune_active_count_drops(engine):
    """After soft-archiving, get_memory_stats()['active'] drops by 1."""
    engine.store("active count drop test memory content", vault="p")
    stats_before = engine.get_memory_stats()
    active_before = stats_before["active"]
    with patch("memorius.temporal.calculate_decay_score", return_value=0.0):
        engine.prune(threshold=0.5, dry_run=False, archive=True)
    stats_after = engine.get_memory_stats()
    assert stats_after["active"] == active_before - 1, (
        f"active count should drop by 1; {active_before} -> {stats_after['active']}"
    )


def test_prune_skips_archived_memories(engine):
    """prune only considers non-archived memories."""
    m = engine.store("already archived memory content", vault="p")
    # Manually archive it first.
    engine.meta.archive_memory(m.id)
    # Now prune should NOT find it (it's already archived).
    with patch("memorius.temporal.calculate_decay_score", return_value=0.0):
        result = engine.prune(threshold=0.5, dry_run=True)
    stale_ids = [s["id"] for s in result["stale"]]
    assert m.id not in stale_ids, "already-archived memory should not appear in stale candidates"


def test_prune_stale_metadata_structure(engine):
    """Each stale entry has the expected keys."""
    engine.store("stale metadata structure test content", vault="p")
    with patch("memorius.temporal.calculate_decay_score", return_value=0.0):
        result = engine.prune(threshold=0.5, dry_run=True)
    for item in result["stale"]:
        assert "id" in item
        assert "content" in item
        assert "vault" in item
        assert "shelf" in item
        assert "decay_score" in item
