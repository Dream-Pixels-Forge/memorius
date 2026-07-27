"""Feature tests for factcheck word-boundary fix (Phase 4.1) and
search access-recording fix (Phase 4.2).

Phase 4.1:
  Before the fix, _detect_contradiction used bare substring `in` tests:
  "is" in text matched "this"/"history", "no" matched "know"/"note",
  yielding huge false-positive contradiction rates. Now it uses \b
  word-boundary regexes. These tests pin the fix with the exact
  sentence pairs that used to false-contradict.

Phase 4.2:
  Before the fix, vault.search() called record_access on EVERY returned
  result, inflating access_count for memories the caller never used.
  Now search() no longer records access; explicit reinforcement is via
  engine.touch(id), and ContextInjector.inject touches only the
  memories it actually injects.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def engine():
    """VaultEngine against an isolated temp store (mirrors test_core)."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.config import load_config
    from memorius.vault import VaultEngine

    config = load_config()
    eng = VaultEngine(config)
    yield eng
    shutil.rmtree(tmp, ignore_errors=True)
    if hasattr(eng, "_vector") and hasattr(eng._vector, "_client"):
        try:
            eng._vector._client = None
        except Exception:
            pass


# ── Phase 4.1: Word-boundary negation / opposing-pair matching ─────────────


def test_negation_is_does_not_match_inside_this():
    """"is" inside "this" must NOT trigger a contradiction."""
    from memorius.factcheck import _detect_contradiction

    assert not _detect_contradiction(
        "the sky is blue", "the sky is also clear today",
    ), "'is' inside 'also'/'this' triggered a false contradiction"


def test_negation_is_not_vs_is_detected():
    """A real negation pair ('is' vs 'is not') must still be caught."""
    from memorius.factcheck import _detect_contradiction

    assert _detect_contradiction(
        "the sky is blue", "the sky is not blue",
    ), "real 'is' vs 'is not' negation should contradict"


def test_opposing_no_does_not_match_inside_know():
    """"no" inside "know" must NOT contradict "yes"."""
    from memorius.factcheck import _detect_contradiction

    assert not _detect_contradiction(
        "i know the answer is yes", "i also know the answer",
    ), "'no' inside 'know' triggered a false contradiction with 'yes'"


def test_opposing_yes_no_still_detected():
    from memorius.factcheck import _detect_contradiction

    assert _detect_contradiction(
        "the feature flag is yes", "the feature flag is no",
    ), "real 'yes' vs 'no' should contradict"


# ── Phase 4.1: Entity-slot heuristic tightening ────────────────────────────


def test_entity_slot_react_vs_vue_still_detected():
    """The headline case: same template, swapped entity, should contradict."""
    from memorius.factcheck import _detect_contradiction

    assert _detect_contradiction(
        "the project uses React for the frontend",
        "the project uses Vue for the frontend",
    ), "entity-slot React vs Vue should contradict"


def test_entity_slot_trailing_word_does_not_false_contradict():
    """'the sky is blue' vs 'the sky is blue today' differ by one trailing
    word but are NOT a contradiction — they agree. The old heuristic
    match_ratio was 0.75 and 'today' is a non-stopword, so it fired.
    The new length-ratio guard rejects this (len 4 vs 5, ratio 0.8 is
    on the edge; the guard is < 0.8 so exactly 0.8 does NOT trip)."""
    from memorius.factcheck import _detect_contradiction

    assert not _detect_contradiction(
        "the sky is blue", "the sky is blue today",
    ), "adding a trailing word should not contradict"


def test_entity_slot_multiple_diffs_do_not_contradict():
    """Two sentences with several differing words are usually a paraphrase,
    not a contradiction. The old heuristic fired for up to min_len//3
    diffs; the new one requires exactly one non-stopword diff."""
    from memorius.factcheck import _detect_contradiction

    assert not _detect_contradiction(
        "the user prefers fast ways to ship code",
        "the developer likes quick paths to deliver apps",
    ), "paraphrase with multiple diffs should not contradict"


# ── Phase 4.2: search no longer records access; touch does ─────────────────


def test_search_does_not_increment_access_count(engine):
    """Before the fix, vault.search() called record_access on every result,
    so two searches would bump access_count to 2 even though nothing was
    actually consumed. Now search() must NOT record access at all --
    access_count stays 0 and last_accessed stays at its store-time value."""
    m = engine.store("reinforcement test memory content here", vault="a")
    # Pull the initial state (access_count should be 0 from a fresh store;
    # last_accessed is set to now at store time by track_memory, not None).
    meta_before = engine.meta.get_memory_meta(m.id)
    assert meta_before["access_count"] == 0
    last_before = meta_before["last_accessed"]

    engine.search("reinforcement", vault="a", limit=5)
    engine.search("reinforcement", vault="a", limit=5)

    meta_after = engine.meta.get_memory_meta(m.id)
    assert meta_after["access_count"] == 0, (
        f"search should not record access; got {meta_after['access_count']}"
    )
    assert meta_after["last_accessed"] == last_before, (
        "search should not advance last_accessed"
    )


def test_touch_increments_access_count(engine):
    """engine.touch(id) is the explicit reinforcement primitive: it must
    bump access_count and set last_accessed."""
    import uuid as _uuid
    m = engine.store("touch test memory content here for access count", vault="b")

    engine.touch(m.id)
    meta_1 = engine.meta.get_memory_meta(m.id)
    assert meta_1["access_count"] == 1
    assert meta_1["last_accessed"] is not None

    engine.touch(m.id)
    meta_2 = engine.meta.get_memory_meta(m.id)
    assert meta_2["access_count"] == 2


def test_touch_missing_id_is_safe(engine):
    """touch on a nonexistent UUID must be a no-op (no crash)."""
    import uuid as _uuid
    engine.touch(str(_uuid.uuid4()))  # must not raise


def test_touch_invalid_id_is_ignored(engine):
    """touch on a non-UUID must be swallowed (debug-logged, not raised)."""
    engine.touch("not-a-uuid")  # must not raise


# ── Phase 4.2: ContextInjector touches only the memories it injects ────────


def test_context_injector_touches_injected_memories(engine):
    """The injector should touch() the memories it actually injects (the
    ones that pass the >20-char content filter and fit the limit) but
    NOT the ones that search() returned but the injector skipped."""
    # Two memories: one long enough to pass the injector's content filter,
    # one too short to be included.
    long_mem = engine.store(
        "a sufficiently long memory about kubernetes orchestration to pass the injector filter",
        vault="c",
    )
    short_mem = engine.store("short", vault="c")

    from memorius.context_inject import ContextInjector
    injector = ContextInjector(engine)
    block = injector.inject("kubernetes orchestration", vault="c", max_items=3)
    assert block, "injector should have produced a block for the long memory"

    long_meta = engine.meta.get_memory_meta(long_mem.id)
    short_meta = engine.meta.get_memory_meta(short_mem.id)
    assert long_meta["access_count"] >= 1, (
        "injected memory should be touched (access_count >= 1)"
    )
    # The short memory should NOT have been touched (it failed the >20 filter).
    assert short_meta["access_count"] == 0, (
        f"non-injected memory should not be touched; got {short_meta['access_count']}"
    )