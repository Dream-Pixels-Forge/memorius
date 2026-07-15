# Memorius
<img width="1584" height="672" alt="memorius" src="https://github.com/user-attachments/assets/1a62163d-1ff5-4112-8b8f-1a6b19afab7a" />

<p align="center">
  <strong>Universal memory vault for any AI agent.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/memorius/"><img src="https://img.shields.io/pypi/v/memorius?color=blue" alt="PyPI version"></a>
  <a href="https://github.com/Dream-Pixels-Forge/memorius/actions/workflows/test.yml"><img src="https://github.com/Dream-Pixels-Forge/memorius/actions/workflows/test.yml/badge.svg" alt="Tests"></a>
  <a href="https://github.com/Dream-Pixels-Forge/memorius/actions/workflows/publish.yml"><img src="https://github.com/Dream-Pixels-Forge/memorius/actions/workflows/publish.yml/badge.svg" alt="PyPI publish"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-blue" alt="Python 3.11 | 3.12"></a>
</p>

> 🧠 **Works with Claude Code, Codex CLI, Gemini CLI, OpenClaude, OpenCode, Pi, and any MCP-compatible agent.**
>
> 🌐 **Landing page:** https://dream-pixels-forge.github.io/memorius/
>
> If you find this project useful, leaving a star ⭐ on the repository is the best way to support my work!



## Why Memorius?

Most AI memory tools lock you into one agent ecosystem. Memorius is **agent-agnostic by design** — the same memory vault works whether you use Claude Code, Codex CLI, Gemini CLI, or any MCP-compatible agent. No vendor lock-in.

| Feature | Memorius | Others |
|---------|----------|--------|
| Agent support | **7 agents** (auto-detected) | Usually 1-3 |
| Protocol | **Open MCP standard** | Proprietary plugins |
| Memory hierarchy | Vault → Shelf → Folder → Note | Flat |
| Temporal decay | ✅ Ebbinghaus forgetting curve | ❌ |
| Knowledge graph | ✅ Auto-linked memories | ❌ |
| Fact-checking | ✅ Contradiction detection | ❌ |
| Obsidian integration | Native import/export | ❌ |
| Self-hosted | ✅ No cloud dependency | Often SaaS |
| Open source | ✅ MIT license | Varies |

```bash
pip install memorius
```

> **REST API server is included by default** — `fastapi`, `uvicorn`, `pydantic`,
> and `sse-starlette` are now core dependencies. No extra `[rest]` install flag needed.

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

<img width="979" height="632" alt="Screenshot from 2026-06-18 15-14-39" src="https://github.com/user-attachments/assets/6cbca59b-1a3c-4b1d-85e8-dd5b256b9061" />


## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                       Memorius                             │
├────────────────────────────────────────────────────────────┤
│  CLI        memorius init | store | search | mine | ...    │
│  MCP        JSON-RPC protocol server (stdin/stdout)        │
│  REST       FastAPI HTTP server                 │
│  Hooks      Auto-detect: Claude Code, Codex, Gemini, ...  │
│  Obsidian   Import / export notes from Obsidian vaults     │
├────────────────────────────────────────────────────────────┤
│  Vault Engine                                              │
│  ├── ChromaStore    Vector search (ChromaDB)               │
│  ├── SQLiteStore    Metadata & hierarchy (SQLite)          │
│  └── Embeddings     Pluggable providers (ONNX / SF / OA)   │
├────────────────────────────────────────────────────────────┤
│  Vault  >  Shelf  >  Folder  >  Note  hierarchy            │
│  Diaries          Session diary entries                    │
│  Mine             Extract memories from transcripts        │
├────────────────────────────────────────────────────────────┤
│  Plugin Gen    →  Generate per-agent plugins               │
│  Normalizers   →  Import Discord/Telegram/WhatsApp/etc     │
│  Obsidian      →  Bidirectional vault sync                 │
└────────────────────────────────────────────────────────────┘
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

retrieval:
  web_fallback: false        # opt-in: augment thin local recall with web
  web_provider: duckduckgo   # duckduckgo (keyless) | tavily (keyed) | mock (tests)
  tavily_api_key: null       # or set TAVILY_API_KEY env var
  web_min_results: 1         # if ZERO local hits, fall back to web
  web_max_results: 5         # max web results to return
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
| `MEMORIUS_WEB_PROVIDER` | `retrieval.web_provider` |
| `MEMORIUS_WEB_FALLBACK` | `retrieval.web_fallback` |
| `MEMORIUS_TAVILY_API_KEY` | `retrieval.tavily_api_key` |

## Web Search

When local recall is thin, Memorius can optionally augment retrieval with
live web results. This is **local-first and opt-in** — web search never runs
unless you ask for it: the `memorius web` command, the `--web` flag on
`search` / `context` / `factcheck`, or `retrieval.web_fallback: true`.

```bash
# Live web search (keyless DuckDuckGo by default)
memorius web "python 3.13 changelog"

# Use the keyed Tavily provider for higher signal-to-noise
memorius web "python 3.13 changelog" --provider tavily

# Augment a local search with web when local hits are thin
memorius search "latest rust release" --web
```

### Providers

| Provider | Key | Notes |
|---|---|---|
| `duckduckgo` (default) | none | Keyless, stdlib-only scraper. Works out of the box. |
| `tavily` | `TAVILY_API_KEY` or `MEMORIUS_TAVILY_API_KEY` | Agent-grade signal-to-noise. Missing key warns and returns `[]` — never crashes. |
| `mock` | n/a | Test double for offline testing. |

### Configuration

```yaml
retrieval:
  web_fallback: false        # opt-in: augment thin local recall with web
  web_provider: duckduckgo   # duckduckgo (keyless) | tavily (keyed) | mock (tests)
  tavily_api_key: null       # or set TAVILY_API_KEY / MEMORIUS_TAVILY_API_KEY
  web_min_results: 1         # fall back to web only when local hits < this
  web_max_results: 5         # max web results to return
```

`MEMORIUS_WEB_PROVIDER`, `MEMORIUS_WEB_FALLBACK`, and `MEMORIUS_TAVILY_API_KEY`
override the corresponding config keys (the raw `TAVILY_API_KEY` is also read
directly). A missing Tavily key never crashes the CLI — it logs a warning and
returns no web results.

## Embedding Providers

| Provider | Requirement | Quality |
|---|---|---|
| `chroma-default` | ChromaDB (bundled ONNX) | Good (384d) |
| `sentence-transformers` | `pip install memorius[local-embeddings]` | Better (768d+) |
| `openai` | `OPENAI_API_KEY` env var | Best (1536d) |

## CLI Reference

### Core commands

```bash
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
  --n                          Max results (default: 10)
memorius mine <file|text>    Extract memories from transcript
  --vault, -v                  Target vault (default: main)
memorius diary <session>     Write a diary entry
  --title, -t                  Entry title
  --summary, -s                Entry summary
  --vault, -v                  Vault name (default: main)
memorius diaries              List recent diary entries
memorius ls                   Explore vault hierarchy
memorius consolidate         Merge duplicate memories
  --vault                      Filter by vault
  --threshold                  Similarity threshold 0-1 (default: 0.80)
  --dry-run                    Preview without changes
memorius extract <file|text> Extract memories from conversation (LLM)
  --vault                      Target vault (default: main)
  --shelf                      Target shelf (default: extracted)
  --backend                    LLM backend: auto|openai|ollama|regex
memorius factcheck <stmt>    Fact-check against stored memories
  --vault                      Filter by vault
memorius context <query>     Get formatted memory context for injection
  --vault                      Filter by vault
  --max                        Max items (default: 5)
memorius profile <session>   Build session memory profile
  --vault                      Vault name (default: main)
memorius stats               Show vault + memory + graph statistics
memorius serve               Start MCP server (stdio)
memorius serve-rest           Start REST API server
memorius web <query>          Live web search (keyless DuckDuckGo by default)
  --provider                  duckduckgo (keyless) | tavily (keyed via TAVILY_API_KEY)
  --max                       Max results (default: 5)
memorius --version            Show version
memorius config               Show current configuration
memorius delete <id>          Delete a memory by ID (validation + confirmation)
  --vault, -v                  Vault scope (must match the memory's vault)
  --shelf, -s                  Shelf scope (must match the memory's shelf)
  --yes, -y                    Skip the confirmation prompt
  --dry-run                    Preview what would be deleted (no changes)
```

### Obsidian integration

```bash
memorius obsidian list                Explore vault structure
  --vault, -v                           Path to Obsidian vault directory
                                        (default: $OBSIDIAN_VAULT_PATH or
                                         ~/Documents/Obsidian Vault)

memorius obsidian import              Import Obsidian notes as memorius memories
  --vault, -v                           Path to Obsidian vault
  --target-vault                        Target memorius vault (default: main)
  --target-shelf                        Target memorius shelf (default: obsidian)
  --tag                                 Only import notes with this tag
  --dry-run                             Preview without importing

memorius obsidian export              Export memorius memories as Obsidian notes
  --vault, -v                           Path to Obsidian vault
  --source-vault                        Source memorius vault (default: main)
  --source-shelf                        Filter by shelf (default: all)
  --dry-run                             Preview without exporting
```

Import preserves the file hierarchy: `vault/Subfolder/note.md` maps to
`vault/Subfolder/vault > shelf > folder > note`. YAML frontmatter is parsed
and stored as memory attributes.

## MCP Protocol

MCP is the primary interface for AI agents to interact with Memorius. Connect
any MCP-compatible client by pointing it at the MCP server:

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
| `memorius_consolidate` | Merge duplicate memories, extract insights |
| `memorius_extract` | Extract structured memories from conversation (LLM) |
| `memorius_factcheck` | Fact-check a statement against stored memories |
| `memorius_context` | Get formatted memory context for injection |
| `memorius_session_profile` | Build session memory profile for inheritance |
| `memorius_graph_stats` | Knowledge graph statistics |
| `memorius_memory_stats` | Memory tracking statistics |

## Agent Skill Installation

Memorius ships with a ready-to-use agent skill (`skills/memorius/SKILL.md`) for agents that support the Hermes Agent skill format. The skill provides auto-capture rules, smart context injection, session diary templates, and workflow patterns — so agents can use memorius proactively without being told.

### Skill Structure

```
skills/
  memorius/
    SKILL.md              # Full skill definition (auto-capture, context injection, diary rules)
    README.md             # Quick command reference
    .memorius_version     # Version tracker
```

### Installing for Hermes Agent

The skill is designed for [Hermes Agent](https://hermes-agent.nousresearch.com) — copy it into your Hermes skills directory:

```bash
# Copy the skill
cp -r skills/memorius ~/.hermes/skills/

# Verify it's loaded
hermes skills list | grep memorius
```

Once installed, Hermes will automatically detect it and follow the skill's workflows.

### Installing for Other Agents

Agents that don't use the Hermes skill format can still use memorius via MCP or CLI:

| Agent | Install Command |
|-------|----------------|
| Claude Code | `claude mcp add memorius -- memorius serve` |
| Codex CLI | `codex mcp add memorius -- memorius serve` |
| Gemini CLI | `gemini mcp add memorius $(which memorius) serve` |
| Cursor | Add to `.cursor/mcp.json`: `{"mcpServers": {"memorius": {"command": "memorius", "args": ["serve"]}}}` |
| Aider | `aider --mcp-servers memorius=memorius serve` |
| Continue | Add memorius to `.continue/config.json` MCP servers |
| OpenClaw | `openclaw mcp set memorius '{"command":"memorius","args":["serve"]}'` |

See `manifest.yaml` for the full list of supported agents and their install commands.

Copying the SKILL.md file directly may also work for agents with their own skills directory (e.g. `~/.claude/skills/`, `~/.codex/skills/`) — check your agent's documentation.

## REST API

The REST server is always available (no extra install flags needed):

```bash
memorius serve-rest
```

Starts a FastAPI server on `http://127.0.0.1:8912` by default.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/status` | System status |
| GET | `/stats` | Full vault + memory + graph stats |
| POST | `/store` | Store a memory |
| POST | `/search` | Semantic search |
| POST | `/mine` | Extract memories from transcript |
| POST | `/diary` | Write diary entry |
| GET | `/vault` | Browse vault hierarchy |
| GET | `/diaries` | List recent diary entries |
| POST | `/consolidate` | Merge duplicate memories |
| POST | `/extract` | Extract memories from conversation (LLM) |
| POST | `/factcheck` | Fact-check statement against vault |
| POST | `/context` | Get formatted memory context for injection |
| GET | `/obsidian` | List notes in Obsidian vault |
| POST | `/obsidian/import` | Import Obsidian notes as memories |
| POST | `/obsidian/export` | Export memories as Obsidian notes |

## Agent Hooks

Memorius includes **universal agent lifecycle hooks** — auto-detecting,
agent-agnostic, and framework-free. Hook scripts are generated per agent:

```bash
memorius-plugin-gen init
# Edit universal-manifest.yaml
memorius-plugin-gen generate
```

### Supported agents

| Agent | Hook protocol | Events |
|---|---|---|
| **Claude Code** (Anthropic) | `stop_hook_active` / `precompact` | stop, precompact, session_start |
| **Codex CLI** (OpenAI) | `session_id` + `context_dir` | session_start, session_stop |
| **Gemini CLI** (Google) | `conversation_id` + `extensions` | stop, session_start |
| **OpenClaw** | `openclaw` marker in payload | stop, session_stop, precompact, session_start |
| **OpenCode** (anomalyco/sst) | `provider` dict + `openCodeVersion` | stop, session_stop, session_start, precompact |
| **Pi** (kachow-compatible) | `event` in Pi event set | session_start, session_shutdown, pre_compact, tool_call, turn_end |
| **OpenClaude** | `OpenClaude` marker in payload | stop, precompact, session_start |

### Auto-detection (no config needed)

Hooks are auto-detected from stdin — no `--agent` flag required. Just pipe
agent hook JSON to the memorius hook engine and it figures out which agent
sent the event:

```bash
# Hook engine auto-detects the agent
cat hook-payload.json | memorius-hook mine
cat hook-payload.json | memorius-hook diary
```

You can also force a specific agent with `--agent`:

```bash
memorius-hook mine --agent claude-code
memorius-hook diary --agent opencode
```

Detection priority (most-specific first):
`OpenClaude → Claude Code → Codex → Gemini CLI → OpenClaw → OpenCode → Pi → Generic`

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
memorius serve-rest         # REST server available out of the box
```

## License

MIT
