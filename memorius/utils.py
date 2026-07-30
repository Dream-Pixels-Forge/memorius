"""Shared utility functions for memorius.

Re-exports from validation.py for backwards compatibility.
"""

import json
from typing import Any, List

# Re-export from validation module for backwards compatibility
from memorius.validation import validate_name, MAX_NAME_LENGTH  # noqa: F401


def safe_parse_json(s: str) -> dict[str, Any]:
    """Parse a JSON string, returning an empty dict on failure.

    Handles None, empty strings, and corrupted JSON without raising.
    Used by store_module, search_module, and others for best-effort
    metadata parsing.
    """
    if not s:
        return {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector
        b: Second vector

    Returns:
        Similarity score between 0.0 and 1.0, or 0.0 if vectors are incompatible
    """
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
