"""Regression tests for verified bugs fixed in the 0.4.5 hardening pass.

Each test pins one specific bug from the review so it cannot silently return.

  Bug 1 — SQLiteStore thread-local connection cross-talk between engines
  Bug 3 — ChromaDB collection-name collisions / length / parsing
  Bug 4 — REST auth + rate-limit middleware returning 500 instead of 401/429
  Bug 5 — Search ranking using a fabricated similarity (no real distances)
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


# ── Bug 1: SQLiteStore instances with different DB paths must not share a connection ──


def test_sqlite_store_no_connection_crosstalk_between_paths():
    """Two SQLiteStore instances with different db paths in the same thread
    must keep their data isolated. Before the fix, both shared one
    thread-local connection keyed to whichever path connected first."""
    from memorius.meta_store import SQLiteStore

    d1 = Path(tempfile.mkdtemp())
    d2 = Path(tempfile.mkdtemp())
    try:
        s1 = SQLiteStore(d1)
        s2 = SQLiteStore(d2)

        s1.ensure_vault("vault_from_s1")

        # s2 must NOT see vaults written to s1's database.
        s2_vaults = [v["name"] for v in s2.list_vaults()]
        assert "vault_from_s1" not in s2_vaults, (
            "SQLiteStore connection cross-talk: s2 sees s1's data"
        )

        # And a vault written via s2 must NOT appear in s1.
        s2.ensure_vault("vault_from_s2")
        s1_vaults = [v["name"] for v in s1.list_vaults()]
        assert "vault_from_s2" not in s1_vaults

        # sanity: each store sees its own vault
        assert "vault_from_s1" in [v["name"] for v in s1.list_vaults()]
        assert "vault_from_s2" in [v["name"] for v in s2.list_vaults()]
    finally:
        s1.close()
        s2.close()
        shutil.rmtree(d1, ignore_errors=True)
        shutil.rmtree(d2, ignore_errors=True)


# ── Bug 3: Chroma collection-name scheme must be collision-free and length-safe ──


def test_collection_name_namespaced_safe():
    """vault 'my-vault' and 'my_vault' must NOT collide into one collection."""
    from memorius.vector_store import ChromaStore

    cs = ChromaStore.__new__(ChromaStore)
    n1 = cs._collection_name("my-vault", "science")
    n2 = cs._collection_name("my_vault", "science")
    assert n1 != n2, (
        f"collection-name collision: both map to {n1!r} -> cross-vault data mixing"
    )


def test_collection_name_within_chroma_length_limit():
    """Even max-length valid names (validate_name allows up to 1000 chars)
    must produce a collection name within ChromaDB's 63-char limit."""
    from memorius.vector_store import ChromaStore

    cs = ChromaStore.__new__(ChromaStore)
    name = cs._collection_name("a" * 100, "b" * 100)
    assert len(name) <= 63, (
        f"collection name too long for ChromaDB: {len(name)} chars (limit 63)"
    )


def test_collection_name_for_underscore_bearing_vault_is_unambiguous():
    """A vault name containing an underscore must not be misparsed on the
    way back out (the legacy split-on-first-_ scheme would report
    vault='my' for 'my_vault_science'). The new scheme is bijective."""
    from memorius.vector_store import ChromaStore

    cs = ChromaStore.__new__(ChromaStore)
    name = cs._collection_name("my_vault", "science")
    # The new scheme round-trips by construction (vault/shelf are stored
    # verbatim, length-prefixed). Re-derive and assert the two pieces
    # are recoverable by splitting on the documented prefix markers.
    # Format: v{len(v):03d}_{vault}_s{len(s):03d}_{shelf}
    assert name.startswith("v008_my_vault_s007_science"), name


# ── Bug 4: REST auth + rate-limit middleware must return proper status codes ──


def _rest_client_with_api_key():
    """Build a TestClient against a fresh isolated engine with MEMORIUS_API_KEY set."""
    os.environ["MEMORIUS_API_KEY"] = "secret"
    tmp = tempfile.mkdtemp()
    os.environ["MEMORIUS_STORAGE_PATH"] = tmp
    from memorius.config import _default_config
    from memorius.vault import VaultEngine
    from memorius.rest_server import MemoriusAPI

    cfg = _default_config()
    cfg["storage"]["path"] = tmp
    eng = VaultEngine(cfg)
    api = MemoriusAPI(eng)
    app = api.create_app()
    from fastapi.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)
    return client, eng, tmp


def test_rest_no_api_key_returns_401_not_500():
    client, eng, tmp = _rest_client_with_api_key()
    try:
        r = client.post("/search", json={"query": "x"})
        assert r.status_code == 401, (
            f"expected 401 for missing API key, got {r.status_code}"
        )
    finally:
        eng.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_rest_wrong_api_key_returns_401_not_500():
    client, eng, tmp = _rest_client_with_api_key()
    try:
        r = client.post(
            "/search",
            json={"query": "x"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert r.status_code == 401, (
            f"expected 401 for wrong API key, got {r.status_code}"
        )
    finally:
        eng.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_rest_rate_limit_returns_429_not_500():
    """Hammer /search until the per-IP rate limit trips; expect 429 (not 500)."""
    # Use an api key so we pass auth. Lower the per-IP cap to a tiny number so
    # a handful of calls trips it (the default 500/min can't be reached through
    # the threaded TestClient portal within a sane test timeout).
    os.environ["MEMORIUS_API_KEY"] = "secret"
    tmp = tempfile.mkdtemp()
    os.environ["MEMORIUS_STORAGE_PATH"] = tmp
    from memorius.config import _default_config
    from memorius.vault import VaultEngine
    from memorius.rest_server import MemoriusAPI
    from fastapi.testclient import TestClient

    cfg = _default_config()
    cfg["storage"]["path"] = tmp
    eng = VaultEngine(cfg)
    api = MemoriusAPI(eng)
    api._rate_limit_max = 3
    client = TestClient(api.create_app(), raise_server_exceptions=False)
    try:
        codes = []
        for _ in range(8):
            r = client.post(
                "/search",
                json={"query": "x"},
                headers={"Authorization": "Bearer secret"},
            )
            codes.append(r.status_code)
            if r.status_code == 429:
                break
        assert 429 in codes, (
            f"rate limit never tripped (saw codes {set(codes)}); "
            f"got {codes[-1] if codes else None} on last call"
        )
        assert codes[-1] != 500, "rate-limit failure leaked as 500 (bug 4 regression)"
    finally:
        eng.close()
        shutil.rmtree(tmp, ignore_errors=True)


# ── Bug 5: Search must use real Chroma distances, not a fabricated rank score ──


def test_search_returns_relevant_result_first_and_no_distance_leak(engine):
    """A query semantically close to one stored memory must surface it, and
    the internal '__distance__' marker must not leak into returned metadata."""
    engine.store(
        "Python is a programming language used for web and data work",
        vault="main", shelf="s1",
    )
    engine.store(
        "Paris is the capital of France and sits on the Seine",
        vault="main", shelf="s2",
    )

    results = engine.search("Python language", vault="main", limit=10)
    assert results, "search returned no results"
    # The Python memory must rank first against a "Python language" query.
    assert results[0].content.startswith("Python"), (
        f"expected Python memory first, got: {results[0].content[:60]!r}"
    )
    # The transient distance marker used for scoring must be stripped before
    # results leave the engine.
    for m in results:
        assert "__distance__" not in m.metadata, (
            "internal '__distance__' leaked into returned memory metadata"
        )


def test_search_does_not_use_synthetic_rank_position_similarity(engine):
    """Before the fix, similarity was `max(0.1, 1.0 - rank_pos * 0.05)`, which
    meant the first result always scored 1.0 regardless of how well it
    matched. With real distances, a poor top match must score below 1.0.

    We can't observe the internal score directly, but we can assert that
    ordering is content-driven (not just 'whatever Chroma returned first'):
    store two memories where the less-relevant one is inserted first, then
    confirm the relevant one ranks above it."""
    engine.store("zzz irrelevant filler text about nothing", vault="main", shelf="a")
    engine.store("the user decided to adopt the rust language for the backend",
                 vault="main", shelf="b")

    results = engine.search("rust backend decision", vault="main", limit=2)
    assert len(results) >= 2
    top = results[0].content
    assert "rust" in top.lower(), (
        f"top result should be the rust decision, got: {top[:60]!r}"
    )