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

# Search scoring weights
WEIGHT_AGE_DECAY = 0.4          # weight for age-based decay
WEIGHT_RECENCY = 0.4            # weight for recency boost
WEIGHT_REINFORCEMENT = 0.2      # weight for access frequency
WEIGHT_SEMANTIC = 0.6           # weight for semantic similarity in search
WEIGHT_TEMPORAL = 0.25          # weight for temporal decay in search
WEIGHT_ACCESS = 0.15            # weight for access count in search


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
    score = (age_decay * WEIGHT_AGE_DECAY + recency_boost * WEIGHT_RECENCY) * (reinforcement * WEIGHT_REINFORCEMENT + 1.0)
    score = max(score, MIN_DECAY_SCORE)
    score = min(score, 1.0)

    return round(score, 4)


def calculate_search_score(
    semantic_similarity: float,
    decay_score: float,
    access_count: int = 0,
    semantic_weight: float = WEIGHT_SEMANTIC,
    decay_weight: float = WEIGHT_TEMPORAL,
    access_weight: float = WEIGHT_ACCESS,
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
    """Find memories below the decay threshold or past their TTL expiry.

    Returns up to *limit* rows ordered oldest-first. A memory qualifies if
    its decay score is below *threshold* **or** its metadata contains an
    ``expires_at`` ISO timestamp that is strictly in the past.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    rows = conn.execute(
        """SELECT id, vault, shelf, folder, note, content, created_at,
                  last_accessed, access_count, metadata
           FROM memory_meta
           WHERE archived = 0
           ORDER BY created_at ASC
           LIMIT ?""",
        (limit,),
    ).fetchall()

    stale: list[dict[str, Any]] = []
    for row in rows:
        row_dict = dict(row)
        expired = False
        expires_at = None

        # Check TTL expiry from metadata JSON
        raw_meta = row_dict.pop("metadata", None) or ""
        if raw_meta:
            try:
                import json as _json
                meta = _json.loads(raw_meta)
                expires_at = meta.get("expires_at")
            except (ValueError, TypeError):
                pass

        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if exp_dt <= now:
                    expired = True
            except (ValueError, TypeError):
                pass

        score = calculate_decay_score(
            created_at=row_dict["created_at"],
            last_accessed=row_dict["last_accessed"],
            access_count=row_dict["access_count"],
        )
        row_dict["decay_score"] = score

        if score < threshold or expired:
            row_dict["expired"] = expired
            row_dict["expires_at"] = expires_at
            stale.append(row_dict)

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
