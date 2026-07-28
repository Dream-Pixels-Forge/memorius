"""Phase 3.2 — memorius doctor health check.

Each check has a passing and failing case.  Checks are read-only.
"""
from __future__ import annotations

import json
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


class TestDoctorHealthy:
    """run_checks returns healthy=True on a clean vault."""

    def test_healthy_vault(self, engine):
        from memorius.doctor import run_checks
        result = run_checks(engine=engine)
        # onnx_model may be "warn" if not downloaded in test env — that's ok
        failing = [c for c in result["checks"] if c["status"] == "fail"]
        assert len(failing) == 0, f"Failing checks: {failing}"
        names = {c["name"]: c["status"] for c in result["checks"]}
        assert names["config"] == "ok"
        assert names["storage_dir"] == "ok"

    def test_has_all_expected_checks(self, engine):
        from memorius.doctor import run_checks
        result = run_checks(engine=engine)
        names = {c["name"] for c in result["checks"]}
        assert "config" in names
        assert "storage_dir" in names
        assert "onnx_model" in names
        assert "vector_count_match" in names
        assert "collection_names" in names
        assert "graph_health" in names


class TestDoctorDrift:
    """Check 4: memory_meta count != vector count → warn."""

    def test_drift_detected(self, engine):
        from memorius.doctor import run_checks

        # Store one memory to create a row in memory_meta + vector
        engine.store("drift test")

        # Manually insert a fake memory_meta row without a vector
        conn = engine._meta._conn()
        conn.execute(
            "INSERT INTO memory_meta (id, vault, shelf, folder, note, content, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("fake-id-1234", "main", "default", "default", "default",
             "phantom", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()

        result = run_checks(engine=engine)
        drift = next(c for c in result["checks"] if c["name"] == "vector_count_match")
        assert drift["status"] == "warn"
        assert "Drift" in drift["detail"]


class TestDoctorGraph:
    """Check 6: graph health — warn if many memories but no edges."""

    def test_graph_warn_when_many_memories_no_edges(self, engine):
        from memorius.doctor import run_checks

        # Create >10 memories
        for i in range(12):
            engine.store(f"unlinked memory {i}")

        # Delete all auto-created graph edges to simulate "no graph building"
        conn = engine._meta._conn()
        try:
            conn.execute("DELETE FROM memory_graph")
            conn.commit()
        except Exception:
            pass

        result = run_checks(engine=engine)
        graph = next(c for c in result["checks"] if c["name"] == "graph_health")
        assert graph["status"] == "warn"

    def test_graph_ok_when_few_memories(self, engine):
        from memorius.doctor import run_checks

        for i in range(5):
            engine.store(f"few memory {i}")

        result = run_checks(engine=engine)
        graph = next(c for c in result["checks"] if c["name"] == "graph_health")
        assert graph["status"] == "ok"


class TestDoctorWithoutEngine:
    """run_checks without an engine still runs config/storage/model checks."""

    def test_no_engine_partial(self):
        from memorius.doctor import run_checks
        result = run_checks(engine=None)
        skipped = [c for c in result["checks"] if c["status"] == "skip"]
        assert len(skipped) >= 3  # vector_count, collection_names, graph_health


class TestDoctorSummary:
    """Summary output is human-readable."""

    def test_summary_contains_check_names(self, engine):
        from memorius.doctor import run_checks
        result = run_checks(engine=engine)
        assert "config" in result["summary"]
        assert "storage_dir" in result["summary"]
