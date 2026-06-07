"""Shared utility functions for memorius."""

import re
from typing import List

# Name validation constants
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
