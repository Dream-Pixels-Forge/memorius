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

import json
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
    UNIQUE(source_id, target_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_graph_source ON memory_graph(source_id);
CREATE INDEX IF NOT EXISTS idx_graph_target ON memory_graph(target_id);
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
        conn.execute(
            "INSERT OR IGNORE INTO memory_graph (source_id, target_id, weight, relation, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_id, target_id, weight, relation, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memory_graph (source_id, target_id, weight, relation, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (target_id, source_id, weight, relation, now),
        )
        conn.commit()
    except sqlite3.OperationalError:
        init_graph_schema(conn)
        link_memories(conn, source_id, target_id, weight, relation)


def get_linked(
    conn: sqlite3.Connection,
    memory_id: str,
    relation: str | None = None,
    min_weight: float = 0.0,
) -> list[dict[str, Any]]:
    """Get all memories linked to a given memory."""
    if relation:
        rows = conn.execute(
            """SELECT target_id, weight, relation FROM memory_graph
               WHERE source_id = ? AND relation = ? AND weight >= ?
               ORDER BY weight DESC""",
            (memory_id, relation, min_weight),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT target_id, weight, relation FROM memory_graph
               WHERE source_id = ? AND weight >= ?
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
            links = get_linked(conn, node_id, min_weight=min_weight)
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
    threshold: float = 0.75,
    max_links: int = 10,
):
    """Automatically create links based on embedding proximity.

    For a given memory, find the most similar others and link them.
    """
    source = None
    for m in all_memories:
        if m.get("id") == memory_id:
            source = m
            break

    if not source or not source.get("vector"):
        return

    scored = []
    for m in all_memories:
        if m.get("id") == memory_id:
            continue
        if not m.get("vector"):
            continue
        sim = _cosine_similarity(source["vector"], m["vector"])
        if sim >= threshold:
            scored.append((m["id"], sim))

    scored.sort(key=lambda x: x[1], reverse=True)

    for target_id, sim in scored[:max_links]:
        link_memories(conn, memory_id, target_id, weight=sim, relation="related")


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
