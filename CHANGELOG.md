# Changelog

## v0.8.2 (2026-08-15)

### Learning Module
- **`LearningCategory` enum** — 7 categories: `bug_fix`, `strategy`, `pattern`, `self_improvement`, `tool_usage`, `code_snippet`, `workflow`.
- **`Learning` dataclass** — structured representation with `content`, `category`, `context`, `solution`, `tags`, `confidence`, `applied_count`.
- **`store_learning()`** — store learnings with category, context, and solution in a dedicated `learnings` shelf.
- **`recall_learnings()`** — search learnings by query, with optional category/tag filtering.
- **`list_learnings()`** — list learnings with pagination and filtering.
- **`apply_learning()`** — mark a learning as applied and optionally store application notes.
- **`get_learning_stats()`** — get statistics on stored learnings by category.

### New MCP Tools
- **`memorius_learn`** — store a learning with category, context, and solution.
- **`memorius_recall`** — search learnings with optional category/tag filtering.
- **`memorius_learnings`** — list learnings with pagination and filtering.
- **`memorius_apply_learning`** — mark a learning as applied.
- **`memorius_learning_stats`** — get statistics on stored learnings.
- **`memorius_stats`** — compact status overview for opencode status bar.

### New CLI Commands
- **`memorius learn`** — store a learning with category, context, and solution.
- **`memorius recall`** — search learnings with optional category/tag filtering.
- **`memorius learnings`** — list learnings with pagination and filtering.
- **`memorius apply-learning`** — mark a learning as applied.
- **`memorius learning-stats`** — get statistics on stored learnings.

## v0.8.1 (2026-08-15)

### Fixed
- **Storage verification** — `store()` now verifies that memories are actually persisted to both the vector store and meta store after writing. Raises `RuntimeError` if either verification fails, preventing silent storage failures.

## v0.8.0 (2026-08-15)

### Temporal Graph Edges
- **`tvalid`/`tinvalid` columns on `memory_graph`** — edges now track temporal validity for historical queries.
- **`invalidate_edge()`** — soft-delete edges by setting `tinvalid` timestamp, preserving audit history.
- **Active edge filtering** — `get_linked()` and `expand_graph()` exclude invalidated edges by default; `include_invalidated=True` to include.
- **Temporal conflict resolution** — `link_memories()` automatically invalidates old edges when creating a new edge with a different relation between the same memory pair.
- **`get_edges_at_time()`** — query edges valid at a specific timestamp for temporal graph snapshots.
- **`get_active_edge_count()`** — count non-invalidated outgoing edges for a memory.

### Heat-Score Promotion
- **`heat_score` column on `memory_meta`** — tracks memory "temperature" (0.0–1.0) based on recency, frequency, and freshness.
- **`calculate_heat_score()`** — weighted combination: 0.4×recency + 0.3×frequency + 0.3×freshness with configurable half-life.
- **`classify_tier()`** — maps heat scores to hot/warm/cold/archived tiers.
- **Tier-boosted search ranking** — hot memories get +0.15, warm +0.05, cold -0.05, archived -0.15 in final search scores.
- **Automatic heat score updates** — recalculation triggered on every memory access via search.

### On-Write Deduplication
- **Semantic dedup on store** — new memories are checked against existing memories for near-duplicates (cosine similarity > 0.92). Duplicate memories are flagged with `duplicate_of` metadata instead of creating full duplicates.
- **Best-effort dedup** — dedup failure does not prevent storage; errors are caught and logged.

### Auto-Consolidation Daemon
- **`ConsolidationDaemon`** — optional background thread for periodic memory consolidation (dedup, contradiction resolution, pruning).
- **Opt-in via config** — `consolidation.enabled: false` by default. Set to `true` to enable.
- **Configurable interval** — default 3600 seconds (1 hour) between consolidation cycles.
- **VaultEngine lifecycle integration** — daemon starts/stops with the vault; cleanup on `close()`.

### BM25 Hybrid Retrieval
- **FTS5 virtual table** — `memory_fts` for full-text keyword search, auto-synced via triggers.
- **`bm25_search()`** — keyword search method on SQLiteStore returning BM25-ranked results.
- **Hybrid retrieval** — `search(use_hybrid=True)` blends vector similarity (60%) with BM25 keyword scores (40%) for improved retrieval.
- **Score normalization** — BM25 ranks are min-max normalized before blending with vector scores.

### Infrastructure
- **Temporal query helpers** — `get_edges_at_time()` and `get_active_edge_count()` for temporal graph analysis.
- **Heat score calculation pipeline** — integrated into search module for automatic tier-based ranking.

## v0.7.2 (2026-08-15)

### Security Hardening (Comprehensive Audit)
- **Path traversal guard on graph export** — `vault.py:export_graph_html` now validates destination path stays within the configured storage directory.
- **Path traversal guard on CLI obsidian export** — `cli/obsidian.py` validates output subdirectory resolves within the export directory.
- **HTML injection prevention** — `graph_visualizer.py` escapes the title via `html.escape()` to prevent XSS in HTML output.
- **Command injection prevention** — Windows daemon startup in `cli/main.py` passes host/port/tls via environment variables instead of string interpolation.
- **LLM extraction trust model** — `llm_extract.py` uses system/user message split to isolate extraction rules from user-provided conversation content. Applied to both OpenAI and Ollama extraction paths.
- **Template injection prevention** — `hooks/engine.py:_substitute_templates` recursion depth limited to 10 to prevent infinite loops.
- **UUID validation on MCP handlers** — `memorius_contradictions`, `memorius_get`, `memorius_update`, `memorius_delete` now validate memory_id format via `validate_memory_id()`.
- **Dependency version pinning** — Minimum versions set for `chromadb>=0.4.22`, `sentence-transformers>=2.6.0`, `httpx>=0.25.0`, `openai>=1.1.0`, `pyyaml>=6.0.1`.
- **Rate limiter memory growth fix** — Sweep frequency reduced to 200 requests; added IP count cap (10,000) to prevent unbounded dict growth.
- **Security documentation** — MCP tool descriptions include security notes about treating memory content as untrusted data. README documents API key security and LLM extraction trust model.

## v0.7.1 (2026-08-15)

### Security Hardening
- **Tar-slip prevention** — `model_download.py` now uses `filter="data"` on Python 3.12+ (PEP 706) and verifies all member paths stay within destination bounds on Python <=3.11.
- **SSRF DNS resolution check** — `hooks/engine.py` webhooks now resolve hostnames via `socket.getaddrinfo` and reject any private, loopback, link-local, reserved, or multicast IP addresses.
- **Command hook authorization gate** — `hooks/engine.py` gates the `command` action type behind an explicit `allow_command_hooks: true` config flag (default: `false`).
- **Timing-safe API key validation** — `rest_server.py` uses `hmac.compare_digest` for constant-time comparison and emits a warning if `MEMORIUS_API_KEY` is under 16 characters.
- **Chunked transfer-encoding size limit** — `rest_server.py` streams and validates incoming chunked bodies against `MAX_CONTENT_LENGTH`.
- **Rate-limiter memory leak fix** — `rest_server.py` performs periodic eviction sweeps to prevent unbounded dict growth across unique IPs.
- **Session ID validation** — Added `validate_session_id()` in `validation.py`; applied to REST `/diary` and MCP `memorius_diary_write`.
- **Obsidian path containment** — REST `/obsidian` endpoints ensure target vault paths stay within the user's home directory.
- **Filesystem-friendly name limits** — Lowered `MAX_NAME_LENGTH` in `validation.py` from 1000 to 128 characters.
- **Output-driven LLM validation** — Removed brittle regex injection blacklist in `llm_extract.py` in favor of strict structured output schema validation.
- **LLM extraction trust model** — Added `EXTRACTION_SYSTEM` system message to isolate extraction rules from user-provided conversation content. Applied to both OpenAI and Ollama extraction paths.
- **Path traversal guards** — `export_graph_html` validates destination path stays within storage directory; CLI obsidian export validates output subdirectory paths.
- **HTML injection prevention** — Graph visualizer title escaped via `html.escape()` to prevent XSS.
- **Command injection prevention** — Windows daemon startup now passes host/port/tls via environment variables instead of string interpolation.
- **Template injection prevention** — `_substitute_templates` recursion depth limited to 10 to prevent infinite loops.
- **UUID validation on MCP handlers** — `memorius_contradictions`, `memorius_get`, `memorius_update`, `memorius_delete` now validate memory_id format.
- **Dependency version pinning** — Minimum versions set for `chromadb>=0.4.22`, `sentence-transformers>=2.6.0`, `httpx>=0.25.0`, `openai>=1.1.0`, `pyyaml>=6.0.1`.
- **Security documentation** — MCP tool descriptions include security notes about treating memory content as untrusted data. README documents API key security.

### Added
- **Knowledge Graph Visualizer** — standalone, zero-dependency interactive HTML visualization of the associative memory graph. Force-directed layout with canvas rendering, shelf/relation filtering, search, node inspector sidebar, and zoom/pan. Accessible via:
  - CLI: `memorius graph view`, `memorius graph export-html`, `memorius graph stats`, `memorius graph json`
  - MCP: `memorius_graph_export` tool (json/html format)
  - REST: `GET /graph/data`, `GET /graph/view`
- **Dependency consolidation** — `sentence-transformers`, `openai`, and `sqlite-vec` moved from optional extras to core dependencies. `pip install memorius` now includes all features out of the box.

### Code Quality
- **Extracted lazy-init pattern** — VaultEngine now uses `_get_store_module()` and `_get_search_module()` helpers, eliminating 8 repeated `if self._X is None: from ... import ...` blocks.
- **Deduplicated JSON parsing** — added `safe_parse_json()` to `utils.py`; used by `store_module.py` (3 call sites) and `search_module.py` (1 call site), removing inline `try/except/json` cargo-cult.
- **Added missing exception annotations** — 6 unannotated `except Exception` blocks in `doctor.py` and 1 in `context_inject.py` now have best-effort rationale comments. (56 total `except Exception` blocks, 39 annotated.)
- **Sealed message-chain breach** — MCP server now calls `engine.list_diaries()` instead of `_engine._meta.list_diaries()`. Added `list_diaries()` public method to `VaultEngine`.
- **Clarified HookEngine naming** — `_get_engine()` → `_get_vault()`, `self._engine` → `self._vault` to avoid confusion with the HookEngine class itself.
- **SQL PRAGMA whitelist** — `_get_columns()` validates table names against a `frozenset` allowlist before PRAGMA interpolation.
- **UUID validation on batch queries** — `get_memory_meta_batch()` validates each memory ID as a UUID before `WHERE IN` interpolation.
- **Typed module dependencies** — `SearchModule` and `StoreModule` constructor `meta` parameter typed as `SQLiteStore` (was `Any`).
- **Scoped connection cleanup** — `VaultEngine.close()` closes only its own DB connection via `close_connection(db_path)`, not all thread connections.
- **Lazy logger formatting** — migrated f-string loggers to `%s` style in `meta_store.py`.
- **Numpy array conversion** — `ChromaDefaultProvider.embed()` converts numpy arrays to plain Python lists for downstream compatibility.

## v0.7.0 (2026-07-29)

### Refactored
- **VaultEngine decomposition** — extracted `SearchModule` (5-stage search pipeline) and `StoreModule` (CRUD operations). VaultEngine reduced from 692 to 328 lines (53% reduction).
- **VectorStore ABC** — `ChromaStore` and `SqliteVecStore` now share an abstract base class for swappable backends.
- **Sealed `_conn()` leakage** — all external callers now use `SQLiteStore` public API (`execute`, `fetchone`, `fetchall`, `transaction`, graph/temporal adapters, import/export methods).
- **Shared Obsidian module** — `memorius/obsidian.py` consolidates helpers used by REST server and CLI.
- **Dead code removal** — HNSW switchover path removed from consolidation.
- **Type hints** — complete type annotations on `SQLiteStore` public API.
- **Exception documentation** — 30 `except Exception` blocks annotated as best-effort with reasons.

### Added
- **26 new tests** — `SearchModule` (7) and `StoreModule` (19) unit tests in `test_domain_modules.py`.

### Fixed
- **Version mismatch** — `__version__` now uses `importlib.metadata.version()` consistently.
- **Legacy test references** — `test_features.py` updated to use `SQLiteStore` public API instead of `_conn()`.

## v0.6.1 (2026-07-29)

### Refactored
- **Initial domain module extraction** — early version of VaultEngine decomposition into `SearchModule` and `StoreModule`. Superseded by v0.7.0 with full sealing and documentation.

## v0.5.0 (2026-07-28)

### Features
- **Cross-encoder reranker** — `memorius search --rerank` uses `cross-encoder/ms-marco-MiniLM-L-6-v2` for higher-precision search ranking. Install via `pip install memorius[ranker]`.
- **SQLite-vec backend** — single-file vector store alternative to ChromaDB. Set `storage.type: sqlite-vec` or `MEMORIUS_STORAGE_TYPE=sqlite-vec`. Install via `pip install memorius[single-file]`.
- **Cursor pagination** — `memorius list` and MCP `memorius_list` support cursor-based pagination for large vaults. `search` also supports `--cursor` for paginated results.
- **Batch embedding** — vector store writes embeddings in batches for improved performance on bulk operations.
- **Daemon mode** — `memorius serve-rest --daemon` / `--stop` with PID file management for background operation.
- **`memorius setup`** — downloads ONNX model with SHA256 verification and initializes vault (`--force`, `--skip-model`).
- **TTL (Time-to-Live)** — `memorius store "..." --ttl 30` sets expiration on memories. Expired memories are eligible for pruning.
- **`memorius prune`** — find and archive/delete stale memories by decay score threshold or TTL expiry (`--dry-run`, `--delete`, `--json`).
- **Export / Import** — `memorius export` (JSON or Markdown) and `memorius import` for vault portability and backups. JSON export includes hierarchy, diaries, and graph edges.
- **`memorius doctor`** — health checks for config, storage, ONNX model, vector/meta drift, and graph integrity. Available via CLI, MCP, and REST.
- **`memorius get` / `memorius update`** — read and modify individual memories by UUID. Update supports content changes (auto re-embeds) and metadata merging.
- **Contradiction edges** — `memorius factcheck` persists bidirectional `relation='contradicts'` edges in the knowledge graph. MCP `memorius_contradictions` and REST `GET /contradictions/{id}` expose them.
- **Graph-aware retrieval** — `memorius search --expand-graph` pulls in 1-hop graph-linked memories ("you also worked on X"). Configurable `graph_hops` and `graph_min_weight`.
- **Metadata & tag filtering** — `memorius search --tag` (repeatable) filters memories by tags. Shell/folder/note filters work via Chroma metadata.
- **`memorius list`** — list memories with cursor pagination, vault filtering, and JSON output.
- **Honest factcheck** — improved contradiction detection with honest access recording on search and store operations.

### Expanded
- **26 CLI commands** (was 18) — added `setup`, `get`, `update`, `list`, `prune`, `export`, `import`, `doctor`
- **22 MCP tools** (was 14) — added `get`, `update`, `delete`, `list`, `contradictions`, `prune`, `doctor`
- **24 REST endpoints** (was 15) — added CRUD, doctor, prune, contradictions, memories list
- **8 agent hooks** — OpenClaude, Claude Code, Codex CLI, Gemini CLI, OpenClaw, OpenCode, Pi, Generic
- **10 hook engine actions** — mine_dir, diary, conditional_diary, command, log, webhook, inject_context, consolidate, factcheck, block

### Improved
- **README** — comprehensive rewrite with all current features, security sections, thread safety, validation, context injection, session inheritance, and optional dependencies.
- **REST security** — API key auth (`MEMORIUS_API_KEY`), rate limiting (500 req/min), request body limits, restrictive CORS.
- **Hook security** — template injection prevention, `shlex.split()` command execution, webhook SSRF protection.
- **Thread safety** — thread-local SQLite connections, `threading.Lock()` for all writes, `atexit` cleanup.

## v0.4.5 (2026-07-15)

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
