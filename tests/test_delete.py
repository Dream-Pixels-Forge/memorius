"""Tests for the delete command: validation, engine.delete, and CLI."""

import builtins
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def engine():
    """Create a VaultEngine with isolated temp storage per test."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.vault import VaultEngine
    from memorius.config import load_config
    config = load_config()
    eng = VaultEngine(config)
    yield eng
    shutil.rmtree(tmp, ignore_errors=True)
    if hasattr(eng, "_vector") and hasattr(eng._vector, "_client"):
        try:
            eng._vector._client = None
        except Exception:
            pass


def _make_engine():
    """Build a VaultEngine against an isolated temp store (mirrors test_core)."""
    tmp = tempfile.mkdtemp()
    os.environ["MEMORIUS_STORAGE_PATH"] = tmp
    from memorius.vault import VaultEngine
    from memorius.config import load_config
    return VaultEngine(load_config()), tmp


# ── Validation ────────────────────────────────────────────────────────────────


def test_validate_memory_id_accepts_uuid():
    from memorius.validation import validate_memory_id
    valid = "c397ab29-e288-4cf4-a8da-69e48415bebb"
    assert validate_memory_id(valid) == valid


def test_validate_memory_id_rejects_bad_input():
    from memorius.validation import validate_memory_id
    for bad in ("", "   ", None, "not-a-uuid", "../etc/passwd", "12345"):
        with pytest.raises(ValueError):
            validate_memory_id(bad)


# ── Engine.delete ─────────────────────────────────────────────────────────────


def test_delete_removes_memory(engine):
    m = engine.store("Delete me: a unique test memory about zebras", vault="del")
    assert engine.meta.get_memory_meta(m.id) is not None

    result = engine.delete(m.id)
    assert result["deleted"] is True
    assert result["found"] is True
    assert result["memory_id"] == m.id
    # metadata gone
    assert engine.meta.get_memory_meta(m.id) is None
    # no longer searchable
    hits = [r for r in engine.search("unique test memory about zebras", vault="del")
            if r.id == m.id]
    assert hits == []


def test_delete_dry_run_does_not_delete(engine):
    m = engine.store("Dry run target memory about giraffes", vault="del")
    result = engine.delete(m.id, dry_run=True)
    assert result["deleted"] is False
    assert result["found"] is True
    assert engine.meta.get_memory_meta(m.id) is not None


def test_delete_missing_memory(engine):
    result = engine.delete("11111111-1111-1111-1111-111111111111")
    assert result["found"] is False
    assert result["deleted"] is False


def test_delete_vault_mismatch_raises(engine):
    m = engine.store("Mismatch memory content", vault="del")
    with pytest.raises(ValueError):
        engine.delete(m.id, vault="other")
    # still present after a failed scoped delete
    assert engine.meta.get_memory_meta(m.id) is not None


def test_delete_cleans_graph_edges(engine):
    a = engine.store("Python is a programming language used widely", vault="del")
    b = engine.store("Python programming is fun and widely used", vault="del")
    conn = engine.meta._conn()
    before = conn.execute(
        "SELECT COUNT(*) FROM memory_graph WHERE source_id = ? OR target_id = ?",
        (a.id, a.id),
    ).fetchone()[0]
    engine.delete(a.id)
    after = conn.execute(
        "SELECT COUNT(*) FROM memory_graph WHERE source_id = ? OR target_id = ?",
        (a.id, a.id),
    ).fetchone()[0]
    # If the two were linked, deletion must remove those edges.
    assert after == 0
    # The surviving memory is untouched.
    assert engine.meta.get_memory_meta(b.id) is not None
    # (before may be 0 if proximity linking didn't trigger — that's fine)


# ── CLI ───────────────────────────────────────────────────────────────────────


def _run_cli(argv):
    from memorius.cli.main import main
    sys.argv = ["memorius"] + argv
    main()


def test_cli_delete_dry_run(capsys):
    eng, tmp = _make_engine()
    try:
        m = eng.store("CLI dry run target about otters", vault="del")
        _run_cli(["delete", m.id, "--dry-run"])
        out = capsys.readouterr().out
        assert "dry-run" in out
        assert eng.meta.get_memory_meta(m.id) is not None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_delete_with_yes(capsys):
    eng, tmp = _make_engine()
    try:
        m = eng.store("CLI yes delete target about lynx", vault="del")
        _run_cli(["delete", m.id, "--yes"])
        out = capsys.readouterr().out
        assert "Deleted" in out
        assert eng.meta.get_memory_meta(m.id) is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_delete_confirm_prompt(monkeypatch, capsys):
    eng, tmp = _make_engine()
    try:
        m = eng.store("CLI confirm prompt target about tigers", vault="del")
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "y")
        _run_cli(["delete", m.id])
        out = capsys.readouterr().out
        assert "Deleted" in out
        assert eng.meta.get_memory_meta(m.id) is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_delete_abort_on_no(monkeypatch, capsys):
    eng, tmp = _make_engine()
    try:
        m = eng.store("CLI abort target about bears", vault="del")
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "n")
        _run_cli(["delete", m.id])
        out = capsys.readouterr().out
        assert "Aborted" in out
        assert eng.meta.get_memory_meta(m.id) is not None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_delete_invalid_id(capsys):
    eng, tmp = _make_engine()
    try:
        _run_cli(["delete", "not-a-uuid"])
        out = capsys.readouterr().out
        assert "Error" in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
