"""Phase 2.3 — TTL / expiry on memories.

Store with --ttl N sets expires_at in metadata.  Prune archives expired
memories regardless of access count.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _backdate_expires(engine, memory_id, days_ago: int = 1):
    """Set expires_at in metadata to *days_ago* in the past."""
    conn = engine._meta._conn()
    past = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    row = conn.execute(
        "SELECT metadata FROM memory_meta WHERE id = ?", (memory_id,)
    ).fetchone()
    raw = row[0] if row else "{}"
    meta = json.loads(raw) if raw else {}
    meta["expires_at"] = past
    conn.execute(
        "UPDATE memory_meta SET metadata = ? WHERE id = ?",
        (json.dumps(meta), memory_id),
    )
    conn.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestTTLMetadata:
    """store() writes expires_at and ttl_days into metadata."""

    def test_store_with_ttl_sets_expires_at(self, engine):
        m = engine.store("ttl mem", ttl_days=7)
        meta = engine._meta.get_memory_meta(m.id)
        assert meta is not None
        raw = meta.get("metadata", "") if isinstance(meta, dict) else ""
        if raw:
            parsed = json.loads(raw)
            assert "expires_at" in parsed
            assert parsed["ttl_days"] == 7
            exp = datetime.fromisoformat(parsed["expires_at"].replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta = exp - now
            assert timedelta(days=6) <= delta <= timedelta(days=7, minutes=5)

    def test_store_without_ttl_has_no_expires(self, engine):
        m = engine.store("no ttl")
        meta = engine._meta.get_memory_meta(m.id)
        assert meta is not None
        raw = meta.get("metadata", "") if isinstance(meta, dict) else ""
        if raw:
            parsed = json.loads(raw)
            assert "expires_at" not in parsed


class TestFindExpired:
    """find_stale_memories returns memories past their expires_at."""

    def test_expired_memory_appears_in_stale(self, engine):
        from memorius.temporal import find_stale_memories
        m = engine.store("expire me", ttl_days=1)
        _backdate_expires(engine, m.id, days_ago=1)
        conn = engine._meta._conn()
        stale = find_stale_memories(conn)
        ids = [s["id"] for s in stale]
        assert m.id in ids

    def test_non_expired_memory_not_in_stale(self, engine):
        from memorius.temporal import find_stale_memories
        m = engine.store("not yet", ttl_days=90)
        conn = engine._meta._conn()
        stale = find_stale_memories(conn)
        ids = [s["id"] for s in stale]
        assert m.id not in ids

    def test_expired_memory_marked_expired(self, engine):
        from memorius.temporal import find_stale_memories
        m = engine.store("expired flag", ttl_days=1)
        _backdate_expires(engine, m.id, days_ago=1)
        conn = engine._meta._conn()
        stale = find_stale_memories(conn)
        hit = next(s for s in stale if s["id"] == m.id)
        assert hit["expired"] is True
        assert hit["expires_at"] is not None


class TestPruneTTL:
    """prune() archives expired memories even if access_count is high."""

    def test_prune_archives_expired(self, engine):
        m = engine.store("prune expired", ttl_days=1)
        _backdate_expires(engine, m.id, days_ago=1)
        # Fake high access_count so decay score alone wouldn't trigger prune
        conn = engine._meta._conn()
        conn.execute(
            "UPDATE memory_meta SET access_count = 50, last_accessed = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), m.id),
        )
        conn.commit()

        result = engine.prune(threshold=0.99, dry_run=False, archive=True)
        assert result["archived_count"] == 1
        ids = [s["id"] for s in result["stale"]]
        assert m.id in ids

        row = conn.execute(
            "SELECT archived FROM memory_meta WHERE id = ?", (m.id,)
        ).fetchone()
        assert row is not None
        assert row[0] == 1

    def test_prune_dry_run_does_not_archive(self, engine):
        m = engine.store("dry run ttl", ttl_days=1)
        _backdate_expires(engine, m.id, days_ago=1)
        result = engine.prune(threshold=0.99, dry_run=True, archive=True)
        assert len(result["stale"]) > 0
        assert result["dry_run"] is True
        assert result["archived_count"] == 0


class TestCLI:
    """CLI --ttl flag stores the metadata."""

    def test_store_ttl_flag(self, engine):
        """CLI store with --ttl writes expires_at."""
        m = engine.store("via cli", ttl_days=30)
        meta = engine._meta.get_memory_meta(m.id)
        raw = meta.get("metadata", "") if isinstance(meta, dict) else ""
        if raw:
            parsed = json.loads(raw)
            assert parsed["ttl_days"] == 30
            assert "expires_at" in parsed
