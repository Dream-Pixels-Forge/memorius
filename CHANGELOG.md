# Changelog

## Unreleased

### Features
- **`memorius delete <id>`** — remove a memory by UUID. Validates the ID
  (must be a valid UUID), confirms existence, shows a content preview, and
  asks for confirmation before deleting (skip with `--yes`; preview with
  `--dry-run`). Hard-deletes from both the vector and metadata stores and
  cleans up dangling knowledge-graph edges. Optional `--vault` / `--shelf`
  scope must match the memory's real location (prevents cross-vault deletes).

## v0.4.4 (2026-07-15)

### Fixes
- **web_search**: drop a redundant `retrieval` re-assignment in
  `get_web_provider`'s `tavily` branch and hoist `import json` to
  module level (no behaviour change).

## v0.4.3 (2026-07-15)

### Features
- **`TavilyProvider`** — keyed, agent-grade web search for the hybrid
  retrieval fallback. Reads the key from `retrieval.tavily_api_key`
  or the `TAVILY_API_KEY` env var; missing key warns and returns
  `[]` (never crashes the CLI). Selected via `retrieval.web_provider:
  tavily` or `MEMORIUS_WEB_PROVIDER=tavily`. `DuckDuckGo`
  (keyless) remains the default.

## v0.4.2 (2026-07-15)

### Features
- **Hybrid retrieval with web fallback** — when local recall is thin,
  memorius can now augment results with *cited* web search
  ("search the internet if needed"). 2026-aligned: grounded,
  local-first retrieval that reaches the live web only as a fallback.
  - `memorius web "<query>"` — new standalone web-search command.
  - `search` / `context` / `factcheck` gain a `--web` flag; `search`
    and `context` also fall back automatically when `retrieval.web_fallback`
    is enabled in config.
  - `memorius/web_search.py`: pluggable `WebSearchProvider` with a
    **keyless** `DuckDuckGoProvider` (stdlib-only) and a `MockProvider`
    for tests. Fallback triggers only when local hits < `web_min_results`.
  - Off by default (privacy / local-first); enable via config or `--web`.
    Env overrides: `MEMORIUS_WEB_FALLBACK`, `MEMORIUS_WEB_PROVIDER`.

## v0.4.1 (2026-07-15)

### Bug Fixes
- **factcheck crash on Windows consoles** — `memorius factcheck` raised
  `UnicodeEncodeError: 'charmap' codec can't encode characters ...` and died
  before printing a verdict. The CLI now forces UTF-8 on `sys.stdout`/
  `sys.stderr` at the top of `main()` (via `_ensure_utf8_streams()`, a
  best-effort `reconfigure` that no-ops on streams that can't be
  reconfigured, e.g. when piped to a file). The emoji verdict glyphs
  (✅ ❌ ⚠️ ❓) now render cleanly on cp1252 consoles.
- Added `tests/test_encoding_regression.py` guarding the cp1252 crash
  across all four factcheck verdict glyphs.

## v0.4.0 (2026-06-14)

### Breaking Changes
- **REST dependencies promoted to core** — `fastapi`, `uvicorn`, `pydantic`, and
  `sse-starlette` moved from `[project.optional-dependencies] rest = [...]` to
  `[project.dependencies]`. The `[rest]` extra is removed. After upgrading:
  ```bash
  pip install --upgrade memorius
  ```
  The REST server (`memorius serve-rest`) now works without any extra install flags.
  Existing installs with `[rest]` extra will continue to work — just switch to
  `pip install memorius` on the next clean install.

### Removed
- `[project.optional-dependencies] rest` extra (no longer needed — all REST deps are core)
- `memorius[rest]` from `all` meta-extra (now just `memorius[local-embeddings,openai]`)

## v0.3.1 (2026-06-10)

### Bug Fixes
- **MCP search crash** — Fixed `"Object of type ndarray is not JSON serializable"` error when calling `memorius_search` via MCP. ChromaDB returns embedding vectors as numpy arrays which `json.dumps()` can't serialize. `Memory.to_dict()` now converts numpy arrays to plain lists, and MCP search responses exclude raw vectors (384-dim, useless to callers).
- **CI/CD test failure** — Removed invalid `--timeout=300` argument from `test.yml`. The `pytest-timeout` plugin was not installed, causing pytest to exit with code 4 (usage error).

## v0.3.0 (2026-06-09)

### Features
- **Temporal decay scoring** — Memories now decay over time (Ebbinghaus forgetting curve) unless accessed or reinforced. Search results are re-ranked by freshness and access frequency.
- **Knowledge graph auto-linking** — New memories are automatically linked to related memories via content similarity (Jaccard index).
- **Fact-checking** — `memorius factcheck` CLI command and MCP tool. TF-IDF-like similarity for contradiction detection.
- **Memory consolidation** — `memorius consolidate` merges duplicate memories and extracts insights.
- **Session profiles** — `memorius profile` builds a memory profile for session inheritance across agent conversations.
- **Memory context injection** — `memorius context` returns formatted memory context ready for injection into agent prompts.
- **Memory extraction** — `memorius extract` uses LLM (OpenAI or Ollama) to identify decisions, preferences, facts, and action items from conversations.
- **Memory tracking** — Active/archived stats, per-vault breakdown, access count tracking.
- **15 REST endpoints** — Full REST API with rate limiting, CORS restrictions, and confirmation guards for destructive operations.
- **14 MCP tools** — Complete MCP tool suite for AI agent integration.

### Architecture
- **vault.py split** — `vault.py` reduced from 943 to 230 lines. Extracted `vector_store.py` (ChromaStore) and `meta_store.py` (SQLiteStore).
- **hooks package split** — `hooks/__init__.py` reduced from 447 lines. Extracted `hooks/models.py`, `hooks/adapters/` subpackage with per-agent adapters.
- **Shared validation module** — `validation.py` with `validate_name()`, `validate_content()`, and constants used by both MCP and REST.
- **Memory dataclass** — Extracted to `memorius/models.py` to resolve circular dependencies.

### Security
- Path traversal guard on Obsidian export
- SQL injection prevention (string concatenation with validated whitelist)
- CORS restricted to `Content-Type` and `Authorization` headers
- Rate limiting: 100 requests/min per IP on REST endpoints
- Error messages sanitized (capped at 200 chars in MCP)

### Reliability
- ChromaDB retry with exponential backoff (3 attempts)
- Ollama health check retry (3 attempts)
- MCP server tracks consecutive errors, shuts down after 10 failures
- 4 previously silent catch blocks now log warnings

### Testing
- 79 tests across 8 test files
- Integration tests for CLI, MCP protocol, and hooks engine
- Validation tests, temporal scoring tests, graph tests

## v0.2.0 (2026-06-05)

### Features
- MCP protocol server (stdio JSON-RPC)
- REST API server (FastAPI)
- Agent hooks engine with auto-detection for 7 agents
- Obsidian import/export
- Plugin generator for per-agent hook scripts
- Conversation normalizers (Discord, Telegram, WhatsApp)
