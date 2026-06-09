"""OpenClaude adapter."""

from memorius.hooks.models import BaseAgentAdapter, HookEvent, HookEventType


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
