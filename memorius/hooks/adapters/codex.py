"""Codex CLI adapter."""

from memorius.hooks.models import BaseAgentAdapter, HookEvent, HookEventType


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
