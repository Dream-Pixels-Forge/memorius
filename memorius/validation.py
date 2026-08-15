"""Shared validation constants and functions for memorius.

Single source of truth for input validation across MCP, REST, and CLI.
"""

from __future__ import annotations

import re
import uuid as _uuid

# ── Name validation ──────────────────────────────────────────────────────────

VALID_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
MAX_NAME_LENGTH = 128


def validate_name(value: str, label: str = "name") -> str:
    """Validate and sanitize a name field (vault, shelf, folder, note).

    Args:
        value: The name string to validate
        label: Human-readable label for error messages

    Returns:
        The validated name string

    Raises:
        ValueError: If the name contains invalid characters or is too long
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    value = value.strip()
    if len(value) > MAX_NAME_LENGTH:
        raise ValueError(f"{label} too long (max {MAX_NAME_LENGTH} chars)")
    if not VALID_NAME_RE.match(value):
        raise ValueError(
            f"{label} can only contain letters, numbers, hyphens, and underscores"
        )
    return value


# ── Memory ID validation ─────────────────────────────────────────────────────


def validate_memory_id(value: str) -> str:
    """Validate a memory ID.

    Memory IDs are generated as ``str(uuid.uuid4())``, so requiring a valid
    UUID here rejects path-traversal and garbage inputs before they reach the
    delete path, and makes accidental mis-deletes harder to do by typo.

    Args:
        value: The memory ID string to validate.

    Returns:
        The validated (stripped) memory ID.

    Raises:
        ValueError: If the ID is missing/blank or not a valid UUID.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("memory_id is required")
    value = value.strip()
    try:
        _uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise ValueError("memory_id must be a valid UUID")
    return value


# ── Session ID validation ────────────────────────────────────────────────────

VALID_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_\-.]+$")
MAX_SESSION_ID_LENGTH = 128


def validate_session_id(value: str) -> str:
    """Validate a session ID.

    Session IDs are free-form agent strings but must be safe for use as
    database keys and filesystem paths. Allows alphanumeric characters,
    hyphens, underscores, and dots.

    Args:
        value: The session ID string to validate.

    Returns:
        The validated (stripped) session ID.

    Raises:
        ValueError: If the ID is missing/blank, too long, or contains
            unsafe characters.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("session_id is required")
    value = value.strip()
    if len(value) > MAX_SESSION_ID_LENGTH:
        raise ValueError(f"session_id too long (max {MAX_SESSION_ID_LENGTH} chars)")
    if not VALID_SESSION_ID_RE.match(value):
        raise ValueError(
            "session_id can only contain letters, numbers, hyphens, underscores, and dots"
        )
    return value


# ── Content validation ───────────────────────────────────────────────────────

MAX_CONTENT_LENGTH = 100_000  # 100KB
MAX_FIELD_LENGTH = 1_000
MAX_SEARCH_LIMIT = 100
MAX_DIARY_CONTENT = 50_000


def validate_content(content: str) -> str:
    """Validate content field. Raises ValueError if invalid."""
    if not isinstance(content, str):
        raise ValueError("Content must be a string")
    if not content.strip():
        raise ValueError("Content cannot be empty")
    if len(content) > MAX_CONTENT_LENGTH:
        raise ValueError(f"Content too long (max {MAX_CONTENT_LENGTH} chars)")
    return content
