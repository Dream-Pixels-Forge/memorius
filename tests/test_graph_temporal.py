"""Tests for temporal graph edge functionality (v0.8.0)."""
import sqlite3
from memorius.graph import init_graph_schema, link_memories, invalidate_edge


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
