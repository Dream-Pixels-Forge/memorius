# Memorius

**Universal memory adapter for AI agents.** Hook lifecycle, REST gateway, and plugin manifest system that bridges **any AI agent** to memory backends like [MemPalace](https://github.com/mempalace/mempalace).

## What is Memorius?

AI coding agents (Claude Code, Codex, Gemini, Cursor, etc.) need persistent memory between sessions — past decisions, project context, user preferences. Each agent has its own hook protocol, plugin format, and transport.

**Memorius is the universal adapter layer.** One integration config, every agent works.

| Problem | Memorius Solution |
|---|---|
| Each agent has its own hook JSON schema | Universal hook lifecycle — `memorius-hook` auto-detects any agent |
| Duplicate plugin dirs per agent | One `manifest.yaml` → `memorius-plugin-gen` generates all plugins |
| MCP server is stdio-only | `memorius-serve` wraps it in HTTP REST (use with curl, browser, scripts) |
| Limited chat format support | `memorius-normalize` adds Discord, Telegram, WhatsApp importers |

## CLI Tools

### `memorius-hook` — Universal Hook Lifecycle

Reads any agent's hook JSON from stdin, auto-detects the agent, and executes configured actions.

```bash
# Works with Claude Code, Codex, Gemini, and more:
echo '{"session_id":"..."}' | memorius-hook run --event stop
```

Auto-detection: **Claude Code**, **Codex CLI**, **Gemini CLI**, **OpenClaw**, plus generic fallback.

### `memorius-serve` — REST Gateway

HTTP API wrapping MemPalace's MCP server. 20+ endpoints. OpenAPI docs.

```bash
memorius-serve --port 8912
curl http://localhost:8912/search?q="auth decisions"
curl http://localhost:8912/status
```

### `memorius-plugin-gen` — Universal Plugin Generator

One `manifest.yaml` → generates `.claude-plugin/`, `.codex-plugin/`, `.cursor/mcp.json`, OpenClaw skill, and more.

```bash
memorius-plugin-gen init          # create skeleton manifest
memorius-plugin-gen generate       # generate plugins for all agents
memorius-plugin-gen list           # 7+ known agent targets
```

### `memorius-normalize` — Chat Format Importer

Import conversations from any source into the palace.

```bash
memorius-normalize detect export.json
memorius-normalize convert discord-export.json
memorius-normalize batch ./chat-exports/
memorius-normalize pipe < export.json
```

Supported formats: **Discord**, **Telegram**, **WhatsApp**, **Generic JSON** (any `{role,content}` format).

## Installation

```bash
pip install memorius                     # core: hooks + plugin gen + normalizers
pip install "memorius[gateway]"          # with REST gateway
```

Or from source:

```bash
git clone https://github.com/Dream-Pixels-Forge/memorius.git
cd memorius
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,gateway]"
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│              Any AI Agent                       │
│  Claude Code │ Codex │ Gemini │ Cursor │ curl   │
└─────────┬────────┬──────────┬────────┬──────────┘
          │        │          │        │
     ┌────┘   ┌────┘    ┌────┘   ┌────┘
     ▼        ▼         ▼        ▼
┌────────┐ ┌────────┐ ┌──────┐ ┌───────────┐
│        │ │        │ │      │ │           │
│ Hook   │ │ REST   │ │Plugin│ │ Normalizer│
│ Engine │ │Gateway │ │ Gen  │ │           │
│        │ │        │ │      │ │           │
└───┬────┘ └───┬────┘ └──┬───┘ └─────┬─────┘
    │          │         │           │
    └──────┬───┘         │           │
           │             │           │
      ┌────▼─────────────▼───────────▼──┐
      │      Memory Backend            │
      │  (MemPalace, ChromaDB, KG)     │
      └────────────────────────────────┘
```

## Quick Start

```bash
# 1. Generate plugins for all your agents
cd /your/project
memorius-plugin-gen generate

# 2. Start the REST gateway (if you have MemPalace installed)
memorius-serve

# 3. Test it
curl http://localhost:8912/health
```

## Contributing

Pull requests welcome! Ideas:
- **More agent adapters** — Cline, Roo Code, Continue.dev direct hooks
- **More normalizers** — Slack exports, Matrix, Zulip
- **Web UI** — dashboard for the REST gateway
- **More backends** — support LanceDB, SQLite, filesystem backends

## License

MIT
