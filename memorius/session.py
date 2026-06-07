"""Cross-session memory inheritance.

When starting a new session, the agent inherits a "memory profile"
from the previous session: unresolved questions, ongoing tasks,
recent decisions. This gives the agent continuity — like human
working memory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("memorius.session")


@dataclass
class SessionProfile:
    """A memory profile inherited from a previous session."""
    session_id: str
    vault: str = "main"
    summary: str = ""
    key_decisions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    ongoing_tasks: list[str] = field(default_factory=list)
    recent_topics: list[str] = field(default_factory=list)
    context_memories: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""


def build_session_profile(
    engine,
    session_id: str,
    vault: str = "main",
) -> SessionProfile:
    """Build a memory profile for a session by analyzing recent activity.

    Examines:
    1. Most recent diary entries
    2. Recently stored memories
    3. Frequently accessed memories
    """
    now = datetime.now(timezone.utc).isoformat()
    profile = SessionProfile(session_id=session_id, vault=vault, created_at=now)

    # 1. Get recent diaries
    diaries = engine._meta.list_diaries(vault=vault, limit=5)
    if diaries:
        latest = diaries[0]
        profile.summary = latest.get("summary", "")
        # Extract topics from diary content
        content = latest.get("content", "")
        if content:
            profile.recent_topics = _extract_topics(content)

    # 2. Get recent memories
    recent = engine.search(query="", vault=vault, limit=10)
    for mem in recent:
        meta = mem.metadata or {}
        category = meta.get("category", "")
        content = mem.content or ""

        if category == "decision":
            profile.key_decisions.append(content[:200])
        elif category == "action_item":
            profile.ongoing_tasks.append(content[:200])
        elif len(content) > 50:
            profile.context_memories.append({
                "content": content[:300],
                "vault": mem.vault,
                "shelf": mem.shelf,
            })

    return profile


def format_profile_for_context(profile: SessionProfile) -> str:
    """Format a session profile as context for the agent.

    Returns a compact text block suitable for injection into
    the system prompt or context window.
    """
    parts = []

    parts.append(f"## Session Profile: {profile.session_id}")
    parts.append(f"Vault: {profile.vault}")

    if profile.summary:
        parts.append(f"\n**Previous Summary:** {profile.summary}")

    if profile.key_decisions:
        parts.append("\n**Key Decisions:**")
        for d in profile.key_decisions[:5]:
            parts.append(f"- {d}")

    if profile.ongoing_tasks:
        parts.append("\n**Ongoing Tasks:**")
        for t in profile.ongoing_tasks[:5]:
            parts.append(f"- {t}")

    if profile.recent_topics:
        parts.append(f"\n**Recent Topics:** {', '.join(profile.recent_topics[:5])}")

    if profile.context_memories:
        parts.append("\n**Relevant Context:**")
        for m in profile.context_memories[:3]:
            parts.append(f"- {m['content'][:150]}")

    return "\n".join(parts)


def inherit_from_previous_session(
    engine,
    new_session_id: str,
    previous_session_id: str | None = None,
    vault: str = "main",
) -> SessionProfile:
    """Inherit memory profile from a previous session.

    If previous_session_id is None, uses the most recent session.
    """
    if previous_session_id:
        # Look for diary of specific session
        diary = engine._meta.get_diary(previous_session_id)
        if diary:
            profile = SessionProfile(
                session_id=new_session_id,
                vault=vault,
                summary=diary.get("summary", ""),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            # Extract from diary content
            content = diary.get("content", "")
            if content:
                profile.recent_topics = _extract_topics(content)
                profile.context_memories = _extract_context(content)
            return profile

    # Fallback: build from recent activity
    return build_session_profile(engine, new_session_id, vault)


def _extract_topics(text: str) -> list[str]:
    """Extract topic keywords from text."""
    # Simple keyword extraction
    words = text.lower().split()
    # Filter common words
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "and", "but", "or",
        "not", "no", "nor", "so", "yet", "both", "either", "neither", "each",
        "every", "all", "any", "few", "more", "most", "other", "some", "such",
        "than", "too", "very", "just", "also", "now", "then", "here", "there",
        "when", "where", "why", "how", "what", "which", "who", "whom", "this",
        "that", "these", "those", "it", "its", "i", "me", "my", "we", "our",
        "you", "your", "he", "him", "his", "she", "her", "they", "them", "their",
    }
    # Count word frequency
    freq: dict[str, int] = {}
    for word in words:
        word = word.strip(".,!?;:\"'()[]{}")
        if len(word) > 3 and word not in stopwords:
            freq[word] = freq.get(word, 0) + 1

    # Return top keywords
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:10]]


def _extract_context(content: str) -> list[dict[str, Any]]:
    """Extract context items from content."""
    items = []
    lines = content.split("\n")
    for line in lines:
        line = line.strip()
        if line and len(line) > 20:
            items.append({"content": line[:300], "vault": "main", "shelf": "context"})
            if len(items) >= 5:
                break
    return items
