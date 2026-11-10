# Memorius
<img alt="memorius" src="assets/banner.png" />

<p align="center">
  <strong>Universal memory vault for any AI agent.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/memorius/"><img src="https://img.shields.io/pypi/v/memorius?color=blue" alt="PyPI version"></a>
  <a href="https://github.com/Dream-Pixels-Forge/memorius/actions/workflows/test.yml"><img src="https://github.com/Dream-Pixels-Forge/memorius/actions/workflows/test.yml/badge.svg" alt="Tests"></a>
  <a href="https://github.com/Dream-Pixels-Forge/memorius/actions/workflows/release.yml"><img src="https://github.com/Dream-Pixels-Forge/memorius/actions/workflows/release.yml/badge.svg" alt="PyPI publish"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-blue" alt="Python 3.11 | 3.12"></a>
  <a href="https://github.com/Dream-Pixels-Forge/memorius/blob/main/CHANGELOG.md"><img src="https://img.shields.io/badge/changelog-v0.9.3-green" alt="Changelog"></a>
</p>

> **Works with Claude Code, Codex CLI, Gemini CLI, OpenClaude, OpenCode, Pi, OpenClaw, and any MCP-compatible agent.**
>
> **📚 Documentation:** https://dream-pixels-forge.github.io/memorius/ — install, CLI reference, MCP server, hooks, REST API, architecture, and the memory engine, all on the site.
>
> If you find this project useful, leaving a star ⭐ on the repository is the best way to support my work!

Memorius is a self-contained, agent-agnostic memory system with hierarchical knowledge
organization, pluggable embeddings, and neuroscience-inspired consolidation. One vault,
many frontends — CLI, MCP, REST, and auto-detecting agent hooks. **No cloud, no API keys,
no lock-in.**

## Install

```bash
pip install memorius
```

All features — vector search, cross-encoder reranker, REST API server, SQLite-vec backend,
OpenAI embeddings, knowledge graph, and the agent skill — are included out of the box. No
extra install flags needed.

Verify:

```bash
memorius --version
memorius init          # creates ~/.memorius/config.yaml + storage dir
```

## CLI Reference

### memorius stats
Show vault + memory + graph statistics
   --json    Output as JSON

### memorius status
Show vault status
   --json    Output as JSON


### memorius bookcase
Launch the 3D walkable vault bookcase (browser opens automatically, loopback only).
   --port <n>        REST API port (default: 8912)
   --static-port <n> Static asset port for the bookcase page (default: 8400)
   --no-browser      Don't open the browser; just serve the page


## Vault Bookcase (3D walkable)

Run the bookcase:

```bash
memorius bookcase
```

It starts the REST API on `http://127.0.0.1:8912`, serves the bookcase page on
`http://127.0.0.1:8400/bookcase.html`, and opens your browser. Everything is
loopback-only — nothing leaves your machine.

Use `memorius bookcase --no-browser` to serve without opening a tab, then open
the printed URL yourself. Use `--port` / `--static-port` if the defaults are
taken.

Once the page is open:

- **Walk:** WASD or arrow keys at eye height, **Shift** to hurry. You can't pass through shelves.
- **Look:** click the room to grab mouse-look (a crosshair appears; **Esc** releases), or click-drag.
- **The librarian** is the Memorius hippo. He meets you at the entrance and is waiting
  beside every book you ask for, holding his glowing book toward it.
- **Ask the librarian:** press **/** and type (or hold the mic). The librarian's lantern takes off;
  the camera follows it in one crane move up over the stacks and down into the right aisle.
  Matching books slide out of the shelf, the top hit furthest, and the librarian says where
  it is relative to you ("about 7 metres to your right, on the middle shelf").
- **Results:** **N** / **P** walk you to the next / previous match; **F** flies back to it.
- **Read:** click a book. It's drawn out of the row and opens in a reading panel with tags,
  age, "beside it on the shelf" neighbours, *Walk me there* and *Read aloud*.
- **Map:** **M** toggles the floor plan (you, the lantern, the hits); click it to be walked there.
- **Vault / layout:** dropdowns switch vault (from `GET /vaults`) or light the newest books.
- **Reset / skip:** **R** resets the view; **Space** or **Esc** skips a camera move. **?** shows all controls.
- **Colour:** every folder has its own cloth binding; fresher memories are brighter with shinier gilt.
- **Floor plan:** the vault is a building. Each shelf is a bay off the central aisle (alternating
  left and right, with a sign over its opening), each folder is a case inside its bay, read
  clockwise, and books run left to right from eye level down. Positions never move, so you
  can learn where things live. "Light newest" makes the newest books glow and lean out, and
  the newest also stand on the new-arrivals table by the doors.

Camera moves, dust and head-bob respect `prefers-reduced-motion`.

## Quick start

```bash
# Initialize a vault
memorius init

# Store a memory
memorius store "The sky is blue because Rayleigh scattering scatters shorter wavelengths more" \
  --vault main --shelf science --folder physics

# Semantic search
memorius search "why is the sky blue"

# Mine memories from a conversation
memorius mine transcript.txt --vault conversations

# Check status
memorius status
```

That's the whole loop: **store → embed → search**. Read the
[Getting Started guide](https://dream-pixels-forge.github.io/memorius/getting-started.html)
for the vault hierarchy, the agent skill, and a recommended first-week flow.

## Documentation

The full docs live on the site — each concern on its own page:

| Page | What's on it |
|---|---|
| [Getting Started](https://dream-pixels-forge.github.io/memorius/getting-started.html) | Install, init, first memory, the Vault→Shelf→Folder→Note hierarchy, agent skill |
| [CLI Reference](https://dream-pixels-forge.github.io/memorius/cli-reference.html) | Every subcommand and flag (incl. `repair` and `--json`) |
| [MCP Server](https://dream-pixels-forge.github.io/memorius/mcp-server.html) | All 29 tools + per-agent client config snippets |
| [Agent Hooks](https://dream-pixels-forge.github.io/memorius/hooks.html) | Auto-detecting lifecycle hooks, 10 actions, normalizers, security |
| [REST API](https://dream-pixels-forge.github.io/memorius/rest-api.html) | Full endpoint table, auth, rate limits, daemon mode, TLS |
| [Architecture](https://dream-pixels-forge.github.io/memorius/architecture.html) | Search pipeline, embeddings, vector backends, graph, configuration |
| [Agent Compatibility](https://dream-pixels-forge.github.io/memorius/agents.html) | Which agents, detection priority, how to plug in your own |
| [Memory Engine](https://dream-pixels-forge.github.io/memorius/consolidation.html) | Decay, consolidation, pruning, fact-checking, reranking, doctor, repair |

<details>
<summary><b>Command cheat sheet</b> (details on the <a href="https://dream-pixels-forge.github.io/memorius/cli-reference.html">CLI reference</a>)</summary>

```bash
memorius store "text" [--vault/--shelf/--folder/--note/--ttl]
memorius search "query" [--n/--expand-graph/--rerank/--web/--tag]
memorius mine file.txt [--vault/--text]
memorius extract file.txt [--backend openai|ollama|regex]
memorius diary "session" [--title/--summary]
memorius ls [vault]
memorius consolidate [--threshold/--dry-run]
memorius factcheck "stmt" [--web]
memorius profile "session"
memorius prune [--threshold/--dry-run/--delete]
memorius graph [view|export-html|stats|json]
memorius learn "text" --category bug_fix
memorius recall "query"
memorius obsidian [list|import|export]
memorius export ./backup [--format json|markdown]
memorius import ./backup.json [--replace]
memorius doctor            # 6 health checks
memorius repair [--reindex/--dry-run]   # fix vector/meta drift (v0.8.6)
memorius stats [--json]      # vault + memory + graph + doctor summary
memorius status [--json]    # vault + embeddings + recent diaries
memorius serve               # MCP server (stdio)
memorius serve-rest [--daemon/--stop]   # FastAPI server
```

</details>

## License

[MIT](LICENSE) · Full release history in [CHANGELOG.md](CHANGELOG.md).
