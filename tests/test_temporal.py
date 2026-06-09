"""Tests for memorius/temporal.py — decay scoring and search ranking."""

from memorius.temporal import (
    calculate_decay_score,
    calculate_search_score,
    find_stale_memories,
    archive_memories,
    WEIGHT_AGE_DECAY,
    WEIGHT_RECENCY,
    WEIGHT_REINFORCEMENT,
    WEIGHT_SEMANTIC,
    WEIGHT_TEMPORAL,
    WEIGHT_ACCESS,
)
from datetime import datetime, timezone, timedelta


def test_decay_score_fresh_memory():
    """A brand-new memory should have a high decay score."""
    now = datetime.now(timezone.utc).isoformat()
    score = calculate_decay_score(created_at=now, access_count=0)
    assert score > 0.5, f"Fresh memory decay too low: {score}"


def test_decay_score_old_memory():
    """A 30-day-old memory with no access should have lower score."""
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    score_old = calculate_decay_score(created_at=old, access_count=0)
    now = datetime.now(timezone.utc).isoformat()
    score_new = calculate_decay_score(created_at=now, access_count=0)
    assert score_old < score_new, f"Old memory ({score_old}) should score lower than new ({score_new})"


def test_decay_score_access_boost():
    """Accessing a memory should boost its score."""
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    score_no_access = calculate_decay_score(created_at=old, last_accessed=None, access_count=0)
    score_with_access = calculate_decay_score(created_at=old, last_accessed=old, access_count=5)
    assert score_with_access > score_no_access, "Access should boost decay score"


def test_decay_score_bounds():
    """Decay score should always be between MIN_DECAY_SCORE and 1.0."""
    from memorius.temporal import MIN_DECAY_SCORE
    very_old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    score = calculate_decay_score(created_at=very_old, access_count=0)
    assert MIN_DECAY_SCORE <= score <= 1.0, f"Score {score} out of bounds"


def test_search_score_combines_weights():
    """Search score should combine semantic, decay, and access."""
    score = calculate_search_score(
        semantic_similarity=0.9,
        decay_score=0.8,
        access_count=3,
    )
    # Should be weighted combination
    expected_min = 0.9 * WEIGHT_SEMANTIC * 0.5  # lower bound
    expected_max = 1.0  # upper bound
    assert expected_min <= score <= expected_max, f"Search score {score} out of expected range"


def test_search_score_prefers_fresh():
    """Fresh memories should score higher than stale ones."""
    fresh = calculate_search_score(semantic_similarity=0.7, decay_score=1.0, access_count=0)
    stale = calculate_search_score(semantic_similarity=0.7, decay_score=0.1, access_count=0)
    assert fresh > stale, f"Fresh ({fresh}) should score higher than stale ({stale})"


def test_constants_are_reasonable():
    """Verify weight constants sum to reasonable values."""
    assert 0 < WEIGHT_AGE_DECAY < 1
    assert 0 < WEIGHT_RECENCY < 1
    assert 0 < WEIGHT_REINFORCEMENT < 1
    assert 0 < WEIGHT_SEMANTIC < 1
    assert 0 < WEIGHT_TEMPORAL < 1
    assert 0 < WEIGHT_ACCESS < 1
