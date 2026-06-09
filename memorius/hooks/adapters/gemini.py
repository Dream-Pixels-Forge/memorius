"""Gemini CLI adapter."""

from memorius.hooks.models import BaseAgentAdapter, HookEvent, HookEventType


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
            can_block=False,
        )
