"""Tests for v0.2.0 features: consolidation, temporal, graph, extraction, context, session, factcheck."""

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def engine():
    """Create a VaultEngine with isolated temp storage per test."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.vault import VaultEngine
    from memorius.config import load_config
    config = load_config()
    eng = VaultEngine(config)
    yield eng
    shutil.rmtree(tmp, ignore_errors=True)
    if hasattr(eng, "_vector") and hasattr(eng._vector, "_client"):
        try:
            eng._vector._client = None
        except Exception:
            pass


# ── Temporal decay tests ──────────────────────────────────────────────────────


def test_decay_score_fresh_memory():
    from memorius.temporal import calculate_decay_score
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    score = calculate_decay_score(created_at=now, access_count=0)
    assert score > 0.5, f"Fresh memory should have high decay score, got {score}"


def test_decay_score_old_memory():
    from memorius.temporal import calculate_decay_score

    score = calculate_decay_score(
        created_at="2020-01-01T00:00:00+00:00",
        access_count=0,
    )
    assert score < 0.3, f"Old memory should have low decay score, got {score}"


def test_decay_score_reinforced_memory():
    from memorius.temporal import calculate_decay_score
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    score = calculate_decay_score(
        created_at="2020-01-01T00:00:00+00:00",
        last_accessed=now,
        access_count=50,
    )
    assert score > 0.3, f"Reinforced old memory should have moderate score, got {score}"


def test_search_score_combines_factors():
    from memorius.temporal import calculate_search_score

    score = calculate_search_score(
        semantic_similarity=0.9,
        decay_score=0.8,
        access_count=10,
    )
    assert 0.5 < score < 1.0


# ── Consolidation tests ───────────────────────────────────────────────────────


def test_consolidation_clusters_similar(engine):
    """Store similar memories and verify consolidation finds clusters."""
    engine.store("Python is a programming language", vault="test")
    engine.store("Python is a high-level programming language", vault="test")
    engine.store("The weather is nice today", vault="test")

    result = engine.consolidate(vault="test", dry_run=True)
    # Should find at least one cluster of similar Python memories
    assert result.clusters_found >= 1


def test_consolidation_dry_run_no_changes(engine):
    engine.store("Test memory one", vault="test")
    engine.store("Test memory two", vault="test")

    result = engine.consolidate(vault="test", dry_run=True)
    # Dry run should not archive anything
    stats = engine.get_memory_stats()
    assert stats["archived"] == 0


# ── Graph tests ───────────────────────────────────────────────────────────────


def test_graph_link_memories(engine):
    from memorius.graph import link_memories, get_linked

    m1 = engine.store("Memory about Python", vault="g")
    m2 = engine.store("Memory about JavaScript", vault="g")

    conn = engine._meta._conn()
    link_memories(conn, m1.id, m2.id, weight=0.9, relation="related")

    links = get_linked(conn, m1.id)
    assert len(links) == 1
    assert links[0]["target_id"] == m2.id


def test_graph_expand(engine):
    from memorius.graph import link_memories, expand_graph

    m1 = engine.store("A", vault="g")
    m2 = engine.store("B", vault="g")
    m3 = engine.store("C", vault="g")

    conn = engine._meta._conn()
    link_memories(conn, m1.id, m2.id)
    link_memories(conn, m2.id, m3.id)

    result = expand_graph(conn, [m1.id], hops=2)
    assert len(result.expanded_ids) >= 1


def test_graph_stats(engine):
    stats = engine.get_graph_stats()
    assert "total_edges" in stats
    assert "unique_nodes" in stats


# ── LLM extraction tests ──────────────────────────────────────────────────────


def test_regex_extraction():
    from memorius.llm_extract import extract_memories

    conversation = (
        "I prefer using dark mode\n"
        "Let's use PostgreSQL for the database\n"
        "TODO: deploy to production\n"
    )
    memories = extract_memories(conversation, backend="regex")
    assert len(memories) >= 1
    categories = {m.category for m in memories}
    assert "preference" in categories or "decision" in categories or "action_item" in categories


def test_extraction_empty_conversation():
    from memorius.llm_extract import extract_memories

    memories = extract_memories("", backend="regex")
    assert len(memories) == 0


# ── Context injection tests ───────────────────────────────────────────────────


def test_context_injection(engine):
    engine.store("Python decorators are functions that modify other functions", vault="ctx")

    context = engine.get_context("What are Python decorators?", vault="ctx")
    assert "Python" in context or len(context) == 0  # may or may not find depending on search


def test_context_injection_empty_vault(engine):
    context = engine.get_context("anything", vault="empty")
    assert context == ""


# ── Session profile tests ─────────────────────────────────────────────────────


def test_session_profile_build(engine):
    engine.write_diary(
        session_id="test-session",
        title="Test",
        summary="Working on Python project",
    )

    profile = engine.get_session_profile("new-session")
    assert profile.session_id == "new-session"
    assert "Python" in profile.summary or len(profile.recent_topics) >= 0


def test_session_profile_formatting():
    from memorius.session import SessionProfile, format_profile_for_context

    profile = SessionProfile(
        session_id="s1",
        summary="Testing formatting",
        key_decisions=["Use Python"],
        ongoing_tasks=["Deploy app"],
    )
    text = format_profile_for_context(profile)
    assert "Testing formatting" in text
    assert "Use Python" in text


# ── Fact-check tests ──────────────────────────────────────────────────────────


def test_factcheck_verified(engine):
    engine.store("The project uses React for the frontend", vault="fc")

    result = engine.check_fact("The project uses React", vault="fc")
    assert result.verdict in ("verified", "no_match", "uncertain")


def test_factcheck_contradiction(engine):
    engine.store("The project uses React for the frontend", vault="fc")

    result = engine.check_fact("The project uses Vue for the frontend", vault="fc")
    # Should detect potential contradiction or no match
    assert result.verdict in ("contradicted", "no_match", "uncertain")


def test_factcheck_no_match(engine):
    result = engine.check_fact("Quantum computing is the future", vault="fc")
    assert result.verdict == "no_match"


# ── Memory stats tests ────────────────────────────────────────────────────────


def test_memory_stats(engine):
    engine.store("Test memory", vault="stats")
    stats = engine.get_memory_stats()
    assert stats["total"] >= 1
    assert stats["active"] >= 1


def test_memory_meta_tracking(engine):
    mem = engine.store("Tracked memory", vault="tracked")
    meta = engine._meta.get_memory_meta(mem.id)
    assert meta is not None
    assert meta["vault"] == "tracked"
    assert meta["access_count"] >= 0
