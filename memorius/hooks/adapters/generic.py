"""Generic fallback adapter."""

import json
from typing import Any

from memorius.hooks.models import BaseAgentAdapter, HookEvent, HookEventType


class GenericAgentAdapter(BaseAgentAdapter):
    """Fallback: tries to extract useful info from any JSON blob.

    This is the universal adapter — if no specific adapter matches,
    we try to make sense of whatever we got.
    """

    agent_name = "generic"

    @classmethod
    def can_parse(cls, data: dict) -> bool:
        return True

    @classmethod
    def parse(cls, data: Any) -> HookEvent:
        if not isinstance(data, dict):
            return HookEvent(
                event_type=HookEventType.UNKNOWN,
                session_id=str(hash(str(data))),
                agent_name="generic",
                raw_payload=data if isinstance(data, dict) else {"_raw": str(data)},
                can_block=False,
            )
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
