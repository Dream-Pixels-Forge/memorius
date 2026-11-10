"""
Universal Hook Lifecycle Adapter for Memorius
=================================================

Decouples Memorius hooks from any single AI agent's hook protocol.

Adapters are now split into individual files under hooks/adapters/:
  - claude_code.py, codex.py, gemini.py, openclaw.py
  - opencode.py, pi.py, openclaude.py, generic.py

This module re-exports everything for backwards compatibility.
"""

from __future__ import annotations

# Re-export adapters and registry
from memorius.hooks.adapters import (  # noqa: F401
    AGENT_ADAPTERS,
    ClaudeCodeAdapter,
    CodexAdapter,
    GeminiCliAdapter,
    GenericAgentAdapter,
    OpenClaudeAdapter,
    OpenClawAdapter,
    OpenCodeAdapter,
    PiAdapter,
    detect_agent,
)

# Re-export models
from memorius.hooks.models import (  # noqa: F401
    AgentAdapterError,
    BaseAgentAdapter,
    HookEvent,
    HookEventType,
    HookResult,
)
