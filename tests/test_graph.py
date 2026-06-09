"""Tests for memorius/graph.py — knowledge graph operations."""

import sqlite3
import tempfile
from pathlib import Path

from memorius.graph import (
    init_graph_schema,
    link_memories,
    get_linked,
    expand_graph,
    auto_link_by_proximity,
    get_graph_stats,
)


def _make_conn():
    """Create an in-memory SQLite connection with graph schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_graph_schema(conn)
    return conn


def test_init_graph_schema():
    """Schema creation should be idempotent."""
    conn = _make_conn()
    # Should not raise on second call
    init_graph_schema(conn)


def test_link_memories():
    """Linking two memories should create bidirectional edges."""
    conn = _make_conn()
    link_memories(conn, "mem-1", "mem-2", weight=0.8, relation="related")
    links = get_linked(conn, "mem-1")
    assert len(links) == 1
    assert links[0]["target_id"] == "mem-2"
    assert links[0]["weight"] == 0.8
    # Bidirectional
    links_back = get_linked(conn, "mem-2")
    assert len(links_back) == 1
    assert links_back[0]["target_id"] == "mem-1"


def test_get_linked_with_relation():
    """Filtering by relation should work."""
    conn = _make_conn()
    link_memories(conn, "mem-1", "mem-2", relation="related")
    link_memories(conn, "mem-1", "mem-3", relation="contradicts")
    related = get_linked(conn, "mem-1", relation="related")
    assert len(related) == 1
    assert related[0]["target_id"] == "mem-2"


def test_get_linked_min_weight():
    """Filtering by minimum weight should work."""
    conn = _make_conn()
    link_memories(conn, "mem-1", "mem-2", weight=0.9)
    link_memories(conn, "mem-1", "mem-3", weight=0.3)
    strong = get_linked(conn, "mem-1", min_weight=0.5)
    assert len(strong) == 1
    assert strong[0]["target_id"] == "mem-2"


def test_expand_graph():
    """Graph expansion should traverse links."""
    conn = _make_conn()
    link_memories(conn, "mem-1", "mem-2", weight=0.9)
    link_memories(conn, "mem-2", "mem-3", weight=0.8)
    result = expand_graph(conn, seed_ids=["mem-1"], hops=2, min_weight=0.5)
    assert "mem-2" in result.expanded_ids
    assert "mem-3" in result.expanded_ids


def test_auto_link_by_proximity():
    """Auto-linking should create edges for similar memories."""
    conn = _make_conn()
    memories = [
        {"id": "mem-1", "content": "Python is a programming language"},
        {"id": "mem-2", "content": "Python is used for machine learning"},
        {"id": "mem-3", "content": "The weather is nice today"},
    ]
    auto_link_by_proximity(conn, "mem-1", memories, threshold=0.1)
    links = get_linked(conn, "mem-1")
    # mem-1 and mem-2 share words, should be linked
    assert len(links) >= 1


def test_get_graph_stats():
    """Stats should reflect graph state."""
    conn = _make_conn()
    link_memories(conn, "mem-1", "mem-2", relation="related")
    link_memories(conn, "mem-1", "mem-3", relation="contradicts")
    stats = get_graph_stats(conn)
    assert stats["total_edges"] >= 4  # bidirectional = 2 edges per link
    assert stats["unique_nodes"] >= 2
    assert "related" in stats["relations"]
    assert "contradicts" in stats["relations"]
