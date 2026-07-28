"""Optional cross-encoder reranker for memorius.

Reranks search results by query-document relevance using a small
cross-encoder model.  Install via ``pip install memorius[ranker]``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("memorius.reranker")


class CrossEncoderReranker:
    """Lightweight cross-encoder reranker backed by sentence-transformers."""

    _DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or self._DEFAULT_MODEL
        self._model = None  # lazy

    def _lazy_load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed. "
                "Install: pip install memorius[ranker]"
            )
        self._model = CrossEncoder(self._model_name)

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[tuple[int, float]]:
        """Rerank documents by relevance to *query*.

        Returns a list of ``(original_index, score)`` tuples sorted by
        descending score.  If *top_k* is given, only the top-k are
        returned.
        """
        if not documents:
            return []

        self._lazy_load()

        pairs = [(query, doc) for doc in documents]
        scores = self._model.predict(pairs)

        ranked = sorted(
            enumerate(scores), key=lambda x: float(x[1]), reverse=True
        )
        if top_k is not None:
            ranked = ranked[:top_k]
        return ranked


# Module-level singleton (lazy)
_reranker: CrossEncoderReranker | None = None


def get_reranker(model_name: str | None = None) -> CrossEncoderReranker:
    """Return the global reranker, creating it on first call.

    If a *model_name* is given that differs from the already-loaded
    singleton, a warning is logged and the original model is reused.
    """
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoderReranker(model_name)
    elif model_name and model_name != _reranker._model_name:
        logger.warning(
            "Reranker already loaded with model '%s'; "
            "ignoring requested model '%s'",
            _reranker._model_name,
            model_name,
        )
    return _reranker


def reset_reranker() -> None:
    """Reset the global singleton (for testing only)."""
    global _reranker
    _reranker = None


def rerank_search_results(
    query: str,
    memories: list,
    top_k: int | None = None,
    model_name: str | None = None,
) -> list:
    """Rerank a list of Memory objects by query relevance.

    Returns a **new** list reordered by cross-encoder score.  Each
    memory's ``metadata`` dict is updated with a ``__rerank_score__``
    key (this mutates the individual Memory objects, not the list).
    """
    if not memories:
        return []

    reranker = get_reranker(model_name)
    documents = [m.content for m in memories]
    ranked = reranker.rerank(query, documents, top_k=top_k)

    reordered = []
    for orig_idx, score in ranked:
        mem = memories[orig_idx]
        if mem.metadata is None:
            mem.metadata = {}
        mem.metadata["__rerank_score__"] = float(score)
        reordered.append(mem)
    return reordered
