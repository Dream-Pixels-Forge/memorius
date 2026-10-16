"""`--json` flag for `memorius stats` / `memorius status`.

Machine-readable output for status-line consumers:
  - single JSON object on stdout, deterministic key order (sort_keys)
  - exit code 0 when checks report warnings (warnings are data)
  - non-zero only on real errors (e.g. store unreadable)
  - text output path (no flag) unchanged

All storage is isolated via tmp_path + MEMORIUS_STORAGE_PATH — no personal
data or absolute paths are hardcoded here.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(argv, capsys):
    """Run the CLI in-process and return everything written to stdout."""
    from memorius.cli.main import main

    sys.argv = ["memorius"] + argv
    main()
    return capsys.readouterr().out


@pytest.fixture
def seeded_engine(tmp_path, monkeypatch):
    """VaultEngine on an isolated store with a little data in it."""
    monkeypatch.setenv("MEMORIUS_STORAGE_PATH", str(tmp_path))
    from memorius.config import load_config
    from memorius.vault import VaultEngine

    eng = VaultEngine(load_config())
    eng.store("memory about harbor lanterns", vault="main")
    eng.store("memory about tide tables", vault="main")
    eng.write_diary(
        session_id="s-1",
        title="Evening log",
        summary="test summary",
        content="test content",
        vault="main",
    )
    yield eng


# ── Cycle 1: the flag exists and is documented ────────────────────────────────


def test_json_flag_documented_in_help(capsys):
    """`stats --help` and `status --help` document the --json flag."""
    from memorius.cli.main import main

    for sub in ("stats", "status"):
        sys.argv = ["memorius", sub, "--help"]
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "--json" in out, f"{sub} --help does not mention --json"
        assert "Output as JSON" in out


def test_store_error_exits_nonzero_without_usage_error(tmp_path):
    """Real errors (store unreadable) exit non-zero — not an argparse usage
    error, and stdout carries no half-baked JSON."""
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    env = {**os.environ, "MEMORIUS_STORAGE_PATH": str(blocker)}
    proc = subprocess.run(
        [sys.executable, "-m", "memorius.cli.main", "stats", "--json"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=120,
    )
    assert proc.returncode != 0, "expected non-zero exit for an unreadable store"
    # must not be argparse rejecting the flag
    assert "unrecognized arguments" not in proc.stderr
    # stdout must not contain a valid JSON document (empty is fine)
    with pytest.raises(json.JSONDecodeError):
        json.loads(proc.stdout)


# ── Cycle 2: stats --json emits the full stat set ─────────────────────────────


def test_stats_json_core_keys(capsys, seeded_engine):
    """`stats --json` writes a single JSON object with the stat set the text
    output shows — and nothing else on stdout."""
    out = _run_cli(["stats", "--json"], capsys)
    assert out.lstrip().startswith("{")
    data = json.loads(out)  # entire stdout must be one JSON document
    assert isinstance(data, dict)

    assert set(data) >= {"vaults", "memories", "embedding", "memory_stats", "graph"}
    assert data["vaults"] == 1
    assert data["memories"] == 2

    assert set(data["embedding"]) == {"provider", "dimension"}
    assert isinstance(data["embedding"]["provider"], str) and data["embedding"]["provider"]
    assert isinstance(data["embedding"]["dimension"], int)

    ms = data["memory_stats"]
    assert set(ms) == {"total", "active", "archived", "by_vault"}
    assert ms["total"] == 2
    assert ms["active"] == 2
    assert ms["archived"] == 0
    assert ms["by_vault"] == {"main": 2}

    g = data["graph"]
    assert set(g) >= {"nodes", "edges", "relations"}
    assert isinstance(g["nodes"], int)
    assert isinstance(g["edges"], int)
    assert isinstance(g["relations"], dict)


# ── Cycle 3: doctor health summary + last-diary recency ───────────────────────


def test_stats_json_doctor_summary_and_diary_recency(capsys, seeded_engine):
    """`stats --json` carries the doctor health summary (per-check name →
    status + warning count) and the last diary's ISO timestamp."""
    out = _run_cli(["stats", "--json"], capsys)
    data = json.loads(out)
    assert set(data) >= {"doctor", "diary"}

    doc = data["doctor"]
    assert set(doc) == {"checks", "healthy", "warnings"}
    assert isinstance(doc["checks"], dict)
    assert "config" in doc["checks"]
    assert all(s in {"ok", "warn", "fail", "skip"} for s in doc["checks"].values())
    assert isinstance(doc["healthy"], bool)
    assert isinstance(doc["warnings"], int)
    assert doc["warnings"] == sum(1 for s in doc["checks"].values() if s == "warn")

    diary = data["diary"]
    assert set(diary) == {"last_created_at"}
    assert diary["last_created_at"] is not None
    datetime.fromisoformat(diary["last_created_at"])  # ISO timestamp


def test_warnings_do_not_affect_exit_code(tmp_path, monkeypatch):
    """Doctor warnings are data: exit code stays 0 and the warning count is
    present in the JSON."""
    # Seed a real warning: memory_meta row without a vector (drift).
    monkeypatch.setenv("MEMORIUS_STORAGE_PATH", str(tmp_path))
    from memorius.config import load_config
    from memorius.vault import VaultEngine

    eng = VaultEngine(load_config())
    eng.store("drift seed memory", vault="main")
    conn = eng._meta._conn()
    conn.execute(
        "INSERT INTO memory_meta (id, vault, shelf, folder, note, content, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("fake-id-1234", "main", "default", "default", "default",
         "phantom", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.commit()

    proc = subprocess.run(
        [sys.executable, "-m", "memorius.cli.main", "stats", "--json"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ},
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"warnings must not fail the command; rc={proc.returncode}\n{proc.stderr}"
    )
    data = json.loads(proc.stdout)
    assert data["doctor"]["warnings"] >= 1
    assert data["doctor"]["checks"]["vector_count_match"] == "warn"


# ── Cycle 4: status --json ────────────────────────────────────────────────────


def test_status_json_subset_keys(capsys, seeded_engine):
    """`status --json` covers what the text status shows: vaults, memories,
    embeddings, and recent diaries (trimmed to recency fields)."""
    out = _run_cli(["status", "--json"], capsys)
    data = json.loads(out)
    assert set(data) == {"vaults", "memories", "embedding", "diaries"}
    assert data["vaults"] == 1
    assert data["memories"] == 2
    assert set(data["embedding"]) == {"provider", "dimension"}

    diaries = data["diaries"]
    assert isinstance(diaries, list)
    assert len(diaries) >= 1
    d0 = diaries[0]
    assert set(d0) == {"created_at", "session_id", "title"}
    datetime.fromisoformat(d0["created_at"])
    assert d0["session_id"] == "s-1"


# ── Cycle 5: deterministic output (snapshot-test friendly) ─────────────────────


def _assert_sorted_keys(obj):
    """Recursively assert every dict's keys are in sorted order."""
    if isinstance(obj, dict):
        keys = list(obj.keys())
        assert keys == sorted(keys), f"keys not sorted: {keys}"
        for v in obj.values():
            _assert_sorted_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            _assert_sorted_keys(v)


def test_json_output_sorted_and_deterministic(capsys, seeded_engine):
    """Two consecutive runs produce byte-identical output; keys are sorted
    at every level so snapshots are stable."""
    a1 = _run_cli(["stats", "--json"], capsys)
    a2 = _run_cli(["stats", "--json"], capsys)
    b1 = _run_cli(["status", "--json"], capsys)
    b2 = _run_cli(["status", "--json"], capsys)

    assert a1 == a2, "stats --json output differs between runs"
    assert b1 == b2, "status --json output differs between runs"

    _assert_sorted_keys(json.loads(a1))
    _assert_sorted_keys(json.loads(b1))


# ── Cycle 6: README documentation ─────────────────────────────────────────────


def test_readme_documents_json_flag():
    """The README's CLI Reference documents --json for stats and status."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    cli_section = readme.split("## CLI Reference", 1)[1]
    assert re.search(
        r"memorius stats\s+Show vault \+ memory \+ graph statistics\n\s+--json",
        cli_section,
    ), "README CLI Reference: stats is missing its --json line"
    assert re.search(
        r"memorius status\s+Show vault status\n\s+--json",
        cli_section,
    ), "README CLI Reference: status is missing its --json line"
