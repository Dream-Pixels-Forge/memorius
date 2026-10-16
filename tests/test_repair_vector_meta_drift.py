"""Regression tests for `memorius repair` — vector/meta drift repair (#21).

After legacy writes or interrupted operations, the Chroma vector store can
drift from the authoritative ``memory_meta`` table:

* **Orphaned vectors** — a Chroma record exists but no ``memory_meta`` row
  does. Doctor's ``vector_count_match`` check then reports drift, and there
  was previously no way to remove these.
* **Missing vectors** — a ``memory_meta`` row exists but its embedding is
  absent from Chroma, so search can't find it. ``--reindex`` restores it by
  re-embedding ``content``.

``VaultEngine.repair()`` reconciles the two:
- always detects orphaned vectors; removes them unless ``dry_run``;
- when ``reindex`` is set, re-embeds metadata rows missing a vector;
- returns a structured report.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def engine():
    """VaultEngine against an isolated temp store (mirrors test_core)."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.config import load_config
    from memorius.vault import VaultEngine

    config = load_config()
    eng = VaultEngine(config)
    yield eng
    eng.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _vector_ids(engine, collection_names=None) -> list[str]:
    """Enumerate all vector IDs across Chroma collections."""
    client = engine._vector._lazy_client()
    ids = []
    cols = (collection_names or [c.name for c in client.list_collections()])
    for name in cols:
        try:
            col = client.get_collection(name)
        except Exception:
            continue
        ids.extend(col.get(include=[])["ids"] or [])
    return ids


def test_repair_no_drift_reports_clean(engine):
    """A healthy store reports in-sync with zero orphans/missing."""
    engine.store("fact one about cats", vault="main", shelf="default")
    engine.store("fact two about dogs", vault="main", shelf="default")

    report = engine.repair()

    assert report["orphans_removed"] == 0
    assert report["orphans_found"] == 0
    assert report["missing_reindexed"] == 0
    assert report["in_sync"] is True
    assert report["meta_count"] == 2
    assert report["vector_count"] == 2


def test_repair_removes_orphaned_vectors(engine):
    """Vectors without a matching memory_meta row are detected and removed."""
    engine.store("legitimate memory", vault="main", shelf="default")

    # Inject an orphaned vector directly into the (main, default) collection.
    col = engine._vector._collection("main", "default")
    orphan_vec = [0.01] * engine._embed.dimension
    col.upsert(ids=["orphan-uuid-1"], embeddings=[orphan_vec],
                metadatas=[{"vault": "main", "shelf": "default"}],
                documents=["phantom record with no metadata row"])

    assert any(i == "orphan-uuid-1" for i in _vector_ids(engine))

    report = engine.repair()

    assert report["orphans_found"] >= 1
    assert report["orphans_removed"] >= 1
    assert report["in_sync"] is True
    # The orphaned vector is gone from the vector store.
    assert not any(i == "orphan-uuid-1" for i in _vector_ids(engine))


def test_repair_dry_run_reports_but_does_not_remove(engine):
    """dry_run=True reports orphans but leaves the store untouched."""
    engine.store("legitimate memory", vault="main", shelf="default")
    col = engine._vector._collection("main", "default")
    col.upsert(ids=["orphan-uuid-2"],
                embeddings=[[0.01] * engine._embed.dimension],
                metadatas=[{"vault": "main", "shelf": "default"}],
                documents=["phantom"])

    report = engine.repair(dry_run=True)

    assert report["dry_run"] is True
    assert report["orphans_found"] >= 1
    assert report["orphans_removed"] == 0
    # Orphan still present because dry-run made no mutation.
    assert any(i == "orphan-uuid-2" for i in _vector_ids(engine))


def test_repair_reindex_restores_missing_vector(engine):
    """reindex=True re-embeds metadata rows whose vector is missing."""
    mem = engine.store("memory that lost its embedding", vault="main", shelf="default")
    content = "memory that lost its embedding"
    meta_id = mem.id

    # Remove the vector from Chroma but keep the metadata row.
    col = engine._vector._collection("main", "default")
    col.delete(ids=[meta_id])
    assert meta_id not in _vector_ids(engine)

    report = engine.repair(reindex=True)

    assert report["missing_reindexed"] >= 1
    # The metadata row's vector is restored.
    assert meta_id in _vector_ids(engine)
    # The re-embedded document is retrievable and preserves content.
    restored = engine._vector.get_by_ids([meta_id], "main", "default",
                                         include_vectors=False)
    assert restored and restored[0].content == content


def test_repair_reports_missing_without_reindex(engine):
    """Without reindex, missing vectors are counted but not restored."""
    mem = engine.store("another memory", vault="main", shelf="default")
    engine._vector._collection("main", "default").delete(ids=[mem.id])

    report = engine.repair()  # reindex=False

    assert report["missing_reindexed"] == 0
    assert report["missing_found"] >= 1
    assert mem.id not in _vector_ids(engine)


def test_repair_handles_empty_store(engine):
    """An empty store is trivially in sync."""
    report = engine.repair()
    assert report["in_sync"] is True
    assert report["meta_count"] == 0
    assert report["vector_count"] == 0


def test_mcp_repair_tool_dispatches(monkeypatch):
    """The MCP tool surfaces the engine's repair report."""
    from memorius.mcp_server import McpServer

    engine = MagicMock()
    engine.repair.return_value = {
        "orphans_found": 3, "orphans_removed": 3,
        "missing_found": 1, "missing_reindexed": 0,
        "in_sync": True, "dry_run": False,
        "meta_count": 10, "vector_count": 10,
    }
    server = McpServer.__new__(McpServer)
    server._engine = engine

    result = server.tool_memorius_repair({"dry_run": True, "reindex": True})

    engine.repair.assert_called_once_with(dry_run=True, reindex=True, vault=None)
    assert result["in_sync"] is True
    assert result["orphans_removed"] == 3


def test_doctor_mentions_repair_on_drift(engine):
    """When drift exists, doctor's vector_count_match detail points to repair."""
    from memorius.doctor import run_checks

    engine.store("some memory", vault="main", shelf="default")
    col = engine._vector._collection("main", "default")
    col.upsert(ids=["orphan-uuid-9"],
                embeddings=[[0.01] * engine._embed.dimension],
                metadatas=[{"vault": "main", "shelf": "default"}],
                documents=["phantom"])

    report = run_checks(engine=engine)
    vec_check = next(c for c in report["checks"] if c["name"] == "vector_count_match")
    assert vec_check["status"] == "warn"
    assert "memorius repair" in vec_check["detail"]


def test_cli_repair_subparser_is_registered():
    """The real CLI parser accepts `memorius repair --dry-run --reindex --vault`
    without requiring the engine to be constructed.

    We verify the subcommand and its flags are registered by reusing the
    module-level parser builder. If the parser isn't factored out, we fall
    back to confirming the dispatch table contains the command name.
    """
    from memorius.cli import main as cli_main

    # Confirm the dispatch table registers "repair".
    # We can't easily call main() without an engine, so instead we verify the
    # subparser is reachable by invoking it through the module's parser.
    # The cleanest way: run `memorius repair --help` and confirm it doesn't
    # error out with "invalid choice".
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "memorius.cli.main", "repair", "--help"],
        capture_output=True, text=True, cwd="/home/dimona/Dream-Pixels-Forge/Dev/cli/memorius",
    )
    # The repair subparser should be reachable (exit 0 from --help), and the
    # flags should be listed.
    assert result.returncode == 0, f"repair --help failed: {result.stderr}"
    assert "--dry-run" in result.stdout
    assert "--reindex" in result.stdout
    assert "--vault" in result.stdout
