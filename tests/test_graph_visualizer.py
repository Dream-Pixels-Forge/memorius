"""Tests for Knowledge Graph Visualizer (graph_visualizer.py, graph.py, and endpoints)."""

import json
import tempfile
from pathlib import Path

from memorius.config import load_config
from memorius.graph import get_graph_data, link_memories, init_graph_schema
from memorius.graph_visualizer import render_graph_html
from memorius.mcp_server import McpServer
from memorius.vault import VaultEngine


def _setup_test_engine(tmp_path: Path) -> VaultEngine:
    config = {
        "storage": {
            "type": "chroma",
            "path": str(tmp_path / "data"),
        },
        "vault": {"default": "main"},
    }
    engine = VaultEngine(config)
    return engine


def test_get_graph_data_empty(tmp_path):
    """get_graph_data on an empty vault should return empty node and edge lists."""
    engine = _setup_test_engine(tmp_path)
    try:
        data = engine.get_graph_data()
        assert data["nodes"] == []
        assert data["edges"] == []
        assert data["summary"]["node_count"] == 0
        assert data["summary"]["edge_count"] == 0
    finally:
        engine.close()


def test_get_graph_data_with_links(tmp_path):
    """get_graph_data should return nodes and connected edges with metadata."""
    engine = _setup_test_engine(tmp_path)
    try:
        # Store memories
        m1 = engine.store("Alpha project architecture design", vault="main", shelf="arch", note="alpha", _vector=[0.1]*384)
        m2 = engine.store("Beta service integration guide", vault="main", shelf="services", note="beta", _vector=[0.2]*384)
        m3 = engine.store("Contradicting statement on architecture", vault="main", shelf="arch", note="gamma", _vector=[0.3]*384)

        # Link memories
        conn = engine._meta._conn()
        link_memories(conn, m1.id, m2.id, weight=0.85, relation="references")
        link_memories(conn, m1.id, m3.id, weight=0.92, relation="contradicts")

        # Fetch graph data
        data = engine.get_graph_data(vault="main")
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 2

        # Check edge relations
        relations = {e["relation"] for e in data["edges"]}
        assert "references" in relations
        assert "contradicts" in relations

        # Check node degrees
        alpha_node = next(n for n in data["nodes"] if n["id"] == m1.id)
        assert alpha_node["degree"] == 2
        assert alpha_node["shelf"] == "arch"

        # Test filtering by relation
        ref_data = engine.get_graph_data(relation="references")
        assert len(ref_data["edges"]) == 1
        assert ref_data["edges"][0]["relation"] == "references"

        # Test filtering by min_weight
        high_weight_data = engine.get_graph_data(min_weight=0.90)
        assert len(high_weight_data["edges"]) == 1
        assert high_weight_data["edges"][0]["relation"] == "contradicts"
    finally:
        engine.close()


def test_render_graph_html():
    """render_graph_html should produce self-contained interactive HTML."""
    sample_data = {
        "nodes": [
            {
                "id": "node-1",
                "label": "arch/alpha",
                "vault": "main",
                "shelf": "arch",
                "note": "alpha",
                "content": "Full architecture description",
                "snippet": "Full architecture...",
                "category": "decision",
                "tags": ["arch", "core"],
                "access_count": 5,
                "degree": 1,
            }
        ],
        "edges": [],
        "summary": {"node_count": 1, "edge_count": 0},
    }

    html = render_graph_html(sample_data, title="Custom Graph Title")
    assert "<!DOCTYPE html>" in html
    assert "Custom Graph Title" in html
    assert "node-1" in html
    assert "<canvas id=\"graph-canvas\"></canvas>" in html
    assert "id=\"inspector\"" in html
    assert "id=\"search-input\"" in html


def test_export_graph_html_file(tmp_path):
    """export_graph_html should write standalone HTML file to disk."""
    engine = _setup_test_engine(tmp_path)
    try:
        engine.store("Test memory content", vault="main", shelf="test", note="sample", _vector=[0.1]*384)

        out_file = tmp_path / "graph_output.html"
        html = engine.export_graph_html(dest=str(out_file))

        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8") == html
        assert "<canvas" in html
    finally:
        engine.close()


def test_mcp_graph_export(tmp_path):
    """McpServer tool_memorius_graph_export should support json and html formats."""
    engine = _setup_test_engine(tmp_path)
    try:
        m1 = engine.store("First memory", vault="main", shelf="s1", note="n1", _vector=[0.1]*384)
        m2 = engine.store("Second memory", vault="main", shelf="s2", note="n2", _vector=[0.2]*384)

        conn = engine._meta._conn()
        link_memories(conn, m1.id, m2.id, weight=0.75, relation="related")

        mcp = McpServer(engine)

        # JSON export
        res_json = mcp.tool_memorius_graph_export({"vault": "main", "format": "json"})
        assert "nodes" in res_json
        assert len(res_json["nodes"]) == 2
        assert len(res_json["edges"]) == 1

        # HTML export
        res_html = mcp.tool_memorius_graph_export({"vault": "main", "format": "html"})
        assert res_html["format"] == "html"
        assert res_html["html_length"] > 1000
        assert "<!DOCTYPE html>" in res_html["preview"]
    finally:
        engine.close()
