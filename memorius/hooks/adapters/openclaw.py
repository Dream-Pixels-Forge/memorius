"""OpenClaw adapter."""

from memorius.hooks.models import BaseAgentAdapter, HookEvent, HookEventType


class OpenClawAdapter(BaseAgentAdapter):
    """Parses OpenClaw's hook-style event payload."""

    agent_name = "openclaw"

    @classmethod
    def can_parse(cls, data: dict) -> bool:
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
