"""Learning module — store and recall agent learnings.

This module provides structured storage for agent learnings including
bug fixes, reusable strategies, patterns, self-improvement insights,
tool usage tips, code snippets, and workflows.

Learnings are stored in a dedicated 'learnings' shelf with rich metadata
for efficient retrieval and categorization.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger("memorius.learning")


class LearningCategory(str, Enum):
    """Categories for agent learnings."""
    BUG_FIX = "bug_fix"
    STRATEGY = "strategy"
    PATTERN = "pattern"
    SELF_IMPROVEMENT = "self_improvement"
    TOOL_USAGE = "tool_usage"
    CODE_SNIPPET = "code_snippet"
    WORKFLOW = "workflow"


# Valid category values for validation
VALID_CATEGORIES = {c.value for c in LearningCategory}

# Default shelf for learnings
LEARNINGS_SHELF = "learnings"


@dataclass
class Learning:
    """A structured agent learning."""
    id: str
    content: str
    category: str
    context: str = ""
    solution: str = ""
    tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    applied_count: int = 0
    last_applied: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    vault: str = "main"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/serialization."""
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "context": self.context,
            "solution": self.solution,
            "tags": self.tags,
            "confidence": self.confidence,
            "applied_count": self.applied_count,
            "last_applied": self.last_applied,
            "created_at": self.created_at,
            "vault": self.vault,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Learning:
        """Create from dictionary."""
        return cls(
            id=data.get("id", ""),
            content=data.get("content", ""),
            category=data.get("category", LearningCategory.STRATEGY.value),
            context=data.get("context", ""),
            solution=data.get("solution", ""),
            tags=data.get("tags", []),
            confidence=float(data.get("confidence", 1.0)),
            applied_count=int(data.get("applied_count", 0)),
            last_applied=data.get("last_applied"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            vault=data.get("vault", "main"),
        )


def validate_category(category: str) -> str:
    """Validate and normalize a learning category.
    
    Args:
        category: The category string to validate.
        
    Returns:
        Normalized category string.
        
    Raises:
        ValueError: If category is not valid.
    """
    category = category.lower().strip()
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
        )
    return category


def format_learning_for_context(learning: Learning) -> str:
    """Format a learning for injection into agent context.
    
    Args:
        learning: The learning to format.
        
    Returns:
        Formatted string suitable for context injection.
    """
    parts = [f"[{learning.category.upper()}]"]
    
    if learning.context:
        parts.append(f"Context: {learning.context}")
    
    parts.append(f"Learning: {learning.content}")
    
    if learning.solution:
        parts.append(f"Solution: {learning.solution}")
    
    if learning.tags:
        parts.append(f"Tags: {', '.join(learning.tags)}")
    
    if learning.applied_count > 0:
        parts.append(f"Applied {learning.applied_count} times")
    
    return "\n".join(parts)


def format_learnings_summary(learnings: list[Learning]) -> dict[str, Any]:
    """Format a summary of learnings with statistics.
    
    Args:
        learnings: List of learnings to summarize.
        
    Returns:
        Summary dictionary with counts by category and total.
    """
    category_counts: dict[str, int] = {}
    total_applied = 0
    
    for learning in learnings:
        cat = learning.category
        category_counts[cat] = category_counts.get(cat, 0) + 1
        total_applied += learning.applied_count
    
    return {
        "total": len(learnings),
        "by_category": category_counts,
        "total_applied": total_applied,
        "categories": sorted(category_counts.keys()),
    }
