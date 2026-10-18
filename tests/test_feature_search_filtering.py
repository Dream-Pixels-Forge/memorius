"""Feature tests for metadata/tag filtering in search (Phase 1.3).

Verifies that:
- engine.search(folder=...) restricts results to that folder via the Chroma
  `where` clause.
- engine.search(note=...) restricts to that note.
- engine.search(tags=[...]) post-filters to memories carrying ALL the
  supplied tags (Chroma can't test list membership, so this is done in
  Python over the over-fetched hit set).
- folder + tags combine (conjunction).
- Filtering is a no-op when none of the filters are supplied (backward
  compat with the pre-1.3 API).
- REST /search threads the folder/note/tags payload keys to the engine.
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
            eng._vector._client = None  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
        except Exception:
            pass


def _seed(engine):
    """Seed a vault with memories in two folders, some tagged.

    Folder "alpha":  about rainbows (tagged visible), about gravity.
    Folder "beta":   about rainbows (tagged visible).

    All three share enough vocabulary that an unfiltered "rainbow" search
    would return all of them; filters let us narrow to a specific folder
    or a specific tag set."""
    engine.store(
        "rainbow has seven colors red orange yellow green blue indigo violet",
        vault="main", shelf="s1", folder="alpha", note="n1",
        metadata={"tags": ["visible", "optics"]},
    )
    engine.store(
        "gravity pulls masses together according to newton and einstein",
        vault="main", shelf="s1", folder="alpha", note="n2",
        metadata={"tags": ["physics"]},
    )
    engine.store(
        "rainbow forms when sunlight refracts through raindrops in the air",
        vault="main", shelf="s1", folder="beta", note="n3",
        metadata={"tags": ["visible", "weather"]},
    )


# ── Engine: folder / note / tags filtering ──────────────────────────────────


def test_search_without_filters_returns_all_matching(engine):
    _seed(engine)
    results = engine.search("rainbow", vault="main", limit=10)
    # No filter -> both rainbow memories (alpha + beta) must appear. The
    # gravity memory may also surface (a 3-memory vault over-fetches), but
    # both rainbow hits MUST be present -- which is the contract this test
    # pins (filters compose ON TOP of this unfiltered baseline).
    rainbow_hits = [m for m in results if m.content.startswith("rainbow")]
    assert len(rainbow_hits) == 2, (
        f"unfiltered search should return both rainbow memories, got {len(rainbow_hits)}"
    )


def test_search_folder_filter_restricts_to_one_folder(engine):
    _seed(engine)
    results = engine.search("rainbow", vault="main", limit=10, folder="alpha")
    assert results, "folder=alpha should still return the rainbow memory there"
    for m in results:
        assert m.folder == "alpha", (
            f"folder filter leaked a non-alpha memory: {m.folder!r}"
        )
    # Only the alpha rainbow memory should be present; the beta one must be gone.
    rainbow_hits = [m for m in results if m.content.startswith("rainbow")]
    assert len(rainbow_hits) == 1
    assert rainbow_hits[0].folder == "alpha"


def test_search_note_filter_restricts_to_one_note(engine):
    _seed(engine)
    results = engine.search("rainbow", vault="main", limit=10, note="n3")
    assert results, "note=n3 should return the rainbow memory there"
    for m in results:
        assert m.note == "n3"


def test_search_tags_filter_requires_all_tags(engine):
    _seed(engine)
    # A memory carries exactly ["visible", "optics"] (alpha rainbow) and
    # ["visible", "weather"] (beta rainbow). Requiring both 'visible' and
    # 'optics' should leave only the alpha rainbow.
    results = engine.search(
        "rainbow", vault="main", limit=10, tags=["visible", "optics"],
    )
    assert results, "tags filter should leave the alpha rainbow memory"
    for m in results:
        md_tags = m.metadata.get("tags") or []
        assert "visible" in md_tags
        assert "optics" in md_tags


def test_search_tags_filter_no_match_returns_empty(engine):
    _seed(engine)
    results = engine.search(
        "rainbow", vault="main", limit=10, tags=["nonexistent-tag"],
    )
    assert results == [], "a tag no memory carries should drop all results"


def test_search_folder_and_tags_combine(engine):
    """folder restricts via Chroma where; tags post-filter in Python.
    Together they should narrow correctly."""
    _seed(engine)
    results = engine.search(
        "rainbow", vault="main", limit=10, folder="beta", tags=["visible"],
    )
    assert results, "beta folder + visible tag should leave the beta rainbow"
    for m in results:
        assert m.folder == "beta"
        assert "visible" in (m.metadata.get("tags") or [])


def test_search_invalid_folder_name_raises(engine):
    """folder is a validated name field; a name with spaces must reject
    early (consistent with vault/store/shelf validation)."""
    from memorius.validation import validate_name

    _seed(engine)
    with pytest.raises(ValueError):
        engine.search("rainbow", vault="main", limit=10, folder="bad folder!")


# ── REST wires the new keys ──────────────────────────────────────────────────


def test_rest_search_threads_folder_filter():
    """REST /search must pass payload.folder through to engine.search as a
    folder filter. We assert by behavior, not by inspecting the call."""
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
    _seed(eng)
    api = MemoriusAPI(eng)
    client = TestClient(api.create_app(), raise_server_exceptions=False)
    try:
        r = client.post(
            "/search",
            json={"query": "rainbow", "vault": "main", "folder": "alpha"},
            headers={"Authorization": "Bearer secret"},
        )
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert results, "folder=alpha via REST should return the alpha rainbow"
        for m in results:
            assert m["folder"] == "alpha"
    finally:
        eng.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_rest_search_threads_tags_filter():
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
    _seed(eng)
    api = MemoriusAPI(eng)
    client = TestClient(api.create_app(), raise_server_exceptions=False)
    try:
        r = client.post(
            "/search",
            json={"query": "rainbow", "vault": "main",
                  "tags": ["visible", "optics"]},
            headers={"Authorization": "Bearer secret"},
        )
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert results, "tags=[visible,optics] should keep the alpha rainbow"
        for m in results:
            tags = m["metadata"].get("tags") or []
            assert "visible" in tags
    finally:
        eng.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_vault_only_search_no_cross_vault_leakage(engine):
    """Vault-only search (without shelf) should not leak memories from other vaults.
    
    This test addresses the issue where memorius_search ignored vault filter
    when shelf was omitted, causing cross-vault data leakage.
    """
    # Create memories in two different vaults
    engine.store("alpha vault memory content", vault="vault_alpha", shelf="shelf_alpha")
    engine.store("beta vault memory content", vault="vault_beta", shelf="shelf_beta")
    
    # Also create some memories in each vault with different shelves to ensure
    # we're testing vault-only (not vault-and-shelf) search
    engine.store("alpha vault another memory", vault="vault_alpha", shelf="shelf_alpha2")
    engine.store("beta vault another memory", vault="vault_beta", shelf="shelf_beta2")
    
    # Search for "alpha" in vault_alpha only (no shelf specified)
    results = engine.search("alpha", vault="vault_alpha", limit=10)
    
    # Should only return memories from vault_alpha
    assert len(results) >= 2  # At least the two alpha memories we stored
    for mem in results:
        assert mem.vault == "vault_alpha", f"Found memory from wrong vault: {mem.vault}"
        assert "alpha" in mem.content.lower()
    
    # Verify no memories from vault_beta are present
    beta_memories = [mem for mem in results if mem.vault == "vault_beta"]
    assert len(beta_memories) == 0, f"Found {len(beta_memories)} memories from vault_beta in vault_alpha search"
    
    # Similarly, search for "beta" in vault_beta only
    results = engine.search("beta", vault="vault_beta", limit=10)
    
    # Should only return memories from vault_beta
    assert len(results) >= 2  # At least the two beta memories we stored
    for mem in results:
        assert mem.vault == "vault_beta", f"Found memory from wrong vault: {mem.vault}"
        assert "beta" in mem.content.lower()
    
    # Verify no memories from vault_alpha are present
    alpha_memories = [mem for mem in results if mem.vault == "vault_alpha"]
    assert len(alpha_memories) == 0, f"Found {len(alpha_memories)} memories from vault_alpha in vault_beta search"
    
    # Test edge case: search in non-existent vault should return empty results
    results = engine.search("nonexistent", vault="vault_nonexistent", limit=10)
    assert len(results) == 0, "Search in non-existent vault should return empty results"