# Dependencies Analyst Report — memorius

**Product:** memorius v0.9.3 — self-contained memory vault for AI agents (pure Python, PyPI).
**Repo:** `/home/dimona/Dream-Pixels-Forge/Dev/cli/memorius`
**Manifest:** `pyproject.toml` (setuptools). **No lockfile committed.** `MANIFEST.in` present.

---

## Scope & Entry Points

- Runtime deps (`pyproject.toml:33-46`): `pyyaml>=6.0.1`, `chromadb>=0.4.22`, `httpx>=0.25.0`, `fastapi>=0.104.1`, `uvicorn[standard]>=0.24.0`, `pydantic>=2.0.0`, `sse-starlette>=1.0.0`, `sentence-transformers>=2.6.0`, `openai>=1.10.0`, `sqlite-vec>=0.1.0`.
- Dev deps: `pytest>=7.0`, `pytest-asyncio>=0.21.0`.
- Console scripts: `memorius`, `memorius-hook`, `memorius-plugin-gen`, `memorius-normalize`.
- Package data: `memorius = ["data/*", "bookcase/*"]`, `include-package-data = true`.

---

## Findings (bullets tagged [observation|risk|gap])

### 1. Dependency graph
- [observation] `chromadb` — default vector store (PersistentClient, collections, embeddings). Heavy; pulls its own HTTP/server deps.
- [observation] `sqlite-vec` — optional vector backend alternative (`sqlite_vec_store.py`).
- [observation] `sentence-transformers` — ONNX embedding model (`all-MiniLM-L6-v2`, 384-dim) downloaded via `memorius/model_download.py` from S3; pulls large transitive surface (`torch`, `transformers`, tokenizers).
- [observation] `openai` — optional OpenAI embedding provider; permits custom base URLs.
- [observation] `fastapi` + `uvicorn[standard]` + `sse-starlette` — REST server (`rest_server.py`).
- [observation] `httpx` — web search provider (`web_search.py`).
- [observation] `pyyaml` — config loading (`config.py` uses `yaml.safe_load`).
- [observation] `pydantic` — FastAPI validation (transitive via fastapi).
- [gap] `prometheus_client` imported for `/metrics` (`rest_server.py:10-12`) but NOT declared in dependencies — runtime `ImportError` on fresh install.
- [gap] `ruff` used locally (`.ruff_cache`) but not a declared dev dependency.

### 2. Licenses
- [observation] memorius is MIT-licensed (`LICENSE`).
- [gap] No license inventory of dependencies; no NOTICE file; no attestation of dependency license compatibility (MIT project depending on Apache-2.0/BSD/etc. transitive deps).
- [gap] No SBOM or provenance/attestation for published package.

### 3. Vulnerabilities / supply chain
- [risk] Loose pins (`>=`, no upper bound) on all runtime deps — `pip install` can silently pull a vulnerable newer release.
- [risk] No lockfile committed → non-deterministic installs across environments/CI.
- [risk] `sentence-transformers` pulls a very large transitive surface (`torch`, `transformers`) — substantially expands supply-chain attack surface for an embedding feature.
- [risk] `chromadb` and `fastapi`/`uvicorn` have historical advisories (path traversal, unauth access, header smuggling, request size). Loose pins mean silent upgrades to vulnerable releases possible.
- [risk] `openai>=1.10.0` permits custom base URLs — a malicious/misconfigured `MEMORIUS_OPENAI_API_KEY`/base could exfiltrate embedding text externally.
- [gap] No dependency vulnerability scanning (`pip-audit`/`safety`/`bandit`) in `.github/workflows/` (`test.yml`, `release.yml`, `pages.yml` only).

### 4. Updates / versioning
- [observation] `requires-python >=3.11`. Tested on Python 3.11/3.12/3.13 (CI matrix).
- [gap] No automated dependency update process (no Dependabot/Renovate config found).
- [gap] No `pnpm-lock.yaml`/`poetry.lock`/`requirements.lock` — pure Python, no lockfile.

### 5. Bundling / tree-shaking
- [observation] Python — no bundler, no tree-shaking applicable. Wheels/sdits include `data/*` and `bookcase/*` package data.
- [observation] `MANIFEST.in` includes README/LICENSE/pyproject/manifest.yaml, hooks script, examples, tests; excludes `__pycache__`/`*.pyc`. Does NOT explicitly list `bookcase/*` (relies on `include-package-data`).
- [gap] `tests/` and `examples/` are included in the package (MANIFEST.in recursive-include) — increases install size with dev-only content.

### 6. Entry points
- [observation] Four console scripts declared in `pyproject.toml` `[project.scripts]`; all map to `memorius.*:main` functions.

### 7. Risks
- [risk] `chromadb` is a heavy default dependency; no lighter mandatory fallback.
- [risk] `sentence-transformers` model download (~80MB) on first use (`model_download.is_model_downloaded()`) — network-dependent first run.
- [risk] `openai` custom base URL + `httpx` web search — outbound data egress surface.
- [gap] `prometheus_client` undeclared breaks `/metrics` contract.

---

## Highlights (3-5 short)

1. Pure Python, 10 runtime deps (loose `>=` pins, no lockfile → non-deterministic installs).
2. `prometheus_client` used for `/metrics` but not declared — broken on fresh install.
3. `sentence-transformers` large transitive surface (`torch`/`transformers`) expands supply-chain risk.
4. No dependency vulnerability scanning in CI; no Dependabot/Renovate.
5. `tests/` and `examples/` shipped inside the package (MANIFEST.in) — bloats install size.

---

## Domain summary

memorius is a pure-Python package with 10 runtime dependencies, all loose-pinned (`>=`, no upper bound) and no lockfile committed — installs are non-deterministic and can silently pull vulnerable newer versions. Key supply-chain risks: `sentence-transformers` pulls a large `torch`/`transformers` transitive surface; `chromadb`/`fastapi`/`uvicorn` have historical advisories; `openai` permits custom base URLs (exfiltration surface). `prometheus_client` is imported for `/metrics` but undeclared, breaking that contract on fresh installs. No dependency vulnerability scanning (`pip-audit`/`safety`/`bandit`) runs in CI, and no Dependabot/Renovate config exists. `tests/` and `examples/` are bundled into the package via MANIFEST.in, bloating install size. Suggested canonical home: `dev-notes/teammate-analysis/dependencies.md` (this file).
