# Security Analyst Report — memorius

**Version:** memorius v0.9.3 (`pyproject.toml:15`)
**Scope:** `Dev/cli/memorius` — Python memory vault, local-first / loopback-only ("No cloud, no API keys, no lock-in").
**Entry points:** `memorius.cli.main:main` (CLI), `memorius.mcp_server.McpServer` (MCP over stdio), `memorius.rest_server.MemoriusAPI` / `run_rest_server` (REST over HTTP), `memorius.bookcase` (loopback static + 3D UI), `memorius.cli.obsidian` (Obsidian import/export).
**Existing guidance:** `dev-notes/SECURITY.md` (requirements doc) and `dev-notes/teammate-analysis/security.md` (prior full audit).

---

## Scope & Entry Points

| Entry point | Transport | Network surface | Auth |
|---|---|---|---|
| `memorius serve` (MCP) | stdio JSON-RPC | none (loopback process) | none |
| `memorius serve-rest` | HTTP via uvicorn | `127.0.0.1:8912` default | `MEMORIUS_API_KEY` bearer (optional) |
| `memorius bookcase` | HTTP static + REST | `127.0.0.1:8400` static, `127.0.0.1:8912` REST | none (loopback only) |
| `memorius` CLI | stdio/args | none | none |
| Web fallback (`--web` / `web_fallback`) | outbound HTTPS to DuckDuckGo/Tavily | outbound only | none (DuckDuckGo keyless; Tavily keyed) |

Default bind address is `127.0.0.1` (`config.py` DEFAULT_CONFIG_YAML `server.host`, `rest_server.py` `run_rest_server` default `host="127.0.0.1"`). There is no cloud component and no default API key.

---

## Findings (bullets tagged [observation|risk|gap])

### 1. AuthN/AuthZ

- [observation] REST server authenticates only when `MEMORIUS_API_KEY` is set, using `hmac.compare_digest` on a Bearer token (`rest_server.py:162-176`). When the env var is unset, all write/delete endpoints (`/store`, `/delete`, `/prune`, `/consolidate`, `/obsidian/import`, `/obsidian/export`) are open to any client that can reach the bind address. `rest_server.py:794-800` logs a warning when bound to a non-loopback host without a key but still starts.
- [risk] MCP server (stdio) has zero authentication and no authorization (`mcp_server.py`, entire file). Any writer to stdin can invoke destructive tools (`memorius_delete`, `memorius_prune`, `memorius_consolidate`, `memorius_graph_export` with a `dest` path). MCP stdio inherits the caller's OS security context, so local compromise = full vault compromise.
- [gap] No RBAC, no session cookies, no JWTs, no idempotency keys on mutating endpoints (`/store`, `/update`, `/delete`, `/prune`, `/consolidate`). MCP `tool_memorius_consolidate` defaults `dry_run=False` (`mcp_server.py` handler) — destructive by default.
- [observation] Loopback-only default binding (`127.0.0.1`) is sufficient only for single-user local use. It is not a substitute for auth: any local process or user can reach the REST port, and `rest_server.py:794-800` explicitly warns when binding to non-localhost without `MEMORIUS_API_KEY`.
- [gap] CORS is permissive: `allow_origin_regex` matches any `127.0.0.1`/`localhost` port, `allow_methods=["*"]`, `allow_headers=["*"]` (`rest_server.py:141-149`). Narrowing to the bookcase static port would reduce cross-port exposure.

### 2. Injection

- [observation] CLI uses `argparse` with typed arguments (`type=int`, `type=float`, `choices=[...]` for extract backend) — no shell interpolation of CLI args (`cli/main.py`). Argument values are passed directly to Python functions.
- [observation] All name/path inputs (`vault`, `shelf`, `folder`, `note`) are validated by `validate_name` (`validation.py:9-28`, regex `^[a-zA-Z0-9_\-]+$`, max 128 chars) before reaching the store in MCP (`mcp_server.py`), REST (`rest_server.py`), and CLI paths. Memory IDs are UUID-validated by `validate_memory_id` (`validation.py:36-59`).
- [observation] `single_instance.py` uses `fcntl.flock` on `<storage>/serve.lock` and `os.kill(pid, SIGTERM/SIGKILL)` for reclaim — no shell, no command-string construction (`single_instance.py:99-192`).
- [observation] `_start_daemon` in `cli/main.py:875-931` launches `subprocess.Popen([sys.executable, "-c", daemon_script], ...)` as a list with `shell=False` (default) on Unix (`start_new_session=True`) and `CREATE_NO_WINDOW | DETACHED_PROCESS` on Windows. Configuration is passed via environment variables (`MEMORIUS_HOST`, `MEMORIUS_PORT`, `MEMORIUS_PID_FILE`, `MEMORIUS_TLS_CERT`, `MEMORIUS_TLS_KEY`, `cli/main.py:906-907, 913-914`), not shell interpolation — so env-var injection into a shell is not possible.
- [risk] `_stop_daemon` on Windows calls `subprocess.run(["taskkill", "/F", "/PID", str(pid)], ...)` as a list (`cli/main.py:852`) — safe, no `shell=True`.
- [gap] `hooks/engine.py:_action_command` uses `shlex.split` + `shell=False` (mitigated) but `_sanitize_template_value` strips null/control chars, not shell metacharacters (`;`, `|`, `&`, backticks, `$()`). Command hooks are opt-in via `allow_command_hooks` (default False).
- [gap] `sqlite_vec_store.py:237-247` builds a SQL `WHERE` clause from an f-string (`f"{k} = ?"`) with keys allowlisted to `{"folder", "note"}`. Parameterized values are used, but the column allowlist is the only injection guard for the SQL skeleton.
- [observation] No `eval`/`exec`/`pickle` found in the codebase. `config.py` uses `yaml.safe_load`. `llm_extract.py` includes an anti-prompt-injection system prompt.

### 3. Secrets

- [observation] No hardcoded keys, tokens, or credentials found in source. `config.py` DEFAULT_CONFIG_YAML contains only a commented-out `# api_key: ...` placeholder under `embeddings.openai`.
- [observation] Secrets are expected via environment variables: `MEMORIUS_API_KEY` (REST auth), `MEMORIUS_OPENAI_API_KEY` / `OPENAI_API_KEY` (OpenAI embeddings), `MEMORIUS_TAVILY_API_KEY` / `TAVILY_API_KEY` (Tavily web search), plus `MEMORIUS_STORAGE_PATH`, `MEMORIUS_HOST`, `MEMORIUS_PORT`, `MEMORIUS_PID_FILE`, `MEMORIUS_TLS_CERT`, `MEMORIUS_TLS_KEY` (`config.py:_apply_env_overrides`, `cli/main.py`).
- [gap] `config.py:_validate_secrets` (`config.py:180-218`) only raises on weak/missing keys when `provider == 'openai'` or `web_provider == 'tavily'`. Other providers accept weak/empty keys silently.
- [gap] No secret redaction in logs. `rest_server.py` and `mcp_server.py` configure JSON log formatters that log request/response detail; `Authorization` headers or payload secrets could leak into logs/error messages.
- [gap] TLS private key files accepted via `--tls-key`/`MEMORIUS_TLS_KEY` with no file-permission validation (`rest_server.py:806-810`, `cli/main.py:906-907`). A world-readable key file would not be refused.

### 4. Crypto

- [gap] No encryption at rest. ChromaDB (`chromadb`) and SQLite (`sqlite-vec` / `SQLiteStore`) store vectors, metadata, and content in plaintext under `~/.memorius/data` (`vault.py` `__init__`, `config.py` storage path).
- [observation] TLS for the REST daemon is opt-in: `--tls-cert`/`--tls-key` CLI args (`cli/main.py:691-699`), passed to the daemon via `MEMORIUS_TLS_CERT`/`MEMORIUS_TLS_KEY` env vars (`cli/main.py:906-907, 913-914`), consumed by uvicorn as `ssl_certfile`/`ssl_keyfile` (`rest_server.py:806-816`). Defaults to plaintext HTTP; `rest_server.py:808-810` warns if only one of cert/key is given.
- [observation] bookcase serves static assets via `http.server.SimpleHTTPRequestHandler` on `127.0.0.1:8400` with no HTTPS (`cli/main.py:783`, loopback-only by design). REST for bookcase also defaults to `127.0.0.1`.

### 5. Dependencies

- [observation] Declared runtime dependencies, all loose-pinned (`>=`, no upper bound), no lockfile committed (`pyproject.toml:33-46`):
  - `pyyaml>=6.0.1`, `chromadb>=0.4.22`, `httpx>=0.25.0`, `fastapi>=0.104.1`, `uvicorn[standard]>=0.24.0`, `pydantic>=2.0.0`, `sse-starlette>=1.0.0`, `sentence-transformers>=2.6.0`, `openai>=1.10.0`, `sqlite-vec>=0.1.0`.
- [risk] `sentence-transformers` pulls a very large transitive surface (`torch`, `transformers`, tokenizers) — expands the supply-chain attack surface substantially for an embedding feature.
- [risk] `openai>=1.10.0` permits custom base URLs; a malicious or misconfigured `MEMORIUS_OPENAI_API_KEY`/base could exfiltrate embedding text to an external endpoint.
- [risk] `chromadb` and `fastapi`/`uvicorn` have historical advisories (path traversal / unauth access / header smuggling / request size). Loose pins mean `pip install` can silently upgrade to a vulnerable release.
- [gap] `prometheus_client` is imported conditionally in `rest_server.py:10-12` and used for `/metrics`, but is **not** declared in `pyproject.toml` dependencies — runtime `ImportError`; `/metrics` returns 503.
- [gap] No dependency vulnerability scanning (`pip-audit`/`safety`/`bandit`) in `.github/workflows/` (`test.yml`, `release.yml`, `pages.yml` only). Cross-reference with the dependencies analyst for CVE detail.

### 6. Headers / CSP

- [gap] REST server sets **no** security headers: no `Content-Security-Policy`, no `X-Frame-Options`, no `X-Content-Type-Options: nosniff`, no `Strict-Transport-Security`. Grep across `memorius/rest_server.py` found no `add_header`/`headers[` security-header writes; only CORS middleware (`rest_server.py:141-149`) and a sanitizing 500 exception handler.
- [gap] `bookcase.html` has no CSP `<meta>` tag and no `X-Frame-Options`. It loads Three.js from an unpkg CDN via importmap with no `integrity` hash (`bookcase.html:34-40`) — CDN compromise equals XSS in the bookcase origin, which can call the local REST API (`http://127.0.0.1:8912`).
- [risk] `graph_visualizer.py` embeds graph data as an inline JS literal: `json_payload = json.dumps(graph_data, ensure_ascii=False)` then `const rawData = {json_payload};` (`graph_visualizer.py:28, 475-478`). `json.dumps` does not escape `</script>`, so user-controlled memory content in graph nodes can break out of the script block → XSS. The graph view is served as `HTMLResponse` from REST (`rest_server.py` `/graph/view`) and exported to HTML (`vault.py:export_graph_html`).
- [observation] `bookcase.js` renders memory content with `escapeHtml()`/`textContent`, no `innerHTML` on user content (mitigated, `SEC-26` in prior audit).

### 7. Path traversal

- [observation] `validate_name` (`validation.py:9-28`) restricts vault/shelf/folder/note to `^[a-zA-Z0-9_\-]+$` (max 128 chars), blocking `..`, `/`, and shell metacharacters before any filesystem use. `validate_memory_id` requires a valid UUID (`validation.py:36-59`), blocking traversal via delete/get/update paths.
- [gap] `resolve_vault_path` in `obsidian.py:17-25` resolves the Obsidian vault path from arg/env/default with **no** path restriction (docstring explicitly: "does NOT restrict it. Callers should add their own path validation"). The REST API adds a home-directory confinement check (`rest_server.py:505-547`), but the CLI `obsidian list/import/export` dispatch calls `_resolve_vault_path` with no home-dir restriction (`cli/obsidian.py:276`).
- [observation] `cli/obsidian.py:export_memories` guards the per-note output path with a `startswith(export_dir.resolve())` traversal check (`cli/obsidian.py` export loop).
- [observation] `export_graph_html` validates `dest` is under the storage directory (`vault.py:629-631`).
- [gap] Backup export/import (`backup.py`) accept `dest`/`src` from CLI args with no traversal check (`cmd_export`/`cmd_import`, `cli/main.py`). `obsidian.py:parse_frontmatter` does manual line-splitting YAML instead of `yaml.safe_load` — low risk, but inconsistent with `config.py`.

### 8. Data exposure

- [observation] MCP search explicitly excludes the vector from results: `{k: v for k, v in m.to_dict().items() if k != "vector"}` (`mcp_server.py: tool_memorius_search`). MCP `get`/`update`/`apply_learning`/`contradictions` also pop `vector` before returning.
- [observation] CLI `cmd_get` and `cmd_update` pop `vector` before printing (`cli/main.py`), but verbose/JSON output still exposes full `content` and `metadata` to the caller.
- [risk] Memory `content` and `metadata` are returned verbatim to MCP/REST/CLI callers (`mcp_server.py: tool_memorius_get`, `tool_memorius_search`, `tool_memorius_list`; `rest_server.py: /get`, `/search`, `/list`, `/memory/{id}`). There is no field-level redaction or caller-based scoping beyond vault/shelf/note filters.
- [risk] `memorius_factcheck` and the CLI `--web` flag send statements/queries to external web providers (DuckDuckGo lite, or Tavily with API key) (`web_search.py: DuckDuckGoProvider._ENDPOINT`, `TavilyProvider._ENDPOINT`; `cli/main.py: cmd_factcheck`, `cmd_context`, `cmd_search` web fallback). Web fallback is opt-in (`retrieval.web_fallback` default `false`, `--web` flag, `web_search.py:web_fallback_enabled`/`should_fallback`) — statements leave the loopbox only when explicitly requested.
- [observation] No vector exposure in MCP/REST/CLI responses by design, but the vector store itself is readable by any local process with access to `~/.memorius/data` (no encryption at rest, see domain 4).

---

## Highlights

- **Auth is opt-in and absent for MCP.** REST is unauthenticated unless `MEMORIUS_API_KEY` is set; MCP over stdio has zero authentication and no authorization. Loopback-only binding (`127.0.0.1`) limits but does not eliminate local exposure.
- **No encryption at rest, TLS opt-only.** Vectors, metadata, and content sit in plaintext under `~/.memorius/data`; HTTPS for the REST daemon requires explicit `--tls-cert`/`--tls-key` and defaults to plaintext HTTP.
- **Injection surface is small but real.** CLI args and names are validated; subprocess uses list-form `Popen`/`shell=False`; the residual risks are the SQLite WHERE allowlist (`sqlite_vec_store.py`), hook command templating (`hooks/engine.py`), and unverified env-derived daemon config.
- **No security headers / CSP.** REST emits no CSP, `X-Frame-Options`, or `X-Content-Type-Options`; `bookcase.html` loads Three.js from a CDN without SRI; `graph_visualizer.py` injects unescaped JSON into `<script>` (XSS via `</script>` breakout).
- **Web data egress is opt-in.** Factcheck/web cross-check sends statements to DuckDuckGo/Tavily; only triggered by `--web` or `web_fallback: true` (default off).

---

## Domain summary

Memorius defends its trust boundary reasonably well for a single-user, loopback-only local vault: input validation is centralized in `memorius/validation.py` (`validate_name`/`validate_memory_id`/`validate_session_id`/`validate_content`), subprocess calls avoid `shell=True`, and vectors are stripped from MCP/REST/CLI responses. The material security gaps are operational rather than architectural: authentication is optional (REST) or absent (MCP), there is no encryption at rest and TLS is opt-in, no security headers/CSP are emitted, dependencies are loose-pinned with no lockfile or vulnerability scanning, and several file/URL sinks (Obsidian paths, backup dest/src, graph HTML export) rely on caller-side checks that are inconsistently applied. The single most important file to harden first is `memorius/rest_server.py`, since it is the only network-facing entry point and currently lacks auth-by-default, security headers, and secret redaction; `memorius/mcp_server.py` is the second priority for adding stdio-side authorization.