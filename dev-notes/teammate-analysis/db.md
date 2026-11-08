# Memorius Database Audit Report

**Repository:** /home/dimona/Dream-Pixels-Forge/Dev/cli/memorius
**Audited files:** `memorius/meta_store.py`, `memorius/sqlite_vec_store.py`, `memorius/vector_store.py`, `memorius/backup.py`, `memorius/vault.py` (+ `memorius/mcp_server.py` for tool-layer defaults)
**Auditor role:** Senior database analyst
**Output:** Markdown only

---

## Executive Summary

Memorius is a dual-store system: a SQLite metadata store (`memorius.db`, table `memory_meta` plus hierarchy/diaries/graph tables) paired with a pluggable vector store (ChromaDB default, optional `sqlite-vec`). The metadata layer is generally well-written: parameterized queries are used everywhere, WAL mode is enabled, a `transaction()` context manager exists, and useful indexes are present on `memory_meta(vault)`, `memory_meta(archived)`, and `memory_meta(created_at, id)`.

The dominant theme across the audit is **cross-store fragility**. The vector store and metadata store are updated independently with no transactional boundary between them, so any failure mid-write (re-embedding, vector upsert, graph edge insert) leaves the two stores silently divergent. Repair exists (`vault.repair()`) but is opt-in and never runs on write paths. Several destructive operations (prune hard-delete, consolidate merge) default to `dry_run=False` with no snapshot/undo, and there are no foreign keys or CHECK constraints at the SQL level, so referential integrity and domain invariants are enforced only by application code.

**Total findings: 14** (1 Critical, 5 High, 6 Medium, 2 Low).

---

## Findings

### SQL — Injection Surface (verified safe, but fragile)

| # | File:line | Severity | Description | Fix |
|---|-----------|----------|-------------|-----|
| 1 | `meta_store.py:82,102` `sqlite_vec_store.py:237-242` `sqlite_vec_store.py:313-315` | Low | All writes use parameterized queries, so injection is not exploitable today. However `sqlite_vec_store.py` `search()` builds the `WHERE` clause by interpolating filter_metadata keys (`f"{k} = ?"`) after validating against `_ALLOWED_FILTER_COLS = {"folder", "note"}`. `get_by_ids()` builds `IN (?,?,...)` placeholders from `len(ids)`. Both are safe only while the allowlist and placeholder logic are maintained; adding a new filter column or a caller-controlled table/column name would reintroduce injection. | Keep the allowlist approach but document it as a security boundary. If dynamic columns are ever required, switch to an explicit whitelist mapping (column name -> SQL fragment) rather than interpolating raw keys. Add a unit test asserting that disallowed `filter_metadata` keys are ignored and never reach the SQL string. |

---

### Concurrency & Connection Management

| # | File:line | Severity | Description | Fix |
|---|-----------|----------|-------------|-----|
| 2 | `meta_store.py:69,72` `sqlite_vec_store.py:84` | Medium | Both stores enable WAL and set `busy_timeout=5000`, which helps but does not eliminate write-write contention under concurrent writers. Every `execute()`/`execute_many()` commits immediately, so lock churn is high under batch loads. | Consider batching multiple operations inside a single `transaction()` block (one commit) for bulk imports/prunes/repairs. Evaluate `PRAGMA synchronous=FULL` or `PRAGMA locking_mode=EXCLUSIVE` for single-process bulk jobs. |
| 3 | `meta_store.py:1077` `meta_store.py:1081` `meta_store.py:41` `sqlite_vec_store.py:115-128` | Medium | `close()` is registered via `atexit` and `__del__` calls `close()`, which can raise or be silently ignored during interpreter shutdown. `_cleanup_idle_connections()` in both stores tracks `last_use_times` but `sqlite_vec_store.py:128` admits it "doesn't actually have access to the connection object" — idle connections are never closed. Connections are thread-local and unbounded, so long-running multi-threaded processes can exhaust file descriptors. | Implement a real connection pool with a hard cap and TTL-based eviction that actually closes idle `sqlite3` connections. Guard `__del__`/shutdown paths so `close()` never raises during interpreter teardown. Add `max_connections` config and `close_all()` for tests. |

---

### Transactional Integrity (cross-store)

| # | File:line | Severity | Description | Fix |
|---|-----------|----------|-------------|-----|
| 4 | `meta_store.py:82,102` `meta_store.py:163` `vault.py:440-469` `vault.py:551-556` | High | `execute()` and `execute_many()` auto-commit per call. A `transaction()` context manager exists (`meta_store.py:163`) but is never used for operations that span both stores. `VaultEngine.store()`, `update_memory()`, `delete()`, and `consolidate()` write to the vector store **and** the meta store independently. If the vector upsert succeeds and the meta insert fails (or vice versa), the stores drift with no rollback. | Wrap cross-store writes (store, update, delete, consolidate merge) in a single transaction boundary where possible. For the vector store (ChromaDB/sqlite-vec) which lacks SQLite transactions, adopt an outbox/write-ahead pattern: write intent to meta first, then vector, then mark meta committed; on failure, reconcile via `repair()`. At minimum, document which operations are non-atomic and surface a `drift_detected` flag in `status()`. |

---

### Backup / Import Integrity

| # | File:line | Severity | Description | Fix |
|---|-----------|----------|-------------|-----|
| 5 | `backup.py:81-154` | High | `import_json()` imports hierarchy + memory meta, then re-derives vectors via `engine._vector.add()` (`backup.py:143-154`). If re-embedding fails, the memory row exists in `memory_meta` but has no vector — the memory is importable but invisible to search. The failure is logged as a warning and ignored; import reports success. | Make vector re-derivation part of import success: fail the import (or mark the memory `archived` / flagged `needs_reindex`) when `engine._vector.add()` raises, and return per-memory errors in the stats dict instead of swallowing them. |
| 6 | `backup.py:~166` `meta_store.py:1019-1034` | Medium | `import_graph_edges()` wraps each edge in `try/except: pass` (`meta_store.py:1019`), so corrupted edges are silently skipped and import reports a count that overstates what was actually persisted. `merge=True` also silently skips existing IDs with no way for the caller to know which were skipped beyond the aggregate counter. | Log each skipped edge with its ID and error reason. Return per-edge import status (imported/skipped/reason) in the stats dict, and expose `memories_skipped` IDs so callers can reconcile. |
| 7 | `backup.py:177-200` | Low | `export_markdown()` writes one `.md` per memory under `<dest>/<vault>/<shelf>/<folder>/<note>/<id>.md`. `dest` comes straight from the CLI argument with no up-front validation; a per-memory path-traversal guard exists inside the loop but `dest` itself is never checked before `mkdir`. | Validate `dest` is an absolute, non-traversal path (resolve and compare against an allowed base directory) before creating anything. Reject relative or `..`-containing destinations up front. |

---

### Destructive Operations (prune / consolidate)

| # | File:line | Severity | Description | Fix |
|---|-----------|----------|-------------|-----|
| 8 | `vault.py:647-680` `cli/main.py:~1100` | High | `prune()` hard-deletes memories when `archive=False` (`vault.py:680` calls `self.delete(mid)`), with no confirmation prompt in the API layer and no undo. `find_stale_memories()` defaults to `limit=100` (`meta_store.py:479` delegates to temporal module), so stale memories beyond the first 100 are never candidates and are never pruned — stale data accumulates silently. | Require an explicit `confirm=True` parameter for hard-delete prune (default `False`). Remove the hard `limit=100` or make it configurable with pagination; document that prune only considers the first N candidates. Add an audit log of pruned/deleted IDs. |
| 9 | `vault.py:551-556` `mcp_server.py:619-623` `mcp_server.py:136` | Critical | `consolidate()` merges memories destructively with no snapshot and no `dry_run` enforcement at the MCP layer — `tool_memorius_consolidate` passes `dry_run=args.get("dry_run", False)`, so consolidation mutates data by default. A bad similarity threshold can merge distinct memories irreversibly. | Make `dry_run=True` the default for the MCP tool and require the caller to opt in to mutation (`dry_run=False` explicitly). Add a pre-consolidation snapshot (export JSON + vector IDs) that can be restored on failure. Surface a preview of candidate merge pairs before any write. |

---

### Indexing & Schema Design

| # | File:line | Severity | Description | Fix |
|---|-----------|----------|-------------|-----|
| 10 | `meta_store.py:372-390` `sqlite_vec_store.py:101-107` `vector_store.py:~180` | Medium | `memory_meta` has indexes on `vault`, `archived`, and `(created_at, id)` — good — but **no individual index on `shelf`, `folder`, or `note`**. Queries filtering by shelf/folder without a vault constraint (e.g. `list_memories(shelf=...)`) scan `memory_meta`. `sqlite-vec` has `idx_memories_vault(vault, shelf)` — good. ChromaDB HNSW is auto-tuned with no operator-controlled `construction_ef`/`M`/`ef_search` except behind an opt-in config flag. | Add indexes: `CREATE INDEX idx_memory_meta_shelf ON memory_meta(shelf)`, `idx_memory_meta_folder ON memory_meta(folder)`, `idx_memory_meta_note ON memory_meta(note)` (or composite `(vault, shelf, folder, note)` matching common query shapes). Expose HNSW tuning parameters in config and apply them at collection creation (`vector_store.py` already reads `vector_optimization` but it is opt-in and undocumented). |

---

### Referential Integrity

| # | File:line | Severity | Description | Fix |
|---|-----------|----------|-------------|-----|
| 11 | `meta_store.py:226-244` `meta_store.py:372-390` `meta_store.py:1019` `vault.py:684-790` | High | `PRAGMA foreign_keys=ON` is only toggled inside the diaries migration script (`meta_store.py:226,244`), never enabled globally. `memory_meta` references `vaults`/`shelves`/`folders`/`notes` by name with `REFERENCES` declared but unenforced (no `PRAGMA foreign_keys`). Deleting a vault does not cascade to memories. Graph edges (`memory_graph`) reference memory IDs with no FK; orphaned edges are possible and `repair()` (`vault.py:684`) only reconciles orphaned **vectors**, not graph edges. | Enable `PRAGMA foreign_keys=ON` on every connection (`_conn()` and `_lazy_conn()`). Add `ON DELETE CASCADE` where semantically correct, or at least validate existence before insert. Extend `repair()` to detect and delete orphaned graph edges (`source_id`/`target_id` not in `memory_meta`), and run it automatically or on a schedule. |

---

### Vector/Meta Drift (write-path)

| # | File:line | Severity | Description | Fix |
|---|-----------|----------|-------------|-----|
| 12 | `vault.py:684-790` | High | `repair()` detects orphaned vectors (vector with no `memory_meta` row) and missing vectors (`memory_meta` row with no vector), but it is **not automatic** and is never invoked on write paths (`store`, `delete`, `update_memory`). Every independent write is a drift opportunity that accumulates until an admin manually runs `repair()`. | Invoke a lightweight drift check after cross-store writes (or as a background reconciliation job), and surface drift counts in `status()`/`get_memory_stats()`. Make `repair()` runnable with `reindex=True` by default for missing vectors. |

---

### Connection Cleanup / Shutdown

| # | File:line | Severity | Description | Fix |
|---|-----------|----------|-------------|-----|
| 13 | `meta_store.py:1077` `meta_store.py:1081` `meta_store.py:41` | Medium | `close()` relies on `atexit`; `__del__` calls `close()` which may fail during interpreter shutdown (logged/swallowed). `close_connection()` pops a connection from the thread-local dict but does not check whether it is in use by an ongoing transaction. | Make `close()` idempotent and shutdown-safe (catch all exceptions, never raise). Track active transactions per connection and refuse/close only idle connections. Prefer explicit `with VaultEngine()` context management over `__del__`. |

---

### Data Types & Domain Constraints

| # | File:line | Severity | Description | Fix |
|---|-----------|----------|-------------|-----|
| 14 | `meta_store.py:372-390` | Medium | `memory_meta.content TEXT DEFAULT ''` has no DB-level size limit (only application `MAX_CONTENT_LENGTH=100KB` — not verified in schema). `metadata TEXT DEFAULT '{}'` stores JSON as text with no validation that it is parseable JSON. No `CHECK` constraints on `archived IN (0,1)` or `access_count >= 0`. Corrupt or out-of-domain data can be inserted directly via SQL. | Add `CHECK (archived IN (0,1))`, `CHECK (access_count >= 0)`, and `CHECK (json_valid(metadata))` to the `memory_meta` DDL. Add a content-length `CHECK (length(content) <= 102400)` at the DB layer as defense in depth. |

---

## Severity Summary

| Severity | Count | Findings |
|----------|-------|----------|
| Critical | 1 | #9 — Consolidation mutates by default, no snapshot/undo |
| High | 5 | #4 — No cross-store transaction boundary; #5 — Import silently drops vectors on re-embed failure; #8 — Hard-delete prune with no confirmation/undo; #11 — No enforced foreign keys; orphaned edges not repaired; #12 — Drift never reconciled on write paths |
| Medium | 6 | #2 — WAL contention / no batching; #3 — Idle connections never closed, unbounded FDs; #6 — Corrupted graph edges silently skipped; #10 — Missing indexes on shelf/folder/note; #13 — Unsafe `close()`/`__del__` during shutdown; #14 — No CHECK constraints / JSON validation |
| Low | 2 | #1 — SQL injection surface safe but fragile; #7 — `export_markdown` dest not pre-validated |

**Total: 14 findings**

---

## Recommended Remediation Order

1. **#9** — Flip MCP `consolidate` default to `dry_run=True`; add snapshot/preview.
2. **#4** — Introduce a cross-store write boundary (transaction + outbox/repair reconciliation) for store/update/delete.
3. **#5** — Fail import (or flag `needs_reindex`) when vector re-derivation fails; stop swallowing errors.
4. **#11** — Enable `PRAGMA foreign_keys=ON` globally; extend `repair()` to orphaned graph edges.
5. **#8** — Add confirmation requirement and remove/raise the `limit=100` cap on stale-memory discovery.
6. **#2 / #3** — Batch commits inside `transaction()`; implement real idle-connection eviction with a connection cap.
7. **#10 / #14** — Add missing indexes and CHECK constraints; validate JSON metadata at the schema layer.
8. **#1 / #7** — Document the filter_metadata allowlist as a security boundary; validate `export_markdown` dest up front.

---
*End of report.*