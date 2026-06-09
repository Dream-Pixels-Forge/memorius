"""Shared data models for memorius."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Memory:
    """A single memory item stored in a note."""
    id: str
    vault: str
    shelf: str
    folder: str
    note: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    vector: list[float] | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.id,
            "vault": self.vault,
            "shelf": self.shelf,
            "folder": self.folder,
            "note": self.note,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.vector is not None:
            d["vector"] = self.vector
        return d
