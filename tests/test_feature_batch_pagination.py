"""Phase 5.1 — Batch embedding for mine() and 5.5 — Cursor pagination."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def engine():
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.config import load_config
    from memorius.vault import VaultEngine

    config = load_config()
    eng = VaultEngine(config)
    yield eng
    shutil.rmtree(tmp, ignore_errors=True)


class TestBatchEmbedding:
    """mine() uses batch embedding for all chunks at once."""

    def test_mine_stores_all_chunks(self, engine):
        text = "First chunk about topic A.\n\nSecond chunk about topic B.\n\nThird chunk about topic C."
        memories = engine.mine(text)
        assert len(memories) == 3

    def test_mine_empty_text(self, engine):
        assert engine.mine("") == []
        assert engine.mine("   ") == []

    def test_mine_single_chunk(self, engine):
        memories = engine.mine("Just one paragraph here.")
        assert len(memories) == 1

    def test_mine_vectors_computed(self, engine):
        memories = engine.mine("Chunk one.\n\nChunk two.")
        for m in memories:
            assert m.vector is not None
            assert len(m.vector) > 0

    def test_mine_stored_searchable(self, engine):
        engine.mine("The quick brown fox jumps over the lazy dog.\n\nA second unrelated sentence.")
        results = engine.search("quick fox")
        assert len(results) > 0
        assert "fox" in results[0].content.lower()


class TestCursorPagination:
    """list_memories supports cursor-based pagination."""

    def test_first_page(self, engine):
        for i in range(5):
            engine.store(f"memory {i}")
        result = engine.list_memories(limit=3, with_vectors=False)
        assert len(result["memories"]) == 3
        assert result["next_cursor"] is not None

    def test_second_page(self, engine):
        for i in range(5):
            engine.store(f"memory {i}")
        page1 = engine.list_memories(limit=3, with_vectors=False)
        page2 = engine.list_memories(limit=3, with_vectors=False, cursor=page1["next_cursor"])
        assert len(page2["memories"]) == 2
        assert page2["next_cursor"] is None

    def test_empty_result(self, engine):
        result = engine.list_memories(limit=10, with_vectors=False)
        assert result["memories"] == []
        assert result["next_cursor"] is None

    def test_cursor_excludes_previous(self, engine):
        for i in range(10):
            engine.store(f"memory {i}")
        page1 = engine.list_memories(limit=5, with_vectors=False)
        page1_ids = {m.id for m in page1["memories"]}
        page2 = engine.list_memories(limit=5, with_vectors=False, cursor=page1["next_cursor"])
        page2_ids = {m.id for m in page2["memories"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_vault_filter_with_cursor(self, engine):
        engine.store("vault1 mem", vault="v1")
        engine.store("vault2 mem", vault="v2")
        engine.store("vault1 mem2", vault="v1")
        result = engine.list_memories(vault="v1", limit=10, with_vectors=False)
        assert len(result["memories"]) == 2
        assert all(m.vault == "v1" for m in result["memories"])


class TestMCPPagination:
    """MCP list tool returns paginated results."""

    def test_list_tool_returns_cursor(self, engine):
        for i in range(5):
            engine.store(f"mcp mem {i}")
        from memorius.mcp_server import McpServer
        server = McpServer(engine)
        result = server.tool_memorius_list({"limit": 3})
        assert result["count"] == 3
        assert result["next_cursor"] is not None

    def test_list_tool_second_page(self, engine):
        for i in range(5):
            engine.store(f"mcp mem {i}")
        from memorius.mcp_server import McpServer
        server = McpServer(engine)
        page1 = server.tool_memorius_list({"limit": 3})
        page2 = server.tool_memorius_list({"limit": 3, "cursor": page1["next_cursor"]})
        assert page2["count"] == 2
        assert page2["next_cursor"] is None


class TestRESTPagination:
    """REST /memories endpoint returns paginated results."""

    def test_list_memories_endpoint(self, engine):
        from fastapi.testclient import TestClient
        from memorius.rest_server import MemoriusAPI

        for i in range(5):
            engine.store(f"rest mem {i}")

        api = MemoriusAPI(engine)
        app = api.create_app()
        client = TestClient(app)

        response = client.get("/memories?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert data["next_cursor"] is not None

        response2 = client.get(f"/memories?limit=3&cursor={data['next_cursor']}")
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["count"] == 2
