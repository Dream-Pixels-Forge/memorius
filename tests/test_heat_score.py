"""Tests for heat-score functionality (v0.8.0)."""

import datetime
import tempfile
import shutil
from pathlib import Path

import pytest

from memorius.temporal import (
    calculate_heat_score,
    classify_tier,
    calculate_combined_score_with_tier,
)
from memorius.meta_store import SQLiteStore


@pytest.fixture
def store():
    tmp = Path(tempfile.mkdtemp())
    s = SQLiteStore(tmp)
    yield s
    shutil.rmtree(tmp, ignore_errors=True)


def test_calculate_heat_score():
    """Heat score should return value between 0.0 and 1.0."""
    now = datetime.datetime.now(datetime.timezone.utc)
    created = (now - datetime.timedelta(days=7)).isoformat()
    accessed = (now - datetime.timedelta(hours=12)).isoformat()
    score = calculate_heat_score(created, accessed, access_count=5)
    assert 0.0 <= score <= 1.0


def test_calculate_heat_score_higher_when_recent():
    """More recently accessed memory should have higher heat score."""
    now = datetime.datetime.now(datetime.timezone.utc)
    created = (now - datetime.timedelta(days=7)).isoformat()
    recent = (now - datetime.timedelta(hours=1)).isoformat()
    old = (now - datetime.timedelta(days=3)).isoformat()
    score_recent = calculate_heat_score(created, recent, access_count=1)
    score_old = calculate_heat_score(created, old, access_count=1)
    assert score_recent > score_old


def test_classify_tier():
    """classify_tier should map scores to tiers."""
    assert classify_tier(0.8) == "hot"
    assert classify_tier(0.5) == "warm"
    assert classify_tier(0.2) == "cold"
    assert classify_tier(0.05) == "archived"


def test_calculate_combined_score_with_tier():
    """Tier should boost combined search score."""
    base = 0.5
    boosted_hot = calculate_combined_score_with_tier(base, "hot")
    boosted_cold = calculate_combined_score_with_tier(base, "cold")
    assert boosted_hot > base
    assert boosted_cold < base


def test_meta_store_has_heat_score(store):
    """SQLiteStore should support heat_score in memory_meta."""
    mid = store.track_memory(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        vault="test", shelf="test", folder="test", note="test",
        content="test heat score",
    )
    heat = store._conn().execute(
        "SELECT heat_score FROM memory_meta WHERE id=?",
        ("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",),
    ).fetchone()
    assert heat is not None
    assert heat[0] == 0.0
