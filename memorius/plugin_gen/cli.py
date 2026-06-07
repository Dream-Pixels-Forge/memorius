"""
Universal Plugin Manifest — single source of truth for all agent plugins.

The problem:
  Memorius maintains three near-identical plugin directories:
  .claude-plugin/, .codex-plugin/, .agents/plugins/. Adding support for
  a new agent requires duplicating the same skeleton.

The solution:
  One universal-manifest.yaml that describes the integration once, then
  `memorius-plugin-gen` generates the per-agent plugin directories.

Usage:
  memorius-plugin-gen generate           # generate from universal-manifest.yaml
  memorius-plugin-gen generate --watch   # watch for changes and regenerate
  memorius-plugin-gen list               # list known agent targets
  memorius-plugin-gen init               # create a skeleton universal-manifest.yaml

Universal manifest format:

  name: memorius
  version: 0.1.0
  description: "Memorius — universal memory vault for any AI agent."
  author: "dimonapatrick243"
  license: MIT
  repository: https://github.com/Dream-Pixels-Forge/memorius

  # MCP server config (shared across all agents)
  mcp:
    command: memorius
    args: [serve]

  # Agent-specific configurations
  agents:
    claude-code:
      hooks:
        stop:
          timeout: 30
        precompact:
          timeout: 90
      skills: true
      marketplace: true
      plugin_json:
        commands: []

    codex:
      hooks:
        session-start: {}
        stop:
          timeout: 30
        precompact:
          timeout: 30
      skills: true
      display_name: "Memorius"
      brand_color: "#7C3AED"

    cursor:
      mcp_only: true
      config_file: .cursor/mcp.json

    gemini-cli:
      hooks:
        precompress: {}
      config_dir: "~/.gemini"

    openclaw:
      mcp_only: true
      skill: true
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

from memorius import __version__ as _MEMORIUS_VERSION


DEFAULT_MANIFEST = """\
# Memorius Universal Plugin Manifest
# One source of truth for all agent integrations.
# Run: memorius-plugin-gen generate

name: memorius
version: "0.1.0"
description: "Memorius — universal memory vault for any AI agent — hooks, MCP, and memory protocol."
author: "dimonapatrick243"
license: MIT
repository: "https://github.com/Dream-Pixels-Forge/memorius"
homepage: "https://github.com/Dream-Pixels-Forge/memorius"

# MCP server shared across all agents
mcp:
  command: memorius
  args: [serve]

# Agent-specific hooks and plugin configurations
agents:
  claude-code:
    hooks:
      stop:
        timeout: 30
      precompact:
        timeout: 90
    skills: true
    marketplace: true
    install:
      - "claude mcp add memorius -- memorius serve"
      - "claude plugin install memorius"

  codex:
    hooks:
      session-start:
        timeout: 15
      stop:
        timeout: 30
      precompact:
        timeout: 30
    skills: true
    display_name: "Memorius"
    brand_color: "#7C3AED"
    install:
      - "codex mcp add memorius -- memorius serve"

  gemini-cli:
    hooks:
      precompress:
        timeout: 30
    install:
      - "gemini mcp add memorius $(which memorius) serve"

  cursor:
    mcp_only: true
    config_file: ".cursor/mcp.json"
    install:
      - "Add to .cursor/mcp.json: {\\\"mcpServers\\\": {\\\"memorius\\\": {\\\"command\\\": \\\"memorius\\\", \\\"args\\\": [\\\"serve\\\"]}}}"

  openclaw:
    mcp_only: true
    skill: true
    install:
      - "openclaw mcp set memorius '{\\\"command\\\":\\\"memorius\\\",\\\"args\\\":[\\\"serve\\\"]}'"

  aider:
    mcp_only: true
    config_file: ".aider.mcp.json"
    install:
      - "aider --mcp-servers memorius=memorius serve"

  continue:
    mcp_only: true
    config_file: ".continue/config.json"
    install:
      - "Add memorius to .continue/config.json MCP servers"
"""


def _load_manifest(path: str | Path) -> dict:
    """Load the universal manifest YAML."""
    path = Path(path).expanduser()
    if not path.exists():
        print(f"Manifest not found: {path}")
        print("Run: memorius-plugin-gen init")
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _ensure_dir(path: Path):
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)


def generate_claude_plugin(manifest: dict, output_dir: Path):
    """Generate .claude-plugin/ directory."""
    plugin_dir = output_dir / ".claude-plugin"
    _ensure_dir(plugin_dir)

    name = manifest.get("name", "memorius")
    version = manifest.get("version", _MEMORIUS_VERSION)
    description = manifest.get("description", "AI memory system")
    repository = manifest.get("repository", "")
    agent_cfg = manifest.get("agents", {}).get("claude-code", {})

    # plugin.json
    plugin_json = {
        "name": name,
        "version": version,
        "description": description,
        "author": {"name": manifest.get("author", "")},
        "license": manifest.get("license", "MIT"),
        "commands": agent_cfg.get("plugin_json", {}).get("commands", []),
        "mcpServers": {
            name: {
                "command": manifest.get("mcp", {}).get("command", "memorius"),
            "args": manifest.get("mcp", {}).get("args", ["serve"]),
        }
        },
        "keywords": ["memory", "ai", "rag", "mcp", "chromadb", "vault", "search"],
        "repository": repository,
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(plugin_json, indent=4) + "\n")

    # .mcp.json
    mcp_json = {
        name: {
            "command": manifest.get("mcp", {}).get("command", "memorius-mcp"),
        }
    }
    (plugin_dir / ".mcp.json").write_text(json.dumps(mcp_json, indent=4) + "\n")

    # marketplace.json
    marketplace_json = {
        "name": name,
        "owner": {
            "name": manifest.get("author", ""),
            "url": repository,
        },
        "plugins": [
            {
                "name": name,
                "source": "./.claude-plugin",
                "description": description,
                "version": version,
                "author": {"name": manifest.get("author", "")},
            }
        ],
    }
    (plugin_dir / "marketplace.json").write_text(json.dumps(marketplace_json, indent=4) + "\n")

    # hooks.json
    hooks_map = {
        "stop": "Stop",
        "precompact": "PreCompact",
    }
    hooks_config = agent_cfg.get("hooks", {})
    hooks_json = {"description": f"{name} auto-save hooks", "hooks": {}}

    for event_name, event_cfg in hooks_config.items():
        claude_name = hooks_map.get(event_name)
        if not claude_name:
            continue
        timeout = event_cfg.get("timeout", 30)
        hooks_json["hooks"][claude_name] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f"bash \"${{CLAUDE_PLUGIN_ROOT}}/hooks/{name}-{event_name}-hook.sh\"",
                        "timeout": timeout,
                    }
                ]
            }
        ]

    (plugin_dir / "hooks.json").write_text(json.dumps(hooks_json, indent=4) + "\n")

    # Generate hook scripts
    hooks_dir = plugin_dir / "hooks"
    _ensure_dir(hooks_dir)

    for event_name in hooks_config:
        script_content = _generate_hook_script(name, event_name, agent="claude-code")
        (hooks_dir / f"{name}-{event_name}-hook.sh").write_text(script_content)
        (hooks_dir / f"{name}-{event_name}-hook.sh").chmod(0o755)

    # Generate skills directory
    if agent_cfg.get("skills", False):
        skills_dir = plugin_dir / "skills"
        _ensure_dir(skills_dir)
        skill_content = _generate_skill_card(name)
        (skills_dir / name).write_text(skill_content)

    # Generate commands
    commands_dir = plugin_dir / "commands"
    _ensure_dir(commands_dir)
    for cmd in ["help", "init", "mine", "search", "status"]:
        cmd_content = f"# {name} {cmd} command\n"
        (commands_dir / f"{cmd}.md").write_text(cmd_content)

    print(f"  Generated: {plugin_dir}")


def generate_codex_plugin(manifest: dict, output_dir: Path):
    """Generate .codex-plugin/ directory."""
    plugin_dir = output_dir / ".codex-plugin"
    _ensure_dir(plugin_dir)

    name = manifest.get("name", "memorius")
    version = manifest.get("version", _MEMORIUS_VERSION)
    description = manifest.get("description", "AI memory system")
    repository = manifest.get("repository", "")
    agent_cfg = manifest.get("agents", {}).get("codex", {})

    # plugin.json
    plugin_json = {
        "name": name,
        "version": version,
        "description": description,
        "author": {"name": manifest.get("author", "")},
        "homepage": repository,
        "repository": repository,
        "license": manifest.get("license", "MIT"),
        "keywords": ["memory", "ai", "rag", "mcp", "chromadb", "vault", "search"],
        "skills": "./skills/",
        "hooks": "./hooks.json",
        "mcpServers": {
            name: {
                "command": manifest.get("mcp", {}).get("command", "memorius"),
            "args": manifest.get("mcp", {}).get("args", ["serve"]),
        }
        },
        "interface": {
            "displayName": agent_cfg.get("display_name", name.title()),
            "shortDescription": description[:80],
            "longDescription": description,
            "developerName": manifest.get("author", ""),
            "category": "Coding",
            "capabilities": ["Interactive", "Read", "Write"],
            "websiteURL": repository,
            "privacyPolicyURL": repository,
            "termsOfServiceURL": repository,
            "defaultPrompt": [
                "Search my memories for recent decisions",
                "Mine this project into my memory vault",
                "Show my vault status and shelf counts",
            ],
            "brandColor": agent_cfg.get("brand_color", "#7C3AED"),
        },
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(plugin_json, indent=4) + "\n")

    # hooks.json
    hooks_map = {
        "session-start": "SessionStart",
        "stop": "Stop",
        "precompact": "PreCompact",
    }
    hooks_config = agent_cfg.get("hooks", {})
    hooks_json = {"hooks": {}}

    for event_name, event_cfg in hooks_config.items():
        codex_name = hooks_map.get(event_name)
        if not codex_name:
            continue
        timeout = event_cfg.get("timeout", 30)
        hooks_json["hooks"][codex_name] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            f"\"${{CODEX_PLUGIN_ROOT}}/hooks/{name}-hook.sh\" {event_name}"
                        ),
                        "timeout": timeout,
                    }
                ]
            }
        ]

    (plugin_dir / "hooks.json").write_text(json.dumps(hooks_json, indent=4) + "\n")

    # Generate hook scripts
    hooks_dir = plugin_dir / "hooks"
    _ensure_dir(hooks_dir)
    hook_script = _generate_codex_hook_script(name)
    (hooks_dir / f"{name}-hook.sh").write_text(hook_script)
    (hooks_dir / f"{name}-hook.sh").chmod(0o755)

    # Generate skills
    if agent_cfg.get("skills", False):
        skills_dir = plugin_dir / "skills"
        _ensure_dir(skills_dir)
        skill_content = _generate_skill_card(name)
        (skills_dir / name).write_text(skill_content)

    print(f"  Generated: {plugin_dir}")


def generate_agents_plugin(manifest: dict, output_dir: Path):
    """Generate .agents/plugins/ directory."""
    plugin_dir = output_dir / ".agents" / "plugins"
    _ensure_dir(plugin_dir)

    name = manifest.get("name", "memorius")

    marketplace_json = {
        "name": name,
        "interface": {
            "displayName": name.title(),
        },
        "plugins": [
            {
                "name": name,
                "source": {
                    "source": "local",
                    "path": "./.codex-plugin",
                },
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "NONE",
                },
                "category": "Coding",
            }
        ],
    }
    (plugin_dir / "marketplace.json").write_text(json.dumps(marketplace_json, indent=4) + "\n")
    print(f"  Generated: {plugin_dir}")


def generate_cursor_config(manifest: dict, output_dir: Path):
    """Generate .cursor/mcp.json snippet."""
    name = manifest.get("name", "memorius")
    agent_cfg = manifest.get("agents", {}).get("cursor", {})
    config_file = agent_cfg.get("config_file", ".cursor/mcp.json")

    cursor_json = {
        "mcpServers": {
            name: {
                "command": manifest.get("mcp", {}).get("command", "memorius"),
            "args": manifest.get("mcp", {}).get("args", ["serve"]),
        }
        }
    }

    cursor_dir = output_dir / ".cursor"
    _ensure_dir(cursor_dir)
    (cursor_dir / "mcp.json").write_text(json.dumps(cursor_json, indent=4) + "\n")
    print(f"  Generated: {cursor_dir / 'mcp.json'}")


def generate_openclaw_skill(manifest: dict, output_dir: Path):
    """Generate OpenClaw skill."""
    skill_dir = output_dir / "integrations" / "openclaw"
    _ensure_dir(skill_dir)

    name = manifest.get("name", "memorius")
    version = manifest.get("version", _MEMORIUS_VERSION)
    repository = manifest.get("repository", "")

    skill_content = f"""---
name: {name}
description: "{manifest.get('description', 'AI memory system')} — Universal hooks, MCP, and memory protocol."
version: {version}
homepage: {repository}
user-invocable: true
metadata:
  openclaw:
    emoji: "🏛"
    os:
      - darwin
      - linux
      - win32
    requires:
      anyBins:
        - {name}
        - python3
    install:
      - id: {name}-pip
        kind: uv
        label: "Install {name.title()} (Python, local ChromaDB)"
        package: {name}
        bins:
          - {name}
---

# {name.title()} — Universal AI Memory System

## Architecture
- **Vaults** = top-level memory vaults (people, projects, domains)
- **Shelves** = broad knowledge areas
- **Folders** = specific subjects or topics
- **Notes** = individual memory chunks (verbatim text)

## Memory Protocol — Use Every Session

1. **ON START**: Call `memorius_status` to load vault overview.
2. **BEFORE ANSWERING**: Call `memorius_search` or check existing notes. Never guess.
3. **IF UNSURE**: Say "let me check" and query the vault.
4. **AFTER SESSION**: Write a diary entry with `memorius_diary_write`.
5. **WHEN FACTS CHANGE**: Invalidate old vault entries, add new ones.

## MCP Tools (29 total — search, knowledge graph, diary, etc.)

See the full list at: {repository}

## Setup

```bash
# Install
uv tool install {name}

# Initialize
{name} init ~/projects/myapp

# Mine
{name} mine ~/projects/myapp

# Connect to OpenClaw
openclaw mcp set {name} '{{"command":"python3","args":["-m","{name}.mcp_server"]}}'
```
"""
    (skill_dir / "SKILL.md").write_text(skill_content)
    print(f"  Generated: {skill_dir / 'SKILL.md'}")


def generate_readme(manifest: dict, output_dir: Path):
    """Generate auto-generated plugin README."""
    name = manifest.get("name", "memorius")
    description = manifest.get("description", "AI memory system")
    repository = manifest.get("repository", "")

    agents = manifest.get("agents", {})
    agent_list = "\n".join(
        f"  - **{k}**" + (f" — hooks: {', '.join(v.get('hooks', {}).keys())}" if v.get("hooks") else " — MCP only")
        for k, v in agents.items()
    )

    readme = f"""# {name.title()} Agent Plugins

{description}

This directory is auto-generated from `universal-manifest.yaml`.
Do not edit manually — regenerate with: `memorius-plugin-gen generate`

## Supported Agents

{agent_list}

## MCP Server

Command: `{manifest.get('mcp', {}).get('command', 'memorius')}` + `{' '.join(manifest.get('mcp', {}).get('args', ['serve']))}`

## Regenerate

```bash
memorius-plugin-gen generate
```

See: {repository}
"""
    (output_dir / "AGENT_PLUGINS_README.md").write_text(readme)
    print(f"  Generated: {output_dir / 'AGENT_PLUGINS_README.md'}")


# Helpers


def _generate_hook_script(name: str, event: str, agent: str = "claude-code") -> str:
    """Generate a hook shell script wrapper."""
    import re as _re

    universal_hook = shutil.which("memorius-hook") or "memorius-hook"

    # Sanitize values to prevent shell injection
    # Only allow alphanumeric, hyphens, and underscores
    _SAFE_RE = _re.compile(r'^[a-zA-Z0-9_\-]+$')
    if not _SAFE_RE.match(name):
        name = _SAFE_RE.sub('', name) or "unnamed"
    if not _SAFE_RE.match(event):
        event = _SAFE_RE.sub('', event) or "unknown"
    if not _SAFE_RE.match(agent):
        agent = _SAFE_RE.sub('', agent) or "unknown"

    return f"""#!/bin/bash
# {name.title()} {event} hook — auto-generated for {agent}
# Uses the universal hook lifecycle engine.

set -euo pipefail

# ── Resolve the universal hook engine ──
UNIVERSAL_HOOK="{universal_hook}"
if ! command -v "$UNIVERSAL_HOOK" >/dev/null 2>&1; then
    # Fallback to python -m
    UNIVERSAL_HOOK="python3 -m memorius.hooks.cli"
fi

# ── Read stdin (the agent's JSON payload) ──
INPUT=$(cat)

# ── Run through universal lifecycle engine ──
echo "$INPUT" | $UNIVERSAL_HOOK run --event {event} --agent {agent}
"""


def _generate_codex_hook_script(name: str) -> str:
    """Generate a combined Codex hook script."""
    import re as _re

    universal_hook = shutil.which("memorius-hook") or "memorius-hook"

    # Sanitize name to prevent shell injection
    _SAFE_RE = _re.compile(r'^[a-zA-Z0-9_\-]+$')
    if not _SAFE_RE.match(name):
        name = _SAFE_RE.sub('', name) or "unnamed"

    return f"""#!/usr/bin/env bash
# {name.title()} hook — auto-generated for Codex CLI
# Single script dispatched by hooks.json with the hook name as $1

set -euo pipefail
HOOK_NAME="${{1:?Usage: {name}-hook.sh <hook-name>}}"
INPUT_FILE=$(mktemp) || {{ echo "Failed to create temp file" >&2; exit 1; }}
cat > "$INPUT_FILE"
cat "$INPUT_FILE" | {universal_hook} run --event "$HOOK_NAME" --agent codex
EXIT_CODE=$?
rm -f "$INPUT_FILE" 2>/dev/null
exit $EXIT_CODE
"""


def _generate_skill_card(name: str) -> str:
    """Generate a skill card for the agent."""
    return f"""You have access to a memory vault via MCP tools.

Key rules:
1. Call `memorius_search` before answering questions about past work.
2. Call `memorius_status` at session start.
3. Write diary entries after each session via `memorius_diary_write`.
4. Never guess from training data when you can verify from the vault.
"""


# CLI commands


def cmd_list(args: list[str]):
    """List known agent targets."""
    known = {
        "claude-code": ".claude-plugin/ (marketplace plugin, hooks, skills)",
        "codex": ".codex-plugin/ (native Codex plugin, hooks, skills)",
        "cursor": ".cursor/mcp.json (MCP config)",
        "gemini-cli": "Gemini CLI hooks + MCP config guide",
        "openclaw": "integrations/openclaw/SKILL.md",
        "aider": ".aider.mcp.json (MCP config)",
        "continue": ".continue/config.json (MCP config)",
    }
    print("Known agent plugin targets:\n")
    for agent, desc in known.items():
        print(f"  {agent:15s}  {desc}")


def cmd_init(args: list[str]):
    """Create a skeleton universal-manifest.yaml."""
    output_dir = Path.cwd()
    if args and args[0]:
        output_dir = Path(args[0])

    manifest_path = output_dir / "universal-manifest.yaml"
    if manifest_path.exists():
        print(f"Manifest already exists: {manifest_path}")
        return 1

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(DEFAULT_MANIFEST)
    print(f"Created skeleton manifest: {manifest_path}")
    return 0


def cmd_generate(args: list[str]):
    """Generate all plugin directories from an agent manifest."""
    import argparse

    parser = argparse.ArgumentParser("memorius-plugin-gen generate")
    parser.add_argument("--manifest", default="universal-manifest.yaml",
                        help="Path to universal-manifest.yaml")
    parser.add_argument("--output", default=".",
                        help="Output directory for generated plugins")
    parser.add_argument("--targets", nargs="*", default=None,
                        help="Specific agents to generate (default: all)")
    parser.add_argument("--watch", action="store_true",
                        help="Watch for changes and regenerate")

    parsed = parser.parse_args(args)

    manifest_path = Path(parsed.manifest)
    output_dir = Path(parsed.output)

    manifest = _load_manifest(manifest_path)
    targets = parsed.targets or list(manifest.get("agents", {}).keys())
    all_targets = list(manifest.get("agents", {}).keys())

    print(f"Generating plugins from: {manifest_path}")
    print(f"Target agents: {', '.join(targets)}\n")

    generators = {
        "claude-code": generate_claude_plugin,
        "codex": generate_codex_plugin,
        "cursor": generate_cursor_config,
        "openclaw": generate_openclaw_skill,
    }

    for agent in targets:
        gen = generators.get(agent)
        if gen:
            print(f"[{agent}]")
            gen(manifest, output_dir)
        else:
            print(f"[{agent}] (generator not available — config guide only)")

    # Always generate agents plugin marketplace
    if "codex" in all_targets or "claude-code" in all_targets:
        generate_agents_plugin(manifest, output_dir)

    # Generate auto-readme
    generate_readme(manifest, output_dir)

    print(f"\nDone. Generated plugins for {len(targets)} agent(s).")

    if parsed.watch:
        print("\nWatch mode: Monitoring manifest for changes (Ctrl+C to stop)...")
        import time
        last_mtime = manifest_path.stat().st_mtime
        try:
            while True:
                time.sleep(2)
                current_mtime = manifest_path.stat().st_mtime
                if current_mtime != last_mtime:
                    print(f"\n[{time.strftime('%H:%M:%S')}] Manifest changed, regenerating...")
                    manifest = _load_manifest(manifest_path)
                    targets = parsed.targets or list(manifest.get("agents", {}).keys())
                    all_targets = list(manifest.get("agents", {}).keys())
                    
                    for agent in targets:
                        gen = generators.get(agent)
                        if gen:
                            print(f"[{agent}]")
                            gen(manifest, output_dir)
                        else:
                            print(f"[{agent}] (generator not available — config guide only)")
                    
                    if "codex" in all_targets or "claude-code" in all_targets:
                        generate_agents_plugin(manifest, output_dir)
                    generate_readme(manifest, output_dir)
                    print(f"Done. Regenerated plugins for {len(targets)} agent(s).")
                    last_mtime = current_mtime
        except KeyboardInterrupt:
            print("\nWatch mode stopped.")


def main():
    """Main entry point for memorius-plugin-gen."""
    import argparse

    parser = argparse.ArgumentParser(
        "memorius-plugin-gen",
        description="Universal plugin manifest → per-agent plugin generator",
    )
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list", help="List known agent targets")
    subparsers.add_parser("init", help="Create skeleton universal-manifest.yaml")
    subparsers.add_parser("generate", help="Generate all plugins from manifest")

    args, remaining = parser.parse_known_args()

    if args.version:
        print(f"memorius-plugin-gen v{_MEMORIUS_VERSION}")
        return 0

    if args.command == "list":
        cmd_list(remaining)
    elif args.command == "init":
        cmd_init(remaining)
    elif args.command == "generate":
        cmd_generate(remaining)
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    main()
