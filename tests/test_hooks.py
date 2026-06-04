"""Tests for memorius.hooks — agent detection, parsing, and lifecycle engine."""

import json
import pytest
from memorius.hooks import (
    detect_agent,
    ClaudeCodeAdapter,
    CodexAdapter,
    GeminiCliAdapter,
    OpenClawAdapter,
    GenericAgentAdapter,
    HookEvent,
    HookEventType,
    HookResult,
)
from memorius.hooks.engine import HookConfig, HookEngine, HookAction, DEFAULT_SAVE_INTERVAL


class TestAgentDetection:
    """Detect which AI agent sent a hook payload."""

    def test_detect_claude_code_via_stop_hook(self):
        """Claude Code stop hook: has session_id + stop_hook_active."""
        payload = {"session_id": "abc123", "stop_hook_active": True, "hook_name": "stop"}
        adapter = detect_agent(payload)
        assert adapter is ClaudeCodeAdapter

    def test_detect_claude_code_via_hook_name(self):
        """Claude Code also detected via session_id + recognized hook_name."""
        payload = {"session_id": "abc123", "hook_name": "precompact"}
        adapter = detect_agent(payload)
        assert adapter is ClaudeCodeAdapter

    def test_detect_claude_code_save_hook(self):
        """Claude Code save hook."""
        payload = {"session_id": "abc123", "hook_name": "save"}
        adapter = detect_agent(payload)
        assert adapter is ClaudeCodeAdapter

    def test_detect_codex(self):
        """Codex CLI: has session_id + context_dir."""
        payload = {"session_id": "abc123", "context_dir": "/tmp/project"}
        adapter = detect_agent(payload)
        assert adapter is CodexAdapter

    def test_detect_gemini(self):
        """Gemini CLI: has session_id + project_id."""
        payload = {"session_id": "abc123", "project_id": "proj-1"}
        adapter = detect_agent(payload)
        assert adapter is GeminiCliAdapter

    def test_detect_openclaw(self):
        """OpenClaw: has hook_type."""
        payload = {"hook_type": "precompact", "session_id": "abc123"}
        adapter = detect_agent(payload)
        assert adapter is OpenClawAdapter

    def test_detect_generic_fallback(self):
        """Unknown payload falls back to GenericAgentAdapter."""
        payload = {"some": "random", "data": "here"}
        adapter = detect_agent(payload)
        assert adapter is GenericAgentAdapter

    def test_detect_generic_empty_dict(self):
        """Empty dict falls back to generic."""
        adapter = detect_agent({})
        assert adapter is GenericAgentAdapter

    def test_detect_list_payload(self):
        """Some agents send a list — detection recurses into first matching element."""
        payload = [
            {"type": "message", "content": "hello"},
            {"session_id": "abc123", "hook_name": "stop"},
        ]
        adapter = detect_agent(payload)
        assert adapter is ClaudeCodeAdapter


class TestClaudeCodeParsing:
    """Claude Code adapter correctly parses hook payloads."""

    def test_parse_stop_hook(self):
        payload = {"session_id": "sess_1", "hook_name": "stop", "transcript_path": "/tmp/transcript.jsonl"}
        event = ClaudeCodeAdapter.parse(payload)
        assert event.event_type == HookEventType.SESSION_STOP
        assert event.session_id == "sess_1"
        assert event.transcript_path == "/tmp/transcript.jsonl"
        assert event.agent_name == "claude-code"
        assert event.can_block is True

    def test_parse_precompact_hook(self):
        payload = {"session_id": "sess_2", "hook_name": "precompact"}
        event = ClaudeCodeAdapter.parse(payload)
        assert event.event_type == HookEventType.PRE_COMPACT

    def test_parse_unknown_hook_name(self):
        payload = {"session_id": "sess_3", "hook_name": "unknown_event"}
        event = ClaudeCodeAdapter.parse(payload)
        assert event.event_type == HookEventType.UNKNOWN

    def test_parse_missing_session_id(self):
        payload = {"hook_name": "stop"}
        event = ClaudeCodeAdapter.parse(payload)
        assert event.session_id == "unknown"


class TestCodexParsing:
    """Codex CLI adapter correctly parses hook payloads."""

    def test_parse_stop_hook(self):
        payload = {"session_id": "sess_1", "event": "stop", "context_dir": "/home/user/project"}
        event = CodexAdapter.parse(payload)
        assert event.event_type == HookEventType.SESSION_STOP
        assert event.project_dir == "/home/user/project"
        assert event.agent_name == "codex"

    def test_parse_session_start(self):
        payload = {"session_id": "sess_2", "event": "session-start"}
        event = CodexAdapter.parse(payload)
        assert event.event_type == HookEventType.SESSION_START


class TestEngine:
    """Hook lifecycle engine processes events and returns decisions."""

    def test_default_config_allows_all(self):
        """Default config should allow all events by default."""
        config = HookConfig.default()
        engine = HookEngine(config)
        event = HookEvent(
            event_type=HookEventType.SESSION_STOP,
            session_id="test",
            agent_name="claude-code",
            can_block=True,
        )
        result = engine.process(event)
        assert result.action == "allow"

    def test_custom_action_does_not_crash(self):
        """Custom config actions don't crash the engine."""
        config = HookConfig(
            actions={
                "session_stop": [
                    HookAction(type="mine", name="diary.mine"),
                ]
            }
        )
        engine = HookEngine(config)
        event = HookEvent(
            event_type=HookEventType.SESSION_STOP,
            session_id="test",
            agent_name="claude-code",
            can_block=True,
        )
        result = engine.process(event)
        assert result.action in ("allow", "block")

    def test_unknown_event_type(self):
        """Unknown event types don't crash the engine."""
        config = HookConfig.default()
        engine = HookEngine(config)
        event = HookEvent(
            event_type=HookEventType.UNKNOWN,
            session_id="test",
            agent_name="generic",
            can_block=False,
        )
        result = engine.process(event)
        assert result.action == "allow"


class TestHookConfig:
    """HookConfig loading and defaults."""

    def test_default_factory(self):
        config = HookConfig.default()
        assert config.save_interval == DEFAULT_SAVE_INTERVAL
        # Default config comes with pre-defined actions for known events
        assert "pre_compress" in config.actions
        assert "session_start" in config.actions
        assert "session_stop" in config.actions

    def test_from_yaml_missing_file(self, tmp_path):
        """Missing file returns defaults without error."""
        missing = tmp_path / "does_not_exist.yaml"
        config = HookConfig.from_yaml(missing)
        assert config.save_interval == DEFAULT_SAVE_INTERVAL

    def test_from_yaml_valid_file(self, tmp_path):
        config_file = tmp_path / "hooks.yaml"
        config_file.write_text("save_interval: 120\nhooks:\n  session_stop:\n    actions:\n      - type: mine\n        name: transcript\n")
        config = HookConfig.from_yaml(config_file)
        assert config.save_interval == 120
        assert "session_stop" in config.actions
        assert len(config.actions["session_stop"]) == 1
