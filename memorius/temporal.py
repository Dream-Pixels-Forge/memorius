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


def _parse_dt(iso_str: str | None) -> datetime:
    """Parse an ISO timestamp string into a UTC datetime.

    Returns the current UTC time if *iso_str* is None or unparseable.
    """
    if not iso_str:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


def calculate_heat_score(
    created_at: str,
    accessed_at: str | None = None,
    access_count: int = 0,
    half_life_days: float = 30.0,
) -> float:
    """Calculate a heat score for a memory (0.0 = cold, 1.0 = hot).

    Combines three factors:
      - Recency of last access (exponential decay)
      - Access frequency (linear, capped at 10)
      - Freshness since creation (exponential decay, 90-day half-life)
    """
    now = datetime.now(timezone.utc)
    created = _parse_dt(created_at)
    last_accessed = _parse_dt(accessed_at) if accessed_at else created

    recency = math.exp(
        -0.693 * (now - last_accessed).total_seconds() / 86400 / half_life_days
    )
    freq = min(1.0, access_count / 10.0)
    freshness = math.exp(
        -0.693 * (now - created).total_seconds() / 86400 / 90.0
    )
    return round(0.4 * recency + 0.3 * freq + 0.3 * freshness, 4)


def classify_tier(score: float) -> str:
    """Map a heat score to a tier label."""
    if score >= 0.7:
        return "hot"
    if score >= 0.3:
        return "warm"
    if score >= 0.1:
        return "cold"
    return "archived"


def calculate_combined_score_with_tier(base_score: float, tier: str) -> float:
    """Apply a tier-based boost to a base search score."""
    BOOST = {"hot": 0.15, "warm": 0.05, "cold": -0.05, "archived": -0.15}
    return base_score + BOOST.get(tier, 0.0)


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
    created = _parse_dt(created_at)

    days_old = max((now - created).total_seconds() / 86400, 0)

    # Base decay from age
    age_decay = 1.0 / (1.0 + days_old * decay_rate)

    # Recency boost from last access
    if last_accessed:
        accessed = _parse_dt(last_accessed)
        days_since_access = max((now - accessed).total_seconds() / 86400, 0)
        recency_boost = 1.0 / (1.0 + days_since_access * decay_rate * 2)
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
