# memorius skill

Agent skill for [memorius](https://github.com/Dream-Pixels-Forge/memorius) — a local-first memory vault
for AI agents. It teaches the agent **when** to capture and recall (always with the user's consent),
**which** command or MCP tool to use, and how to report results honestly. See [`SKILL.md`](SKILL.md).

## Install

```bash
pip install memorius
memorius init
npx skills add github.com/Dream-Pixels-Forge/memorius/tree/main/skills/memorius
```

Optional — connect the MCP server so the agent can use `memorius_*` tools directly:

```bash
claude mcp add memorius -- memorius serve
```

## Command summary

| Area | Commands |
|---|---|
| Store | `store`, `learn`, `update` |
| Recall | `search`, `context`, `recall`, `factcheck`, `get`, `list`, `ls`, `learnings`, `web` |
| Sessions | `diary`, `diaries`, `profile` |
| Ingest | `mine`, `extract`, `obsidian list/import/export`, `memorius-normalize` |
| Maintenance | `stats`, `status`, `doctor`, `consolidate`, `prune`, `repair`, `delete`, `export`, `import`, `graph` |
| Servers | `serve` (MCP stdio), `serve-rest`, `bookcase` |
| Hooks | `memorius-hook run/init-config/status`, `memorius-plugin-gen list/init/generate` |

Run `memorius <command> --help` for the authoritative flags.

## Hierarchy

```
vault/            e.g. main
  shelf/          e.g. decisions, bugs, preferences, projects
    folder/       e.g. acme-api
      note        individual memory (default: "default")
```
