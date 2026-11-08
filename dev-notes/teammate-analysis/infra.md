# Infra Analyst Report — memorius

**Product:** memorius v0.9.3 — self-contained memory vault for AI agents, published on PyPI, installed via pip, runs locally (no cloud).
**Repo:** `/home/dimona/Dream-Pixels-Forge/Dev/cli/memorius`
**CI:** GitHub Actions (`.github/workflows/`). **Guidance:** `dev-notes/AUDIT.md`, `dev-notes/PROGRESS.md`, `dev-notes/GOAL-v0.8.6-release-and-docs.md`.

---

## Scope & Entry Points

- Build: `pyproject.toml` (setuptools backend), `MANIFEST.in`, entry-point scripts.
- Deploy: PyPI publish, pip install, local-only (~/.memorius), no Docker/K8s.
- CI/CD: `.github/workflows/test.yml` (PR/push), `release.yml` (PyPI publish).
- Environments: `MEMORIUS_STORAGE_PATH`, default `~/.memorius/data`, config `~/.memorius/config.yaml`.
- Secrets: `MEMORIUS_API_KEY`, TLS cert/key env vars; no hardcoded keys.
- Monitoring/logging: JSON formatter in `mcp_server.run` and `rest_server`; `doctor` health checks; `stats`/`status` commands.
- Observability: `/health`, `/stats`, `/status`, `/graph/stats`, `/metrics` (Prometheus, undeclared dep).
- Reliability: single-instance flock guard, `repair` for vector/meta drift, `backup`/export for DR.

---

## Findings (bullets tagged [observation|risk|gap])

### 1. Build
- [observation] `pyproject.toml`: setuptools build backend, `name="memorius"`, `version="0.9.3"`, `requires-python >=3.11`, loose version pins (`>=`, no upper bound), no lockfile committed. Optional `dev = [pytest, pytest-asyncio]`.
- [observation] Four console scripts: `memorius = "memorius.cli.main:main"`, `memorius-hook = "memorius.hooks.cli:main"`, `memorius-plugin-gen = "memorius.plugin_gen.cli:main"`, `memorius-normalize = "memorius.normalizers.cli:main"`.
- [observation] Package data: `[tool.setuptools.package-data] memorius = ["data/*", "bookcase/*"]`, `include-package-data = true`.
- [observation] `MANIFEST.in`: includes README/LICENSE/pyproject/manifest.yaml, `hooks/memorius-hook.sh`, recursive-include `examples/*.py` and `tests/*.py`; recursive-exclude `__pycache__` and `*.pyc`. Does NOT explicitly list `bookcase/*` — relies on `include-package-data` + package-data.
- [gap] No lockfile → non-deterministic installs; `pip install` can silently pull newer transitive versions.

### 2. Deploy
- [observation] Published on PyPI (`pypi.org/project/memorius`), installed via `pip install memorius`. `release.yml` workflow handles PyPI publish.
- [gap] No Dockerfile, no container image, no K8s manifests, no systemd unit. Deployment is "pip install + run locally" — single-user, single-machine assumption.
- [gap] No configuration management (Ansible/Terraform) for the `~/.memorius` data dir.

### 3. CI/CD
- [observation] `.github/workflows/test.yml`: runs on push to `main` + PRs + workflow_dispatch; matrix `python-version: ['3.11','3.12','3.13']`, `fail-fast: false`; installs `pip install -e ".[dev]"`; runs `pytest tests/test_core.py tests/test_features.py tests/test_polish_regressions.py` (unit) and `pytest tests/test_integration.py tests/test_single_instance.py tests/test_serve_single_instance.py` (integration).
- [gap] CI runs only 7 of ~50 test files (~14%). CRUD, search, graph, backup, doctor, cors, sqlite-vec, bookcase, TTL, hooks, CLI-json, regression tests are NOT executed by CI.
- [gap] No coverage thresholds, no `--cov`, no coverage dependency, no coverage report upload.
- [observation] `paths-ignore: ['docs/**', '**.md']` on push — doc-only changes skip CI (reasonable).
- [observation] `.ruff_cache` and `.pytest_cache` present — ruff and pytest used locally, but ruff not in CI workflow.

### 4. Environments
- [observation] No formal dev/staging/prod environment separation. Default config dir `~/.memorius`, config `~/.memorius/config.yaml`, storage `~/.memorius/data` (`config.py DEFAULT_CONFIG_YAML`).
- [observation] Env overrides via `config.py:_apply_env_overrides`: `MEMORIUS_STORAGE_PATH`, `MEMORIUS_HOST`, `MEMORIUS_PORT`, `MEMORIUS_PID_FILE`, `MEMORIUS_TLS_CERT`, `MEMORIUS_TLS_KEY`, `MEMORIUS_API_KEY`, `MEMORIUS_OPENAI_API_KEY`, `MEMORIUS_TAVILY_API_KEY`.
- [gap] No `.env.example`, no env-specific config files, no staging/prod config templates.

### 5. Secrets
- [observation] No hardcoded keys/tokens/credentials in source. `config.py` DEFAULT_CONFIG_YAML has only a commented-out `# api_key: ...` placeholder under `embeddings.openai`.
- [observation] Secrets via env vars: `MEMORIUS_API_KEY` (REST auth), `MEMORIUS_OPENAI_API_KEY`/`OPENAI_API_KEY` (OpenAI embeddings), `MEMORIUS_TAVILY_API_KEY`/`TAVILY_API_KEY` (Tavily web search).
- [gap] `config.py:_validate_secrets` only raises on weak/missing keys for `provider=='openai'` or `web_provider=='tavily'`; other providers accept weak/empty keys silently.
- [gap] No secret redaction in logs — JSON log formatters log request/response detail; `Authorization` headers or payload secrets could leak.

### 6. Monitoring/logging
- [observation] `mcp_server.run()` installs a JSON `logging.Formatter` on the `memorius` logger (timestamp/level/message/logger, exception info) to stdout; `rest_server.py:176-190` installs the same. CLI `logging.basicConfig(level=logging.WARNING)`; `--debug` raises to DEBUG.
- [observation] `doctor.run_checks(engine)` — 6 checks: config keys, storage dir writable, ONNX model present, `memory_meta` vs Chroma vector count (drift), collection name length ≤ 63, graph edges present when memories > 10. Best-effort: failures become `warn`/`fail`, never raise.
- [observation] `stats`/`status` CLI commands and MCP `memorius_stats`/`memorius_status` provide compact vault statistics.

### 7. Observability endpoints
- [observation] `GET /health`, `/health/live`, `/health/ready`; `GET /stats`; `GET /status`; `GET /graph/stats`; `GET /doctor`; `GET /metrics` (Prometheus, if `prometheus_client` installed).
- [gap] `/metrics` returns 503 on fresh installs because `prometheus_client` is not a declared dependency.
- [gap] No structured request tracing, no request IDs, no distributed tracing.

### 8. Reliability
- [observation] Single-instance guard for `memorius serve`: exclusive non-blocking `fcntl.flock` on `<storage>/serve.lock`, PID stamped; live holder → `ServeAlreadyRunningError`; `--reclaim` takes over orphaned instance (`single_instance.py:116-170`). Covered by `tests/test_single_instance.py` / `test_serve_single_instance.py`.
- [gap] `serve-rest --daemon` uses a separate, uncoordinated PID file mechanism (`Popen(start_new_session=True)`, `~/.memorius/serve.pid`); two guards, two PID files, no coordination.
- [observation] `VaultEngine.repair` reconciles vector/meta drift (orphaned vectors removed, missing vectors re-embedded with `reindex=True`); dry-run supported.
- [observation] `backup.py` export/import (JSON/Markdown) for disaster recovery; tested round-trip (`tests/test_feature_backup.py`).

---

## Highlights (3-5 short)

1. Pure-Python PyPI package, `pip install memorius`, local-only (~/.memorius), no Docker/K8s/container.
2. CI (`test.yml`) runs only 7 of ~50 test files and has no coverage thresholds.
3. Single-instance flock guard protects `memorius serve` only; `serve-rest --daemon` uses a separate uncoordinated PID file.
4. `/metrics` (Prometheus) is referenced but `prometheus_client` is not a declared dependency — broken on fresh install.
5. No secret redaction in logs; `prometheus_client` undeclared; loose dependency pins with no lockfile.

---

## Domain summary

memorius is a pure-Python PyPI package installed via pip, running locally under `~/.memorius` with no Docker/K8s/container story. Build uses setuptools with loose pins and no lockfile. CI (`test.yml`) runs only 7 of ~50 test files across Python 3.11/3.12/3.13 and has no coverage thresholds. Observability relies on JSON-formatted logs (mcp_server/rest_server), doctor health checks, stats/status commands, and `/health`/`/stats`/`/doctor` REST endpoints — but `/metrics` (Prometheus) is broken on fresh installs because `prometheus_client` is undeclared. Reliability rests on a single-instance flock guard for `memorius serve` (not `serve-rest --daemon`, which uses a separate uncoordinated PID file), plus manual `repair` for vector/meta drift and `backup`/export for DR. Secrets come from env vars with no redaction in logs. Suggested canonical home: `dev-notes/teammate-analysis/infra.md` (this file).
