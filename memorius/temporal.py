"""Temporal decay and reinforcement for memories.

Memories decay over time (Ebbinghaus forgetting curve) unless accessed or
reinforced. This makes the vault self-cleaning: stale memories fade,
important ones stay bright.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from typing import Any


# ── Decay constants ──────────────────────────────────────────────────────────

DEFAULT_DECAY_RATE = 0.02       # memories lose ~2% relevance per day
MIN_DECAY_SCORE = 0.05          # floor — memories never fully vanish
REINFORCEMENT_LOG_BASE = 2.0    # logarithmic reinforcement scaling
ARCHIVE_THRESHOLD = 0.1         # below this → auto-archive


def calculate_decay_score(
    created_at: str,
    last_accessed: str | None = None,
    access_count: int = 0,
    decay_rate: float = DEFAULT_DECAY_RATE,
) -> float:
    """Calculate the temporal decay score for a memory.

    Score ranges from ~0.0 (stale) to 1.0 (fresh/reinforced).
    Combines:
      - Time since creation (older = lower)
      - Time since last access (longer ago = lower)
      - Access frequency (more accesses = higher, logarithmic)
    """
    now = datetime.now(timezone.utc)

    # Parse creation time
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 1.0  # can't parse → assume fresh

    days_old = max((now - created).total_seconds() / 86400, 0)

    # Base decay from age
    age_decay = 1.0 / (1.0 + days_old * decay_rate)

    # Recency boost from last access
    if last_accessed:
        try:
            accessed = datetime.fromisoformat(last_accessed.replace("Z", "+00:00"))
            days_since_access = max((now - accessed).total_seconds() / 86400, 0)
            recency_boost = 1.0 / (1.0 + days_since_access * decay_rate * 2)
        except (ValueError, AttributeError):
            recency_boost = 0.5
    else:
        recency_boost = 0.5

    # Reinforcement from access count (logarithmic)
    reinforcement = math.log(access_count + 1, REINFORCEMENT_LOG_BASE) + 1.0
    reinforcement = min(reinforcement, 5.0)  # cap at 5x

    # Combine: age decay weighted 40%, recency 40%, reinforcement 20%
    score = (age_decay * 0.4 + recency_boost * 0.4) * (reinforcement * 0.2 + 1.0)
    score = max(score, MIN_DECAY_SCORE)
    score = min(score, 1.0)

    return round(score, 4)


def calculate_search_score(
    semantic_similarity: float,
    decay_score: float,
    access_count: int = 0,
    semantic_weight: float = 0.6,
    decay_weight: float = 0.25,
    access_weight: float = 0.15,
) -> float:
    """Calculate final search ranking score.

    Combines semantic similarity with temporal decay and access frequency.
    """
    reinforcement = math.log(access_count + 1, REINFORCEMENT_LOG_BASE) + 1.0
    reinforcement = min(reinforcement, 3.0) / 3.0  # normalize to 0-1

    score = (
        semantic_similarity * semantic_weight
        + decay_score * decay_weight
        + reinforcement * access_weight
    )
    return round(score, 4)


def mark_accessed(conn: sqlite3.Connection, memory_id: str):
    """Update last_accessed timestamp and increment access_count for a memory."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE memory_meta
           SET last_accessed = ?,
               access_count = access_count + 1,
               updated_at = ?
           WHERE id = ?""",
        (now, now, memory_id),
    )
    conn.commit()


def find_stale_memories(
    conn: sqlite3.Connection,
    threshold: float = ARCHIVE_THRESHOLD,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Find memories below the decay threshold (candidates for archival)."""
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        """SELECT id, vault, shelf, folder, note, content, created_at,
                  last_accessed, access_count
           FROM memory_meta
           WHERE archived = 0
           ORDER BY created_at ASC
           LIMIT ?""",
        (limit,),
    ).fetchall()

    stale = []
    for row in rows:
        score = calculate_decay_score(
            created_at=row["created_at"],
            last_accessed=row["last_accessed"],
            access_count=row["access_count"],
        )
        if score < threshold:
            stale.append(dict(row))
            stale[-1]["decay_score"] = score

    return stale


def archive_memories(conn: sqlite3.Connection, memory_ids: list[str]):
    """Mark memories as archived (soft delete)."""
    now = datetime.now(timezone.utc).isoformat()
    for mid in memory_ids:
        conn.execute(
            "UPDATE memory_meta SET archived = 1, updated_at = ? WHERE id = ?",
            (now, mid),
        )
    conn.commit()
