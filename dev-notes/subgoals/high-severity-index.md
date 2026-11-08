# High-Severity Findings → Issue Index

Tracks all 50 high-severity findings from `dev-notes/teammate-analysis/INDEX.md`.
Each finding is mapped to a GitHub issue that covers it.

## Cluster Issues

| Issue | Title | Findings Covered |
|-------|-------|-----------------|
| #60 | high: Path traversal guards (H-07..H-09) | H-07, H-08, H-09 |
| #61 | high: Injection hardening (H-10..H-12) | H-10, H-11, H-12 |
| #62 | high: SSRF / DNS rebinding (H-13) | H-13 |
| #63 | high: CORS + TLS hardening (H-05, H-06) | H-05, H-06 |
| #64 | high: Daemon PID safety (H-27) | H-27 |
| #65 | high: Auth/RBAC + idempotency on mutations (H-01..H-04) | H-01, H-02, H-03, H-04 |
| #66 | high: XSS (H-18, H-19) | H-18, H-19 |
| #67 | high: Destructive ops + cross-store transactions (H-14..H-17) | H-14, H-15, H-16, H-17 |
| #68 | high: Dependency pinning + lockfile + scanning (H-20..H-22) | H-20, H-21, H-22 |
| #69 | high: Validation gaps (H-25, H-26) | H-25, H-26 |
| #70 | high: Resource exhaustion (H-23, H-24) | H-23, H-24 |

## Finding → Issue Mapping

| Finding | Domain | Title | Location | Issue |
|---------|--------|-------|----------|-------|
| H-01 | Auth | No RBAC on mutations | rest_server.py, mcp_server.py | #65 |
| H-02 | Auth | No idempotency keys on mutating endpoints | rest_server.py, mcp_server.py | #65 |
| H-03 | Auth | MCP server zero auth (cross-ref C-02) | mcp_server.py | #65 |
| H-04 | Auth | No session-based authZ | rest_server.py | #65 |
| H-05 | Auth | CORS allows every localhost port | rest_server.py:147 | #63 |
| H-06 | Auth | TLS opt-in only, plaintext default | rest_server.py:773-810 | #63 |
| H-07 | Path Traversal | backup export/import dest/src minimal guard | backup.py:41-73, 81-140 | #60 |
| H-08 | Path Traversal | obsidian resolve_vault_path no restriction | obsidian.py:17-25 | #60 |
| H-09 | Path Traversal | cmd_bookcase directory listing | main.py:783 | #60 |
| H-10 | Injection | hooks _sanitize_template_value no shell metachar stripping | hooks/engine.py:85-95 | #61 |
| H-11 | Injection | sqlite_vec_store WHERE f-string allowlist | sqlite_vec_store.py:228-247 | #61 |
| H-12 | Injection | graph_visualizer raw JSON script injection | graph_visualizer.py:28,477 | #66 |
| H-13 | SSRF | hooks webhook SSRF DNS-rebind bypassable | hooks/engine.py:543-641 | #62 |
| H-14 | Data Loss | backup import_json --replace destructive, no transaction | backup.py:81-140 | #67 |
| H-15 | Data Loss | prune --delete hard-delete no confirmation | vault.py:647-690, main.py:1291-1314 | #67 |
| H-16 | Data Loss | consolidation merges destructively no snapshot | vault.py | #67 |
| H-17 | Data Loss | No cross-store transactions (vector + meta) | vault.py:280+ | #67 |
| H-18 | XSS | Three.js from unpkg CDN without SRI | bookcase.html:34-40 | #66 |
| H-19 | XSS | graph_visualizer raw JSON payload | graph_visualizer.py:28,477 | #66 |
| H-20 | Dependencies | All deps loose-pinned, no lockfile | pyproject.toml:33-46 | #68 |
| H-21 | Dependencies | prometheus_client used but not declared | rest_server.py:10-12 | #68 |
| H-22 | Dependencies | No dependency vulnerability scanning in CI | .github/workflows/test.yml | #68 |
| H-23 | Resource | rate_limit dict grows unboundedly | rest_server.py:209-232 | #70 |
| H-24 | Resource | ThreadingHTTPServer thread-per-connection no limit | main.py:783 | #70 |
| H-25 | Validation | REST /extract backend not validated | rest_server.py:459 | #69 |
| H-26 | Validation | MCP tools access args directly → KeyError | mcp_server.py:634, 646, 660 | #69 |
| H-27 | Daemon | _start_daemon string manipulation, PID file risk | main.py:1180-1240 | #64 |

## Status
- **50 of 50 findings mapped to cluster issues #60-#70**
- **11 cluster issues created** (one per category)
- Each cluster issue lists all individual findings it covers with file:line references