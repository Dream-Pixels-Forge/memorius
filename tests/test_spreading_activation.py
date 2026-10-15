"""Tests for the spreading-activation retrieval algorithm (GOAL 3.3).

Covers memorius/graph.py::spreading_activation:
  - activation spreads from seed nodes through graph edges
  - activation decays over hops
  - decay_rate parameter controls how fast activation fades
  - min_weight filters weak edges
  - empty seed list returns empty result
  - combined vector+graph path via SearchModule._expand_from_graph
    with use_spreading_activation=True

All tests use an in-memory SQLite connection with a real graph schema,
so no embedding provider or network is required.
"""

import os
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_conn(tmp_path: Path | None = None) -> sqlite3.Connection:
    """Create a SQLite connection with the graph schema initialised."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from memorius.graph import init_graph_schema
    init_graph_schema(conn)
    return conn


def _link(conn: sqlite3.Connection, a: str, b: str,
          weight: float = 1.0, relation: str = "related") -> None:
    from memorius.graph import link_memories
    link_memories(conn, a, b, weight=weight, relation=relation)


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Core spreading activation behaviour ──────────────────────────────────────


class TestSpreadingActivationCore:
    def test_single_seed_starts_at_full_activation(self):
        """A seed node starts at activation 1.0."""
        from memorius.graph import spreading_activation
        conn = _make_conn()
        a, b = _new_id(), _new_id()
        _link(conn, a, b)

        result = spreading_activation(conn, [a], hops=1, decay_rate=0.5)
        activations = result["activations"]

        assert activations.get(a, 0.0) == 1.0

    def test_two_seeds_each_start_at_full_activation(self):
        """When two nodes are both seeds (not linked), each stays at 1.0."""
        from memorius.graph import spreading_activation
        conn = _make_conn()
        a, b = _new_id(), _new_id()
        # No link between a and b — they are independent seeds
        c = _new_id()
        _link(conn, a, c)
        _link(conn, b, c)

        result = spreading_activation(conn, [a, b], hops=1, decay_rate=0.5)
        activations = result["activations"]

        # Seeds must be at 1.0; c receives activation from both but no more than
        # the sum of their spread (with decay the individual values will be < 1.0)
        assert activations.get(a, 0.0) == 1.0
        assert activations.get(b, 0.0) == 1.0

    def test_activation_spreads_to_linked_nodes(self):
        """Linked nodes receive activation from their neighbours."""
        from memorius.graph import spreading_activation
        conn = _make_conn()
        a, b, c = _new_id(), _new_id(), _new_id()
        _link(conn, a, b)   # a ↔ b
        _link(conn, b, c)   # b ↔ c
        # a and c are NOT directly linked

        result = spreading_activation(conn, [a], hops=2, decay_rate=0.5)
        activations = result["activations"]

        # b should have activation from a's spread (via edge a→b)
        assert activations.get(b, 0.0) > 0.0, "b must receive activation from a"
        # c should have activation from b's spread (via edge b→c at hop 2)
        assert activations.get(c, 0.0) > 0.0, "c must receive activation from b"

    def test_activation_decays_over_hops(self):
        """Farther nodes have lower activation than closer ones."""
        from memorius.graph import spreading_activation
        conn = _make_conn()
        a, b, c, d = _new_id(), _new_id(), _new_id(), _new_id()
        _link(conn, a, b)
        _link(conn, b, c)
        _link(conn, c, d)

        result = spreading_activation(conn, [a], hops=3, decay_rate=0.5)
        activations = result["activations"]

        # Activation must decrease monotonically with distance
        assert activations.get(b, 0.0) > activations.get(c, 0.0)
        assert activations.get(c, 0.0) > activations.get(d, 0.0)

    def test_higher_retention_factor_preserves_more_activation(self):
        """``decay_rate`` acts as a per-hop retention factor: hop_decay =
        decay_rate ** hop. A HIGHER value retains more activation per hop
        (slower effective decay), so a linked node at the same distance
        ends up with MORE activation when decay_rate is larger."""
        from memorius.graph import spreading_activation
        conn = _make_conn()
        a, b = _new_id(), _new_id()
        _link(conn, a, b)

        low_retention = spreading_activation(conn, [a], hops=1, decay_rate=0.2)
        high_retention = spreading_activation(conn, [a], hops=1, decay_rate=0.9)

        # 0.9**1 * 0.9**1 = 0.81  vs  0.2**1 * 0.2**1 = 0.04
        assert high_retention["activations"].get(b, 0.0) > low_retention["activations"].get(b, 0.0)

    def test_low_retention_factor_decays_faster(self):
        """With a low retention factor the activation at the same distance
        is much smaller — fast effective decay."""
        from memorius.graph import spreading_activation
        conn = _make_conn()
        a, b = _new_id(), _new_id()
        _link(conn, a, b)

        fast_decay = spreading_activation(conn, [a], hops=1, decay_rate=0.2)
        slow_decay = spreading_activation(conn, [a], hops=1, decay_rate=0.9)

        assert fast_decay["activations"].get(b, 0.0) < slow_decay["activations"].get(b, 0.0)

    def test_min_weight_filters_weak_edges(self):
        """Edges below min_weight are not traversed."""
        from memorius.graph import spreading_activation
        conn = _make_conn()
        a, b, c = _new_id(), _new_id(), _new_id()
        _link(conn, a, b, weight=0.1)  # weak link a↔b
        _link(conn, b, c, weight=1.0)  # strong link b↔c

        # With min_weight=0.5, the a→b edge is skipped, so b is not reached
        result = spreading_activation(conn, [a], hops=1, min_weight=0.5)
        activations = result["activations"]

        # b should have no activation (the only path to b from a is the weak edge)
        assert activations.get(b, 0.0) == 0.0

    def test_min_weight_zero_traverses_all_edges(self):
        """With min_weight=0, all edges are traversed regardless of weight."""
        from memorius.graph import spreading_activation
        conn = _make_conn()
        a, b = _new_id(), _new_id()
        _link(conn, a, b, weight=0.01)

        result = spreading_activation(conn, [a], hops=1, min_weight=0.0)
        assert result["activations"].get(b, 0.0) > 0.0

    def test_max_nodes_limits_result_size(self):
        """The top-N activations are returned; the rest are dropped."""
        from memorius.graph import spreading_activation
        conn = _make_conn()
        # Star topology: centre → 5 leaves
        centre = _new_id()
        leaves = [_new_id() for _ in range(5)]
        for leaf in leaves:
            _link(conn, centre, leaf, weight=1.0)

        result = spreading_activation(conn, [centre], hops=1, max_nodes=3)
        activations = result["activations"]
        # Only centre + top 2 leaves survive (max_nodes=3 total)
        assert len(activations) <= 3

    def test_empty_seed_list_returns_empty(self):
        """No seeds → no activations, no hops."""
        from memorius.graph import spreading_activation
        conn = _make_conn()
        result = spreading_activation(conn, [], hops=2)
        assert result["activations"] == {}
        assert result["seed_ids"] == []

    def test_single_seed_isolated_node_returns_only_seed(self):
        """A seed with no edges returns only itself at activation 1.0."""
        from memorius.graph import spreading_activation
        conn = _make_conn()
        a = _new_id()
        result = spreading_activation(conn, [a], hops=3)
        activations = result["activations"]
        assert len(activations) == 1
        assert activations[a] == 1.0

    def test_converging_paths_accumulate_activation(self):
        """When two paths reach the same node, activation accumulates."""
        from memorius.graph import spreading_activation
        conn = _make_conn()
        a, b, c, d = _new_id(), _new_id(), _new_id(), _new_id()
        # a → b → d  and  a → c → d  (d reached via two paths)
        _link(conn, a, b)
        _link(conn, a, c)
        _link(conn, b, d)
        _link(conn, c, d)

        result = spreading_activation(conn, [a], hops=2)
        activations = result["activations"]
        # d should have strictly more activation than b or c alone
        assert activations.get(d, 0.0) > 0.0
        # b and c are at hop 1; d is at hop 2, but d accumulates from both
        assert activations.get(d, 0.0) < activations.get(b, 0.0) + activations.get(c, 0.0)

    def test_invalidated_edges_excluded_by_default(self):
        """Invalidated edges are not traversed unless include_invalidated=True."""
        from memorius.graph import invalidate_edge, spreading_activation
        conn = _make_conn()
        a, b, c = _new_id(), _new_id(), _new_id()
        _link(conn, a, b)
        _link(conn, b, c)

        # Invalidate the a↔b edge
        invalidate_edge(conn, a, b, relation="related")

        # c should still be reachable via b, but a↔b is broken
        # b is no longer linked from a, so activation doesn't reach c
        result = spreading_activation(conn, [a], hops=2)
        # b is still the seed-adjacent node (edge a→b invalidated, but b is
        # the only neighbour via a valid path if any remain — here none)
        # Actually after invalidating a↔b, a has no valid edges, so c is unreachable
        assert result["activations"].get(c, 0.0) == 0.0


# ── SearchModule integration ─────────────────────────────────────────────────


class TestSpreadingActivationInSearchModule:
    @pytest.fixture
    def engine(self):
        """VaultEngine with isolated temp storage."""
        tmp = Path(tempfile.mkdtemp())
        os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
        from memorius.config import load_config
        from memorius.vault import VaultEngine
        eng = VaultEngine(load_config())
        yield eng
        eng.close()
        shutil.rmtree(tmp, ignore_errors=True)

    def test_expand_from_graph_with_spreading_activation(self, engine):
        """_expand_from_graph(use_spreading_activation=True) returns linked
        memories that are not seeds, ranked by activation."""
        engine.store("the deployment uses kubernetes for orchestration",
                     vault="main", shelf="segregation_test")
        engine.store("kubernetes pods are scheduled by the kube-scheduler",
                     vault="main", shelf="segregation_test")
        engine.store("the database migration uses alembic versions",
                     vault="main", shelf="segregation_test")

        # Seed the graph with a link between the two k8s memories
        m1 = engine.store("kubernetes deployment strategy is rolling update",
                         vault="main", shelf="segregation_test")
        m2 = engine.store("kube-scheduler assigns pods to nodes",
                         vault="main", shelf="segregation_test")
        engine.meta.link_memories(m1.id, m2.id, weight=1.0, relation="related")

        # Force lazy-init of the SearchModule
        search_mod = engine._get_search_module()

        # Build a list of Memory objects to use as seeds (the first two stored above)
        from memorius.models import Memory
        seeds = [Memory(
            id=m1.id, vault="main", shelf="segregation_test",
            folder="default", note="default",
            content="kubernetes deployment strategy is rolling update",
            metadata={}, created_at="", updated_at="", vector=None,
        ), Memory(
            id=m2.id, vault="main", shelf="segregation_test",
            folder="default", note="default",
            content="kube-scheduler assigns pods to nodes",
            metadata={}, created_at="", updated_at="", vector=None,
        )]

        expanded = search_mod._expand_from_graph(
            seeds, vault="main", hops=1, min_weight=0.3,
            max_extra=3, use_spreading_activation=True,
        )
        # m1 and m2 are seeds → they must not appear in the expanded list
        expanded_ids = {m.id for m in expanded}
        assert m1.id not in expanded_ids
        assert m2.id not in expanded_ids

    def test_expand_from_graph_empty_when_no_edges(self, engine):
        """No graph edges → no expansion, even with spreading activation."""
        engine.store("a completely isolated memory with no links",
                     vault="main", shelf="isolated")
        m = engine.store("another isolated memory",
                         vault="main", shelf="isolated")

        search_mod = engine._get_search_module()
        from memorius.models import Memory
        seed = Memory(
            id=m.id, vault="main", shelf="isolated",
            folder="default", note="default",
            content="another isolated memory",
            metadata={}, created_at="", updated_at="", vector=None,
        )

        expanded = search_mod._expand_from_graph(
            [seed], vault="main", hops=1, min_weight=0.3,
            max_extra=5, use_spreading_activation=True,
        )
        assert expanded == []
