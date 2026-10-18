# Memorius Implementation Plan

Status of the repo after the 0.4.5 hardening pass that produced this document:

- **Phase 0 — Bug fixes: COMPLETE** (9 verified bugs fixed; 9 regression tests added in `tests/test_regression_bugs.py`; full suite 123 green — 104 non-integration in ~40s, 10 integration in ~92s, 9 regression in ~14s).
- **Phase 1.1 — Graph-aware retrieval: COMPLETE** (`engine.search(expand_graph=...)` walks the knowledge graph from primary hits and appends 1-hop linked memories, deduped and capped at `ceil(limit*1.5)`; `ContextInjector.inject` defaults `expand_graph=True`; `memorius search --expand-graph` CLI flag; MCP `memorius_search.expand_graph` and REST `POST /search.expand_graph` booleans; new `engine.get_memories_by_ids()` helper; 9 feature tests in `tests/test_feature_graph_retrieval.py`. Suite now 132 green — 122 non-integration in ~58s, 10 integration in ~76s, 9 feature in ~33s).
- **Phase 1.3 — Metadata/tag filtering in search: COMPLETE** (`engine.search(..., folder=, note=, tags=)` threads folder/note to Chroma's `where` clause; tags are post-filtered in Python (Chroma can't test list membership) over a 4x over-fetch so the limit still holds after the universe shrinks; CLI `memorius search --folder --note --tag` (tag repeatable, AND-semantics); MCP `memorius_search.folder/note/tags` and REST `POST /search` gain the same keys; 9 feature tests in `tests/test_feature_search_filtering.py`. Suite now 141 green — 131 non-integration in ~104s, 10 integration in ~71s, 9 feature in ~23s).
- **Phase 4.1 — Factcheck word-boundary fix: COMPLETE** (`_detect_contradiction` now uses `\b` word-boundary regexes instead of bare `in` substring, so "is" no longer matches inside "this"/"history" and "no" no longer matches inside "know"/"note"; added `("always","never")` and `("increase","decrease")` opposing pairs; entity-slot heuristic tightened to require nearly-equal sentence length (len_ratio >= 0.8 — trailing additions no longer trip) and exactly one non-stopword entity diff (multiple diffs = paraphrase, not contradiction); 12 feature tests in `tests/test_feature_factcheck_access.py`. Suite 153 green — 143 non-integration, 10 integration.).
- **Phase 4.2 — Search access-recording fix: COMPLETE** (vault.search no longer calls record_access on every returned result — that distorted the reinforcement model; new `engine.touch(memory_id)` provides explicit reinforcement; ContextInjector.inject touches only the memories it actually injects — the ones that pass the >20-char content filter and fit the limit). Tests in the same file. **0.5.0 release scope now complete**: 1.1 + 1.3 + 4.1 + 4.2.
- This document covers **Phase 1 onward — new features**, with 1.1 already shipped. The remainder is deliberately a plan, not a spec: each item names the goal, the files it touches, the user-facing API surface, the tests it needs, and the risks. Implementation is staged so each phase ships independently and never blocks the next.

Prioritization rubric: **Impact × Confidence ÷ Effort**. P1 items are the ones that most materially change what memorius *does* for the user; P4 are nice-to-haves and infra hardening.

---

## Phase 1 — Make the graph and metadata retrieval actually pay off  *(highest leverage)*

The knowledge graph and temporal metadata already exist and are already maintained, but neither is *read* during retrieval. Three features wire them into the hot path. Ship together as one coherent "smarter recall" release.

### 1.1 Graph-aware retrieval — `expand_graph` in `search` / `context`  ✅ SHIPPED
**Goal:** when a memory matches a query, also surface 1-hop linked memories (the "you also worked on X" effect). The graph is built on every store but never read today.

**Shipped in commit after the 0.4.5 hardening pass.** `engine.search(..., expand_graph=True, graph_hops=1, graph_min_weight=0.3)` appends graph-expanded memories (deduped against seeds, capped at `math.ceil(limit * 1.5)` total). `ContextInjector.inject` defaults `expand_graph=True`. CLI `--expand-graph`, MCP `memorius_search.expand_graph`, REST `POST /search.expand_graph` (all default off except context injection, where it's on). New `engine.get_memories_by_ids(ids, with_vectors=...)` helper. 9 feature tests in `tests/test_feature_graph_retrieval.py`.

**Files:** `memorius/vault.py` (search), `memorius/context_inject.py` (inject), `memorius/graph.py` (no change — `expand_graph` already exists), `memorius/mcp_server.py` + `memorius/rest_server.py` (optional `expand` flag).

**API surface:**
- `engine.search(query, ..., expand_graph: bool = False, graph_hops: int = 1, graph_min_weight: float = 0.3)` — when `expand_graph=True`, after the primary results, run `expand_graph(conn, [m.id for m in results], hops=graph_hops, min_weight=graph_min_weight)` and append the expanded memories (deduped, excluding the seeds) to the result list, capped so total ≤ `limit * 1.5`.
- MCP `memorius_search` / REST `POST /search`: add optional `expand_graph` boolean (default false to preserve current behavior; opt-in for graph-savvy agents).
- `context` injector: default `expand_graph=True` with `graph_hops=1` (context is the natural place to pull in related memories).

**Tests:** store A; store B linked to A (via content proximity); store unrelated C. Search for A with `expand_graph=True` → results contain B. Without the flag → B absent. Confirm dedup when B is already a primary hit.

**Risks:** graph can grow large; cap `expand_graph` `max_nodes` (already 50) and only expand when the primary result set is < `limit`. Backward-compatible because it's opt-in.

### 1.2 Contradiction edges — persist factcheck verdicts in the graph  ✅ SHIPPED
**Goal:** `factcheck` already detects contradictions; today they're discarded. Persist them as `relation='contradicts'` edges so the graph becomes a soft "memory consistency" layer future searches/factchecks can exploit.

**Files:** `memorius/factcheck.py` (after computing contradicting memories, call `link_memories(conn, statement_memory_id, contra_memory_id, weight=confidence, relation='contradicts')`), `memorius/graph.py` (`get_linked` already filters by relation — no change), `memorius/vault.py` (expose `contradicts` via a new `get_contradictions(memory_id)` helper).

**API surface:** `engine.get_contradictions(memory_id)` returns linked memories with `relation='contradicts'`. Add MCP `memorius_contradictions` + REST `GET /contradictions/{id}`.

**Tests:** store M1 "project uses React"; store M2 "project uses Vue"; `factcheck("project uses Vue")` → creates a `contradicts` edge M2→M1; `get_contradictions(M2.id)` returns M1.

**Risks:** factcheck's substring matching is noisy (see Phase 4.1); ship 1.2 *after* 4.1 to avoid persisting junk edges. If shipped first, gate edge creation on `confidence >= 0.7`.

### 1.3 Metadata & tag filtering in search  ✅ SHIPPED
**Goal:** `ChromaStore.search` already accepts `filter_metadata`; expose it so users can filter by folder/note/arbitrary tags without leaving the query.

**Shipped in commit after Phase 1.1.** `engine.search(..., folder=, note=, tags=)` validates folder/note (name regex) and passes them to Chroma's `where` clause; `tags` is a list with AND-semantics and is post-filtered in Python over a 4x over-fetch (Chroma's `where` can't test list membership, so we pull more and filter down — the limit still holds after the universe shrinks). CLI `memorius search --folder F --note N --tag T [--tag T2]`; MCP `memorius_search` gains `folder`/`note`/`tags` schema fields; REST `POST /search` gains the same payload keys. 9 feature tests in `tests/test_feature_search_filtering.py`.

**Files:** `memorius/vault.py` (thread `filter_metadata` through), `memorius/cli/main.py` (`memorius search ... --folder F --note N --tag T`), `memorius/mcp_server.py` + `memorius/rest_server.py` (optional `filter` object).

**Tests:** store 3 memories across 2 folders; `search(q, folder=...)` returns only the matching folder's hits.

**Risks:** Chroma `where` clauses only support scalar equality on indexed metadata fields — document the constraint; no range/in on the same field. (Folder/note are already stored as Chroma metadata in `ChromaStore.add`.)

---

## Phase 2 — Complete the CRUD + lifecycle surface  *(fills obvious gaps)*

### 2.1 `get` / `update` / `delete` for a single memory, in all three interfaces  ✅ SHIPPED
**Goal:** today you can `store` and you can `delete` (CLI only). You cannot fetch one memory by ID, update its content, or delete it via MCP/REST. Complete the surface.

**Files:** `memorius/vault.py` (`get_memory(id)`, `update_memory(id, content=None, metadata=None)`), `memorius/meta_store.py` (`get_memory_meta` already exists; add `update_memory_meta`), `memorius/vector_store.py` (`ChromaStore.get` is one-shot; `update` = re-embed + upsert, already supported via `add`'s upsert path), CLI (`memorius get <id>`, `memorius update <id> --content ...`), MCP (`memorius_get`, `memorius_update`, `memorius_delete`), REST (`GET /memory/{id}`, `PATCH /memory/{id}`, `DELETE /memory/{id}`).

**API surface:**
- `get_memory(id)` → `Memory` (validates UUID, returns None if absent).
- `update_memory(id, content=None, metadata=None)` → re-embeds if content changed, upserts into Chroma, updates `memory_meta` row + `updated_at`. Metadata is merged (shallow), not replaced.
- `delete_memory(id, vault=None, shelf=None, dry_run=False)` → already exists; just wire to MCP/REST.

**Tests:** round-trip store→get→update→get (content changed, `updated_at` advanced, vector re-embedded); update metadata-only (content+vector unchanged); delete via MCP returns the same shape as CLI delete.

**Risks:** `update` changing content but keeping the same ID invalidates graph edges whose `weight` was computed from the old embedding — acceptable (edges stay; they just become stale). Document it.

### 2.2 `memorius prune` — surface the existing stale-archive machinery  ✅ SHIPPED
**Goal:** `temporal.find_stale_memories` and `temporal.archive_memories` exist but have no CLI command. Memories decay silently; users can't act on decay.

**Files:** `memorius/cli/main.py` (`memorius prune --threshold 0.1 --dry-run --archive`), `memorius/mcp_server.py` + `memorius/rest_server.py` (`memorius_prune` / `POST /prune`).

**API surface:** `engine.prune(threshold=ARCHIVE_THRESHOLD, dry_run=False, archive=True)` returns `{stale: [...], archived_count}`. `--dry-run` lists candidates without touching them. Default action is archive (soft), not delete.

**Tests:** store a memory, monkeypatch `calculate_decay_score` to return below threshold, `prune --dry-run` lists it, `prune` (no dry-run) sets `archived=1` in `memory_meta`, `get_memory_stats()['active']` drops by 1.

**Risks:** None functional. Communicate clearly that prune = soft archive, not destruction.

### 2.3 TTL / expiry on memories  ✅ SHIPPED
**Goal:** natural extension of the decay model — a memory can declare it expires after N days, after which `prune` archives it regardless of access.

**Files:** `memorius/models.py` (no schema change — store `expires_at` ISO timestamp in `metadata`), `memorius/temporal.py` (`find_stale_memories` also returns rows whose `metadata.expires_at < now`), `memorius/vault.py` (`store(..., ttl_days=N)` sets `metadata['expires_at']`), CLI (`memorius store ... --ttl 7`).

**Tests:** store with `--ttl 0` → immediately eligible for prune (dry-run lists it); store with `--ttl 30` → not eligible until 30 days pass (mock `now`).

**Risks:** `expires_at` lives in the JSON `metadata` column — Chroma metadata filtering on a date string is awkward; we only need it server-side in SQL, so this is fine.

---

## Phase 3 — Backup, migration, and import/export  *(trust & portability)*

### 3.1 `memorius export / import` — full vault dump (JSON + Markdown)  ✅ SHIPPED
**Goal:** a single-file backup of everything (memories + diaries + hierarchy + graph) and a matching importer. The existing Obsidian export only covers memories and is lossy.

**Files:** new `memorius/backup.py` (`export_vault(engine, path, fmt='json'|'markdown')`, `import_vault(engine, path, merge=True`), CLI (`memorius export vault.json`, `memorius import vault.json --merge`), MCP/REST (`POST /export`, `POST /import`).

**API surface:**
- JSON format: `{schema_version, exported_at, vaults: [...], memories: [...], diaries: [...], graph_edges: [...]}`. Idempotent re-import (keyed by memory ID, skip-or-replace).
- Markdown format: one file per memory under `<vault>/<shelf>/<folder>/<note>/<id>.md` with YAML frontmatter preserving metadata + the graph edges as frontmatter links. Best-effort round-trip.

**Tests:** export an empty vault → re-import → empty vault (no error); export a vault with 3 memories + 1 diary + 2 graph edges → wipe → import → diff equals zero (counts + a sample memory's content + the graph edges). Markdown round-trip loses graph edges (documented) but preserves content + hierarchy.

**Risks:** schema_version gate on import (reject older schemas with a message pointing at a migration path). Large vaults → stream JSON rather than build one giant dict (use `json.dump` with an iterator; not needed for v1).

### 3.2 `memorius doctor` — health check  ✅ SHIPPED
**Goal:** a single command that tells the user whether their install is healthy: config present & valid, ONNX model downloaded, SQLite DB opens, Chroma collections all under the 63-char limit and carrying `memorius_vault` metadata (i.e., the legacy migration ran), graph table present, no orphaned memory_meta rows (whose Chroma vector is gone).

**Shipped.** `memorius/doctor.py` with `run_checks(engine=None)` returning `{checks, healthy, summary}`. Checks: config parseable + required keys, storage dir writable, ONNX model present, memory_meta vs Chroma row count drift, collection names >63 chars, graph table health (warn if >10 memories but 0 edges). CLI `memorius doctor`. MCP `memorius_doctor` tool. REST `GET /doctor`. 7 feature tests in `tests/test_feature_doctor.py`. Suite: 201 green (191 non-int + 10 integration).

---

## Phase 4 — Quality hardening of existing features  *(not flashy, removes footguns)*

### 4.1 Factcheck: stop matching `"is"` inside `"this"` and `"no"` inside `"know"`  ✅ SHIPPED
**Goal:** `_detect_contradiction` uses bare `in` substring checks → huge false-positive rate. Rewrite to word-boundary regexes.

**Shipped.** `_detect_contradiction` now uses `re.search(rf"\b{re.escape(phrase)}\b", text)` for every negation pair (`is`/`is not`, `use`/`don't use`, etc.) and opposing pair (`yes`/`no`, `enable`/`disable`, etc.), with `("always","never")` and `("increase","decrease")` added. The entity-slot heuristic is tightened: sentences must have nearly-equal word count (length ratio >= 0.8, so trailing additions like "the sky is blue" vs "the sky is blue today" no longer trip), and exactly one non-stopword entity must differ (paraphrases with multiple diffs don't contradict). Tests: `tests/test_feature_factcheck_access.py` — 12 tests pinning the substring fix (`is` in `this`, `no` in `know`), the entity-slot tightening (trailing-word guard, multi-diff paraphrase guard), and the regression-safe real-contradiction cases (React vs Vue, `yes` vs `no`, `is` vs `is not`).

### 4.2 `search` records access on every returned result — distortion  ✅ SHIPPED
**Goal:** `vault.search` calls `record_access` for every result, including ones the agent never reads. This inflates `access_count` and corrupts the reinforcement model. Only record access when a memory is actually *used*.

**Shipped.** `vault.search` no longer calls `record_access` on its results. New public method `engine.touch(memory_id)` for explicit reinforcement — validates the UUID, safe on missing/invalid ids. `ContextInjector.inject` now calls `touch()` only on memories it actually injects (the ones that pass the >20-char content filter and fit the limit), not on the larger search candidate set. Tests: `tests/test_feature_factcheck_access.py` — search does not increment `access_count` or advance `last_accessed` across two searches; `touch` increments `access_count` to 1 then 2; missing/invalid ids are safe; injector touches the long injected memory but not the short filtered-out one.

**Files:** `memorius/factcheck.py`. Replace each `pos in text_a_lower` with `re.search(rf"\b{re.escape(pos)}\b", text_a_lower)`. Opposing pairs the same. Keep the entity-slot heuristic but require it to fire only when negations/pairs didn't match.

**Tests:** the sentences that previously false-contradicted ("the sky is blue" vs "the sky is blue today", "I know X" vs "yes X") now verify, not contradict.

**Risks:** Behavior change — some previously-"contradicted" verdicts will become "verified"; this is the point. Note in CHANGELOG.

### 4.2 `search` records access on every returned result — distortion
**Goal:** `vault.search` calls `record_access` for every result, including ones the agent never reads. This inflates `access_count` and corrupts the reinforcement model. Only record access when a memory is actually *used* (returned by `context` injection that the agent accepted, or fetched via `get_memory`).

**Files:** `memorius/vault.py` (remove the `record_access` loop from `search`; add `record_access(id)` calls to `get_memory` and to `ContextInjector.inject` only when a memory is actually injected). Add a new `engine.touch(id)` public method for explicit reinforcement.

**Tests:** `search` twice → `access_count` stays 0; `get_memory(id)` once → `access_count` becomes 1.

**Risks:** Small behavior change for callers relying on access_count growth from search alone — but that growth was noise. Document.

### 4.3 REST CORS wildcards are silently no-ops  ✅ SHIPPED
**Goal:** Starlette doesn't match `http://127.0.0.1:*` or `file://` against actual origins. Either enumerate the ports you actually serve on, or switch to `allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$"`.

**Shipped.** Replaced wildcard `allow_origins` list with `allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$"` plus explicit `allow_origins=["app://obsidian.md"]`. 6 tests in `tests/test_feature_cors.py` covering preflight on various ports/origins, actual requests with Origin header, and rejection of unknown origins.

### 4.4 Consolidation scaling — drop the in-memory O(n²)  ✅ SHIPPED
**Goal:** `consolidate` loads all vectors into RAM and does pairwise cosine. Past ~10k memories this is both slow and likely to OOM. Use Chroma's per-collection similarity query instead.

**Shipped.** Rewrote `consolidation.py` with two paths: `_find_clusters_in_memory` (O(N²) pairwise, used for ≤500 memories) and `_find_clusters_hnsw` (per-collection pairwise with union-find, used for >500 memories). `find_similar_clusters` auto-selects the path via `_HNSW_SWICHOVER = 500`. 10 tests in `tests/test_feature_consolidation_scaling.py` covering correctness of both paths, auto-switch detection, and a performance guard (600 memories under 5s). Suite: 217 green (207 non-int + 10 integration).

---

## Phase 5 — Performance & DX niceties  *(defer until P1-P4 shipped)*

- **5.1 Batch embedding for `mine` and bulk import** ✅ SHIPPED — `mine()` now batch-embeds all chunks in a single `embed()` call. `store()` accepts optional `_vector` param for pre-computed vectors. 5 tests in `tests/test_feature_batch_pagination.py`. Part of commit `2028bdc`.
- **5.2 Optional cross-encoder rerank** ✅ SHIPPED — `memorius[ranker]` extra (`sentence-transformers>=2.2.0`) lazy-loads `cross-encoder/ms-marco-MiniLM-L-6-v2`. `CrossEncoderReranker` class in `memorius/reranker.py` with `rerank_search_results()` and `get_reranker()` singleton. Wired into `vault.search(rerank=False)` with graceful ImportError fallback. CLI `--rerank` on search. MCP `rerank` boolean on `memorius_search`. REST `POST /search` accepts `rerank` field. `pyproject.toml` adds `ranker` extra, `all` updated. 10 tests in `tests/test_feature_rerank.py`.
- **5.3 SQLite-vec fallback for vectors** ✅ SHIPPED — `memorius/sqlite_vec_store.py` implements `SqliteVecStore` class (add/search/delete/get_by_ids/count/get_collections) using `sqlite-vec` extension with in-Python cosine distance. `VaultEngine` wired to select `SqliteVecStore` when `storage.type: "sqlite-vec"` in config. `pyproject.toml` adds `single-file` extra (`sqlite-vec>=0.1.0`), `all` updated. Cursor pagination tie-breaking fixed: composite `(created_at, id) < (?, ?)` tuple cursor in `meta_store.py`. 16 tests in `tests/test_feature_sqlite_vec.py`. Full suite: 254 green.
- **5.4 `serve-rest` daemon / socket activation** ✅ SHIPPED — `memorius serve-rest --daemon` (double-fork on Unix, detached subprocess on Windows) + `--stop` + `--pid-file`. 8 tests in `tests/test_feature_daemon.py`. Part of commit `ae5e0cb`.
- **5.5 Cursor pagination on search / list** ✅ SHIPPED — `list_memories()` returns `{"memories": [...], "next_cursor": timestamp|None}`. `cursor` param on MCP `memorius_list` and REST `GET /memories`. CLI `memorius list --cursor`. 8 tests in `tests/test_feature_batch_pagination.py`. Part of commit `2028bdc`.

---

## Sequencing & release plan

| Release | Contents | Why these together |
|---|---|---|
| **0.5.0** ✅ | Phase 1 (1.1, 1.3) + Phase 4.1, 4.2 | "Smarter recall" — graph + filters + honest factcheck + honest access stats ship as one coherent retrieval-quality story. 1.2 deferred to 0.5.1 pending 4.1. **ALL SHIPPED.** |
| **0.5.1** ✅ | Phase 1.2 + Phase 2.1 (get/update/delete) + Phase 2.2 (prune) | Contradiction edges need 4.1's clean factcheck; CRUD completion + prune form the "lifecycle" release. **ALL SHIPPED.** |
| **0.6.0** ✅ | Phase 2.3 (TTL) + Phase 3.1 (export/import) + Phase 3.2 (doctor) | Trust & portability — backup/restore/healthcheck as a release theme. **ALL SHIPPED.** |
| **0.7.0** ✅ | Phase 4.3, 4.4 (scale) | Quality hardening before any growth push. **ALL SHIPPED.** |
| **0.8.0** ✅ | Phase 5.1, 5.4, 5.5 | Batch embedding, daemon, cursor pagination. **ALL SHIPPED.** |
| **0.9.0** ✅ | Phase 5.2, 5.3 (cross-encoder rerank, sqlite-vec) | Opt-in/nice-to-haves — rerank for quality, sqlite-vec for single-file simplicity. **ALL SHIPPED.** |

Each phase's feature is independently testable, independently mergeable, and independently revertable. No phase is gated on another except as called out in 1.2 → 4.1.

---

## What this plan deliberately does *not* include

- **A cloud/SaaS sync mode.** Memorius's local-first posture is a feature; sync would belong in a separate companion package, not core.
- **A web UI.** A REST API + the existing CLI/MCP surface cover the agent-first use case; a UI is a separate project.
- **Changing the embedding default.** `chroma-default` (ONNX MiniLM) is the right zero-deps default. Better embeddings remain opt-in via `sentence-transformers` / `openai`.
- **Major schema migrations.** 0.4.5 already migrated the legacy `palaces/wings/rooms/drawers` hierarchy and the legacy Chroma collection names. The plan adds columns/JSON fields only.