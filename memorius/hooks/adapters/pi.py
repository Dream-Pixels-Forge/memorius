"""Pi adapter."""

from memorius.hooks.models import BaseAgentAdapter, HookEvent, HookEventType


class PiAdapter(BaseAgentAdapter):
    """Parses Pi's hook-style event payload.

    Pi uses a declarative hook system delivered via a TypeScript extension
    bridge. Events: session_start, tool_call, turn_end, session_shutdown,
    session_before_compact.
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
            can_block=False,
        )
