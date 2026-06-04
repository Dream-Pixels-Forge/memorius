"""
Universal Hook Lifecycle Adapter for Memorius
=================================================

Decouples Memorius hooks from any single AI agent's hook protocol.

The problem:
  Claude Code, Codex CLI, Gemini CLI, Cursor, OpenClaw, OpenCode,
  Pi, and OpenClaude all have
  different hook event names, JSON payload schemas, and lifecycle
  semantics (block vs. allow, synchronous vs. async). Currently
  Memorius duplicates shell wrappers per agent.

The solution:
  A single hook lifecycle engine that reads a declarative config,
  normalises any agent's event into a common internal event model,
  and executes the appropriate Memorius action (mine, diary, compact).

Usage:
  # Agent-agnostic: pipe stdin from any supported agent
  memorius-hook run

  # Explicitly specify the agent (auto-detected from stdin shape if omitted)
  memorius-hook run --agent claude-code
  memorius-hook run --agent codex --event precompact
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Common event model — the universal representation of any agent's hook event
# ---------------------------------------------------------------------------


class HookEventType(str, Enum):
    """Supported hook event types across all agents."""
    SESSION_START = "session_start"
    SESSION_STOP = "session_stop"
    PRE_COMPRESS = "pre_compress"
    POST_COMPRESS = "post_compress"
    PRE_COMPACT = "pre_compact"  # Gemini CLI naming
    UNKNOWN = "unknown"


@dataclass
class HookEvent:
    """Normalised hook event, regardless of which agent produced it."""
    event_type: HookEventType
    session_id: str
    transcript_path: Optional[str] = None
    project_dir: Optional[str] = None
    agent_name: str = "unknown"
    raw_payload: dict = field(default_factory=dict)

    # Agent lifecycle semantics
    can_block: bool = False        # Can this hook block the agent's lifecycle?
    block_message: Optional[str] = None  # Reason shown when blocking


@dataclass
class HookResult:
    """Result of processing a hook event, returned to the agent."""
    action: str = "allow"  # "allow", "block", "schedule"
    reason: Optional[str] = None
    exit_code: int = 0
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent adapters — each knows how to parse its agent's JSON stdin
# ---------------------------------------------------------------------------


class AgentAdapterError(Exception):
    """Raised when an agent's input cannot be parsed."""


class BaseAgentAdapter:
    """Base class for agent-specific hook input parsers."""

    agent_name: str = "unknown"
    event_type_map: dict[str, HookEventType] = {}

    @classmethod
    def can_parse(cls, data: dict) -> bool:
        """Detect if this adapter can handle the given payload."""
        raise NotImplementedError

    @classmethod
    def parse(cls, data: dict) -> HookEvent:
        """Parse agent-specific JSON into a universal HookEvent."""
        raise NotImplementedError


class ClaudeCodeAdapter(BaseAgentAdapter):
    """Parses Claude Code's hook protocol v1."""

    agent_name = "claude-code"
    event_type_map = {
        "stop": HookEventType.SESSION_STOP,
        "precompact": HookEventType.PRE_COMPACT,
    }

    @classmethod
    def can_parse(cls, data: dict) -> bool:
        has_session = bool(data.get("session_id"))
        has_stop_flag = "stop_hook_active" in data
        has_hook_name = data.get("hook_name", "").lower() in ("stop", "precompact", "save")
        return has_session and (has_stop_flag or has_hook_name)

    @classmethod
    def parse(cls, data: dict) -> HookEvent:
        raw_type = data.get("hook_name", "stop").lower()
        event_type = cls.event_type_map.get(raw_type, HookEventType.UNKNOWN)
        return HookEvent(
            event_type=event_type,
            session_id=str(data.get("session_id", "unknown")),
            transcript_path=data.get("transcript_path"),
            agent_name=cls.agent_name,
            raw_payload=data,
            can_block=True,
        )


class CodexAdapter(BaseAgentAdapter):
    """Parses Codex CLI's hook protocol."""

    agent_name = "codex"
    event_type_map = {
        "session-start": HookEventType.SESSION_START,
        "stop": HookEventType.SESSION_STOP,
        "precompact": HookEventType.PRE_COMPACT,
    }

    @classmethod
    def can_parse(cls, data: dict) -> bool:
        return bool(data.get("session_id")) and "context_dir" in data

    @classmethod
    def parse(cls, data: dict) -> HookEvent:
        raw_type = data.get("event", "stop").lower()
        event_type = cls.event_type_map.get(raw_type, HookEventType.UNKNOWN)
        return HookEvent(
            event_type=event_type,
            session_id=str(data.get("session_id", "unknown")),
            transcript_path=data.get("transcript_path"),
            project_dir=data.get("context_dir"),
            agent_name=cls.agent_name,
            raw_payload=data,
            can_block=True,
        )


class GeminiCliAdapter(BaseAgentAdapter):
    """Parses Gemini CLI's PreCompress hook protocol."""

    agent_name = "gemini-cli"
    event_type_map = {
        "precompress": HookEventType.PRE_COMPACT,
    }

    @classmethod
    def can_parse(cls, data: dict) -> bool:
        return bool(data.get("session_id")) and "project_id" in data

    @classmethod
    def parse(cls, data: dict) -> HookEvent:
        raw_type = data.get("event", "precompress").lower()
        event_type = cls.event_type_map.get(raw_type, HookEventType.UNKNOWN)
        return HookEvent(
            event_type=event_type,
            session_id=str(data.get("session_id", "unknown")),
            transcript_path=data.get("transcript_path"),
            project_dir=data.get("project_dir"),
            agent_name=cls.agent_name,
            raw_payload=data,
            can_block=False,  # Gemini doesn't use block protocol
        )


class OpenClawAdapter(BaseAgentAdapter):
    """Parses OpenClaw's hook-style event payload."""

    agent_name = "openclaw"

    @classmethod
    def can_parse(cls, data: dict) -> bool:
        # Only match when openclaw is explicitly indicated
        return any(
            "openclaw" in str(k).lower() or "openclaw" in str(v).lower()
            for k, v in data.items()
        )

    @classmethod
    def parse(cls, data: dict) -> HookEvent:
        raw_type = data.get("event_type", data.get("hook_type", "session_stop")).lower()
        event_type_map = {
            "session_stop": HookEventType.SESSION_STOP,
            "stop": HookEventType.SESSION_STOP,
            "session_start": HookEventType.SESSION_START,
            "precompact": HookEventType.PRE_COMPACT,
        }
        event_type = event_type_map.get(raw_type, HookEventType.UNKNOWN)
        return HookEvent(
            event_type=event_type,
            session_id=str(data.get("session_id", "unknown")),
            transcript_path=str(data.get("transcript_path", "")),
            agent_name=cls.agent_name,
            raw_payload=data,
            can_block=bool(data.get("can_block", False)),
        )


class OpenCodeAdapter(BaseAgentAdapter):
    """Parses OpenCode's hook-style event payload.

    OpenCode (anomalyco/opencode) uses a JSON-based communication
    protocol. This adapter detects OpenCode by checking for
    OpenCode-specific fields like 'provider', 'permission',
    or OpenCode-specific session markers.
    """

    agent_name = "opencode"
    event_type_map = {
        "stop": HookEventType.SESSION_STOP,
        "session_stop": HookEventType.SESSION_STOP,
        "session_start": HookEventType.SESSION_START,
        "precompact": HookEventType.PRE_COMPACT,
    }

    @classmethod
    def can_parse(cls, data: dict) -> bool:
        # Check for OpenCode-specific fields (not just generic session_id+event)
        has_provider = data.get("provider") is not None and isinstance(data.get("provider"), dict)
        has_opencode_marker = any(
            "opencode" in str(k).lower() or "opencode" in str(v).lower()
            for k, v in data.items()
        )
        has_session = bool(data.get("session_id"))
        has_opencode_event = data.get("event", "").lower() in {"stop", "session_stop", "session_start", "precompact"}
        return (has_session and has_opencode_event and has_provider) or has_opencode_marker

    @classmethod
    def parse(cls, data: dict) -> HookEvent:
        raw_type = data.get("event", data.get("hook_name", "stop")).lower()
        event_type = cls.event_type_map.get(raw_type, HookEventType.UNKNOWN)
        return HookEvent(
            event_type=event_type,
            session_id=str(data.get("session_id", "unknown")),
            transcript_path=data.get("transcript_path") or data.get("log_path"),
            agent_name=cls.agent_name,
            raw_payload=data,
            can_block=True,
        )


class PiAdapter(BaseAgentAdapter):
    """Parses Pi's hook-style event payload.

    Pi uses a declarative hook system delivered via a TypeScript extension
    bridge. Events: session_start, tool_call, turn_end, session_shutdown,
    session_before_compact.

    Pi's home directory is ~/.pi/agent/ and uses settings.json.
    """

    agent_name = "pi"
    event_type_map = {
        "session_start": HookEventType.SESSION_START,
        "session_shutdown": HookEventType.SESSION_STOP,
        "stop": HookEventType.SESSION_STOP,
        "shutdown": HookEventType.SESSION_STOP,
        "tool_call": HookEventType.UNKNOWN,
        "turn_end": HookEventType.SESSION_STOP,
        "session_before_compact": HookEventType.PRE_COMPACT,
        "precompact": HookEventType.PRE_COMPACT,
    }

    @classmethod
    def can_parse(cls, data: dict) -> bool:
        has_session = bool(data.get("session_id"))
        # Mirrors event_type_map keys (the events this adapter actually claims to handle).
        pi_events = {
            "session_start", "session_shutdown", "session_before_compact",
            "tool_call", "turn_end", "stop", "shutdown", "precompact",
        }
        has_pi_event = data.get("event", "").lower() in pi_events
        has_hook_type = data.get("hook_type", "").lower() in pi_events
        return has_session and (has_pi_event or has_hook_type)

    @classmethod
    def parse(cls, data: dict) -> HookEvent:
        raw_type = data.get("event", data.get("hook_type", "session_shutdown")).lower()
        event_type = cls.event_type_map.get(raw_type, HookEventType.UNKNOWN)
        return HookEvent(
            event_type=event_type,
            session_id=str(data.get("session_id", "unknown")),
            transcript_path=data.get("transcript_path"),
            agent_name=cls.agent_name,
            raw_payload=data,
            can_block=False,  # Pi uses bridge extension, not block protocol
        )


class OpenClaudeAdapter(BaseAgentAdapter):
    """Parses OpenClaude's hook-style event payload.

    OpenClaude is a Claude Code-compatible open-source agent that
    mirrors Claude Code's hook protocol with OpenClaude-specific naming.
    """

    agent_name = "openclaude"
    event_type_map = {
        "stop": HookEventType.SESSION_STOP,
        "precompact": HookEventType.PRE_COMPACT,
        "session_start": HookEventType.SESSION_START,
    }

    @classmethod
    def can_parse(cls, data: dict) -> bool:
        # Only match when OpenClaude is explicitly indicated
        # (otherwise ClaudeCodeAdapter handles the standard format)
        has_openclaude_marker = any(
            "openclaude" in str(k).lower() or "openclaude" in str(v).lower()
            for k, v in data.items()
        )
        if not has_openclaude_marker:
            return False
        has_session = bool(data.get("session_id"))
        return has_session

    @classmethod
    def parse(cls, data: dict) -> HookEvent:
        raw_type = data.get("hook_name", data.get("hook_type", "stop")).lower()
        event_type = cls.event_type_map.get(raw_type, HookEventType.UNKNOWN)
        return HookEvent(
            event_type=event_type,
            session_id=str(data.get("session_id", "unknown")),
            transcript_path=data.get("transcript_path"),
            agent_name=cls.agent_name,
            raw_payload=data,
            can_block=True,
        )


class GenericAgentAdapter(BaseAgentAdapter):
    """Fallback: tries to extract useful info from any JSON blob.

    This is the universal adapter — if no specific adapter matches,
    we try to make sense of whatever we got. This is what makes the
    system "universal": an agent doesn't need a specific adapter
    written to use Memorius hooks.
    """

    agent_name = "generic"

    @classmethod
    def can_parse(cls, data: dict) -> bool:
        # This always returns True — it's the last resort
        return True

    @classmethod
    def parse(cls, data: Any) -> HookEvent:
        if not isinstance(data, dict):
            # Handle non-dict payloads (e.g. JSON arrays)
            return HookEvent(
                event_type=HookEventType.UNKNOWN,
                session_id=str(hash(str(data))),
                agent_name="generic",
                raw_payload=data if isinstance(data, dict) else {"_raw": str(data)},
                can_block=False,
            )
        # Try common field names across agents
        session_id = (
            data.get("session_id")
            or data.get("session")
            or data.get("conversation_id")
            or data.get("id")
            or str(hash(json.dumps(data, sort_keys=True)))
        )
        transcript_path = (
            data.get("transcript_path")
            or data.get("transcript")
            or data.get("log_path")
            or data.get("file")
        )
        project_dir = data.get("project_dir") or data.get("context_dir") or data.get("workspace")

        # Detect event type from available keys
        keys_lower = {k.lower() for k in data.keys()}
        if keys_lower & {"precompact", "precompress", "compact"}:
            event_type = HookEventType.PRE_COMPACT
        elif keys_lower & {"stop", "shutdown", "exit", "close"}:
            event_type = HookEventType.SESSION_STOP
        elif keys_lower & {"start", "begin", "session_start"}:
            event_type = HookEventType.SESSION_START
        else:
            event_type = HookEventType.UNKNOWN

        return HookEvent(
            event_type=event_type,
            session_id=str(session_id),
            transcript_path=transcript_path,
            project_dir=project_dir,
            agent_name="generic",
            raw_payload=data,
            can_block=False,
        )


# Registry: ordered by specificity (most specific first)
AGENT_ADAPTERS: list[type[BaseAgentAdapter]] = [
    OpenClaudeAdapter,    # before ClaudeCode (checks "openclaude" whole word)
    ClaudeCodeAdapter,
    CodexAdapter,
    GeminiCliAdapter,
    OpenClawAdapter,
    OpenCodeAdapter,
    PiAdapter,
    GenericAgentAdapter,  # must be last
]


def detect_agent(data: dict) -> type[BaseAgentAdapter]:
    """Auto-detect which agent produced this payload."""
    # Lists are not valid hook payloads — use generic adapter
    if isinstance(data, list):
        return GenericAgentAdapter

    for adapter_cls in AGENT_ADAPTERS:
        if adapter_cls is GenericAgentAdapter:
            continue  # checked last
        if adapter_cls.can_parse(data):
            return adapter_cls
    return GenericAgentAdapter
