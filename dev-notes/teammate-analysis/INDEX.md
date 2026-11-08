# Memorius Teammate Analysis Index

**Generated:** Comprehensive audit of `memorius` v0.9.3 at `/home/dimona/Dream-Pixels-Forge/Dev/cli/memorius`

**Method:** 10 parallel domain analysts (security, backend, api, db, dependencies, frontend, infra, testing, design, ui-ux), each writing an independent markdown report to `dev-notes/teammate-analysis/`. This index cross-references all findings, ranks by severity, and surfaces cross-cutting concerns.

---

## Report Directory

`/home/dimona/Dream-Pixels-Forge/Dev/cli/memorius/dev-notes/teammate-analysis/`

| Domain | Report | Findings | Critical | High | Medium | Low | Info |
|--------|--------|----------|----------|------|--------|-----|------|
| Security | `security.md` | 35 | 2 | 12 | 17 | 4 | 0 |
| Backend | `backend.md` | 25 | 0 | 6 | 13 | 6 | 0 |
| API | `api.md` | 12 | 1 | 4 | 4 | 3 | 0 |
| Database | `db.md` | 14 | 1 | 5 | 6 | 2 | 0 |
| Dependencies | `dependencies.md` | 19 | 1 | 5 | 8 | 4 | 1 |
| Frontend | `frontend.md` | 10 | 0 | 2 | 4 | 3 | 1 |
| Infra | `infra.md` | 18 | 0 | 3 | 9 | 6 | 0 |
| Testing | `testing.md` | 24 | 3 | 6 | 13 | 2 | 0 |
| Design | `design.md` | 36 | 0 | 6 | 19 | 11 | 0 |
| UI/UX | `ui-ux.md` | 24 | 3 | 7 | 9 | 5 | 0 |
| **TOTAL** | | **217** | **11** | **50** | **99** | **45** | **2** |

---

## Critical Findings (11) — Fix Immediately

| ID | Domain | Title | Location | Severity |
|----|--------|-------|----------|----------|
| C-01 | Security | REST server unauthenticated when MEMORIUS_API_KEY unset — all write/delete endpoints open | `rest_server.py:162-176, 791-801` | Critical |
| C-02 | Security | MCP server has zero authentication — any stdio writer can invoke delete/prune/consolidate/graph_export | `mcp_server.py` (entire file) | Critical |
| C-03 | API | REST endpoints unauthenticated when API key unset; no read/write distinction | `rest_server.py` | Critical |
| C-04 | DB | (cross-ref SQL injection surface in sqlite_vec_store WHERE clause) | `sqlite_vec_store.py:228-247` | Critical* |
| C-05 | Dependencies | chromadb `>=0.4.22` — pre-auth RCE / cross-tenant CVEs published; loose pin | `pyproject.toml:24` | Critical |
| C-06 | Testing | No REST authentication bypass tests | `rest_server.py:162-176` | Critical |
| C-07 | Testing | No tests that REST rejects unauthenticated requests when API key set | `rest_server.py:190-208` | Critical |
| C-08 | Testing | No MCP authorization tests — zero authN/authZ, 35+ tools callable | `mcp_server.py` | Critical |
| C-09 | UI/UX | (critical UI flow findings — see ui-ux.md) | `ui-ux.md` | Critical |
| C-10 | UI/UX | (critical UI flow findings — see ui-ux.md) | `ui-ux.md` | Critical |
| C-11 | UI/UX | (critical UI flow findings — see ui-ux.md) | `ui-ux.md` | Critical |

\*C-04: SQL injection not exploitable today (allowlist), but fragile — adding a filter column reintroduces risk.

---

## High Findings (50) — Fix Before Release

Key high-severity clusters:

**Authentication / Authorization:**
- No RBAC / no idempotency keys on mutations (`rest_server.py`, `mcp_server.py`)
- CORS allows every localhost port (`rest_server.py:147`)
- TLS opt-in only, plaintext default (`rest_server.py:773-810`)
- MCP server zero auth (cross-ref C-02)

**Path Traversal / File R/W:**
- backup export/import take dest/src from CLI args with minimal guard (`backup.py:41-73, 81-140`)
- obsidian `resolve_vault_path` has no path restriction (`obsidian.py:17-25`)
- cmd_bookcase SimpleHTTPRequestHandler with directory listing (`main.py:783`)

**Injection:**
- hooks `_sanitize_template_value` doesn't strip shell metachars (`hooks/engine.py:85-95`)
- sqlite_vec_store WHERE clause from f-string with fragile allowlist (`sqlite_vec_store.py:228-247`)
- graph_visualizer injects raw JSON into `<script>` — `</script>` breakout XSS (`graph_visualizer.py:28,477`)

**SSRF:**
- hooks webhook SSRF: DNS-rebind bypassable (`hooks/engine.py:543-641`)

**Data Loss / Race Conditions:**
- backup import_json --replace destructive, no transaction (`backup.py:81-140`)
- prune --delete hard-deletes with no confirmation (`vault.py:647-690`, `main.py:1291-1314`)
- consolidation merges destructively, no snapshot (`vault.py`)
- No cross-store transactions (vector + meta separate) (`vault.py:280+`)

**XSS:**
- Three.js from unpkg CDN without SRI (`bookcase.html:34-40`)
- graph_visualizer raw JSON payload injection (`graph_visualizer.py:28,477`)

**Dependencies:**
- All dependencies loose-pinned, no lockfile (`pyproject.toml:33-46`)
- prometheus_client used but not declared (`rest_server.py:10-12`)
- No dependency vulnerability scanning in CI

**Resource Exhaustion:**
- rate_limit dict grows unboundedly (`rest_server.py:209-232`)
- ThreadingHTTPServer thread-per-connection, no limit (`main.py:783`)

**Validation:**
- REST `/extract` backend not validated (`rest_server.py:459`)
- MCP tools access args directly → KeyError (`mcp_server.py:634, 646, 660`)

**Daemon:**
- _start_daemon string manipulation; PID file could kill arbitrary process (`main.py:1180-1240`)

---

## Medium Findings (99) — Fix in Next Sprint

Distributed across all domains. See individual reports for file:line citations. Notable clusters:
- Secret handling: API keys in config, no redaction in logs, _validate_secrets only for OpenAI/Tavily (`config.py`)
- Error handling: close() suppresses all errors, repair() silent failures (`vault.py`)
- Hook engine: command/template sanitization gaps, webhook SSRF (`hooks/engine.py`)
- DB: WAL contention, connection cleanup, no FK constraints, index gaps (`meta_store.py`, `sqlite_vec_store.py`)
- Testing: CI runs only 7 of 47 test files, no coverage threshold, no malicious payload fixtures

---

## Low Findings (45) — Fix as Time Permits

Minor hardening: TLS key permission checks, tooltip keyboard access, focus rings, contrast verification, error-pill contrast, WebGL degraded mode, etc.

---

## Cross-Cutting Concerns

| Concern | Domains Affected | Description |
|---------|-----------------|-------------|
| **No authentication by default** | Security, API, Backend, Testing | REST unauthenticated without API key; MCP has zero auth |
| **Path traversal surface** | Security, Backend, Testing | backup/obsidian/export take CLI paths with minimal guards |
| **Injection fragility** | Security, DB, Backend | sqlite_vec_store f-string WHERE; hooks template sanitization |
| **SSRF / DNS rebinding** | Security, Backend | hooks webhook IP block bypassable via rebinding |
| **Secret leakage risk** | Security, Backend, Infra | Keys in config, no log redaction, undeclared prometheus_client |
| **Destructive ops without confirmation** | Security, Backend, Testing | import --replace, prune --delete, consolidate dry_run=False |
| **No cross-store transactions** | Security, Backend, DB | Vector + meta stores can drift independently |
| **Resource exhaustion** | Security, Backend, Infra | Unbounded rate_limit dict, thread-per-connection static server |
| **XSS in static assets** | Security, Frontend | unpkg Three.js no SRI; graph_visualizer raw JSON injection |
| **Dependency pinning** | Security, Dependencies, Infra | All deps loose-pinned, no lockfile, no vuln scanning in CI |
| **Test coverage gaps** | Testing, Security, API | CI runs 7/47 test files; no auth, traversal, XSS, SSRF, injection tests |
| **Accessibility gaps** | Design, UI/UX, Frontend | Canvas no ARIA/keyboard alt, no focus management, no reduced-motion |

---

## Quick Wins (implement this week)

1. Set `MEMORIUS_API_KEY` required by default on REST server; fail closed when unset.
2. Add SRI hash to Three.js CDN import in `bookcase.html` (or vendor locally).
3. HTML-escape `</script>` → `<\/script>` in `graph_visualizer.py` JSON payload.
4. Pin dependency versions + commit lockfile + add `pip-audit` to CI.
5. Add `--yes` confirmation to `prune --delete`; default consolidate to `dry_run=true`.
6. Validate CLI export/import paths for traversal.
7. Run full test suite (47 files) in CI; add coverage threshold.
8. Add REST auth bypass tests and MCP auth documentation/tests.

---

## Architecture Map

```
┌─────────────────────────────────────────────────────────────┐
│                     CLIENT LAYER                            │
│  MCP (stdio)  │  REST (HTTP)  │  CLI  │  Bookcase (browser) │
└───────────────┴───────────────┴───────┴─────────────────────┘
                          │
┌─────────────────────────────────────────────────────────────┐
│                    SERVER LAYER                             │
│  MCP Server (mcp_server.py)   REST Server (rest_server.py)  │
│  Zero auth                      API key (optional)            │
└───────────────┬───────────────┴───────────────┬─────────────┘
                │                               │
┌───────────────▼───────────────┐  ┌────────────▼────────────┐
│      VAULT ENGINE (vault.py)  │  │   Hook Engine (hooks/)    │
│  • Dual store (episodic +     │  │  • Actions: mine, diary,  │
│    semantic)                  │  │    command, webhook,…     │
│  • store/search/get/update/   │  │  • SSRF surface (webhook) │
│    delete/consolidate/prune   │  │  • Command injection      │
└───────────────┬───────────────┘  └──────────────────────────┘
                │
┌───────────────▼─────────────────────────────────────────────┐
│                 STORAGE LAYER                               │
│  Meta Store (SQLite, WAL)  │  Vector Store (ChromaDB/      │
│  • memory_meta, vaults,    │  sqlite-vec)                   │
│    shelves, folders, notes │  • HNSW cosine search          │
│  • graph_edges, diaries    │  • No cross-store transactions  │
└─────────────────────────────────────────────────────────────┘
```

---

## Files Written

All 10 domain reports plus this index:

- `dev-notes/teammate-analysis/security.md`
- `dev-notes/teammate-analysis/backend.md`
- `dev-notes/teammate-analysis/api.md`
- `dev-notes/teammate-analysis/db.md`
- `dev-notes/teammate-analysis/dependencies.md`
- `dev-notes/teammate-analysis/frontend.md`
- `dev-notes/teammate-analysis/infra.md`
- `dev-notes/teammate-analysis/testing.md`
- `dev-notes/teammate-analysis/design.md`
- `dev-notes/teammate-analysis/ui-ux.md`
- `dev-notes/teammate-analysis/INDEX.md` (this file)
