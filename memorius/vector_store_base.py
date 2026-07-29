"""Abstract base class for vector stores.

Defines the interface that ChromaStore and SqliteVecStore both implement.
This enables swappable backends with a single API surface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VectorStore(ABC):
    """Abstract vector store — all backends must implement these methods."""

    @abstractmethod
    def add(self, memory: Any) -> None:
        """Add or update a memory in vector storage."""
        ...

    @abstractmethod
    def delete(self, memory_id: str, vault: str, shelf: str) -> None:
        """Delete a memory by ID within a vault/shelf."""
        ...

    @abstractmethod
    def search(
        self,
        query: str,
        vault: str | None = None,
        shelf: str | None = None,
        n_results: int = 10,
        filter_metadata: dict[str, str] | None = None,
    ) -> list:
        """Search memories by semantic similarity. Returns list of Memory objects."""
        ...

    @abstractmethod
    def get_collections(self) -> list[dict[str, str]]:
        """List all vault/shelf combos with counts."""
        ...

    @abstractmethod
    def count(self, vault: str | None = None, shelf: str | None = None) -> int:
        """Count memories."""
        ...

    @abstractmethod
    def get_by_ids(
        self,
        ids: list[str],
        vault: str,
        shelf: str,
        include_vectors: bool = True,
    ) -> list:
        """Fetch memories by id from a specific (vault, shelf) collection."""
        ...
