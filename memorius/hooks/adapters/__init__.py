"""Agent adapters subpackage — one adapter per file."""

from memorius.hooks.adapters.base import BaseAgentAdapter
from memorius.hooks.adapters.claude_code import ClaudeCodeAdapter
from memorius.hooks.adapters.codex import CodexAdapter
from memorius.hooks.adapters.gemini import GeminiCliAdapter
from memorius.hooks.adapters.openclaw import OpenClawAdapter
from memorius.hooks.adapters.opencode import OpenCodeAdapter
from memorius.hooks.adapters.pi import PiAdapter
from memorius.hooks.adapters.openclaude import OpenClaudeAdapter
from memorius.hooks.adapters.generic import GenericAgentAdapter

# Registry: ordered by specificity (most specific first)
AGENT_ADAPTERS: list[type[BaseAgentAdapter]] = [
    OpenClaudeAdapter,
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
    if isinstance(data, list):
        return GenericAgentAdapter
    for adapter_cls in AGENT_ADAPTERS:
        if adapter_cls is GenericAgentAdapter:
            continue
        if adapter_cls.can_parse(data):
            return adapter_cls
    return GenericAgentAdapter
