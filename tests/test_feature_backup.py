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
            eng._vector._client = None
        except Exception:
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
                engine2._vector._client = None
            except Exception:
                pass

    def test_import_skip_existing(self, engine):
        """merge=True skips memories already present."""
        from memorius.backup import export_json, import_json

        m = engine.store("existing mem")
        export_path = Path(tempfile.mkdtemp()) / "skip.json"
        export_json(engine, export_path)

        # Import into same engine (merge=True = skip)
        stats = import_json(engine, export_path, merge=True)
        assert stats["memories_skipped"] == 1
        assert stats["memories_imported"] == 0

    def test_import_replace_existing(self, engine):
        """merge=False overwrites existing memories."""
        from memorius.backup import export_json, import_json

        m = engine.store("original content")
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
        from memorius.graph import link_memories, init_graph_schema

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
        except Exception:
            pytest.fail("Graph edge not found after import")

        shutil.rmtree(tmp3, ignore_errors=True)
        if hasattr(engine3, "_vector") and hasattr(engine3._vector, "_client"):
            try:
                engine3._vector._client = None
            except Exception:
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
