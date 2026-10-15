"""Tests for the extended knowledge graph schema with typed edges (GOAL 3.2).

Verifies that the new typed edge relations — temporal, causal, episodic and
semantic — can be stored and retrieved, and that the pre-existing
``related`` / ``supersedes`` relations continue to function.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    """Create a VaultEngine with isolated temp storage per test."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.config import load_config
    from memorius.vault import VaultEngine

    eng = VaultEngine(load_config())
    yield eng
    eng.close()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def conn(engine):
    """A graph-ready connection to the engine's primary metadata store."""
    from memorius.graph import init_graph_schema

    c = engine._meta._conn()
    init_graph_schema(c)
    yield c
    c.commit()


# ── Typed-edge constants ─────────────────────────────────────────────────────


class TestTypedEdgeConstants:
    def test_new_edge_type_constants_exist(self):
        from memorius import graph

        assert graph.TEMPORAL_BEFORE == "temporal_before"
        assert graph.CAUSAL_LEADS_TO == "causal_leads_to"
        assert graph.EPISODIC_PART_OF == "episodic_part_of"
        assert graph.SEMANTIC_INSTANCE_OF == "semantic_instance_of"

    def test_legacy_edge_type_constants_unchanged(self):
        from memorius import graph

        assert graph.RELATED == "related"
        assert graph.SUPERSEDES == "supersedes"


# ── Store & retrieve typed edges ─────────────────────────────────────────────


class TestTypedEdgeRoundTrip:
    @pytest.mark.parametrize("relation", [
        "temporal_before",
        "causal_leads_to",
        "episodic_part_of",
        "semantic_instance_of",
    ])
    def test_each_new_edge_type_stored_and_retrieved(self, engine, conn, relation):
        from memorius.graph import get_linked, link_memories

        a = engine.store("event alpha", vault="main", shelf="g")
        b = engine.store("event beta", vault="main", shelf="g")

        link_memories(conn, a.id, b.id, weight=0.9, relation=relation)
        conn.commit()

        linked = get_linked(conn, a.id, relation=relation)
        assert b.id in {row["target_id"] for row in linked}

    def test_relation_filter_isolates_edge_types(self, engine, conn):
        """A temporal edge is NOT returned when querying for causal edges."""
        from memorius.graph import get_linked, link_memories

        a = engine.store("cause candidate", vault="main", shelf="g")
        b = engine.store("effect candidate", vault="main", shelf="g")

        link_memories(conn, a.id, b.id, weight=0.9, relation="temporal_before")
        conn.commit()

        causal = get_linked(conn, a.id, relation="causal_leads_to")
        assert causal == []

        temporal = get_linked(conn, a.id, relation="temporal_before")
        assert b.id in {row["target_id"] for row in temporal}

    def test_typed_edges_are_bidirectional(self, engine, conn):
        from memorius.graph import get_linked, link_memories

        a = engine.store("whole event", vault="main", shelf="g")
        b = engine.store("part of the event", vault="main", shelf="g")

        link_memories(conn, a.id, b.id, weight=0.7, relation="episodic_part_of")
        conn.commit()

        forward = get_linked(conn, a.id, relation="episodic_part_of")
        backward = get_linked(conn, b.id, relation="episodic_part_of")
        assert b.id in {r["target_id"] for r in forward}
        assert a.id in {r["target_id"] for r in backward}

    def test_typed_edge_weight_survives_round_trip(self, engine, conn):
        from memorius.graph import get_linked, link_memories

        a = engine.store("class def", vault="main", shelf="g")
        b = engine.store("instance of the class", vault="main", shelf="g")

        link_memories(conn, a.id, b.id, weight=0.65, relation="semantic_instance_of")
        conn.commit()

        edge = get_linked(conn, a.id, relation="semantic_instance_of")[0]
        assert edge["weight"] == pytest.approx(0.65)


# ── Legacy relations still work ──────────────────────────────────────────────


class TestLegacyRelations:
    def test_related_edges_continue_to_function(self, engine, conn):
        from memorius.graph import get_linked, link_memories

        a = engine.store("first related item", vault="main", shelf="g")
        b = engine.store("second related item", vault="main", shelf="g")

        link_memories(conn, a.id, b.id, weight=0.5, relation="related")
        conn.commit()

        linked = get_linked(conn, a.id, relation="related")
        assert b.id in {row["target_id"] for row in linked}

    def test_supersedes_edges_continue_to_function(self, engine, conn):
        from memorius.graph import get_linked, link_memories

        old = engine.store("outdated fact", vault="main", shelf="g")
        new = engine.store("corrected fact", vault="main", shelf="g")

        link_memories(conn, new.id, old.id, weight=1.0, relation="supersedes")
        conn.commit()

        linked = get_linked(conn, new.id, relation="supersedes")
        assert old.id in {row["target_id"] for row in linked}

    def test_auto_linking_uses_related_relation(self, engine):
        """The pre-existing auto-link-by-proximity feature keeps creating
        plain 'related' edges between similar memories."""
        # Use two memories with strong word overlap so the Jaccard
        # similarity exceeds the 0.3 threshold.
        engine.store("kubernetes orchestrates container workloads and pods",
                     vault="main", shelf="auto")
        b = engine.store("kubernetes orchestrates container workloads and pods in cluster",
                         vault="main", shelf="auto")

        linked = engine._meta.get_linked(b.id)
        relations = {row["relation"] for row in linked}
        assert "related" in relations


# ── Graph stats include typed edges ──────────────────────────────────────────


class TestGraphStatsWithTypedEdges:
    def test_stats_count_includes_typed_edges(self, engine, conn):
        from memorius.graph import link_memories

        a = engine.store("node one", vault="main", shelf="g")
        b = engine.store("node two", vault="main", shelf="g")

        before = engine.get_graph_stats().get("total_edges", 0)
        link_memories(conn, a.id, b.id, weight=0.9, relation="causal_leads_to")
        conn.commit()
        after = engine.get_graph_stats().get("total_edges", 0)

        # Bidirectional insert → +2 edges.
        assert after >= before + 2
