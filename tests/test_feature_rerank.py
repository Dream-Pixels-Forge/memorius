"""Tests for Phase 5.2 — Cross-encoder rerank."""
from unittest.mock import patch, MagicMock

import pytest

from memorius.config import load_config
from memorius.vault import VaultEngine


@pytest.fixture
def engine(tmp_path):
    config = load_config()
    config["storage"]["path"] = str(tmp_path / "data")
    return VaultEngine(config)


class TestRerankerModule:
    def test_import_without_sentence_transformers(self):
        """reranker module imports even without sentence-transformers."""
        from memorius import reranker
        assert hasattr(reranker, "rerank_search_results")

    def test_rerank_search_results_empty(self):
        """rerank_search_results returns empty list for empty input."""
        from memorius.reranker import rerank_search_results
        result = rerank_search_results("query", [])
        assert result == []

    def test_reranker_singleton(self):
        """get_reranker returns the same instance."""
        from memorius.reranker import get_reranker, reset_reranker
        reset_reranker()
        r1 = get_reranker()
        r2 = get_reranker()
        assert r1 is r2


class TestSearchRerankFlag:
    def test_search_rerank_defaults_false(self, engine):
        """search() works with rerank=False (default)."""
        engine.store("Python is a programming language", vault="test", shelf="main")
        results = engine.search("programming", vault="test", limit=5, rerank=False)
        assert len(results) >= 1

    def test_search_rerank_false_no_score_in_metadata(self, engine):
        """search() with rerank=False does not add __rerank_score__."""
        engine.store("Python is a programming language", vault="test", shelf="main")
        results = engine.search("programming", vault="test", limit=5, rerank=False)
        for m in results:
            assert "__rerank_score__" not in (m.metadata or {})

    def test_search_rerank_import_error_graceful(self, engine):
        """search() with rerank=True falls back gracefully if cross-encoder missing."""
        engine.store("Python is a programming language", vault="test", shelf="main")
        with patch("memorius.reranker.rerank_search_results", side_effect=ImportError("no sentence-transformers")):
            results = engine.search("programming", vault="test", limit=5, rerank=True)
        # Should still return results (just un-reranked)
        assert len(results) >= 1

    def test_search_rerank_exception_graceful(self, engine):
        """search() with rerank=True falls back gracefully on any exception."""
        engine.store("Python is a programming language", vault="test", shelf="main")
        with patch("memorius.reranker.rerank_search_results", side_effect=RuntimeError("model failed")):
            results = engine.search("programming", vault="test", limit=5, rerank=True)
        assert len(results) >= 1


class TestCLIRerankFlag:
    def test_rerank_flag_accepted(self):
        """search --help shows --rerank."""
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.argv=['memorius', 'search', '--help']; from memorius.cli.main import main; main()"],
            capture_output=True, text=True,
        )
        assert "--rerank" in result.stdout


class TestMCPRerankFlag:
    def test_search_tool_has_rerank(self):
        """MCP search tool schema includes rerank parameter."""
        from memorius.mcp_server import McpServer
        tools = McpServer.TOOLS
        search_tool = next(t for t in tools if t["name"] == "memorius_search")
        assert "rerank" in search_tool["inputSchema"]["properties"]


class TestRESTRerankFlag:
    def test_search_endpoint_accepts_rerank(self, engine):
        """REST /search accepts rerank field."""
        from fastapi.testclient import TestClient
        from memorius.rest_server import MemoriusAPI
        api = MemoriusAPI(engine)
        app = api.create_app()
        client = TestClient(app)
        engine.store("Python is a language", vault="main", shelf="default")
        resp = client.post(
            "/search",
            json={"query": "language", "rerank": False},
        )
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1
