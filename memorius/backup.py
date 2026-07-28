"""Export and import a full memorius vault.

Supports two formats:
  - **json**: a single file containing everything (memories, diaries,
    hierarchy, graph edges).  Idempotent re-import keyed by memory ID.
  - **markdown**: one ``.md`` file per memory under
    ``<vault>/<shelf>/<folder>/<note>/<id>.md`` with YAML frontmatter.
    Graph edges are emitted as ``links`` in the frontmatter (best-effort
    round-trip — edges may be lost on re-import if target IDs changed).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("memorius.backup")

SCHEMA_VERSION = 1


# ── JSON export / import ─────────────────────────────────────────────────────

def export_json(engine, dest: str | Path) -> Path:
    """Export the entire vault to a single JSON file.

    Returns the path written.
    """
    from memorius.graph import init_graph_schema

    dest = Path(dest)
    conn = engine._meta._conn()

    # ── hierarchy ──
    vaults = [dict(r) for r in conn.execute(
        "SELECT name, description, created_at, updated_at FROM vaults"
    ).fetchall()]

    shelves = [dict(r) for r in conn.execute(
        "SELECT vault, name, description, created_at, updated_at FROM shelves"
    ).fetchall()]

    folders = [dict(r) for r in conn.execute(
        "SELECT vault, shelf, name, description, created_at, updated_at FROM folders"
    ).fetchall()]

    notes = [dict(r) for r in conn.execute(
        "SELECT vault, shelf, folder, name, description, memory_count, created_at, updated_at FROM notes"
    ).fetchall()]

    # ── memories (meta only — vectors are re-derived on import) ──
    memories = [dict(r) for r in conn.execute(
        "SELECT id, vault, shelf, folder, note, content, metadata, "
        "access_count, last_accessed, created_at, updated_at "
        "FROM memory_meta"
    ).fetchall()]

    # ── diaries ──
    diaries = [dict(r) for r in conn.execute(
        "SELECT id, session_id, vault, title, summary, content, "
        "exchange_count, created_at, updated_at FROM diaries"
    ).fetchall()]

    # ── graph edges ──
    graph_edges: list[dict[str, Any]] = []
    try:
        graph_edges = [dict(r) for r in conn.execute(
            "SELECT source_id, target_id, weight, relation, created_at "
            "FROM memory_graph"
        ).fetchall()]
    except Exception:
        pass  # graph table may not exist

    payload = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "vaults": vaults,
        "shelves": shelves,
        "folders": folders,
        "notes": notes,
        "memories": memories,
        "diaries": diaries,
        "graph_edges": graph_edges,
    }

    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)

    logger.info("Exported %d memories, %d diaries, %d graph edges to %s",
                len(memories), len(diaries), len(graph_edges), dest)
    return dest


def import_json(engine, src: str | Path, *, merge: bool = True) -> dict[str, Any]:
    """Import memories from a JSON export file.

    Args:
        merge: if True (default) skip memories whose ID already exists;
               if False overwrite existing memories.

    Returns a summary dict with counts of items imported/skipped.
    """
    src = Path(src)
    with open(src, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    ver = payload.get("schema_version", 0)
    if ver > SCHEMA_VERSION:
        raise ValueError(
            f"Export uses schema_version={ver}; this build supports up to "
            f"{SCHEMA_VERSION}. Please upgrade memorius before importing."
        )

    conn = engine._meta._conn()
    stats: dict[str, int] = {
        "vaults_imported": 0,
        "shelves_imported": 0,
        "folders_imported": 0,
        "notes_imported": 0,
        "memories_imported": 0,
        "memories_skipped": 0,
        "diaries_imported": 0,
        "diaries_skipped": 0,
        "graph_edges_imported": 0,
    }

    now = datetime.now(timezone.utc).isoformat()

    # ── hierarchy ──
    for v in payload.get("vaults", []):
        conn.execute(
            "INSERT OR IGNORE INTO vaults (name, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (v["name"], v.get("description", ""), v.get("created_at", now), v.get("updated_at", now)),
        )
        stats["vaults_imported"] += 1

    for s in payload.get("shelves", []):
        conn.execute(
            "INSERT OR IGNORE INTO shelves (vault, name, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (s["vault"], s["name"], s.get("description", ""), s.get("created_at", now), s.get("updated_at", now)),
        )
        stats["shelves_imported"] += 1

    for f in payload.get("folders", []):
        conn.execute(
            "INSERT OR IGNORE INTO folders (vault, shelf, name, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (f["vault"], f["shelf"], f["name"], f.get("description", ""), f.get("created_at", now), f.get("updated_at", now)),
        )
        stats["folders_imported"] += 1

    for n in payload.get("notes", []):
        conn.execute(
            "INSERT OR IGNORE INTO notes (vault, shelf, folder, name, description, memory_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (n["vault"], n["shelf"], n["folder"], n["name"],
             n.get("description", ""), n.get("memory_count", 0),
             n.get("created_at", now), n.get("updated_at", now)),
        )
        stats["notes_imported"] += 1
    conn.commit()

    # ── memories ──
    existing_ids = set()
    try:
        rows = conn.execute("SELECT id FROM memory_meta").fetchall()
        existing_ids = {r[0] for r in rows}
    except Exception:
        pass

    for m in payload.get("memories", []):
        mid = m["id"]
        if mid in existing_ids:
            if not merge:
                # overwrite
                conn.execute(
                    "UPDATE memory_meta SET vault=?, shelf=?, folder=?, note=?, "
                    "content=?, metadata=?, access_count=?, last_accessed=?, "
                    "created_at=?, updated_at=? WHERE id=?",
                    (m["vault"], m["shelf"], m["folder"], m["note"],
                     m["content"], m.get("metadata", "{}"),
                     m.get("access_count", 0), m.get("last_accessed"),
                     m.get("created_at", now), m.get("updated_at", now), mid),
                )
                stats["memories_imported"] += 1
            else:
                stats["memories_skipped"] += 1
            continue

        # ensure hierarchy nodes exist
        engine._meta.ensure_note(m["vault"], m["shelf"], m["folder"], m["note"])

        conn.execute(
            "INSERT INTO memory_meta (id, vault, shelf, folder, note, content, "
            "metadata, access_count, last_accessed, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, m["vault"], m["shelf"], m["folder"], m["note"],
             m["content"], m.get("metadata", "{}"),
             m.get("access_count", 0), m.get("last_accessed"),
             m.get("created_at", now), m.get("updated_at", now)),
        )
        stats["memories_imported"] += 1

        # re-embed and add to Chroma
        try:
            from memorius.models import Memory
            mem = Memory(
                id=mid, vault=m["vault"], shelf=m["shelf"],
                folder=m["folder"], note=m["note"],
                content=m["content"],
                metadata=json.loads(m.get("metadata") or "{}"),
            )
            engine._vector.add(mem)
        except Exception as exc:
            logger.warning("Failed to re-embed memory %s: %s", mid, exc)

        try:
            conn.commit()
        except Exception:
            pass  # connection may be closed after vector add

    # ── diaries ──
    existing_diary_ids: set[str] = set()
    try:
        rows = conn.execute("SELECT id FROM diaries").fetchall()
        existing_diary_ids = {r[0] for r in rows}
    except Exception:
        pass

    for d in payload.get("diaries", []):
        did = d["id"]
        if did in existing_diary_ids:
            if not merge:
                conn.execute(
                    "UPDATE diaries SET session_id=?, vault=?, title=?, summary=?, "
                    "content=?, exchange_count=?, created_at=?, updated_at=? WHERE id=?",
                    (d["session_id"], d["vault"], d.get("title", ""),
                     d.get("summary", ""), d.get("content", ""),
                     d.get("exchange_count", 0),
                     d.get("created_at", now), d.get("updated_at", now), did),
                )
                stats["diaries_imported"] += 1
            else:
                stats["diaries_skipped"] += 1
            continue

        conn.execute(
            "INSERT INTO diaries (id, session_id, vault, title, summary, content, "
            "exchange_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (did, d["session_id"], d["vault"], d.get("title", ""),
             d.get("summary", ""), d.get("content", ""),
             d.get("exchange_count", 0),
             d.get("created_at", now), d.get("updated_at", now)),
        )
        stats["diaries_imported"] += 1
    conn.commit()

    # ── graph edges ──
    from memorius.graph import init_graph_schema
    init_graph_schema(conn)
    for e in payload.get("graph_edges", []):
        try:
            conn.execute(
                "INSERT OR IGNORE INTO memory_graph (source_id, target_id, weight, relation, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (e["source_id"], e["target_id"], e.get("weight", 1.0),
                 e.get("relation", "related"), e.get("created_at", now)),
            )
            stats["graph_edges_imported"] += 1
        except Exception:
            pass
    conn.commit()

    logger.info("Imported: %s", stats)
    return stats


# ── Markdown export (read-only; best-effort) ─────────────────────────────────

def export_markdown(engine, dest: str | Path) -> Path:
    """Export memories as individual Markdown files with YAML frontmatter.

    Layout::

        <dest>/<vault>/<shelf>/<folder>/<note>/<memory_id>.md

    Graph edges are included as ``links`` in frontmatter.
    """
    dest = Path(dest)
    conn = engine._meta._conn()

    memories = [dict(r) for r in conn.execute(
        "SELECT id, vault, shelf, folder, note, content, metadata, "
        "access_count, last_accessed, created_at, updated_at "
        "FROM memory_meta"
    ).fetchall()]

    # Pre-fetch graph edges grouped by source_id
    edges_by_source: dict[str, list[dict]] = {}
    try:
        for row in conn.execute(
            "SELECT source_id, target_id, weight, relation FROM memory_graph"
        ).fetchall():
            d = dict(row)
            edges_by_source.setdefault(d["source_id"], []).append(d)
    except Exception:
        pass

    for m in memories:
        mid = m["id"]
        meta = json.loads(m.get("metadata") or "{}")
        edges = edges_by_source.get(mid, [])

        md_path = dest / m["vault"] / m["shelf"] / m["folder"] / m["note"] / f"{mid}.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)

        # Build YAML frontmatter
        fm_lines = ["---"]
        fm_lines.append(f"id: {mid}")
        fm_lines.append(f"vault: {m['vault']}")
        fm_lines.append(f"shelf: {m['shelf']}")
        fm_lines.append(f"folder: {m['folder']}")
        fm_lines.append(f"note: {m['note']}")
        fm_lines.append(f"created_at: \"{m.get('created_at', '')}\"")
        fm_lines.append(f"updated_at: \"{m.get('updated_at', '')}\"")
        fm_lines.append(f"access_count: {m.get('access_count', 0)}")
        if m.get("last_accessed"):
            fm_lines.append(f"last_accessed: \"{m['last_accessed']}\"")
        if meta:
            fm_lines.append(f"metadata: {json.dumps(meta, ensure_ascii=False)}")
        if edges:
            link_strs = [
                f"  - target: {e['target_id']}  # {e.get('relation', 'related')} (w={e.get('weight', 1.0)})"
                for e in edges
            ]
            fm_lines.append("links:")
            fm_lines.extend(link_strs)
        fm_lines.append("---")
        fm_lines.append("")

        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(fm_lines))
            fh.write(m.get("content", ""))
            fh.write("\n")

    logger.info("Exported %d memories as Markdown to %s", len(memories), dest)
    return dest
