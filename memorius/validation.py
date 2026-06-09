"""Shared validation constants and functions for memorius.

Single source of truth for input validation across MCP, REST, and CLI.
"""

from __future__ import annotations

import re

# ── Name validation ──────────────────────────────────────────────────────────

VALID_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
MAX_NAME_LENGTH = 1000


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
