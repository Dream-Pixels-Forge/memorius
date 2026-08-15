"""Tests for temporal graph edge functionality (v0.8.0)."""
import datetime
import sqlite3
from memorius.graph import (
    get_active_edge_count,
    get_edges_at_time,
    init_graph_schema,
    invalidate_edge,
    link_memories,
    expand_graph,
    get_linked,
)


def test_graph_schema_has_temporal_columns():
    """Graph schema should include tvalid and tinvalid columns."""
    conn = sqlite3.connect(":memory:")
    init_graph_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_graph)").fetchall()}
    assert "tvalid" in cols
    assert "tinvalid" in cols
    conn.close()


def test_link_memories_sets_tvalid():
    """link_memories should set tvalid on new edges."""
    conn = sqlite3.connect(":memory:")
    init_graph_schema(conn)
    link_memories(conn, "m1", "m2", relation="test")
    row = conn.execute(
        "SELECT tvalid, tinvalid FROM memory_graph WHERE source_id='m1' AND target_id='m2'"
    ).fetchone()
    assert row is not None
    assert row[0] is not None  # tvalid
    assert row[1] is None  # tinvalid
    conn.close()


def test_invalidate_edge_sets_tinvalid():
    """invalidate_edge should set tinvalid on the edge."""
    conn = sqlite3.connect(":memory:")
    init_graph_schema(conn)
    link_memories(conn, "m1", "m2", relation="supports")
    invalidate_edge(conn, "m1", "m2", relation="supports")
    row = conn.execute(
        "SELECT tvalid, tinvalid FROM memory_graph WHERE source_id='m1' AND target_id='m2'"
    ).fetchone()
    assert row is not None
    assert row[1] is not None  # tinvalid should be set
    conn.close()


def test_invalidate_edge_without_relation():
    """invalidate_edge should handle missing relation gracefully."""
    conn = sqlite3.connect(":memory:")
    init_graph_schema(conn)
    link_memories(conn, "m1", "m2", relation="supports")
    invalidate_edge(conn, "m1", "m2")
    row = conn.execute(
        "SELECT tinvalid FROM memory_graph WHERE source_id='m1' AND target_id='m2'"
    ).fetchone()
    assert row is not None
    assert row[0] is not None
    conn.close()


def test_get_linked_excludes_invalidated():
    """get_linked should exclude invalidated edges by default."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_graph_schema(conn)
    link_memories(conn, "m1", "m2", relation="supports")
    link_memories(conn, "m1", "m3", relation="related")
    invalidate_edge(conn, "m1", "m2", relation="supports")
    linked = get_linked(conn, "m1")
    target_ids = [l["target_id"] for l in linked]
    assert "m2" not in target_ids
    assert "m3" in target_ids
    conn.close()


def test_get_linked_includes_invalidated_when_requested():
    """get_linked(include_invalidated=True) should include invalidated edges."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_graph_schema(conn)
    link_memories(conn, "m1", "m2", relation="supports")
    invalidate_edge(conn, "m1", "m2", relation="supports")
    linked = get_linked(conn, "m1", include_invalidated=True)
    target_ids = [l["target_id"] for l in linked]
    assert "m2" in target_ids
    conn.close()


def test_expand_graph_excludes_invalidated():
    """expand_graph should exclude invalidated edges by default."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_graph_schema(conn)
    link_memories(conn, "m1", "m2", relation="supports")
    link_memories(conn, "m2", "m3", relation="related")
    invalidate_edge(conn, "m1", "m2", relation="supports")
    result = expand_graph(conn, ["m1"], hops=2)
    expanded_ids = result.expanded_ids
    assert "m2" not in expanded_ids
    assert "m3" not in expanded_ids
    conn.close()


def test_link_memories_invalidates_conflicting():
    """link_memories should invalidate old edge when relation changes."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_graph_schema(conn)
    link_memories(conn, "m1", "m2", relation="supports")
    link_memories(conn, "m1", "m2", relation="contradicts")
    rows = conn.execute(
        "SELECT relation, tinvalid FROM memory_graph WHERE source_id='m1' AND target_id='m2'"
    ).fetchall()
    old = [r for r in rows if r["relation"] == "supports"]
    new = [r for r in rows if r["relation"] == "contradicts"]
    assert len(old) == 1
    assert len(new) == 1
    assert old[0]["tinvalid"] is not None
    assert new[0]["tinvalid"] is None
    conn.close()


def test_get_edges_at_time():
    """get_edges_at_time should return edges valid at a specific timestamp."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_graph_schema(conn)
    link_memories(conn, "m1", "m2", relation="supports")
    link_memories(conn, "m1", "m3", relation="related")
    invalidate_edge(conn, "m1", "m2", relation="supports")
    edges = get_edges_at_time(conn, "m1", at_time=datetime.datetime.now().isoformat())
    target_ids = [e["target_id"] for e in edges]
    assert "m2" not in target_ids
    assert "m3" in target_ids
    conn.close()


def test_get_active_edge_count():
    """get_active_edge_count should return count of non-invalidated edges."""
    conn = sqlite3.connect(":memory:")
    init_graph_schema(conn)
    link_memories(conn, "m1", "m2", relation="supports")
    link_memories(conn, "m1", "m3", relation="related")
    assert get_active_edge_count(conn, "m1") == 2
    invalidate_edge(conn, "m1", "m2", relation="supports")
    assert get_active_edge_count(conn, "m1") == 1
    conn.close()
