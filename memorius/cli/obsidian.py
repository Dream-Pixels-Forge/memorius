"""memorius obsidian — integrate with Obsidian vaults.

Import notes from an Obsidian vault into memorius, export memories
as Obsidian markdown, or explore vault structure.

Usage:
  memorius obsidian list [--vault ~/Obsidian]              # list notes in vault
  memorius obsidian import [--vault ~/Obsidian]             # import notes as memories
  memorius obsidian export [--vault ~/Obsidian]             # export memories as notes
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from memorius.vault import VaultEngine

logger = logging.getLogger("memorius.obsidian")

# ── Helpers ──────────────────────────────────────────────────────────────────

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

OBSIDIAN_VAULT_HINT = (
    "Set $OBSIDIAN_VAULT_PATH or pass --vault. "
    "Default: ~/Documents/Obsidian Vault"
)


def _resolve_vault_path(vault_arg: str | None) -> Path:
    """Resolve the Obsidian vault path from arg, env var, or default."""
    raw = vault_arg or Path.home().as_posix() + "/Documents/Obsidian Vault"
    path = Path(raw).expanduser().resolve()
    return path


def _yaml_safe(v: Any) -> str:
    """Convert a Python value to a YAML-safe inline string."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_yaml_safe(x) for x in v) + "]"
    # String — wrap if it contains special chars
    s = str(v)
    if any(c in s for c in (":", "#", "{", "}", "[", "]", ",", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`", '"', "'")):
        return repr(s)
    return s


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and body from an Obsidian markdown file.

    Returns (frontmatter_dict, body_text). Frontmatter is empty dict if absent.
    Frontmatter keys are lowercased for consistency.
    """
    m = FRONTMATTER_RE.match(content)
    if not m:
        return {}, content.strip()

    raw_yaml = m.group(1)
    body = content[m.end() :].strip()

    # Minimal YAML parse (supports only key: value, no nested structures)
    meta: dict[str, Any] = {}
    for line in raw_yaml.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip().lower()
            val = val.strip()
            # Try basic type coercion
            if val in ("true", "True"):
                meta[key] = True
            elif val in ("false", "False"):
                meta[key] = False
            elif val and val[0] in ("'", '"') and val[-1] == val[0]:
                meta[key] = val[1:-1]
            else:
                meta[key] = val
    return meta, body


def _make_wikilink(title: str) -> str:
    """Create an Obsidian-compatible wikilink from a title."""
    return f"[[{title}]]"


def _guess_title(content: str) -> str:
    """Guess a title from markdown content — first # heading or first line."""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    first = content.splitlines()[0] if content.splitlines() else "untitled"
    return first[:80]


# ── Core logic ───────────────────────────────────────────────────────────────


def list_notes(vault_path: Path) -> list[dict[str, Any]]:
    """List all .md notes in the Obsidian vault with metadata."""
    if not vault_path.is_dir():
        logger.warning(f"Vault not found: {vault_path}")
        return []

    notes: list[dict[str, Any]] = []
    for md_file in sorted(vault_path.rglob("*.md")):
        relative = md_file.relative_to(vault_path)
        stat = md_file.stat()
        notes.append({
            "path": str(md_file),
            "relative": str(relative),
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "folder": str(relative.parent) if relative.parent != Path(".") else "/",
        })
    return notes


def import_notes(
    vault_path: Path,
    engine: VaultEngine,
    target_vault: str = "main",
    target_shelf: str = "obsidian",
    dry_run: bool = False,
    tag_filter: str | None = None,
) -> int:
    """Import Obsidian notes as memorius memories.

    Returns count of imported notes.
    """
    if not vault_path.is_dir():
        print(f"Error: Obsidian vault not found: {vault_path}")
        print(f"  {OBSIDIAN_VAULT_HINT}")
        return 0

    count = 0
    for md_file in sorted(vault_path.rglob("*.md")):
        # Skip hidden dirs
        if any(p.startswith(".") for p in md_file.relative_to(vault_path).parts):
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"Skipping {md_file}: {e}")
            continue

        meta, body = _parse_frontmatter(content)

        # Apply tag filter if set
        if tag_filter:
            tags = meta.get("tags", "")
            if isinstance(tags, str):
                tag_list = [t.strip().lstrip("#") for t in tags.replace(",", " ").split()]
            else:
                tag_list = tags if isinstance(tags, list) else [str(tags)]
            if tag_filter not in tag_list:
                continue

        # Determine vault/shelf/folder/note from file hierarchy
        relative = md_file.relative_to(vault_path)
        parts = list(relative.parts)
        folder_path = "/".join(parts[:-1]) if parts[:-1] else "root"
        note_name = parts[-1].replace(".md", "") if parts else "untitled"

        # Title from frontmatter or content
        title = meta.get("title", _guess_title(body or content))

        if dry_run:
            print(f"  [DRY RUN] Would import: {relative} -> {target_vault}/{target_shelf}/{folder_path}/{note_name}")
            count += 1
            continue

        # Use body if available, otherwise full content without frontmatter
        store_content = body if body else content
        if not store_content.strip():
            continue

        # Build metadata
        metadata = dict(meta)
        metadata["source"] = "obsidian"
        metadata["obsidian_path"] = str(relative)
        metadata["obsidian_title"] = title

        memory = engine.store(
            content=store_content,
            vault=target_vault,
            shelf=target_shelf,
            folder=folder_path,
            note=note_name,
            metadata=metadata,
        )
        count += 1

        if count <= 5:
            print(f"  Imported: {relative} -> {target_vault}/{target_shelf}/{folder_path}/{note_name}")

    print(f"\nImported {count} notes from Obsidian vault '{vault_path.name}'")
    return count


def export_memories(
    vault_path: Path,
    engine: VaultEngine,
    source_vault: str = "main",
    source_shelf: str | None = None,
    dry_run: bool = False,
) -> int:
    """Export memorius memories as Obsidian markdown notes.

    Returns count of exported memories.
    """
    if not vault_path.is_dir():
        print(f"Error: Obsidian vault not found: {vault_path}")
        print(f"  {OBSIDIAN_VAULT_HINT}")
        return 0

    export_dir = vault_path / "memorius-export"
    count = 0

    # Get all memories — search with empty query to get everything
    # We search by vault/shelf since we can't list all memories directly
    vaults = engine._meta.list_vaults()
    target_vaults = [v["name"] for v in vaults if v["name"] == source_vault]

    for vname in target_vaults:
        shelves = engine._meta.list_shelves(vname)
        for sh in shelves:
            if source_shelf and sh["name"] != source_shelf:
                continue

            folders = engine._meta.list_folders(vname, sh["name"])
            for f in folders:
                notes = engine._meta.list_notes(vname, sh["name"], f["name"])
                for n in notes:
                    if dry_run:
                        print(f"  [DRY RUN] Would export: {vname}/{sh['name']}/{f['name']}/{n['name']} ({n['memory_count']} memories)")
                        count += 1
                        continue

                    # Get memories in this note
                    results = engine.search(
                        query="",
                        vault=vname,
                        shelf=sh["name"],
                        limit=n["memory_count"] or 50,
                    )

                    # Skip if no memories found
                    if not results:
                        continue

                    # Build output path mirroring hierarchy
                    note_subdir = export_dir / sh["name"] / f["name"]
                    note_subdir.mkdir(parents=True, exist_ok=True)
                    note_file = note_subdir / f"{n['name']}.md"

                    # Build Obsidian note content
                    lines = ["---"]
                    lines.append(f'title: "{n["name"]}"')
                    lines.append(f"source_vault: {vname}")
                    lines.append(f"shelf: {sh['name']}")
                    lines.append(f"folder: {f['name']}")
                    lines.append("source: memorius")
                    lines.append("---")
                    lines.append("")

                    if n.get("description"):
                        lines.append(f"# {n['description']}")
                        lines.append("")

                    for mem in results:
                        lines.append(mem.content)
                        lines.append("")
                        lines.append("---")
                        lines.append("")

                    note_file.write_text("\n".join(lines), encoding="utf-8")
                    count += 1

                    if count <= 5:
                        print(f"  Exported: {vname}/{sh['name']}/{f['name']}/{n['name']} -> {note_file}")

    print(f"\nExported {count} notes to '{export_dir}'")
    return count


# ── CLI dispatch ─────────────────────────────────────────────────────────────


def cmd_obsidian(engine: VaultEngine, args: Any, config: dict[str, Any]) -> int:
    """Dispatch obsidian subcommands."""
    vault_path = _resolve_vault_path(args.obsidian_vault)

    if args.subcommand == "list":
        notes = list_notes(vault_path)
        if not notes:
            print(f"No notes found in vault: {vault_path}")
            print(f"  {OBSIDIAN_VAULT_HINT}")
            return 0

        print(f"Obsidian vault: {vault_path}")
        print(f"Total notes: {len(notes)}")
        print()

        # Group by top-level folder
        folders: dict[str, int] = {}
        for n in notes:
            top = n["folder"].split("/")[0] if n["folder"] != "/" else "(root)"
            folders[top] = folders.get(top, 0) + 1

        for folder, count in sorted(folders.items()):
            print(f"  {folder}/  ({count} notes)")

        # Show recent files
        print("\nRecent notes (10):")
        for n in sorted(notes, key=lambda x: x["modified"], reverse=True)[:10]:
            print(f"  {n['relative']}  ({n['size']}B)")

        return 0

    elif args.subcommand == "import":
        tag_filter = args.tag
        return import_notes(
            vault_path,
            engine,
            target_vault=args.target_vault or "main",
            target_shelf=args.target_shelf or "obsidian",
            dry_run=args.dry_run,
            tag_filter=tag_filter,
        )

    elif args.subcommand == "export":
        return export_memories(
            vault_path,
            engine,
            source_vault=args.source_vault or "main",
            source_shelf=args.source_shelf,
            dry_run=args.dry_run,
        )

    else:
        print(f"Unknown obsidian subcommand: {args.subcommand}")
        return 1
