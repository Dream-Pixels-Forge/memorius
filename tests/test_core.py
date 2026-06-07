"""Tests for memorius — core vault engine, search, mine, and storage."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def engine():
    """Create a VaultEngine with isolated temp storage per test."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.vault import VaultEngine
    from memorius.config import load_config
    config = load_config()
    eng = VaultEngine(config)
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
    m = engine.store("Python is a high-level programming language", vault="test")
    assert m.id
    assert m.vault == "test"
    assert m.shelf == "default"
    
    results = engine.search("programming languages", vault="test")
    assert len(results) >= 1
    assert "Python" in results[0].content
    
    results_unrelated = engine.search("zzzzzzzzzz", vault="test")
    assert len(results_unrelated) <= len(results)


def test_vault_hierarchy(engine):
    """Store across hierarchy and explore it."""
    engine.store("alpha", vault="v1", shelf="s1", folder="f1", note="n1")
    engine.store("beta", vault="v1", shelf="s1", folder="f1", note="n2")
    engine.store("gamma", vault="v1", shelf="s2", folder="f1", note="n1")
    
    vaults = engine._meta.list_vaults()
    assert any(p["name"] == "v1" for p in vaults)
    
    shelves = engine._meta.list_shelves("v1")
    assert len(shelves) == 2
    
    folders_s1 = engine._meta.list_folders("v1", "s1")
    assert len(folders_s1) == 1
    assert folders_s1[0]["name"] == "f1"


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
    
    memories = engine.mine(text=transcript, vault="test-mine")
    assert len(memories) >= 1
    assert all(m.vault == "test-mine" for m in memories)


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
    assert "memorius_vault_ls" in tool_names
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
    assert "memorius" in out.getvalue()


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
    assert "vaults" in status
    assert "embedding_provider" in status
    assert "embedding_dimension" in status
    assert status["embedding_dimension"] == 384
