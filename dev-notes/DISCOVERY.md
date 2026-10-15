# Memorius Deep Discovery Analysis

## Runtime Ecosystem

### Dependencies (from pyproject.toml)
- **Core**: pyyaml>=6.0.1, chromadb>=0.4.22, httpx>=0.25.0, fastapi>=0.104.1, uvicorn[standard]>=0.24.0, pydantic>=2.0.0, sse-starlette>=1.0.0, sentence-transformers>=2.6.0, openai>=1.10.0, sqlite-vec>=0.1.0
- **Dev**: pytest>=7.0, pytest-asyncio>=0.21.0

### Entry Points
- CLI: `memorius = "memorius.cli.main:main"`
- MCP Server: `memorius-hook = "memorius.hooks.cli:main"` 
- Plugin Generator: `memorius-plugin-gen = "memorius.plugin_gen.cli:main"`
- Normalizer: `memorius-normalize = "memorius.normalizers.cli:main"`

### Server Components
- **MCP Server**: JSON-RPC protocol server (stdin/stdout) - primary interface for AI agents
- **REST Server**: FastAPI HTTP server (API key auth + rate limit) - alternative interface
- **Hook Engine**: Auto-detect: Claude Code, Codex, Gemini, etc. - agent lifecycle integration
- **Obsidian Integration**: Bidirectional vault sync with Obsidian

### Storage Backends
- **ChromaDB** (default): Persistent HNSW cosine search, auto-migration from legacy collections
- **SQLite-vec**: Single-file alternative, no ChromaDB dependency

### Embedding Providers
- **chroma-default**: ChromaDB (included ONNX) - Good (384d)
- **sentence-transformers**: Better (768d+)
- **openai**: Best (1536d or 3072d) - requires OPENAI_API_KEY

### Key Functional Modules
1. **Vault Engine**: Thin orchestrator coordinating all modules
2. **SearchModule**: 5-stage search pipeline (Filter → Vector → Temporal → Rerank → Graph)
3. **StoreModule**: Memory CRUD operations
4. **KnowledgeGraph**: Auto-linked memories + contradictions
5. **TemporalDecay**: Ebbinghaus forgetting curve
6. **Embeddings**: Pluggable providers (ONNX / SF / OA)
7. **Factcheck**: Contradiction detection with web fallback
8. **Consolidation**: Cluster + merge duplicate memories
9. **Prune**: Decay-based stale memory archival
10. **Extract**: LLM-powered structured extraction
11. **Mine**: Extract memories from transcripts
12. **Hooks**: Agent lifecycle integration
13. **Plugin Gen**: Per-agent plugin manifest generator
14. **Normalizers**: Conversation format importers (Discord, Telegram, WhatsApp, etc.)

## Database Models

### SQLiteStore (Metadata Store)
Tables (inferred from code):
- **vaults**: id, name, created_at
- **shelves**: id, vault_id, name, created_at
- **folders**: id, shelf_id, name, created_at
- **notes**: id, folder_id, name, content, created_at, updated_at, expires_at
- **memories**: id, vault_id, shelf_id, folder_id, note_id, content, vector_id, created_at, updated_at, expires_at
- **graph_edges**: id, source_memory_id, target_memory_id, relation_type, created_at
- **learnings**: id, category, context, solution, created_at
- **diaries**: id, session_id, title, summary, content, exchange_count, created_at

### ChromaDB/SQLite-vec (Vector Store)
Collections (per vault/shelf combination):
- Naming scheme: `v{len(vault):03d}_{vault}_s{len(shelf):03d}_{shelf}`
- Stores: embeddings, documents (content), metadata (vault, shelf, folder, note, timestamps, custom metadata)

## Auth Flows

### REST Server Authentication
- **API Key Auth**: Requires `MEMORIUS_API_KEY` env var
- **Header**: `Authorization: Bearer <key>`
- **Rate Limiting**: 500 requests/min per IP
- **CORS**: Restrictive by default (Obsidian app + localhost only)

### MCP Server Authentication
- **Transport Security**: Relies on stdio transport security (no additional auth layer)
- **Agent Validation**: Auto-detection of agent type via payload markers

### Hook Engine Authentication
- **Auto-detection**: No config needed - detects agent from stdin payload
- **Supported Agents**: Claude Code, Codex CLI, Gemini CLI, OpenClaw, OpenCode, Pi, Generic
- **Actions**: mine_dir, diary, conditional_diary, command, log, webhook, inject_context, consolidate, factcheck, allow/block

## Active CI Pipelines

### GitHub Actions (from .github/workflows/)
1. **test.yml**: 
   - Runs on push/pull_request to main
   - Tests: type-check, lint, build
   - Uses: actions/checkout@v4, pnpm/action-setup@v4, actions/setup-node@v4 (node-version: 24)
   - Commands: `pnpm install --frozen-lockfile`, `pnpm tsc --noEmit`, `pnpm lint`, `pnpm build`

2. **publish.yml**:
   - Runs on push to tags starting with 'v'
   - Builds and publishes to PyPI
   - Uses: pypa/gh-action-pypi-release

### Local Development Commands
- `pytest`: Run test suite
- `memorius doctor`: Run health checks
- `memorius status`: Show vault status
- `memorius serve-rest`: Start REST API server
- `memorius serve`: Start MCP server

## Current Architecture Assessment

### Strengths
1. **Agent-agnostic design**: Works with 7+ agents via MCP/CLI/hooks
2. **Multi-layer storage**: Vector (semantic) + SQLite (metadata/time) + Graph (relationships)
3. **Temporal awareness**: Ebbinghaus forgetting curve in search ranking
4. **Knowledge graph**: Auto-linked memories with contradiction detection
5. **Observability**: `memorius doctor`, `memorius stats`, hook-based introspection
6. **Multi-tenancy**: Vault > Shelf > Folder > Note hierarchy with strong isolation
7. **Flexibility**: Pluggable embedding providers, swapable vector backends
8. **Production-ready**: Rate limiting, input validation, path traversal guards, dependency pinning

### Areas for Improvement (vs 2026 Trends)
1. **Neuroscience-inspired mechanisms**: Missing sleep-phase consolidation, interference-based forgetting, engram maturation, neuromodulator-gated retrieval
2. **Advanced graph semantics**: Graph lacks temporal/causal/episodic edge types, spreading-activation retrieval
3. **Hybrid retrieval**: No inverted-index (BM25/TF-IDF) fallback for keyword/exact-match
4. **Token efficiency**: No product quantization/binary quantizers for vector index optimization
5. **Episodic/Semantic segregation**: No automatic separation of raw traces vs distilled facts
6. **Production-grade observability**: Missing Prometheus metrics, fine-grained latency/utilization tracking
7. **Value-driven retention**: No utility scoring based on retrieval frequency/reward signals
8. **Managed cloud option**: Purely self-hosted, no hosted/VPC offering

## Recommended Improvement Areas

Based on the gap analysis, the priority enhancement areas align with the goal:
1. Neuroscience-inspired consolidation module
2. Extended knowledge graph with typed/temporal edges
3. Hybrid keyword/vector retrieval with score fusion
4. Token-efficient vector index options
5. Automatic episodic vs. semantic segregation
6. Production-grade observability (Prometheus metrics, enhanced doctor)
7. Documentation and usage guides