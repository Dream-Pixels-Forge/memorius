"""Knowledge graph for memories — associative memory connections.

Instead of just hierarchical vault/shelf/folder/note, build a graph
where memories link to each other. Enables "related memories" — when
you search for X, you also get memories that reference X.

Links are created by:
  - Co-occurrence in same session
  - Explicit reference
  - Embedding proximity
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .utils import cosine_similarity


@dataclass
class MemoryNode:
    """A node in the knowledge graph."""
    id: str
    content: str
    vault: str
    shelf: str
    folder: str
    note: str
    linked_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """An edge in the knowledge graph."""
    source_id: str
    target_id: str
    weight: float = 1.0
    relation: str = "related"  # related, co_occurs, references, contradicts
    created_at: str = ""


@dataclass
class GraphResult:
    """Result of a graph traversal."""
    seed_ids: list[str]
    expanded_ids: list[str]
    nodes: list[MemoryNode]
    edges: list[GraphEdge]
    total_hops: int = 0


# ── Graph schema migration ───────────────────────────────────────────────────


GRAPH_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_graph (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    relation TEXT DEFAULT 'related',
    created_at TEXT NOT NULL,
    tvalid TEXT NOT NULL,
    tinvalid TEXT,
    UNIQUE(source_id, target_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_graph_source ON memory_graph(source_id);
CREATE INDEX IF NOT EXISTS idx_graph_target ON memory_graph(target_id);
CREATE INDEX IF NOT EXISTS idx_graph_tvalid ON memory_graph(tvalid);
"""


def init_graph_schema(conn: sqlite3.Connection):
    """Create graph tables if they don't exist."""
    conn.executescript(GRAPH_SCHEMA)
    conn.commit()


# ── Graph operations ─────────────────────────────────────────────────────────


def link_memories(
    conn: sqlite3.Connection,
    source_id: str,
    target_id: str,
    weight: float = 1.0,
    relation: str = "related",
):
    """Create a bidirectional link between two memories."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        existing = conn.execute(
            "SELECT relation FROM memory_graph WHERE source_id=? AND target_id=? AND tinvalid IS NULL",
            (source_id, target_id),
        ).fetchone()
        if existing and existing[0] != relation:
            invalidate_edge(conn, source_id, target_id, relation=existing[0])
            invalidate_edge(conn, target_id, source_id, relation=existing[0])

        conn.execute(
            "INSERT OR IGNORE INTO memory_graph (source_id, target_id, weight, relation, created_at, tvalid) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (source_id, target_id, weight, relation, now, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memory_graph (source_id, target_id, weight, relation, created_at, tvalid) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (target_id, source_id, weight, relation, now, now),
        )
        conn.commit()
    except sqlite3.OperationalError:
        init_graph_schema(conn)
        link_memories(conn, source_id, target_id, weight, relation)


def invalidate_edge(conn: sqlite3.Connection, source_id: str, target_id: str,
                    relation: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if relation:
        conn.execute(
            "UPDATE memory_graph SET tinvalid=? WHERE source_id=? AND target_id=? AND relation=?",
            (now, source_id, target_id, relation),
        )
    else:
        conn.execute(
            "UPDATE memory_graph SET tinvalid=? WHERE source_id=? AND target_id=?",
            (now, source_id, target_id),
        )
    conn.commit()


def get_linked(
    conn: sqlite3.Connection,
    memory_id: str,
    relation: str | None = None,
    min_weight: float = 0.0,
    include_invalidated: bool = False,
) -> list[dict[str, Any]]:
    """Get all memories linked to a given memory."""
    temporal_filter = "" if include_invalidated else "AND tinvalid IS NULL"
    if relation:
        rows = conn.execute(
            f"""SELECT target_id, weight, relation FROM memory_graph
               WHERE source_id = ? AND relation = ? AND weight >= ?
               {temporal_filter}
               ORDER BY weight DESC""",
            (memory_id, relation, min_weight),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""SELECT target_id, weight, relation FROM memory_graph
               WHERE source_id = ? AND weight >= ?
               {temporal_filter}
               ORDER BY weight DESC""",
            (memory_id, min_weight),
        ).fetchall()
    return [dict(r) for r in rows]


def expand_graph(
    conn: sqlite3.Connection,
    seed_ids: list[str],
    hops: int = 1,
    min_weight: float = 0.3,
    max_nodes: int = 50,
    include_invalidated: bool = False,
) -> GraphResult:
    """Expand from seed IDs through the graph.

    BFS traversal up to `hops` levels deep.
    """
    result = GraphResult(seed_ids=seed_ids, expanded_ids=[], nodes=[], edges=[])
    visited = set(seed_ids)
    frontier = list(seed_ids)

    for hop in range(hops):
        next_frontier = []
        for node_id in frontier:
            links = get_linked(conn, node_id, min_weight=min_weight, include_invalidated=include_invalidated)
            for link in links:
                tid = link["target_id"]
                if tid not in visited:
                    visited.add(tid)
                    next_frontier.append(tid)
                    result.expanded_ids.append(tid)
                    result.edges.append(GraphEdge(
                        source_id=node_id,
                        target_id=tid,
                        weight=link["weight"],
                        relation=link["relation"],
                    ))
                    if len(result.expanded_ids) >= max_nodes:
                        break
            if len(result.expanded_ids) >= max_nodes:
                break
        frontier = next_frontier
        if not frontier or len(result.expanded_ids) >= max_nodes:
            break
        result.total_hops = hop + 1

    return result


def auto_link_by_proximity(
    conn: sqlite3.Connection,
    memory_id: str,
    all_memories: list[dict[str, Any]],
    threshold: float = 0.3,
    max_links: int = 10,
):
    """Automatically create links based on content similarity.

    For a given memory, find the most similar others and link them.
    Uses word overlap (Jaccard) when vectors are not available.
    """
    source = None
    for m in all_memories:
        if m.get("id") == memory_id:
            source = m
            break

    if not source:
        return

    source_content = (source.get("content") or "").lower()
    if not source_content:
        return
    source_words = set(source_content.split())

    scored = []
    for m in all_memories:
        if m.get("id") == memory_id:
            continue

        # Prefer vector cosine similarity if available
        if source.get("vector") and m.get("vector"):
            sim = cosine_similarity(source["vector"], m["vector"])
        else:
            # Fall back to word overlap (Jaccard)
            target_content = (m.get("content") or "").lower()
            if not target_content:
                continue
            target_words = set(target_content.split())
            if not source_words or not target_words:
                continue
            intersection = source_words & target_words
            union = source_words | target_words
            sim = len(intersection) / len(union) if union else 0.0

        if sim >= threshold:
            scored.append((m["id"], sim))

    scored.sort(key=lambda x: x[1], reverse=True)

    for target_id, sim in scored[:max_links]:
        link_memories(conn, memory_id, target_id, weight=round(sim, 4), relation="related")


def get_graph_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Get statistics about the knowledge graph."""
    try:
        total_edges = conn.execute("SELECT COUNT(*) FROM memory_graph").fetchone()[0]
        unique_nodes = conn.execute(
            "SELECT COUNT(DISTINCT source_id) FROM memory_graph"
        ).fetchone()[0]
        relations = conn.execute(
            "SELECT relation, COUNT(*) FROM memory_graph GROUP BY relation"
        ).fetchall()
        return {
            "total_edges": total_edges,
            "unique_nodes": unique_nodes,
            "relations": {r[0]: r[1] for r in relations},
        }
    except sqlite3.OperationalError:
        return {"total_edges": 0, "unique_nodes": 0, "relations": {}}


def get_graph_data(
    conn: sqlite3.Connection,
    vault: str | None = None,
    shelf: str | None = None,
    relation: str | None = None,
    min_weight: float = 0.0,
    limit: int = 500,
) -> dict[str, Any]:
    """Fetch complete graph topology (nodes and edges) for visualization.

    Args:
        conn: SQLite connection.
        vault: Optional vault filter.
        shelf: Optional shelf filter.
        relation: Optional relation type filter.
        min_weight: Minimum edge weight threshold.
        limit: Maximum number of nodes to return.

    Returns:
        Dictionary with 'nodes', 'edges', and 'summary' keys.
    """
    import json

    init_graph_schema(conn)

    # 1. Fetch memories matching vault/shelf filters
    mem_query = (
        "SELECT id, vault, shelf, folder, note, content, metadata, "
        "access_count, last_accessed, created_at FROM memory_meta WHERE archived = 0"
    )
    mem_params: list[Any] = []
    if vault:
        mem_query += " AND vault = ?"
        mem_params.append(vault)
    if shelf:
        mem_query += " AND shelf = ?"
        mem_params.append(shelf)

    mem_query += " ORDER BY access_count DESC, created_at DESC LIMIT ?"
    mem_params.append(limit)

    memory_rows = conn.execute(mem_query, mem_params).fetchall()
    memories_by_id = {}
    nodes = []

    for r in memory_rows:
        row_dict = dict(r)
        mid = row_dict["id"]
        meta_str = row_dict.get("metadata") or "{}"
        try:
            meta = json.loads(meta_str) if isinstance(meta_str, str) else meta_str
        except Exception:
            meta = {}
        
        content = row_dict.get("content") or ""
        snippet = content[:180] + ("..." if len(content) > 180 else "")

        node = {
            "id": mid,
            "label": f"{row_dict.get('shelf', '')}/{row_dict.get('note', '')}",
            "vault": row_dict.get("vault", "main"),
            "shelf": row_dict.get("shelf", "default"),
            "folder": row_dict.get("folder", "default"),
            "note": row_dict.get("note", "default"),
            "snippet": snippet,
            "content": content,
            "category": meta.get("category", "general"),
            "tags": meta.get("tags", []),
            "access_count": row_dict.get("access_count", 0),
            "created_at": row_dict.get("created_at", ""),
            "last_accessed": row_dict.get("last_accessed", ""),
        }
        nodes.append(node)
        memories_by_id[mid] = node

    if not nodes:
        return {"nodes": [], "edges": [], "summary": {"node_count": 0, "edge_count": 0}}

    # 2. Fetch edges connecting these nodes
    id_set = set(memories_by_id.keys())
    edge_query = (
        "SELECT source_id, target_id, weight, relation, created_at "
        "FROM memory_graph WHERE weight >= ?"
    )
    edge_params: list[Any] = [min_weight]
    if relation:
        edge_query += " AND relation = ?"
        edge_params.append(relation)

    edge_rows = conn.execute(edge_query, edge_params).fetchall()
    edges = []
    seen_undirected_pairs = set()

    for er in edge_rows:
        ed = dict(er)
        s_id = ed["source_id"]
        t_id = ed["target_id"]

        # Only include edges between visible nodes
        if s_id in id_set and t_id in id_set:
            pair = tuple(sorted([s_id, t_id])) + (ed["relation"],)
            if pair in seen_undirected_pairs:
                continue
            seen_undirected_pairs.add(pair)

            edges.append({
                "source": s_id,
                "target": t_id,
                "weight": ed.get("weight", 1.0),
                "relation": ed.get("relation", "related"),
                "created_at": ed.get("created_at", ""),
            })

    # Degree / connection count on nodes
    degree_map: dict[str, int] = {n["id"]: 0 for n in nodes}
    for e in edges:
        degree_map[e["source"]] = degree_map.get(e["source"], 0) + 1
        degree_map[e["target"]] = degree_map.get(e["target"], 0) + 1

    for n in nodes:
        n["degree"] = degree_map.get(n["id"], 0)

    return {
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "vault": vault or "all",
            "shelf": shelf or "all",
        },
    }
