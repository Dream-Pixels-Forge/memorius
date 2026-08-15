"""Tests for temporal graph edge functionality (v0.8.0)."""
import sqlite3
from memorius.graph import init_graph_schema


def test_graph_schema_has_temporal_columns():
    """Graph schema should include tvalid and tinvalid columns."""
    conn = sqlite3.connect(":memory:")
    init_graph_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_graph)").fetchall()}
    assert "tvalid" in cols
    assert "tinvalid" in cols
    conn.close()
