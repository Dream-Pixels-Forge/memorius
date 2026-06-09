"""OpenCode adapter."""

from memorius.hooks.models import BaseAgentAdapter, HookEvent, HookEventType


class OpenCodeAdapter(BaseAgentAdapter):
    """Parses OpenCode's hook-style event payload."""

    agent_name = "opencode"
    event_type_map = {
        "stop": HookEventType.SESSION_STOP,
        "session_stop": HookEventType.SESSION_STOP,
        "session_start": HookEventType.SESSION_START,
        "precompact": HookEventType.PRE_COMPACT,
    }

    @classmethod
    def can_parse(cls, data: dict) -> bool:
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
