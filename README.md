# Memorius

**Universal memory vault for any AI agent.**

Memorius is a self-contained, agent-agnostic memory system that gives LLMs and AI agents persistent, searchable memory with a hierarchical knowledge organization. Drop-in with multi-backend vector storage, pluggable embeddings, built-in MCP + REST servers, and agent-agnostic hooks.

```
pip install memorius
```

## Quick Start

```bash
# Initialize a vault
memorius init

# Store a memory
memorius store "The sky is blue because Rayleigh scattering scatters shorter wavelengths more" --vault main --shelf science --folder physics

# Semantic search
memorius search "why is the sky blue"

# Mine memories from a conversation
memorius mine transcript.txt --vault conversations

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
│  Vault Engine                                           │
│  ├── ChromaStore    Vector search (ChromaDB)            │
│  ├── SQLiteStore    Metadata & hierarchy (SQLite)       │
│  └── Embeddings     Pluggable providers                 │
├─────────────────────────────────────────────────────────┤
│  Vault  >  Shelf  >  Folder  >  Note  hierarchy         │
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

vault:
  default: main

server:
  mcp_port: 8910
  rest_port: 8912
  host: 127.0.0.1
```

Environment variable overrides:

| Variable | Overrides |
|---|---|
| `MEMORIUS_STORAGE_PATH` | `storage.path` |
| `MEMORIUS_EMBEDDINGS_PROVIDER` | `embeddings.provider` |
| `MEMORIUS_DEFAULT_VAULT` | `vault.default` |
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
  memorius init                Initialize a new vault
  memorius status              Show vault status
  memorius store <text>        Store a memory
    --vault, -v                  Vault name (default: main)
    --shelf, -s                  Shelf name (default: default)
    --folder, -f                 Folder name (default: default)
    --note, -n                   Note name (default: default)
  memorius search <query>      Semantic search
    --vault, -v                  Filter by vault
    --shelf, -s                  Filter by shelf
    --limit, -l                  Max results (default: 10)
  memorius mine <file|text>    Extract memories from transcript
    --vault, -v                  Target vault (default: main)
  memorius diary <session>     Write a diary entry
    --title, -t                  Entry title
    --summary, -s                Entry summary
    --vault, -v                  Vault name (default: main)
  memorius diaries              List recent diary entries
  memorius ls                   Explore vault hierarchy
  memorius serve                Start MCP server (stdio)
  memorius serve-rest           Start REST API server
  memorius --version            Show version
```

## MCP Protocol

MCP is the primary interface for AI agents to interact with Memorius. Connect any MCP-compatible client (Claude Code, Cursor, Codex CLI, Gemini CLI, etc.) by pointing it at the MCP server:

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
| `memorius_status` | Memory vault status |
| `memorius_store` | Store content in vault/shelf/folder/note hierarchy |
| `memorius_search` | Semantic search across vault |
| `memorius_mine` | Extract memories from conversation |
| `memorius_diary_write` | Write session diary entry |
| `memorius_diary_list` | List diary entries |
| `memorius_vault_ls` | Browse vault hierarchy |

## REST API

Start the REST server:

```bash
memorius serve-rest
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

## Agent Hooks (optional)

Memorius includes agent-agnostic lifecycle hooks. Hook scripts are generated per agent:

```bash
memorius-plugin-gen init
# Edit universal-manifest.yaml
memorius-plugin-gen generate
```

This generates plugins for Claude Code, Codex CLI, Cursor, Gemini CLI, Windsurf, and more.

## Plugin Generator (optional)

```bash
memorius-plugin-gen list          # Show supported agents
memorius-plugin-gen init          # Create universal-manifest.yaml
memorius-plugin-gen generate      # Generate plugins for all agents
```

## Conversation Normalizers (optional)

```bash
memorius-normalize input.json     # Auto-detect and normalize
memorius-normalize input.json --format discord
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
