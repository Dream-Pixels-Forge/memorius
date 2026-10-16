"""Regression tests for MCP `memorius_stats` graph-block key mismatch (#20).

`tool_memorius_stats` read `graph_stats.get("node_count")` /
`graph_stats.get("edge_count")` but `get_graph_stats()` returns
`unique_nodes` / `total_edges` — the graph block always reported 0/0.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unittest.mock import MagicMock, patch


def _engine_with_graph() -> MagicMock:
    """A MagicMock engine that returns a populated graph-stats dict."""
    engine = MagicMock()
    engine.status.return_value = {
        "memories": {"total": 10, "vaults": {"main": 10}},
        "vaults": {"main": 10},
        "embedding_provider": "test",
        "embedding_dimension": 384,
    }
    engine.get_learning_stats.return_value = {
        "total": 0,
        "by_category": {},
        "total_applied": 0,
    }
    engine.get_graph_stats.return_value = {
        "total_edges": 1025,
        "unique_nodes": 290,
        "relations": {"related": 1024, "supersedes": 1},
    }
    return engine


def _run_stats_tool(args: dict = {}) -> dict:
    engine = _engine_with_graph()

    from memorius.mcp_server import McpServer

    server = McpServer.__new__(McpServer)
    server._engine = engine
    result = server.tool_memorius_stats(args)
    return result


def test_stats_graph_block_reports_real_numbers(tmp_path: Path):
    """memorius_stats must surface the real graph node/edge counts, not 0/0."""
    result = _run_stats_tool({})
    graph = result["graph"]
    assert graph["nodes"] == 290, (
        f"graph.nodes should be 290 (from unique_nodes), got {graph['nodes']}"
    )
    assert graph["edges"] == 1025, (
        f"graph.edges should be 1025 (from total_edges), got {graph['edges']}"
    )


def test_stats_graph_block_empty_graph_reports_zero(tmp_path: Path):
    """With an empty graph the keys should still resolve to 0 (not KeyError)."""
    engine = _engine_with_graph()
    engine.get_graph_stats.return_value = {"total_edges": 0, "unique_nodes": 0, "relations": {}}

    from memorius.mcp_server import McpServer

    server = McpServer.__new__(McpServer)
    server._engine = engine
    result = server.tool_memorius_stats({})
    assert result["graph"]["nodes"] == 0
    assert result["graph"]["edges"] == 0
