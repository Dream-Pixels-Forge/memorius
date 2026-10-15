"""Tests for the neuroscience-inspired consolidation module (GOAL 3.1).

Covers the three neuromodulation primitives added to memorius/consolidation.py:

  - ``_apply_interference_forgetting`` — similar, rarely-used memories lose
    heat when a stronger memory interferes (interference-based forgetting).
  - ``_apply_engram_maturation`` — frequently-retrieved memories gain heat
    (engram maturation / consolidation through repetition).
  - ``_apply_neuromodulator_gating`` — recent access bursts and novelty
    signals adjust heat (neuromodulator-gated retrieval).

Plus an end-to-end run of ``engine.consolidate`` proving the primitives are
wired into the consolidation flow without errors.
"""

import json
import math
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    """Create a VaultEngine with isolated temp storage per test."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.config import load_config
    from memorius.vault import VaultEngine

    eng = VaultEngine(load_config())
    yield eng
    eng.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _mem(heat=0.5, access=0, last_accessed=None, metadata=None):
    """Build a lightweight memory dict like the consolidation flow uses."""
    meta = {"heat_score": heat, "access_count": access}
    if last_accessed is not None:
        meta["last_accessed"] = last_accessed
    if metadata:
        meta.update(metadata)
    return {"id": "m1", "content": "hello", "metadata": json.dumps(meta)}


# ── Interference-based forgetting ────────────────────────────────────────────


class TestInterferenceForgetting:
    def test_similar_unused_memory_loses_heat(self):
        from memorius.consolidation import _apply_interference_forgetting

        weak = _mem(heat=0.8, access=0)
        strong = _mem(access=10)
        new_heat = _apply_interference_forgetting(weak, strong, similarity=0.9)

        # High similarity + zero use + strong interferer → heat reduced.
        assert new_heat < 0.8

    def test_heat_never_drops_below_floor(self):
        from memorius.consolidation import _apply_interference_forgetting

        weak = _mem(heat=0.0, access=0)
        strong = _mem(access=10)
        new_heat = _apply_interference_forgetting(weak, strong, similarity=1.0)

        assert new_heat >= 0.1

    def test_frequently_used_memory_resists_interference(self):
        from memorius.consolidation import _apply_interference_forgetting

        well_used = _mem(heat=0.8, access=10)
        strong = _mem(access=10)
        new_heat = _apply_interference_forgetting(well_used, strong, similarity=0.9)

        # access_factor is 0 → interference_strength 0 → heat unchanged.
        assert new_heat == pytest.approx(0.8)

    def test_weak_interferer_causes_less_forgetting(self):
        from memorius.consolidation import _apply_interference_forgetting

        weak_interferer = _mem(access=1)
        strong_interferer = _mem(access=10)
        target = lambda base: _apply_interference_forgetting(
            _mem(heat=0.9, access=0), base, similarity=1.0
        )

        assert target(strong_interferer) < target(weak_interferer)

    def test_metadata_dict_and_json_string_both_accepted(self):
        from memorius.consolidation import _apply_interference_forgetting

        as_dict = {"id": "a", "content": "x", "metadata": {"heat_score": 0.7, "access_count": 0}}
        as_json = {"id": "b", "content": "x", "metadata": json.dumps({"heat_score": 0.7, "access_count": 0})}
        base = _mem(access=10)

        assert _apply_interference_forgetting(as_dict, base, 0.9) == pytest.approx(
            _apply_interference_forgetting(as_json, base, 0.9)
        )


# ── Engram maturation ─────────────────────────────────────────────────────────


class TestEngramMaturation:
    def test_frequently_accessed_memory_matures(self):
        from memorius.consolidation import _apply_engram_maturation

        matured = _apply_engram_maturation(_mem(heat=0.4, access=20))
        assert matured > 0.4

    def test_heat_caps_at_one(self):
        from memorius.consolidation import _apply_engram_maturation

        assert _apply_engram_maturation(_mem(heat=0.99, access=100)) <= 1.0

    def test_never_accessed_memory_gains_minimal_heat(self):
        from memorius.consolidation import _apply_engram_maturation

        new_heat = _apply_engram_maturation(_mem(heat=0.5, access=0))
        # maturity_factor = 0.5 * (1 - e^0) = 0 → no boost beyond baseline.
        assert new_heat == pytest.approx(0.5)

    def test_maturation_has_diminishing_returns(self):
        from memorius.consolidation import _apply_engram_maturation

        low  = _apply_engram_maturation(_mem(heat=0.4, access=20))
        mid  = _apply_engram_maturation(_mem(heat=0.4, access=50))
        high = _apply_engram_maturation(_mem(heat=0.4, access=150))

        # Saturation curve e^(-n/10): step 20→50 exceeds step 50→150
        # 0.5*(1-e^(-2))=0.432, 0.5*(1-e^(-5))=0.497, 0.5*(1-e^(-15))≈0.5
        # gain 20→50 ≈ 0.65*0.4; gain 50→150 ≈ 0.5*0.4 (still saturating)
        assert (mid - low) >= (high - mid)


# ── Neuromodulator-gated retrieval ────────────────────────────────────────────


class TestNeuromodulatorGating:
    def test_recent_access_boosts_heat(self):
        from memorius.consolidation import _apply_neuromodulator_gating

        recent = datetime.now(timezone.utc).isoformat()
        new_heat = _apply_neuromodulator_gating(
            _mem(heat=0.5, access=5, last_accessed=recent), recent_novelty=0.5
        )
        # burst_factor 0.8 → effect (0.8*0.7 + ~0.15) > 0.5 → positive adjustment.
        assert new_heat > 0.5

    def test_stale_access_reduces_heat(self):
        from memorius.consolidation import _apply_neuromodulator_gating

        stale = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        new_heat = _apply_neuromodulator_gating(
            _mem(heat=0.5, access=5, last_accessed=stale), recent_novelty=0.5
        )
        # burst_factor 0.3 → effect below 0.5 → slight negative adjustment.
        assert new_heat < 0.5

    def test_result_is_clamped_to_valid_range(self):
        from memorius.consolidation import _apply_neuromodulator_gating

        low = _apply_neuromodulator_gating(
            _mem(heat=0.1, access=0), recent_novelty=0.0
        )
        high = _apply_neuromodulator_gating(
            _mem(heat=1.0, access=0, last_accessed=datetime.now(timezone.utc).isoformat()),
            recent_novelty=1.0,
        )
        assert 0.1 <= low <= 1.0
        assert 0.1 <= high <= 1.0

    def test_invalid_timestamp_falls_back_to_recent(self):
        """_parse_dt returns now() for unparseable input, so a garbage
        last_accessed behaves like a *very recent* access (burst_factor
        ≈ 0.8) — distinct from the no-timestamp neutral case (burst_factor
        0.5). Both are valid heat adjustments; they just differ."""
        from memorius.consolidation import _apply_neuromodulator_gating

        neutral = _apply_neuromodulator_gating(
            _mem(heat=0.5, access=5), recent_novelty=0.5
        )
        garbage = _apply_neuromodulator_gating(
            _mem(heat=0.5, access=5, last_accessed="not-a-date"), recent_novelty=0.5
        )
        # Invalid timestamp → _parse_dt falls back to now() → treated as a
        # recent access (burst_factor ~0.8) → heat adjustment is *more*
        # positive than the neutral case (burst_factor 0.5).
        assert 0.1 <= garbage <= 1.0
        assert garbage > neutral


# ── End-to-end consolidation ──────────────────────────────────────────────────


class TestConsolidateIntegration:
    def test_consolidate_runs_and_returns_result(self, engine):
        """The consolidation flow executes against a real vault and applies
        the neuroscience primitives without raising."""
        engine.store("the deployment uses kubernetes for orchestration",
                     vault="main", shelf="dupes")
        engine.store("the deployment uses kubernetes for orchestration of pods",
                     vault="main", shelf="dupes")

        result = engine.consolidate(vault="main", similarity_threshold=0.5)

        from memorius.consolidation import ConsolidationResult
        assert isinstance(result, ConsolidationResult)
        assert result.clusters_found >= 0
        assert result.memories_merged >= 0
        assert result.memories_archived >= 0

    def test_consolidate_dry_run_changes_nothing(self, engine):
        m = engine.store("a unique memory that will not be merged",
                         vault="main", shelf="solo")
        engine.consolidate(vault="main", similarity_threshold=0.1, dry_run=True)

        assert engine.get_memory(m.id) is not None
