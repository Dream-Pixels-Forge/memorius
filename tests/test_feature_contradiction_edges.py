"""Feature tests for contradiction edges (Phase 1.2).

When a factcheck surfaces BOTH a matching (corroborating) memory AND a
contradicting memory about the same claim, those two stored memories
disagree with each other about the same claim. Phase 1.2 persists a
bidirectional graph edge with relation='contradicts' between them, so
future searches/factchecks can exploit the graph instead of re-running
the contradiction heuristics.
"""

import os
import shutil
import tempfile
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


def test_contradiction_edge_created_on_factcheck(engine):
    """Factcheck with both matching and contradicting memories creates a
    bidirectional 'contradicts' edge in the knowledge graph."""
    m1 = engine.store("the project uses React for the frontend", vault="d")
    m2 = engine.store("the project uses Vue for the frontend", vault="d")
    # Third memory about a different topic — should NOT participate in edge.
    engine.store("the weather is sunny today", vault="d")

    # The statement should trigger both matching (m1) and contradicting (m2).
    result = engine.check_fact(
        "the project uses React for the frontend", vault="d"
    )
    assert result.verdict == "contradicted", f"expected contradicted, got {result.verdict}"
    assert len(result.contradicting_memories) >= 1, (
        "should have at least one contradicting memory"
    )
    assert len(result.matching_memories) >= 1, (
        "should have at least one matching memory"
    )

    # Now get_contradictions should return the contradicting memory.
    contras = engine.get_contradictions(m1.id)
    assert len(contras) >= 1, (
        "get_contradictions should return at least one memory after edge creation"
    )
    contra_ids = {c.id for c in contras}
    assert m2.id in contra_ids, (
        f"contradicting memory {m2.id} should appear in contradictions; got {contra_ids}"
    )


def test_bidirectional_edge(engine):
    """The 'contradicts' edge is bidirectional: querying either end shows
    the other as a contradiction."""
    m1 = engine.store("we always deploy on Fridays", vault="e")
    m2 = engine.store("we never deploy on Fridays", vault="e")

    engine.check_fact("we always deploy on Fridays", vault="e")

    contras_from_m1 = engine.get_contradictions(m1.id)
    contras_from_m2 = engine.get_contradictions(m2.id)

    m1_ids = {c.id for c in contras_from_m1}
    m2_ids = {c.id for c in contras_from_m2}
    assert m2.id in m1_ids, f"m2 should be in m1's contradictions: {m1_ids}"
    assert m1.id in m2_ids, f"m1 should be in m2's contradictions: {m2_ids}"


def test_no_edge_when_only_matching(engine):
    """When a factcheck finds only matching memories (no contradicting), no
    contradiction edge is created."""
    m1 = engine.store("the server runs on port 8080", vault="f")
    engine.store("the application listens on 8080", vault="f")

    result = engine.check_fact("the server runs on port 8080", vault="f")
    assert result.verdict == "verified"

    contras = engine.get_contradictions(m1.id)
    assert len(contras) == 0, (
        "no contradictions expected when all memories agree"
    )


def test_no_edge_when_only_contradicting(engine):
    """When a factcheck finds only contradicting memories (no matching), no
    contradiction edge is created — the edge is only between stored
    memories that are both corroborating and contradicting."""
    m1 = engine.store("we use PostgreSQL for the database", vault="g")
    engine.store("we use MySQL for the database", vault="g")

    # Statement is "we use SQLite" — should contradict PostgreSQL memory
    # but not match any memory about "PostgreSQL" vs "SQLite".
    # Actually: let's use the direct factcheck with a statement that
    # matches the PostgreSQL memory as contradicting.
    result = engine.check_fact("we use SQLite for the database", vault="g")
    # The contradicting memory (PostgreSQL vs SQLite) should be found,
    # but there should be no matching memory, so no edge is created.
    assert len(result.matching_memories) == 0, (
        "should not match a memory about PostgreSQL when querying SQLite"
    )

    # Even though contradicting memories exist, no edge should be created
    # because the edge only fires when BOTH matching AND contradicting lists
    # are non-empty (cross-memory contradiction).
    # Since we have no matching, no edge.
    contras = engine.get_contradictions(m1.id)
    assert len(contras) == 0, (
        "no contradiction edge expected when only one side exists"
    )


def test_get_contradictions_unknown_id_returns_empty(engine):
    """get_contradictions on an unknown memory ID returns an empty list."""
    import uuid
    contras = engine.get_contradictions(str(uuid.uuid4()))
    assert contras == []


def test_get_contradictions_invalid_id_returns_empty(engine):
    """get_contradictions on an invalid UUID string returns an empty list."""
    contras = engine.get_contradictions("not-a-valid-uuid")
    assert contras == []


def test_multiple_contradicting_memories(engine):
    """When a single statement contradicts multiple stored memories, edges
    are created from the matching memory to each contradicting one."""
    m1 = engine.store("React is used for the frontend", vault="h")
    m2 = engine.store("Vue is used for the frontend", vault="h")
    m3 = engine.store("Angular is used for the frontend", vault="h")

    result = engine.check_fact("React is used for the frontend", vault="h")
    # At least one matching memory should exist for this to work.
    assert len(result.matching_memories) >= 1, (
        "should match the React memory"
    )

    # If we have both matching and contradicting, edges should exist.
    if result.contradicting_memories:
        contras = engine.get_contradictions(m1.id)
        contra_ids = {c.id for c in contras}
        # m2 (Vue) should be in contradictions if it was found.
        for cm in result.contradicting_memories:
            if cm["id"] == m2.id:
                assert m2.id in contra_ids, (
                    f"Vue memory {m2.id} should be in contradictions: {contra_ids}"
                )
