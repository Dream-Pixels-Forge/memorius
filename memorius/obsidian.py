"""Shared Obsidian integration helpers.

Used by both the REST server and the CLI to avoid circular imports.
Functions here are pure utilities — no CLI or server dependencies.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def resolve_vault_path(vault_arg: str | None = None) -> Path:
    """Resolve the Obsidian vault path from arg, env var, or default.

    Security note: This resolves the path but does NOT restrict it.
    Callers (REST API, CLI) should add their own path validation as needed.
    For example, the REST API checks that the path is within the home directory.
    """
    raw = (
        vault_arg
        or os.environ.get("OBSIDIAN_VAULT_PATH")
        or Path.home().as_posix() + "/Documents/Obsidian Vault"
    )
    return Path(raw).expanduser().resolve()


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and body from an Obsidian markdown file.

    Returns (frontmatter_dict, body_text).
    """
    m = FRONTMATTER_RE.match(content)
    if not m:
        return {}, content.strip()

    raw_yaml = m.group(1)
    body = content[m.end():].strip()

    meta: dict[str, Any] = {}
    for line in raw_yaml.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip().lower()
            val = val.strip()
            if val in ("true", "True"):
                meta[key] = True
            elif val in ("false", "False"):
                meta[key] = False
            elif val and val[0] in ("'", '"') and val[-1] == val[0]:
                meta[key] = val[1:-1]
            else:
                meta[key] = val
    return meta, body


def scan_vault(vault_path: Path) -> list[dict[str, Any]]:
    """List all .md notes in an Obsidian vault with metadata."""
    if not vault_path.is_dir():
        return []

    notes: list[dict[str, Any]] = []
    for md_file in sorted(vault_path.rglob("*.md")):
        relative = md_file.relative_to(vault_path)
        # Skip hidden dirs
        if any(p.startswith(".") for p in relative.parts):
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        meta, _ = parse_frontmatter(content)
        stat = md_file.stat()

        # Extract tags from frontmatter
        tags_raw = meta.get("tags", "")
        if isinstance(tags_raw, str):
            tags = [t.strip().lstrip("#") for t in tags_raw.replace(",", " ").split() if t.strip()]
        elif isinstance(tags_raw, list):
            tags = [str(t) for t in tags_raw]
        else:
            tags = []

        folder = str(relative.parent) if relative.parent != Path(".") else "/"

        notes.append({
            "name": md_file.stem,
            "path": str(md_file),
            "relative": str(relative),
            "folder": folder,
            "tags": tags,
            "size": stat.st_size,
            "modified": stat.st_mtime,
        })
    return notes


def parse_note(file_path: str | Path) -> str:
    """Read an Obsidian note and return the body (without frontmatter)."""
    path = Path(file_path)
    if not path.is_file():
        return ""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    _, body = parse_frontmatter(content)
    return body
