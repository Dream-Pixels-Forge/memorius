# Database Analyst Report — memorius

**Product:** memorius v0.9.3 — self-contained memory vault for AI agents (vector search, session diaries, knowledge graph).
**Repo:** `/home/dimona/Dream-Pixels-Forge/Dev/cli/memorius`
**Storage stack:** ChromaDB (`chromadb>=0.4.22`) default vector store + `sqlite-vec>=0.1.0` alternative (`memorius/sqlite_vec_store.py`); SQLite metadata store (`memorius/meta_store.py`); knowledge graph in `memorius/graph.py` reached via `SQLiteStore` adapter methods.
**No formal SQL schema/migrations** — Chroma and sqlite-vec manage their own files under `~/.memorius/data`.

---

## Scope & Entry Points

- `memorius/vault.py` — `VaultEngine` orchestrator (Vault > Shelf > Folder > Note hierarchy).
- `memorius/meta_store.py` — `SQLiteStore` (metadata + graph tables).
- `memorius/vector_store.py` + `memorius/vector_store_base.py` — `ChromaStore` (default).
- `memorius/sqlite_vec_store.py` — `SqliteVecStore` (optional vector backend).
- `memorius/graph.py` — nodes/edges with relations `related/references/contradicts/co_occurs`.
- `memorius/backup.py` — `export_json`/`export_markdown`/`import_json`.
- `memorius/doctor.py` — storage/vector drift checks; `memorius repair`.
- `pyproject.toml` — `chromadb`, `sqlite-vec` runtime deps; `requires-python >=3.11`.

---

## Findings (bullets tagged [observation|risk|gap])

### 1. Schema — memory model
- [observation] Memory row: `id` (UUID4), `content`, `vault`, `shelf`, `folder`, `note`, `metadata` (JSON), `created_at`, `updated_at`, `expires_at` (ttl), `decay_score`, plus the embedding `vector` held only in the vector store (stripped from API responses). `memorius/models.py` `Memory` dataclass; `SQLiteStore` mirrors these columns in `memory_meta`.
- [observation] Hierarchy enforced by name validation: `validate_name` (`validation.py:9-28`, regex `^[a-zA-Z0-9_\-]+$`, max 128 chars) blocks `..`, `/`, metacharacters before any filesystem or DB use.
- [observation] Episodic/semantic split: two vector stores (`vectors`, `vectors_episodic`) and two meta stores created in `VaultEngine.__init__` (`vault.py:84-105`). Routing in `store()` is a path heuristic — episodic only when `shelf=="conversations" AND folder=="mined" AND note=="transcript"` (`vault.py:325-336`); everything else goes semantic.

### 2. Migrations — versioned schema handling
- [gap] No migration tooling, no versioned schema table, no `alembic`-equivalent. Chroma and sqlite-vec self-manage their files; `config.py` handles config versioning only. Prior-version data compatibility is not explicitly addressed (v0.9.3 assumes current-format storage).
- [observation] `doctor.run_checks` reports drift between `memory_meta` row count and Chroma vector count and suggests `memorius repair` (`doctor.py`), but there is no auto-migration on startup or write paths.

### 3. Queries
- [observation] Semantic search path: embed query → vector similarity query → metadata filter (vault/shelf/folder/note) → post-filter tags in Python (Chroma `where` cannot test list membership, per `search_module.py` docstring). `VaultEngine.search` (`vault.py:232`) queries semantic + episodic SearchModules, merges semantic-first then episodic by distance, caps at `ceil(limit*1.5)` when `expand_graph` else `limit`.
- [observation] Graph traversal: 1-hop expand via `SQLiteStore.expand_graph` (`meta_store.py`), relations `related/references/contradicts/co_occurs`, `graph_min_weight` default 0.3.
- [observation] Cursor pagination: composite cursor `"timestamp~memory_id"` in `SQLiteStore.list_memories_meta` (`meta_store.py:503-562`), ordering `(created_at, id) < (?, ?)`; `VaultEngine.list_memories` merges episodic + semantic and re-sorts by `created_at` DESC (`vault.py:391-421`). `VaultEngine.search` has NO `cursor` parameter despite MCP `memorius_search` advertising one (`mcp_server.py:509-529` vs `vault.py:232`) — advertised but ignored.
- [observation] TTL/decay: `ARCHIVE_THRESHOLD=0.1` (`temporal.py:24`); `find_stale_memories` flags decay < threshold or past `expires_at` (`temporal.py:123`); `VaultEngine.prune` archives/hard-deletes stale (`vault.py:647-690`).

### 4. Indexes
- [observation] ChromaDB manages its own HNSW/index internals (no memorius-level index config exposed). `sqlite_vec_store` uses sqlite-vec virtual tables (`sqlite_vec_store.py`).
- [observation] BM25 keyword search exists (`tests/test_bm25.py`) and hybrid retrieval (`tests/test_hybrid_retrieval.py`) — covered by tests but not a prominent CLI/MCP surface.
- [gap] No explicit index tuning, no full-text index configuration, no composite index hints beyond what Chroma/sqlite-vec provide by default.

### 5. Transactions — atomicity & rollback
- [risk] No cross-store transactions: `StoreModule.store` (`store_module.py:76-96`) writes vector first, then meta, then verifies both contain the row. A meta failure after vector success (or vice versa) leaves drift with no rollback. `repair()` is the offline remedy, never run automatically on write paths or startup.
- [risk] `VaultEngine.close()` swallows every exception (`except Exception: pass`, `vault.py:123-129`) and `__del__` calls it — cleanup failures (unclosed Chroma/SQLite) are silently masked at interpreter shutdown.
- [observation] `SQLiteStore` uses thread-local connections per db path + one `threading.Lock` per instance + `PRAGMA busy_timeout=5000` + WAL (`meta_store.py:55-70`, `113-128`); `sqlite_vec_store.SqliteVecStore` uses `threading.local()` connection + one `threading.Lock` (`sqlite_vec_store.py:42-44, 105`).
- [gap] `ChromaStore` creates a lazy `PersistentClient` per instance with a collection-cache dict and `_retry` backoff (`vector_store.py:82-103`); no explicit lock around collection cache or client creation.

### 6. RLS / row-level isolation
- [observation] Per-vault isolation: every store query filters by `vault`; `ensure_vault("main", ...)` created on init (`vault.py`, `cmd_init`). Multi-vault supported (CLI `--vault`, MCP `vault` param, REST `?vault=`).
- [gap] No row-level security beyond vault name filtering; no users, roles, or per-memory ACLs. Any caller who can reach the engine/REST/MCP can read any vault's content (subject only to the optional `MEMORIUS_API_KEY` on REST).

### 7. Backups
- [observation] `memorius.backup`: `export_json(engine, dest)`, `export_markdown(engine, dest)`, `import_json(engine, src, merge)` (`backup.py`). CLI `memorius export`/`import` wrap these (`cli/main.py`).
- [observation] Backup round-trip tested: `tests/test_feature_backup.py` (JSON round-trip, markdown export, schema-version rejection, graph edges round-trip).
- [observation] Drift repair: `VaultEngine.repair` enumerates Chroma collections, finds orphaned vector IDs (no `memory_meta` row) and missing IDs (meta row with no vector), removes orphans and re-embeds missing when `reindex=True` (`vault.py:684-786`); metadata store is source of truth; dry-run supported.
- [gap] No automated/scheduled backup; no WAL archiving; no point-in-time recovery; backup files not integrity-checked (no checksums).

### 8. Storage layout
- [observation] Default config `~/.memorius/config.yaml`; storage path `~/.memorius/data` (`config.py DEFAULT_CONFIG_YAML`); overridable via `MEMORIUS_STORAGE_PATH` env var.
- [observation] Single-instance lock: `<storage>/serve.lock` (`fcntl.flock`, `single_instance.py`); daemon PID file `~/.memorius/serve.pid` (`cli/main.py`).
- [gap] Chroma persist directory location not explicitly configured; relies on Chroma defaults within the storage path.

---

## Highlights (3-5 short)

1. Storage is ChromaDB (default) + SQLite metadata + optional sqlite-vec, with no formal schema/migrations — Chroma and sqlite-vec self-manage their files.
2. No cross-store transactions: vector and meta are written non-atomically; drift is repaired on demand via `VaultEngine.repair`, never automatically.
3. Per-vault isolation exists but there is no RBAC/ACL beyond vault name filtering.
4. Backups exist (JSON/Markdown export/import, tested round-trip) but are manual, unscheduled, and unchecksummed.
5. Cursor pagination works for `list_memories` but `search` advertises an unused `cursor`.

---

## Domain summary

memorius persists memories in ChromaDB (default vector store) or sqlite-vec, with a SQLite metadata store holding the Vault > Shelf > Folder > Note hierarchy and a small knowledge graph (`related/references/contradicts/co_occurs`). There is no migration tooling or versioned schema; Chroma and sqlite-vec manage their own files. Queries flow embed → vector → metadata filter → post-filter tags, with 1-hop graph expansion and composite-cursor (`timestamp~id`) pagination for listing. The critical database risk is the absence of cross-store atomicity: vector and meta writes are non-transactional, so `repair()` must be run manually to reconcile drift. Per-vault isolation exists but no RBAC/ACL. Backups (JSON/Markdown export/import) are tested but manual and unscheduled. The clearest place to continue work: `memorius/store_module.py` (write-path atomicity), `memorius/vault.py` (repair/prune), and `memorius/meta_store.py` (cursor/listing). Suggested canonical home: `dev-notes/teammate-analysis/database.md` (this file).
