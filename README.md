# Memorius

**Universal memory palace for any AI agent.**

Memorius is a self-contained, agent-agnostic memory system that gives LLMs and AI agents persistent, searchable memory with a hierarchical knowledge organization. Drop-in replacement for MemPalace with multi-backend vector storage, pluggable embeddings, built-in MCP + REST servers, and agent-agnostic hooks.

```
pip install memorius
```

## Quick Start

```bash
# Initialize a palace
memorius init

# Store a memory
memorius store "The sky is blue because Rayleigh scattering scatters shorter wavelengths more" --palace main --wing science --room physics

# Semantic search
memorius search "why is the sky blue"

# Mine memories from a conversation
memorius mine transcript.txt --palace conversations

# Check status
memorius status

# Write a diary entry
memorius diary --session "session-001" --title "Research findings"
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Memorius                           │
├─────────────────────────────────────────────────────────┤
│  CLI        memorius init | store | search | mine | ... │
│  MCP        JSON-RPC protocol server (stdin/stdout)     │
│  REST       FastAPI HTTP server (optional)              │
│  Hooks      Agent-agnostic lifecycle hooks              │
├─────────────────────────────────────────────────────────┤
│  Palace Engine                                          │
│  ├── ChromaStore    Vector search (ChromaDB)            │
│  ├── SQLiteStore    Metadata & hierarchy (SQLite)       │
│  └── Embeddings     Pluggable providers                 │
├─────────────────────────────────────────────────────────┤
│  Palace  >  Wing  >  Room  >  Drawer  hierarchy        │
│  Diaries          Session diary entries                 │
│  Mine             Extract memories from transcripts     │
├─────────────────────────────────────────────────────────┤
│  Plugin Gen    →  Generate per-agent plugins            │
│  Normalizers   →  Import Discord/Telegram/WhatsApp/etc  │
└─────────────────────────────────────────────────────────┘
```

## Configuration

Config lives at `~/.memorius/config.yaml` (auto-created on `memorius init`):

```yaml
storage:
  path: ~/.memorius/data

embeddings:
  provider: chroma-default  # chroma-default | sentence-transformers | openai
  model: all-MiniLM-L6-v2

server:
  mcp_port: 8910
  rest_port: 8911
  host: 127.0.0.1

palace:
  default: main
```

Environment variable overrides:

| Variable | Overrides |
|---|---|
| `MEMORIUS_STORAGE_PATH` | `storage.path` |
| `MEMORIUS_EMBEDDINGS_PROVIDER` | `embeddings.provider` |
| `MEMORIUS_MCP_PORT` | `server.mcp_port` |
| `MEMORIUS_REST_PORT` | `server.rest_port` |
| `MEMORIUS_HOST` | `server.host` |
| `MEMORIUS_OPENAI_API_KEY` | `embeddings.openai.api_key` |

## Embedding Providers

| Provider | Requirement | Quality |
|---|---|---|
| `chroma-default` | ChromaDB (bundled ONNX) | Good (384d) |
| `sentence-transformers` | `pip install memorius[local-embeddings]` | Better (768d+) |
| `openai` | `OPENAI_API_KEY` env var | Best (1536d) |

## CLI Reference

```
Usage:
  memorius init              Initialize a new palace
  memorius status            Show palace status
  memorius store <text>      Store a memory
    --palace, -p               Palace name (default: main)
    --wing, -w                 Wing name (default: default)
    --room, -r                 Room name (default: general)
    --drawer, -d               Drawer name (default: notes)
  memorius search <query>    Semantic search
    --palace, -p               Filter by palace
    --limit, -l                Max results (default: 10)
  memorius mine <file|text>  Extract memories from transcript
    --palace, -p               Target palace (default: main)
  memorius diary             Write a diary entry
    --session, -s              Session identifier
    --title, -t                Entry title
  memorius serve              Start MCP server
  memorius version            Show version
```

## MCP Protocol

MCP is the primary interface for AI agents to interact with Memorius. Connect any MCP-compatible client (Claude Code, Cursor, Codex CLI, etc.) by pointing it at the MCP server:

```json
{
  "mcpServers": {
    "memorius": {
      "command": "memorius",
      "args": ["serve"]
    }
  }
}
```

Available MCP tools:

| Tool | Description |
|---|---|
| `memorius_status` | Memory palace status |
| `memorius_store` | Store content in palace hierarchy |
| `memorius_search` | Semantic search across memories |
| `memorius_mine` | Extract memories from conversation |
| `memorius_diary_write` | Write session diary entry |
| `memorius_diary_list` | List diary entries |
| `memorius_palace_ls` | Browse palace hierarchy |

## REST API

Start the REST server:

```bash
memorius serve --rest
```

Endpoints:

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/store` | Store a memory |
| POST | `/search` | Semantic search |
| POST | `/mine` | Extract memories |
| GET | `/status` | System status |
| POST | `/diary` | Write diary entry |
| GET | `/palace` | Browse hierarchy |

## Agent Hooks

Memorius includes agent-agnostic lifecycle hooks. Hook scripts are generated per agent:

```bash
memorius plugin-gen init
# Edit universal-manifest.yaml
memorius plugin-gen generate
```

This generates plugins for Claude Code, Codex CLI, Cursor, Gemini CLI, Windsurf, and more — all pointing at your local Memorius server.

## Plugin Generator

```bash
memorius plugin-gen list          # Show supported agents
memorius plugin-gen init          # Create universal-manifest.yaml
memorius plugin-gen generate      # Generate plugins for all agents
```

## Conversation Normalizers

```bash
memorius normalize input.json     # Auto-detect and normalize
memorius normalize input.json --format discord
```

Supported formats: Discord, Telegram, WhatsApp, generic JSON, plain text.

## Development

```bash
git clone https://github.com/Dream-Pixels-Forge/memorius.git
cd memorius
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest

# Run end-to-end
memorius init
memorius store "test memory"
memorius search "test"
```

## License

MIT
