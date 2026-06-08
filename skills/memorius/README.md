# memorius

**Self-contained memory vault for any AI agent.**

memorius provides persistent memory storage with vector search, session diaries, and hooks for agent frameworks.

## Quick Start

```bash
memorius init                    # Create vault
memorius store "important fact"  # Store a memory
memorius search "important"      # Find it later
```

## Commands

| Command | Description |
|---------|-------------|
| `memorius init` | Initialize a new vault |
| `memorius status` | Show vault status |
| `memorius store <content>` | Store a memory |
| `memorius search <query>` | Semantic search |
| `memorius mine <file>` | Mine memories from transcript |
| `memorius extract <file>` | Extract with LLM |
| `memorius diary <session>` | Write session diary |
| `memorius diaries` | List recent diaries |
| `memorius context <topic>` | Get context for injection |
| `memorius factcheck <statement>` | Verify against vault |
| `memorius consolidate` | Merge similar memories |
| `memorius ls` | Explore vault hierarchy |
| `memorius stats` | Memory statistics |
| `memorius serve` | Start MCP server |
| `memorius serve-rest` | Start REST API |
| `memorius config --show` | Show configuration |
| `memorius obsidian list/import/export` | Obsidian sync |

## Flags

| Flag | Commands | Description |
|------|----------|-------------|
| `--vault` | most | Target vault name |
| `--shelf` | store, search, mine, extract | Shelf category |
| `--folder` | store | Folder sub-category |
| `--note` | store | Note name |
| `--n` | search | Result limit |
| `--backend` | extract | LLM backend (auto/openai/ollama/regex) |
| `--threshold` | consolidate | Similarity threshold (0-1) |
| `--dry-run` | consolidate | Preview without changes |
| `--max` | context | Max context items |
| `--text` | mine, extract | Inline text input |

## Vault Hierarchy

```
vault/
  shelf/
    folder/
      note (individual memory)
```

## MCP Server

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

## Dependencies

- chromadb (vector search)
- httpx (HTTP client)
- pyyaml (config)
