"""Memory consolidation engine — the \"sleep\" system.

Merges duplicate/similar memories, extracts key insights, and creates
summary memories. Like how human brains consolidate during sleep.

Pipeline:
  1. Cluster memories by embedding similarity (cosine > threshold)
  2. For each cluster, extract: key fact, context, confidence
  3. Store consolidated memory, mark originals as archived
  4. Update note memory_count
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from memorius.temporal import calculate_decay_score, archive_memories
from .utils import cosine_similarity

logger = logging.getLogger("memorius.consolidation")


@dataclass
class ConsolidationResult:
    """Result of a consolidation pass."""
    clusters_found: int = 0
    memories_merged: int = 0
    memories_archived: int = 0
    insights_extracted: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


def find_similar_clusters(
    memories: list[dict[str, Any]],
    similarity_threshold: float = 0.80,
) -> list[list[dict[str, Any]]]:
    """Group memories into clusters by embedding similarity.

    Uses a simple greedy clustering: for each memory, find all others
    with cosine similarity >= threshold.
    """
    if not memories:
        return []

    clusters: list[list[dict[str, Any]]] = []
    assigned: set[int] = set()

    for i, mem_i in enumerate(memories):
        if i in assigned:
            continue

        cluster = [mem_i]
        assigned.add(i)
        vec_i = mem_i.get("vector")
        if vec_i is None:
            continue

        for j, mem_j in enumerate(memories):
            if j in assigned:
                continue
            vec_j = mem_j.get("vector")
            if vec_j is None:
                continue

            sim = cosine_similarity(vec_i, vec_j)
            if sim >= similarity_threshold:
                cluster.append(mem_j)
                assigned.add(j)

        if len(cluster) > 1:
            clusters.append(cluster)

    return clusters


def extract_insight(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract a consolidated insight from a cluster of similar memories.

    Uses heuristic extraction (no LLM required):
    - Longest content as the base
    - Merges unique metadata
    - Averages decay scores for confidence
    """
    if not cluster:
        return {}

    # Pick the longest content as the base insight
    base = max(cluster, key=lambda m: len(m.get("content", "")))

    # Merge unique metadata
    all_metadata: dict[str, Any] = {}
    for mem in cluster:
        meta = mem.get("metadata", {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        all_metadata.update(meta)

    # Calculate confidence from decay scores
    scores = []
    for mem in cluster:
        score = calculate_decay_score(
            created_at=mem.get("created_at", ""),
            last_accessed=mem.get("last_accessed"),
            access_count=mem.get("access_count", 0),
        )
        scores.append(score)
    avg_confidence = sum(scores) / len(scores) if scores else 0.5

    # Source IDs for tracking
    source_ids = [mem.get("id", "") for mem in cluster]

    return {
        "content": base.get("content", ""),
        "metadata": {
            **all_metadata,
            "consolidated_from": source_ids,
            "cluster_size": len(cluster),
            "confidence": round(avg_confidence, 3),
        },
        "source_ids": source_ids,
        "vault": base.get("vault", "main"),
        "shelf": base.get("shelf", "default"),
        "folder": base.get("folder", "default"),
        "note": base.get("note", "default"),
    }


def consolidate(
    engine,
    vault: str | None = None,
    similarity_threshold: float = 0.80,
    dry_run: bool = False,
) -> ConsolidationResult:
    """Run a consolidation pass on the vault.

    Args:
        engine: VaultEngine instance
        vault: Filter by vault (None = all)
        similarity_threshold: Cosine similarity threshold for clustering
        dry_run: If True, report what would happen without making changes

    Returns:
        ConsolidationResult with statistics
    """
    result = ConsolidationResult()

    # Collect all memories with vectors
    search_results = engine.search(query="", vault=vault, limit=10000)
    memories = [m.to_dict() for m in search_results]

    if not memories:
        logger.info("No memories to consolidate")
        return result

    # Find similar clusters
    clusters = find_similar_clusters(memories, similarity_threshold)
    result.clusters_found = len(clusters)

    for cluster in clusters:
        insight = extract_insight(cluster)
        if not insight:
            continue

        result.details.append({
            "cluster_size": len(cluster),
            "source_ids": insight["source_ids"],
            "insight_preview": insight["content"][:100],
        })

        if dry_run:
            result.memories_merged += 1
            result.memories_archived += len(cluster)
            continue

        # Store consolidated memory
        engine.store(
            content=insight["content"],
            vault=insight["vault"],
            shelf=insight["shelf"],
            folder=insight["folder"],
            note=insight["note"],
            metadata=insight["metadata"],
        )
        result.memories_merged += 1
        result.insights_extracted += 1

        # Archive originals
        try:
            conn = engine._meta._conn()
            archive_memories(conn, insight["source_ids"])
            result.memories_archived += len(insight["source_ids"])
        except Exception as e:
            logger.warning(f"Could not archive source memories: {e}")

    logger.info(
        f"Consolidation complete: {result.clusters_found} clusters, "
        f"{result.memories_merged} merged, {result.memories_archived} archived"
    )
    return result
