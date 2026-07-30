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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memorius.validation import validate_name as _validate_name

logger = logging.getLogger("memorius.backup")

SCHEMA_VERSION = 1


def _validate_hierarchy_names(vaults, shelves, folders, notes):
    """Validate all hierarchy items before import to prevent path traversal."""
    for v in vaults:
        _validate_name(v.get("name", ""), "vault")
    for s in shelves:
        _validate_name(s.get("name", ""), "shelf")
    for f in folders:
        _validate_name(f.get("name", ""), "folder")
    for n in notes:
        _validate_name(n.get("name", ""), "note")


# ── JSON export / import ─────────────────────────────────────────────────────

def export_json(engine, dest: str | Path) -> Path:
    """Export the entire vault to a single JSON file.

    Returns the path written.
    """
    dest = Path(dest)

    # ── hierarchy ──
    hierarchy = engine._meta.export_hierarchy()

    # ── memories (meta only — vectors are re-derived on import) ──
    memories = engine._meta.export_memories_meta()

    # ── diaries ──
    diaries = engine._meta.export_diaries()

    # ── graph edges ──
    graph_edges = engine._meta.export_graph_edges()

    payload = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "vaults": hierarchy["vaults"],
        "shelves": hierarchy["shelves"],
        "folders": hierarchy["folders"],
        "notes": hierarchy["notes"],
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

    # ── hierarchy ──
    # Validate all imported names to prevent path traversal
    _validate_hierarchy_names(
        payload.get("vaults", []),
        payload.get("shelves", []),
        payload.get("folders", []),
        payload.get("notes", []),
    )
    engine._meta.import_hierarchy(
        payload.get("vaults", []),
        payload.get("shelves", []),
        payload.get("folders", []),
        payload.get("notes", []),
    )
    stats["vaults_imported"] = len(payload.get("vaults", []))
    stats["shelves_imported"] = len(payload.get("shelves", []))
    stats["folders_imported"] = len(payload.get("folders", []))
    stats["notes_imported"] = len(payload.get("notes", []))

    # ── memories ──
    for m in payload.get("memories", []):
        # Validate memory hierarchy fields to prevent path traversal
        _validate_name(m["vault"], "vault")
        _validate_name(m["shelf"], "shelf")
        _validate_name(m["folder"], "folder")
        _validate_name(m["note"], "note")
        engine._meta.ensure_note(m["vault"], m["shelf"], m["folder"], m["note"])
        imported = engine._meta.import_memory_meta(m, merge=merge)
        if imported:
            stats["memories_imported"] += 1
            # re-embed and add to Chroma
            try:
                from memorius.models import Memory
                mem = Memory(
                    id=m["id"], vault=m["vault"], shelf=m["shelf"],
                    folder=m["folder"], note=m["note"],
                    content=m["content"],
                    metadata=json.loads(m.get("metadata") or "{}"),
                )
                engine._vector.add(mem)
            except Exception as exc:  # best-effort: re-embedding failure — memory still imported to meta
                logger.warning("Failed to re-embed memory %s: %s", m["id"], exc)
        else:
            stats["memories_skipped"] += 1

    # ── diaries ──
    for d in payload.get("diaries", []):
        imported = engine._meta.import_diary(d, merge=merge)
        if imported:
            stats["diaries_imported"] += 1
        else:
            stats["diaries_skipped"] += 1

    # ── graph edges ──
    stats["graph_edges_imported"] = engine._meta.import_graph_edges(
        payload.get("graph_edges", [])
    )

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

    memories = engine._meta.export_memories_meta()

    # Pre-fetch graph edges grouped by source_id
    edges_by_source: dict[str, list[dict]] = {}
    for edge in engine._meta.export_graph_edges():
        edges_by_source.setdefault(edge["source_id"], []).append(edge)

    for m in memories:
        mid = m["id"]
        meta = json.loads(m.get("metadata") or "{}")
        edges = edges_by_source.get(mid, [])

        md_path = dest / m["vault"] / m["shelf"] / m["folder"] / m["note"] / f"{mid}.md"
        # Path traversal guard: resolved path must stay inside dest
        md_path_resolved = md_path.resolve()
        if not str(md_path_resolved).startswith(str(dest.resolve())):
            logger.warning("Skipping memory %s: path traversal detected", mid)
            continue
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
