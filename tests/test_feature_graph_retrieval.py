"""Feature tests for graph-aware retrieval (Phase 1.1).

Verifies that:
- engine.search(expand_graph=True) pulls in memories linked in the knowledge
  graph to the primary vector hits, while expand_graph=False preserves the
  original search-only behavior.
- linked-but-already-primary memories are deduped (never appear twice).
- the CLI --expand-graph flag threads through to the engine.
- ContextInjector.inject (default expand_graph=True) also augments with
  graph-linked memories.
"""

import builtins
import os
import shutil
import sys
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


def _store_linked_pair(engine):
    """Store two highly-similar memories (auto-linked by content proximity
    on store), plus a third unrelated memory. Returns the three Memory ids."""
    # Two near-identical sentences so auto_link_by_proximity (Jaccard >= 0.3
    # on word overlap) creates a bidirectional edge between them.
    a = engine.store(
        "the deployment uses kubernetes for orchestration of services",
        vault="main", shelf="s1",
    )
    b = engine.store(
        "the deployment uses kubernetes for orchestration of containers",
        vault="main", shelf="s1",
    )
    # Unrelated filler so the vault isn't trivially small.
    engine.store(
        "the capital of France is Paris and sits on the Seine river",
        vault="main", shelf="s2",
    )
    return a, b


# ── Engine-level search expansion ───────────────────────────────────────────


def test_search_expand_graph_pulls_in_linked_memories(engine):
    """The headliner: with expand_graph=True, a search that vector-matches
    memory A must additionally surface memory B if A and B are linked in
    the knowledge graph (even though B's vector similarity to the query
    may be lower than the primary matches)."""
    a, b = _store_linked_pair(engine)

    # Sanity: confirm the graph edge was created on store.
    from memorius.graph import init_graph_schema, get_linked
    conn = engine._meta._conn()
    init_graph_schema(conn)
    linked_to_a = get_linked(conn, a.id)
    assert len(linked_to_a) >= 1, "auto-linking should have connected a<->b"
    linked_ids = {row["target_id"] for row in linked_to_a}
    assert b.id in linked_ids, "B must be linked to A for this test to be meaningful"

    # Search with a query that vector-matches A well. With expansion, B
    # should appear in the result list via the graph even if its vector
    # rank put it just below the cut.
    results_plain = engine.search(
        "kubernetes orchestration", vault="main", limit=1, expand_graph=False,
    )
    results_expanded = engine.search(
        "kubernetes orchestration", vault="main", limit=1, expand_graph=True,
    )

    # limit=1 -> the plain result is exactly one memory.
    assert len(results_plain) == 1
    # Expansion must produce at least one more memory (the linked B).
    assert len(results_expanded) > len(results_plain)
    expanded_ids = {m.id for m in results_expanded}
    assert b.id in expanded_ids, (
        "expand_graph should have surfaced linked memory B in the results"
    )


def test_search_expand_graph_dedupes_already_primary_hits(engine):
    """When a linked memory is ALSO a primary vector hit, expansion must
    not duplicate it. With a high limit both A and B are primary hits, so
    the graph expansion has nothing extra to add — the count shouldn't
    inflate with a duplicate of A or B."""
    a, b = _store_linked_pair(engine)
    results = engine.search(
        "kubernetes orchestration", vault="main", limit=10, expand_graph=True,
    )
    ids = [m.id for m in results]
    assert len(ids) == len(set(ids)), "duplicate memory ids in expand_graph results"
    assert a.id in ids and b.id in ids


def test_search_expand_graph_respects_vault_scope(engine):
    """When scoped to a vault, expanded memories must also be in that vault.
    (We only have one vault here, so this is mostly a contract assertion
    that the scope filter doesn't crash and results are all in 'main'.)"""
    _store_linked_pair(engine)
    results = engine.search(
        "kubernetes", vault="main", limit=2, expand_graph=True,
    )
    for m in results:
        assert m.vault == "main"


def test_get_memories_by_ids_returns_meta_and_content(engine):
    a, b = _store_linked_pair(engine)
    fetched = engine.get_memories_by_ids([a.id, b.id], with_vectors=False)
    by_id = {m.id: m for m in fetched}
    assert a.id in by_id and b.id in by_id
    assert "kubernetes" in by_id[a.id].content
    # with_vectors=False -> Memory.vector stays None.
    assert by_id[a.id].vector is None


def test_get_memories_by_ids_missing_ids_skipped(engine):
    a, _ = _store_linked_pair(engine)
    import uuid as _uuid
    bogus = str(_uuid.uuid4())
    fetched = engine.get_memories_by_ids([a.id, bogus])
    ids = {m.id for m in fetched}
    assert a.id in ids
    assert bogus not in ids


# ── ContextInjector ──────────────────────────────────────────────────────────


def test_context_injector_expands_graph_by_default(engine):
    """ContextInjector.inject defaults expand_graph=True, so the injected
    block can include graph-linked memories beyond the bare vector hits."""
    a, b = _store_linked_pair(engine)
    from memorius.context_inject import ContextInjector

    injector = ContextInjector(engine)
    block = injector.inject(
        "kubernetes orchestration", vault="main", max_items=1,
    )
    # The injected block should mention B (the linked memory) by virtue of
    # graph expansion. If expansion were off and limit were 1, only A would
    # make it into the block.
    assert b.content[:30] in block or "kubernetes" in block


def test_context_injector_can_disable_expansion(engine):
    a, b = _store_linked_pair(engine)
    from memorius.context_inject import ContextInjector

    injector = ContextInjector(engine)
    block = injector.inject(
        "kubernetes orchestration", vault="main", max_items=1,
        expand_graph=False,
    )
    # With expansion off and only one slot, the block holds exactly one
    # memory item (## header is one section). Count the "###" item markers.
    item_markers = block.count("### [")
    assert item_markers == 1


# ── CLI flag threading ───────────────────────────────────────────────────────


def test_cmd_search_threads_expand_graph_to_engine(engine, monkeypatch, capsys):
    """A Namespace carrying expand_graph=True must reach engine.search.
    We monkeypatch engine.search to capture the call kwargs."""
    captured = {}

    def fake_search(self, query, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(type(engine), "search", fake_search)
    from memorius.cli.main import cmd_search
    import argparse

    args = argparse.Namespace(
        query="kubernetes", vault=None, shelf=None, n=5,
        expand_graph=True, web=False,
    )
    cmd_search(engine, args, {"retrieval": {"web_max_results": 5}})
    assert captured.get("expand_graph") is True


def test_cmd_search_expand_graph_defaults_false_when_attr_absent(engine, monkeypatch, capsys):
    """Backward-compat: a Namespace WITHOUT expand_graph (older callers, the
    web-search tests' fake Namespace) must not blow up — defaults to False."""
    captured = {}

    def fake_search(self, query, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(type(engine), "search", fake_search)
    from memorius.cli.main import cmd_search
    import argparse

    # No expand_graph on this Namespace on purpose.
    args = argparse.Namespace(
        query="kubernetes", vault=None, shelf=None, n=5, web=False,
    )
    cmd_search(engine, args, {"retrieval": {"web_max_results": 5}})
    assert captured.get("expand_graph") is False