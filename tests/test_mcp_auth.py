"""Tests for MCP authorization (issue #53).

When MEMORIUS_MCP_TOKEN is set, destructive MCP tools require a matching
mcp_token in their arguments. Non-destructive tools remain open.
When the env var is unset, all tools are open (backward compatible).

Auth is enforced at the _handle_call_tool dispatch level, so tests call
_handle_call_tool with JSON-RPC-style params (name + arguments).
"""

import os
from pathlib import Path

import pytest


def _make_engine(tmp_path):
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp_path)
    from memorius.config import load_config
    from memorius.vault import VaultEngine
    return VaultEngine(load_config())


def _make_server(engine):
    from memorius.mcp_server import McpServer
    server = McpServer.__new__(McpServer)
    server._engine = engine
    return server


def _call_tool(server, tool_name: str, arguments: dict):
    """Call a tool through the JSON-RPC dispatch path (_handle_call_tool).

    Returns a normalized dict with either ``result`` (success) or ``error``
    (auth failure) key, plus a ``text`` field with the response body string.
    """
    resp = server._handle_call_tool(
        msg_id=1,
        params={"name": tool_name, "arguments": arguments},
    )
    if "error" in resp:
        return {"error": resp["error"]["message"], "text": resp["error"]["message"]}
    return {"result": resp["result"], "text": resp["result"]["content"][0]["text"]}


def test_mcp_no_token_all_tools_open(tmp_path):
    """Without MEMORIUS_MCP_TOKEN, destructive tools work without mcp_token."""
    os.environ.pop("MEMORIUS_MCP_TOKEN", None)
    engine = _make_engine(tmp_path)
    server = _make_server(engine)

    result = _call_tool(server, "memorius_status", {})
    assert "error" not in result


def test_mcp_token_set_destructive_with_token(tmp_path, monkeypatch):
    """With MEMORIUS_MCP_TOKEN set, destructive tool with correct token works."""
    os.environ["MEMORIUS_MCP_TOKEN"] = "test-secret-token"
    try:
        engine = _make_engine(tmp_path)
        server = _make_server(engine)

        # Non-destructive tool works without token
        result = _call_tool(server, "memorius_status", {})
        assert "error" not in result

        # Destructive tool with correct token: no auth error
        result = _call_tool(
            server,
            "memorius_delete",
            {"memory_id": "00000000-0000-0000-0000-000000000001", "mcp_token": "test-secret-token"},
        )
        assert "error" not in result
        assert "MCP authorization required" not in result["text"]
    finally:
        os.environ.pop("MEMORIUS_MCP_TOKEN", None)


def test_mcp_token_set_destructive_without_token(tmp_path, monkeypatch):
    """With MEMORIUS_MCP_TOKEN set, destructive tool without token returns auth error."""
    os.environ["MEMORIUS_MCP_TOKEN"] = "test-secret-token"
    try:
        engine = _make_engine(tmp_path)
        server = _make_server(engine)

        result = _call_tool(
            server,
            "memorius_delete",
            {"memory_id": "00000000-0000-0000-0000-000000000001"},
        )
        assert "error" in result
        assert "MCP authorization required" in result["error"]
    finally:
        os.environ.pop("MEMORIUS_MCP_TOKEN", None)


def test_mcp_token_set_destructive_wrong_token(tmp_path, monkeypatch):
    """With MEMORIUS_MCP_TOKEN set, destructive tool with wrong token returns auth error."""
    os.environ["MEMORIUS_MCP_TOKEN"] = "test-secret-token"
    try:
        engine = _make_engine(tmp_path)
        server = _make_server(engine)

        result = _call_tool(
            server,
            "memorius_delete",
            {"memory_id": "00000000-0000-0000-0000-000000000001", "mcp_token": "wrong-token"},
        )
        assert "error" in result
        assert "MCP authorization required" in result["error"]
    finally:
        os.environ.pop("MEMORIUS_MCP_TOKEN", None)


def test_mcp_token_set_nondestructive_without_token(tmp_path, monkeypatch):
    """With MEMORIUS_MCP_TOKEN set, non-destructive tools work without token."""
    os.environ["MEMORIUS_MCP_TOKEN"] = "test-secret-token"
    try:
        engine = _make_engine(tmp_path)
        server = _make_server(engine)

        result = _call_tool(server, "memorius_status", {})
        assert "error" not in result

        result = _call_tool(server, "memorius_store", {"content": "test content"})
        assert "error" not in result
        assert "authorization" not in result["text"].lower()
    finally:
        os.environ.pop("MEMORIUS_MCP_TOKEN", None)


def test_mcp_token_set_consolidate_without_token(tmp_path, monkeypatch):
    """With MEMORIUS_MCP_TOKEN set, consolidate without token returns auth error."""
    os.environ["MEMORIUS_MCP_TOKEN"] = "test-secret-token"
    try:
        engine = _make_engine(tmp_path)
        server = _make_server(engine)

        result = _call_tool(server, "memorius_consolidate", {})
        assert "error" in result
        assert "MCP authorization required" in result["error"]
    finally:
        os.environ.pop("MEMORIUS_MCP_TOKEN", None)


def test_mcp_token_set_prune_without_token(tmp_path, monkeypatch):
    """With MEMORIUS_MCP_TOKEN set, prune without token returns auth error."""
    os.environ["MEMORIUS_MCP_TOKEN"] = "test-secret-token"
    try:
        engine = _make_engine(tmp_path)
        server = _make_server(engine)

        result = _call_tool(server, "memorius_prune", {})
        assert "error" in result
        assert "MCP authorization required" in result["error"]
    finally:
        os.environ.pop("MEMORIUS_MCP_TOKEN", None)
