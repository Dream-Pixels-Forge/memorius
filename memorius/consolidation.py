"""Memory consolidation engine — the "sleep" system.

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
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from memorius.temporal import calculate_decay_score, _parse_dt
from .utils import cosine_similarity

logger = logging.getLogger("memorius.consolidation")


class ConsolidationDaemon(threading.Thread):
    def __init__(self, meta_store, vector_store, config: dict):
        super().__init__(daemon=True)
        self._meta_store = meta_store
        self._vector_store = vector_store
        self._config = config.get("consolidation", {})
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        interval = self._config.get("interval_seconds", 3600)
        while not self._stop_event.is_set():
            self._stop_event.wait(interval)
            if not self._stop_event.is_set():
                self._run_cycle()

    def _run_cycle(self):
        pass


@dataclass
class ConsolidationResult:
    """Result of a consolidation pass."""
    clusters_found: int = 0
    memories_merged: int = 0
    memories_archived: int = 0
    insights_extracted: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


def _find_clusters_in_memory(
    memories: list[dict[str, Any]],
    similarity_threshold: float = 0.80,
) -> list[list[dict[str, Any]]]:
    """Greedy O(N²) pairwise clustering — used for small vaults."""
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


def _apply_interference_forgetting(memory: dict, base_memory: dict, similarity: float) -> float:
    """Apply interference-based forgetting to a memory.
    
    Reduces heat score based on similarity to a stronger memory and low usage.
    
    Args:
        memory: The memory to potentially forget (dict with metadata)
        base_memory: The stronger memory causing interference (dict with metadata)
        similarity: Cosine similarity between the memories (0.0 to 1.0)
        
    Returns:
        New heat score for the memory
    """
    # Extract relevant factors
    meta = memory.get("metadata", {})
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (json.JSONDecodeError, TypeError):
            meta = {}
    
    base_meta = base_memory.get("metadata", {})
    if isinstance(base_meta, str):
        try:
            base_meta = json.loads(base_meta)
        except (json.JSONDecodeError, TypeError):
            base_meta = {}
    
    # Get current heat score (default to 0.5 if not available)
    current_heat = meta.get("heat_score", 0.5)
    
    # Get access count (default to 0)
    access_count = meta.get("access_count", 0)
    base_access_count = base_meta.get("access_count", 0)
    
    # Interference is stronger when:
    # 1. Similarity is high (more similar = more interference)
    # 2. The target memory has low access count (less used = more susceptible)
    # 3. The base memory has high access count (more used = stronger interference source)
    
    similarity_factor = similarity  # 0.0 to 1.0
    access_factor = 1.0 - min(access_count / 10.0, 1.0)  # 0.0 to 1.0 (inverted)
    base_strength_factor = min(base_access_count / 10.0, 1.0)  # 0.0 to 1.0
    
    # Calculate interference strength
    interference_strength = similarity_factor * access_factor * base_strength_factor
    
    # Apply forgetting: reduce heat score by interference strength
    # But don't go below a minimum threshold
    new_heat = max(current_heat - (interference_strength * 0.3), 0.1)
    
    return new_heat


def _apply_engram_maturation(memory: dict) -> float:
    """Apply engram maturation to strengthen a memory.
    
    Increases heat score based on access count (consolidation through repetition).
    
    Args:
        memory: The memory to strengthen (dict with metadata)
        
    Returns:
        New heat score for the memory
    """
    # Extract relevant factors
    meta = memory.get("metadata", {})
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (json.JSONDecodeError, TypeError):
            meta = {}
    
    # Get current heat score (default to 0.5 if not available)
    current_heat = meta.get("heat_score", 0.5)
    
    # Get access count (default to 0)
    access_count = meta.get("access_count", 0)
    
    # Maturation is stronger with higher access count
    # But has diminishing returns to prevent overheating
    access_factor = min(access_count / 20.0, 0.8)  # Max 0.8 boost from access
    maturity_factor = 0.5 * (1.0 - math.exp(-access_count / 10.0))  # Saturation curve
    
    # Apply maturation: increase heat score
    # But don't go above maximum threshold
    new_heat = min(current_heat + (maturity_factor * 0.4), 1.0)
    
    return new_heat


def _apply_neuromodulator_gating(memory: dict, recent_novelty: float = 0.5) -> float:
    """Apply neuromodulator‑gated retrieval adjustments.
    
    Adjusts heat score based on attention/novelty signals.
    Simplified approximation: recent access bursts increase weight,
    novel stimuli in familiar contexts get boosted.
    
    Args:
        memory: The memory to adjust (dict with metadata)
        recent_novelty: Measure of recent environmental novelty (0.0 to 1.0)
        
    Returns:
        New heat score for the memory
    """
    # Extract relevant factors
    meta = memory.get("metadata", {})
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (json.JSONDecodeError, TypeError):
            meta = {}
    
    # Get current heat score (default to 0.5 if not available)
    current_heat = meta.get("heat_score", 0.5)
    
    # Get access count and last accessed time
    access_count = meta.get("access_count", 0)
    last_accessed = meta.get("last_accessed")
    
    # Calculate access burstiness (recent frequency vs overall frequency)
    # This is a simplified approximation
    burst_factor = 0.5  # Default neutral
    if last_accessed:
        try:
            last_access_dt = _parse_dt(last_accessed)
            now = datetime.now(timezone.utc)
            hours_since_access = (now - last_access_dt).total_seconds() / 3600
            
            # Very recent access suggests attentional boost
            if hours_since_access < 1:
                burst_factor = 0.8  # Strong recent access
            elif hours_since_access < 6:
                burst_factor = 0.6  # Moderately recent
            elif hours_since_access < 24:
                burst_factor = 0.4  # Somewhat recent
            else:
                burst_factor = 0.3  # Not recent
        except (ValueError, AttributeError):
            burst_factor = 0.5  # Default on parse error
    
    # Novelty boost: novel stimuli in familiar contexts get attention
    # Familiarity approximated by inverse of access count (low count = novel)
    familiarity = min(access_count / 10.0, 1.0)  # 0.0 to 1.0
    novelty_factor = recent_novelty * (1.0 - familiarity)  # Novel in familiar context
    
    # Combine factors
    neuromodulator_effect = (burst_factor * 0.7) + (novelty_factor * 0.3)
    neuromodulator_effect = max(0.0, min(1.0, neuromodulator_effect))  # Clamp to 0-1
    
    # Apply effect: can increase or decrease heat score slightly
    # Centered around 0.5 so it can go either way
    adjustment = (neuromodulator_effect - 0.5) * 0.2  # Max +/- 0.1 adjustment
    new_heat = max(0.1, min(1.0, current_heat + adjustment))
    
    return new_heat


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
    page = engine.list_memories(vault=vault, limit=10000, with_vectors=True)
    memories = [m.to_dict() for m in page["memories"]]

    if not memories:
        logger.info("No memories to consolidate")
        return result

    # Find similar clusters using in-memory comparison
    clusters = _find_clusters_in_memory(memories, similarity_threshold)
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

        # Apply neuroscience-inspired memory modifications instead of archiving
        try:
            # Get the base memory (the insight)
            base_memory = None
            for mem in cluster:
                if mem.get("id") == insight.get("source_ids", [""])[0]:
                    base_memory = mem
                    break
            
            if base_memory is None:
                # Fallback: use the first memory in cluster as base
                base_memory = cluster[0]
            
            # Apply engram maturation to the base memory (strengthen highly-used memories)
            base_meta = base_memory.get("metadata", {})
            if isinstance(base_meta, str):
                try:
                    base_meta = json.loads(base_meta)
                except (json.JSONDecodeError, TypeError):
                    base_meta = {}
            
            new_heat = _apply_engram_maturation(base_memory)
            base_meta["heat_score"] = new_heat
            
            # Update the base memory in the database
            engine._meta.update_memory_meta(
                base_memory["id"],
                metadata=base_meta
            )
            
            # Apply interference-based forgetting to other memories in the cluster
            for mem in cluster:
                if mem.get("id") == base_memory.get("id"):
                    continue  # Skip the base memory
                
                # Calculate similarity to base memory
                vec_i = mem.get("vector")
                vec_j = base_memory.get("vector")
                if vec_i is not None and vec_j is not None:
                    similarity = cosine_similarity(vec_i, vec_j)
                    
                    # Apply interference-based forgetting
                    meta = mem.get("metadata", {})
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except (json.JSONDecodeError, TypeError):
                            meta = {}
                    
                    new_heat = _apply_interference_forgetting(mem, base_memory, similarity)
                    meta["heat_score"] = new_heat
                    
                    # Apply neuromodulator‑gated retrieval adjustments
                    # For simplicity, we'll use a fixed novelty value; in a full implementation,
                    # this would come from recent environmental context
                    new_heat = _apply_neuromodulator_gating(mem, recent_novelty=0.5)
                    meta["heat_score"] = new_heat
                    
                    # Update the memory in the database
                    engine._meta.update_memory_meta(
                        mem["id"],
                        metadata=meta
                    )
        except Exception as e:
            logger.warning(f"Error applying neuroscience-inspired modifications: {e}")
            # Fallback to original archiving behavior on error
            try:
                engine._meta.archive_memories(insight["source_ids"])
                result.memories_archived += len(insight["source_ids"])
            except Exception as e2:
                logger.warning(f"Could not archive source memories: {e2}")

    logger.info(
        f"Consolidation complete: {result.clusters_found} clusters, "
        f"{result.memories_merged} merged, {result.memories_archived} archived"
    )
    return result
