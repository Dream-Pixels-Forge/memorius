"""Tests for memorius — core palace engine, search, mine, and storage."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def engine():
    """Create a PalaceEngine with isolated temp storage per test."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.palace import PalaceEngine
    from memorius.config import load_config
    config = load_config()
    eng = PalaceEngine(config)
    yield eng
    shutil.rmtree(tmp, ignore_errors=True)
    # ChromeDB's Rust backend holds file handles; force cleanup
    if hasattr(eng, "_vector") and hasattr(eng._vector, "_client"):
        try:
            eng._vector._client = None
        except Exception:
            pass


def test_config_loading():
    """Config loads with defaults even without a config file."""
    from memorius.config import load_config
    config = load_config()
    assert "storage" in config
    assert "embeddings" in config
    assert "server" in config
    assert "hooks" in config
    assert config["embeddings"]["provider"] == "chroma-default"


def test_embeddings_chroma_default():
    """ChromaDefaultProvider uses ChromaDB's built-in ONNX embedding."""
    from memorius.embeddings import ChromaDefaultProvider
    provider = ChromaDefaultProvider()
    vectors = provider.embed(["hello world", "test sentence"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 384  # all-MiniLM-L6-v2 dimension
    import math
    norm = math.sqrt(sum(v*v for v in vectors[0]))
    assert abs(norm - 1.0) < 0.01


def test_store_and_search(engine):
    """Store a memory and find it via semantic search."""
    m = engine.store("Python is a high-level programming language", palace="test")
    assert m.id
    assert m.palace == "test"
    assert m.wing == "default"
    
    results = engine.search("programming languages", palace="test")
    assert len(results) >= 1
    assert "Python" in results[0].content
    
    results_unrelated = engine.search("zzzzzzzzzz", palace="test")
    assert len(results_unrelated) <= len(results)


def test_palace_hierarchy(engine):
    """Store across hierarchy and explore it."""
    engine.store("alpha", palace="p1", wing="w1", room="r1", drawer="d1")
    engine.store("beta", palace="p1", wing="w1", room="r1", drawer="d2")
    engine.store("gamma", palace="p1", wing="w2", room="r1", drawer="d1")
    
    palaces = engine._meta.list_palaces()
    assert any(p["name"] == "p1" for p in palaces)
    
    wings = engine._meta.list_wings("p1")
    assert len(wings) == 2
    
    rooms_w1 = engine._meta.list_rooms("p1", "w1")
    assert len(rooms_w1) == 1
    assert rooms_w1[0]["name"] == "r1"


def test_diary(engine):
    """Write and retrieve diary entries."""
    entry = engine.write_diary(
        session_id="sess-001",
        title="Test Session",
        summary="A test diary entry",
        exchange_count=5,
    )
    assert entry["session_id"] == "sess-001"
    assert entry["title"] == "Test Session"
    
    diaries = engine._meta.list_diaries()
    assert any(d["session_id"] == "sess-001" for d in diaries)
    
    found = engine._meta.get_diary("sess-001")
    assert found is not None
    assert found["title"] == "Test Session"


def test_mine_transcript(engine):
    """Mine extracts memories from a transcript."""
    transcript = """User: What is machine learning?
Assistant: Machine learning is a subset of AI that enables systems to learn from data.
User: Give me an example.
Assistant: Spam detection is a classic example of supervised learning."""
    
    memories = engine.mine(transcript, palace="test-mine")
    assert len(memories) >= 1
    assert all(m.palace == "test-mine" for m in memories)


def test_mcp_server_exists():
    """MCP server module loads with all tools defined."""
    from memorius.mcp_server import McpServer
    assert len(McpServer.TOOLS) >= 7
    tool_names = [t["name"] for t in McpServer.TOOLS]
    assert "memorius_status" in tool_names
    assert "memorius_store" in tool_names
    assert "memorius_search" in tool_names
    assert "memorius_mine" in tool_names
    assert "memorius_diary_write" in tool_names
    assert "memorius_palace_ls" in tool_names
    assert "memorius_diary_list" in tool_names


def test_cli_help():
    """CLI parses help and version."""
    from memorius.cli.main import main
    import sys, io
    
    sys.argv = ["memorius", "--version"]
    out = io.StringIO()
    sys.stdout = out
    try:
        main()
    except SystemExit:
        pass
    sys.stdout = sys.__stdout__
    assert "memorius" in out.getvalue() and "0.1." in out.getvalue()


def test_plugin_gen_imports():
    """Plugin generator module loads."""
    from memorius.plugin_gen import cli as pg
    assert hasattr(pg, "cmd_list")
    assert hasattr(pg, "cmd_generate")
    assert hasattr(pg, "cmd_init")


def test_normalizers_imports():
    """Normalizer module loads and detects formats."""
    from memorius.normalizers import detect_format, normalize
    assert callable(detect_format)
    assert callable(normalize)


def test_hooks_imports():
    """Hooks module loads with agent adapters."""
    from memorius.hooks import detect_agent, ClaudeCodeAdapter, HookEventType
    assert callable(detect_agent)
    assert hasattr(HookEventType, "SESSION_STOP")


def test_storage_status(engine):
    """Engine.status() returns structured info."""
    status = engine.status()
    assert "memories" in status
    assert "palaces" in status
    assert "embedding_provider" in status
    assert "embedding_dimension" in status
    assert status["embedding_dimension"] == 384
