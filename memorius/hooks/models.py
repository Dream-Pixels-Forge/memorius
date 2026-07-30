"""Shared types for the hook lifecycle system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class HookEventType(str, Enum):
    """Supported hook event types across all agents."""
    SESSION_START = "session_start"
    SESSION_STOP = "session_stop"
    PRE_COMPRESS = "pre_compress"
    POST_COMPRESS = "post_compress"
    PRE_COMPACT = "pre_compact"
    UNKNOWN = "unknown"


@dataclass
class HookEvent:
    """Normalised hook event, regardless of which agent produced it."""
    event_type: HookEventType
    session_id: str
    transcript_path: Optional[str] = None
    project_dir: Optional[str] = None
    agent_name: str = "unknown"
    raw_payload: dict = field(default_factory=dict)
    can_block: bool = False
    block_message: Optional[str] = None


@dataclass
class HookResult:
    """Result of processing a hook event, returned to the agent."""
    action: str = "allow"
    reason: Optional[str] = None
    exit_code: int = 0
    metadata: dict = field(default_factory=dict)


class AgentAdapterError(Exception):
    """Raised when an agent's input cannot be parsed."""


class BaseAgentAdapter:
    """Base class for agent-specific hook input parsers."""

    agent_name: str = "unknown"
    event_type_map: dict[str, HookEventType] = {}

    @classmethod
    def can_parse(cls, data: dict) -> bool:
        raise NotImplementedError

    @classmethod
    def parse(cls, data: dict) -> HookEvent:
        raise NotImplementedError
