"""Claude Code adapter."""

from memorius.hooks.models import BaseAgentAdapter, HookEvent, HookEventType


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
