"""SearchModule — semantic search pipeline with temporal decay, reranking,
and graph expansion.

Extracted from VaultEngine.search() to isolate the 5-stage search concern:
  1. Filter stage (folder/note metadata narrowing)
  2. Vector stage (semantic similarity via ChromaStore/SqliteVecStore)
  3. Temporal stage (decay scoring + search ranking)
  4. Rerank stage (cross-encoder reranking, opt-in)
  5. Graph stage (knowledge graph expansion, opt-in)

The module is stateless — it receives dependencies at call time and
delegates storage to VectorStore and MetaStore.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from memorius.models import Memory
from memorius.vector_store_base import VectorStore
from memorius.validation import validate_name

logger = logging.getLogger("memorius.search")


class SearchModule:
    """Stateless search pipeline — all methods take explicit dependencies."""

    def __init__(self, vector: VectorStore, meta: Any):
        """
        Args:
            vector: The vector store (ChromaStore or SqliteVecStore).
            meta: The MetaStore (for temporal scoring and graph expansion).
        """
        self._vector = vector
        self._meta = meta

    def search(
        self,
        query: str,
        vault: str | None = None,
        shelf: str | None = None,
        limit: int = 10,
        expand_graph: bool = False,
        graph_hops: int = 1,
        graph_min_weight: float = 0.3,
        folder: str | None = None,
        note: str | None = None,
        tags: list[str] | None = None,
        rerank: bool = False,
    ) -> list[Memory]:
        """Search vault contents by semantic similarity with temporal decay
        ranking.

        When ``expand_graph=True``, after the primary ranked results are
        selected, walk the knowledge graph up to ``graph_hops`` hops from
        each seed memory and append linked memories (deduped against the
        seeds) so the caller also sees "what's connected to this". The
        total returned size is capped at ``ceil(limit * 1.5)``.
        """
        # ── 1. Filter stage ──────────────────────────────────────────────
        filter_metadata: dict[str, str] = {}
        if folder is not None:
            filter_metadata["folder"] = validate_name(folder, "folder")
        if note is not None:
            filter_metadata["note"] = validate_name(note, "note")

        # Over-fetch so the post-filter for tags can still return up to
        # `limit` after discarding non-matching memories.
        fetch_n = (limit * 4) if tags else (limit * 2)

        # ── 2. Vector stage ──────────────────────────────────────────────
        results = self._vector.search(
            query, vault=vault, shelf=shelf, n_results=fetch_n,
            filter_metadata=filter_metadata or None,
        )

        # ── 2b. Tag post-filter ──────────────────────────────────────────
        if tags:
            wanted = {str(t) for t in tags}
            filtered: list[Memory] = []
            for mem in results:
                md_tags = (mem.metadata or {}).get("tags") or []
                if isinstance(md_tags, str):
                    try:
                        import json as _json
                        md_tags = _json.loads(md_tags)
                    except Exception:  # best-effort: corrupted JSON tags — treat as string literal
                        md_tags = [md_tags]
                if wanted.issubset({str(t) for t in (md_tags or [])}):
                    filtered.append(mem)
            results = filtered

        # ── 3. Temporal stage ────────────────────────────────────────────
        try:
            from memorius.temporal import calculate_decay_score, calculate_search_score
            meta_map = self._meta.get_memory_meta_batch([m.id for m in results])
            scored = []
            for rank_pos, mem in enumerate(results):
                meta = meta_map.get(mem.id)
                decay = 1.0
                access_count = 0
                if meta:
                    decay = calculate_decay_score(
                        created_at=meta.get("created_at", ""),
                        last_accessed=meta.get("last_accessed"),
                        access_count=meta.get("access_count", 0),
                    )
                    access_count = meta.get("access_count", 0)
                distance = float((mem.metadata or {}).get("__distance__", 0.0) or 0.0)
                semantic_sim = max(0.0, min(1.0, 1.0 - distance))
                final_score = calculate_search_score(
                    semantic_similarity=semantic_sim,
                    decay_score=decay,
                    access_count=access_count,
                )
                scored.append((mem, final_score))
            scored.sort(key=lambda x: x[1], reverse=True)
            results = [m for m, _ in scored[:limit]]
            for mem in results:
                if "__distance__" in (mem.metadata or {}):
                    del mem.metadata["__distance__"]
        except Exception:  # best-effort: temporal scoring failure — fall back to raw rank order
            logger.debug("Temporal decay scoring failed, using rank order")
            results = results[:limit]

        # ── 4. Rerank stage (opt-in) ─────────────────────────────────────
        if rerank and results:
            try:
                from memorius.reranker import rerank_search_results
                results = rerank_search_results(query, results, top_k=limit)
            except ImportError:
                logger.debug("Cross-encoder reranker not installed, skipping")
            except Exception:  # best-effort: reranker failure — keep original similarity order
                logger.debug("Reranking failed, keeping original order")

        # ── 5. Graph expansion (opt-in) ──────────────────────────────────
        if expand_graph and results:
            expanded = self._expand_from_graph(
                results, vault=vault, hops=graph_hops,
                min_weight=graph_min_weight,
                max_extra=max(0, math.ceil(limit * 1.5) - len(results)),
            )
            if expanded:
                results = results + expanded

        return results

    def _expand_from_graph(
        self,
        seeds: list[Memory],
        vault: str | None,
        hops: int,
        min_weight: float,
        max_extra: int,
    ) -> list[Memory]:
        """Walk the knowledge graph from ``seeds`` and return linked memories
        not already present in ``seeds``."""
        if max_extra <= 0 or not seeds:
            return []
        try:
            self._meta.init_graph()
            res = self._meta.expand_graph(
                [m.id for m in seeds], hops=max(1, hops),
                min_weight=min_weight, max_nodes=max_extra,
            )
            expanded_ids = list(res.expanded_ids)
        except Exception:  # best-effort: graph expansion failure — return empty, not an error
            logger.debug("Graph expansion failed (best-effort)")
            return []
        if not expanded_ids:
            return []
        # Fetch and filter
        from memorius.vault import VaultEngine  # avoid circular
        # Use meta to fetch by IDs — lightweight, no vectors
        metas = self._meta.get_memory_meta_batch(expanded_ids)
        seed_ids = {m.id for m in seeds}
        out: list[Memory] = []
        for mid, meta in metas.items():
            if mid in seed_ids:
                continue
            if vault is not None and meta.get("vault") != vault:
                continue
            # Build a lightweight Memory from meta only (no vector)
            out.append(Memory(
                id=mid,
                vault=meta.get("vault", ""),
                shelf=meta.get("shelf", ""),
                folder=meta.get("folder", ""),
                note=meta.get("note", ""),
                content=meta.get("content", ""),
                metadata={},
                created_at=meta.get("created_at", ""),
                updated_at=meta.get("updated_at", ""),
                vector=None,
            ))
            if len(out) >= max_extra:
                break
        return out
