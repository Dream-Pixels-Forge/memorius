"""Phase 3.1 — Export / import vault (backup).

Round-trip: store memories → export to JSON → wipe → import → verify
counts and a sample memory's content match.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def engine():
    """VaultEngine against an isolated temp store."""
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
        except Exception:  # noqa: BLE001, S110
            pass


# ── JSON round-trip ──────────────────────────────────────────────────────────

class TestExportImportJSON:
    """Full JSON export → import round-trip."""

    def test_round_trip(self, engine):
        from memorius.backup import export_json, import_json

        # Store some data
        m1 = engine.store("hello world", vault="main", shelf="s1",
                          folder="f1", note="n1", ttl_days=30)
        m2 = engine.store("second memory", vault="main", shelf="s2",
                          folder="f2", note="n2", metadata={"tags": ["a", "b"]})
        # Write a diary
        engine._meta.write_diary(
            session_id="sess-1",
            vault="main",
            title="Test diary",
            summary="Summary",
            content="Dear diary...",
            exchange_count=5,
        )

        # Export
        export_path = Path(tempfile.mkdtemp()) / "backup.json"
        export_json(engine, export_path)
        assert export_path.exists()

        # Verify structure
        with open(export_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["schema_version"] == 1
        assert len(data["memories"]) == 2
        assert len(data["diaries"]) == 1

        # Wipe and re-import
        # (We can't easily wipe the engine, so import into a fresh engine)
        from memorius.config import load_config as lc2
        from memorius.vault import VaultEngine as VE2
        tmp2 = Path(tempfile.mkdtemp())
        os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp2)
        engine2 = VE2(lc2())

        stats = import_json(engine2, export_path)
        assert stats["memories_imported"] == 2
        assert stats["memories_skipped"] == 0
        assert stats["diaries_imported"] == 1

        # Verify content round-tripped
        got = engine2.get_memory(m1.id)
        assert got is not None
        assert got.content == "hello world"

        got2 = engine2.get_memory(m2.id)
        assert got2 is not None
        assert got2.content == "second memory"

        # Verify diary
        diaries = engine2._meta.list_diaries()
        assert len(diaries) >= 1
        titles = [d["title"] for d in diaries]
        assert "Test diary" in titles

        shutil.rmtree(tmp2, ignore_errors=True)
        if hasattr(engine2, "_vector") and hasattr(engine2._vector, "_client"):
            try:
                engine2._vector._client = None  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
            except Exception:  # noqa: BLE001, S110
                pass

    def test_import_skip_existing(self, engine):
        """merge=True skips memories already present."""
        from memorius.backup import export_json, import_json

        engine.store("existing mem")
        export_path = Path(tempfile.mkdtemp()) / "skip.json"
        export_json(engine, export_path)

        # Import into same engine (merge=True = skip)
        stats = import_json(engine, export_path, merge=True)
        assert stats["memories_skipped"] == 1
        assert stats["memories_imported"] == 0

    def test_import_replace_existing(self, engine):
        """merge=False overwrites existing memories."""
        from memorius.backup import export_json, import_json

        engine.store("original content")
        export_path = Path(tempfile.mkdtemp()) / "replace.json"
        export_json(engine, export_path)

        # Overwrite in place
        stats = import_json(engine, export_path, merge=False)
        assert stats["memories_imported"] == 1
        assert stats["memories_skipped"] == 0

    def test_empty_vault_round_trip(self, engine):
        from memorius.backup import export_json, import_json

        export_path = Path(tempfile.mkdtemp()) / "empty.json"
        export_json(engine, export_path)

        stats = import_json(engine, export_path)
        assert stats["memories_imported"] == 0
        assert stats["diaries_imported"] == 0

    def test_graph_edges_round_trip(self, engine):
        """Graph edges survive export → import."""
        from memorius.backup import export_json, import_json
        from memorius.graph import init_graph_schema, link_memories

        m1 = engine.store("node one")
        m2 = engine.store("node two")
        conn = engine._meta._conn()
        init_graph_schema(conn)
        link_memories(conn, m1.id, m2.id, weight=0.8, relation="related")
        conn.commit()

        export_path = Path(tempfile.mkdtemp()) / "graph.json"
        export_json(engine, export_path)

        # Import into fresh engine
        from memorius.config import load_config as lc3
        from memorius.vault import VaultEngine as VE3
        tmp3 = Path(tempfile.mkdtemp())
        os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp3)
        engine3 = VE3(lc3())

        stats = import_json(engine3, export_path)
        assert stats["graph_edges_imported"] >= 1

        # Verify edge exists
        conn3 = engine3._meta._conn()
        try:
            row = conn3.execute(
                "SELECT COUNT(*) FROM memory_graph WHERE source_id=? AND target_id=?",
                (m1.id, m2.id),
            ).fetchone()
            assert row[0] >= 1
        except Exception:  # noqa: BLE001
            pytest.fail("Graph edge not found after import")

        shutil.rmtree(tmp3, ignore_errors=True)
        if hasattr(engine3, "_vector") and hasattr(engine3._vector, "_client"):
            try:
                engine3._vector._client = None  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
            except Exception:  # noqa: BLE001, S110
                pass

    def test_schema_version_rejects_future(self, engine):
        """Import rejects exports from a newer schema_version."""
        from memorius.backup import import_json

        future_payload = {
            "schema_version": 999,
            "exported_at": "2099-01-01T00:00:00",
            "vaults": [], "shelves": [], "folders": [], "notes": [],
            "memories": [], "diaries": [], "graph_edges": [],
        }
        path = Path(tempfile.mkdtemp()) / "future.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(future_payload, fh)

        with pytest.raises(ValueError, match="schema_version"):
            import_json(engine, path)


class TestExportMarkdown:
    """Markdown export produces files with YAML frontmatter."""

    def test_export_creates_files(self, engine):
        from memorius.backup import export_markdown

        m = engine.store("md content", vault="main", shelf="s1",
                         folder="f1", note="n1")
        dest = Path(tempfile.mkdtemp()) / "md_out"
        export_markdown(engine, dest)

        md_file = dest / "main" / "s1" / "f1" / "n1" / f"{m.id}.md"
        assert md_file.exists()

        text = md_file.read_text(encoding="utf-8")
        assert text.startswith("---")
        assert f"id: {m.id}" in text
        assert "md content" in text

    def test_export_includes_metadata(self, engine):
        from memorius.backup import export_markdown

        m = engine.store("tagged", metadata={"tags": ["x"]})
        dest = Path(tempfile.mkdtemp()) / "md_meta"
        export_markdown(engine, dest)

        # find the file
        md_files = list(dest.rglob(f"{m.id}.md"))
        assert len(md_files) == 1
        text = md_files[0].read_text(encoding="utf-8")
        assert "tags" in text


# ── Path traversal guards (issue #60, H-07) ──────────────────────────────────

class TestPathTraversal:
    """Backup dest/src paths must not escape allowed base directories."""

    def test_export_json_blocks_traversal(self, engine):
        from memorius.backup import export_json

        dest = Path(tempfile.gettempdir()) / "../../../etc/memorius_hack.json"
        with pytest.raises(ValueError, match="must be inside one of"):
            export_json(engine, dest)

    def test_import_json_blocks_traversal(self, engine):
        from memorius.backup import import_json

        src = Path(tempfile.gettempdir()) / "../../../etc/memorius_hack.json"
        with pytest.raises(ValueError, match="must be inside one of"):
            import_json(engine, src)

    def test_export_markdown_blocks_traversal(self, engine):
        from memorius.backup import export_markdown

        dest = Path(tempfile.gettempdir()) / "../../../etc/md_out"
        with pytest.raises(ValueError, match="must be inside one of"):
            export_markdown(engine, dest)

    def test_export_json_under_tmp_allowed(self, engine):
        """Export under /tmp should work (it's an allowed base)."""
        from memorius.backup import export_json

        dest = Path(tempfile.mkdtemp()) / "backup.json"
        path = export_json(engine, dest)
        assert path.exists()


# ── Obsidian path confinement (issue #60, H-08) ──────────────────────────────

class TestObsidianPathConfinement:
    """resolve_vault_path with restrict_to_home=True blocks paths outside home."""

    def test_obsidian_allows_home_path(self, tmp_path, monkeypatch):
        from memorius.obsidian import resolve_vault_path

        home = Path.home().resolve()
        # Use a path under home
        vault = home / "Documents" / "Obsidian Vault"
        result = resolve_vault_path(str(vault), restrict_to_home=True)
        assert result == vault.resolve()

    def test_obsidian_blocks_outside_home(self, monkeypatch):
        from memorius.obsidian import resolve_vault_path

        with pytest.raises(ValueError, match="must be inside"):
            resolve_vault_path("/etc/passwd", restrict_to_home=True)

    def test_obsidian_no_restrict_allows_any(self, monkeypatch):
        """Without restrict_to_home, any path is allowed (backward compat)."""
        from memorius.obsidian import resolve_vault_path

        result = resolve_vault_path("/tmp/some/vault")
        assert result == Path("/tmp/some/vault").resolve()
