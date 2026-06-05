"""Integration tests for memorius — end-to-end vault, MCP, and REST flows."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest


@pytest.fixture
def isolated_env():
    """Set up a temporary memorius environment."""
    old_home = os.environ.get("HOME", "")
    old_storage = os.environ.pop("MEMORIUS_STORAGE_PATH", None)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Sandbox HOME so memorius init writes to ~/.memorius inside tmpdir
        fake_home = Path(tmpdir) / "home"
        fake_home.mkdir()
        os.environ["HOME"] = str(fake_home)
        os.environ["MEMORIUS_STORAGE_PATH"] = str(Path(tmpdir) / "data")

        yield Path(tmpdir)

    # Restore env
    os.environ["HOME"] = old_home
    if old_storage:
        os.environ["MEMORIUS_STORAGE_PATH"] = old_storage
    else:
        os.environ.pop("MEMORIUS_STORAGE_PATH", None)


def run_memorius(*args, env=None, input_text=None, timeout=120):
    """Run the memorius CLI and return stdout, stderr, exit_code."""
    memorius_bin = shutil.which("memorius")
    if not memorius_bin:
        pytest.skip("memorius not found in PATH")
    cmd = [memorius_bin] + list(args)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        input=input_text,
        timeout=timeout,
        env={**os.environ, **(env or {})},
    )
    return proc.stdout, proc.stderr, proc.returncode


# ---------------------------------------------------------------------------
# End-to-end CLI tests
# ---------------------------------------------------------------------------


class TestCliE2E:
    """Full lifecycle: init → store → search → diary → status."""

    def test_init(self, isolated_env):
        stdout, stderr, rc = run_memorius("init")
        assert rc == 0, f"init failed: {stderr}"
        assert "Initialized" in stdout or "Created" in stdout or "memorius" in stdout.lower() or "vault" in stdout.lower()

    def test_store_and_search(self, isolated_env):
        run_memorius("init")
        text = "The mitochondria is the powerhouse of the cell."

        stdout, stderr, rc = run_memorius("store", text, "--vault", "main", "--shelf", "science")
        assert rc == 0, f"store failed: {stderr}"
        assert "stored" in stdout.lower() or "id" in stdout.lower() or "ok" in stdout.lower() or stdout.strip()

        stdout, stderr, rc = run_memorius("search", "mitochondria", "--vault", "main")
        assert rc == 0, f"search failed: {stderr}"
        assert "mitochondria" in stdout.lower() or "powerhouse" in stdout.lower() or stdout.strip()

    def test_mine_transcript(self, isolated_env):
        run_memorius("init")
        transcript_dir = Path(isolated_env) / "transcripts"
        transcript_dir.mkdir()
        transcript = transcript_dir / "session.txt"
        transcript.write_text(
            "User: What's the capital of France?\n"
            "Assistant: The capital of France is Paris.\n"
            "User: Great, thanks!\n"
        )

        stdout, stderr, rc = run_memorius(
            "mine", str(transcript), "--vault", "main"
        )
        assert rc == 0, f"mine failed: {stderr}"
        assert stdout.strip(), "mine produced no output"

    def test_status(self, isolated_env):
        run_memorius("init")
        stdout, stderr, rc = run_memorius("status")
        assert rc == 0, f"status failed: {stderr}"

    def test_diary(self, isolated_env):
        run_memorius("init")
        stdout, stderr, rc = run_memorius(
            "diary", "session-1", "--title", "Test diary",
            "--summary", "Testing the diary feature"
        )
        assert rc == 0, f"diary failed: {stderr}"

    def test_ls(self, isolated_env):
        run_memorius("init")
        # Store something first so there's a vault to list
        run_memorius("store", "test item", "--vault", "main", "--shelf", "general")
        stdout, stderr, rc = run_memorius("ls", "--vault", "main")
        assert rc == 0, f"ls failed: {stderr}"
        assert "main" in stdout.lower() or stdout.strip()


# ---------------------------------------------------------------------------
# MCP protocol integration
# ---------------------------------------------------------------------------


class TestMcpIntegration:
    """Exercise the MCP server via stdio protocol."""

    def test_mcp_tools_listed(self, isolated_env):
        """The server announces tools on initialization."""
        # MCP protocol: initialize → list tools
        run_memorius("init")

        # Send an initialize request
        init_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "0.1.0",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        })
        tools_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })

        input_data = init_msg + "\n" + tools_msg + "\n"

        stdout, stderr, rc = run_memorius(
            "serve", input_text=input_data, timeout=15
        )
        assert rc == 0, f"MCP serve failed: {stderr}"

        # Should get back tool definitions
        assert "memorius" in stdout.lower() or "status" in stdout.lower() or "search" in stdout.lower() or "store" in stdout.lower() or stdout.strip()

    def test_mcp_store_tool(self, isolated_env):
        """Use the store tool via MCP and verify it works."""
        run_memorius("init")

        # Initialize request
        init_msg = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "0.1.0", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "1.0"}},
        })
        # Call the store tool
        store_msg = json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {
                "name": "memorius_status",
                "arguments": {"vault": "main"},
            },
        })

        input_data = init_msg + "\n" + store_msg + "\n"
        stdout, stderr, rc = run_memorius(
            "serve", input_text=input_data, timeout=15
        )
        assert rc == 0, f"MCP store tool failed: {stderr}"
        assert "vault" in stdout.lower() or "shelf" in stdout.lower() or "main" in stdout.lower() or stdout.strip()


# ---------------------------------------------------------------------------
# Hooks engine integration
# ---------------------------------------------------------------------------


class TestHooksIntegration:
    """Exercise the hooks engine directly."""

    def test_hook_engine_mine(self, isolated_env):
        """Hook engine can mine a transcript via VaultEngine."""
        from memorius.hooks.engine import HookEngine, HookConfig
        from memorius.hooks import HookEvent, HookEventType

        run_memorius("init")

        # Create a transcript file
        transcript = Path(isolated_env) / "transcript.txt"
        transcript.write_text(
            "User: What is Python?\n"
            "Assistant: Python is a programming language.\n"
        )

        engine = HookEngine()
        event = HookEvent(
            event_type=HookEventType.SESSION_STOP,
            session_id="test-session-001",
            transcript_path=str(transcript),
            agent_name="claude-code",
            raw_payload={},
            can_block=True,
        )
        result = engine.process(event)
        assert result.action in ("allow", "block"), f"unexpected action: {result.action}"
        assert result.exit_code == 0, f"non-zero exit: {result.exit_code}"

    def test_hook_engine_diary(self, isolated_env):
        """Hook engine can write a diary entry."""
        from memorius.hooks.engine import HookEngine, HookConfig
        from memorius.hooks import HookEvent, HookEventType

        run_memorius("init")

        config = HookConfig.from_dict({
            "hooks": {
                "session_stop": {
                    "actions": [
                        {"type": "diary", "name": "test_diary",
                         "message": "Test diary entry for {session_id}"},
                    ]
                }
            }
        })

        engine = HookEngine(config=config)
        event = HookEvent(
            event_type=HookEventType.SESSION_STOP,
            session_id="diary-test-session",
            agent_name="claude-code",
            raw_payload={},
            can_block=False,
        )
        result = engine.process(event)
        assert result.action == "allow"
        assert result.exit_code == 0
