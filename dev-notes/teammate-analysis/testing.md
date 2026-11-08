# Testing Analyst Report — memorius

**Product:** memorius — self-contained memory vault for AI agents (vector search, session diaries, agent-agnostic hooks)
**Version:** 0.9.3 (`pyproject.toml`)
**Scope:** `tests/` (~50 test files), CI `.github/workflows/test.yml`, `pyproject.toml` dev deps, `memorius/` package
**Report location:** `dev-notes/teammate-analysis/testing.md`

---

## Scope & Entry Points

| Entry point | Path | Purpose |
|---|---|---|
| Test suite root | `tests/` | ~47–50 test files, one `engine` fixture per file |
| Dev dependencies | `pyproject.toml:37-38` | `pytest>=7.0`, `pytest-asyncio>=0.21.0` |
| CI workflow | `.github/workflows/test.yml` | Runs pytest on push to `main` + PRs |
| CLI entry | `memorius.cli.main:main` | `memorius` console script |
| Vault engine | `memorius.vault:VaultEngine` | Core store/search/mine/diary surface |
| Embeddings | `memorius.embeddings` | `ChromaDefaultProvider` (ONNX all-MiniLM-L6-v2, 384-dim) |
| Model download | `memorius.model_download` | `is_model_downloaded()`, `setup_model()`, S3 URL |
| Web search | `memorius.web_search` | DuckDuckGo / Tavily / MockProvider |
| Doctor | `memorius.doctor:run_checks` | Health checks (config, storage, onnx_model, drift, graph) |
| Single-instance guard | `memorius.single_instance` | `flock` on `<storage>/serve.lock` |

There is **no `conftest.py`** anywhere in the repo (confirmed by `find`). Every test file re-declares its own `engine` fixture.

---

## Findings (bullets tagged [observation|risk|gap])

### 1. Coverage — which features have tests, and gaps

**Covered (dedicated test files exist):**
- CRUD — `tests/test_core.py`, `tests/test_feature_crud.py`, `tests/test_delete.py`, `tests/test_domain_modules.py` (StoreModule/SearchModule get/update/delete/list/pagination)
- Search — `tests/test_feature_search_filtering.py` (folder/note/tags), `tests/test_bm25.py`, `tests/test_feature_rerank.py`, `tests/test_feature_sqlite_vec.py`, `tests/test_hybrid_retrieval.py`, `tests/test_token_efficient_index.py`, `tests/test_feature_graph_retrieval.py`, `tests/test_web_search.py`
- Graph — `tests/test_graph.py`, `tests/test_graph_temporal.py`, `tests/test_graph_visualizer.py`, `tests/test_feature_contradiction_edges.py`, `tests/test_mcp_stats_graph_keys.py`, `tests/test_knowledge_graph_typing.py`
- Consolidation — `tests/test_feature_consolidation_scaling.py`, `tests/test_neuroscience_consolidation.py`, `tests/test_consolidation_daemon.py`
- Backup — `tests/test_feature_backup.py` (JSON round-trip, markdown export, schema-version rejection, graph edges round-trip)
- Doctor — `tests/test_feature_doctor.py` (healthy/drift/graph/partial checks)
- CORS — `tests/test_feature_cors.py`
- sqlite-vec — `tests/test_feature_sqlite_vec.py`
- Bookcase — `tests/test_bookcase.py` (asset well-formedness, REST contract, serve E2E over loopback, walkable-library asset contract)
- Single-instance — `tests/test_single_instance.py` (flock unit), `tests/test_serve_single_instance.py` (real subprocess E2E)
- Hooks — `tests/test_hooks_engine_mine_dir.py` (stub vault engine, no real storage), `tests/test_integration.py` (HookEngine E2E)
- CLI json flag — `tests/test_cli_json_flag.py` (deterministic sorted JSON, doctor warnings are data, README cross-check)
- TTL — `tests/test_feature_ttl.py` (expires_at, find_stale_memories, prune archive/dry-run)
- Regression guards — `tests/test_regression_bugs.py` (Bugs 1,3,4,5), `tests/test_polish_regressions.py` (version drift, pi_adapter, save_interval, checkpoint exchange_count, WhatsApp regex, LICENSE/package data, plugin_gen version)

**Gaps / thin coverage:**
- No `conftest.py`, so the `engine` fixture (~15 lines each: `tempfile.mkdtemp`, `MEMORIUS_STORAGE_PATH`, `VaultEngine`, teardown with `eng._vector._client = None`) is copy-pasted into nearly every file ([gap], maintenance risk if the engine teardown contract changes).
- **No async tests at all** despite `pytest-asyncio>=0.21.0` being a declared dev dependency — `grep` found zero `async def test` and zero `@pytest.mark.asyncio` in `tests/` ([observation], the dependency is effectively unused).
- **No coverage thresholds configured** — `pyproject.toml` has no `[tool.pytest.ini_options]`/`addopts`/`--cov`, and `test.yml` runs plain `python -m pytest ... -q --tb=short` with no coverage flag ([risk], CI cannot enforce a coverage floor).
- **CI runs only 7 of ~50 test files**: unit = `test_core.py`, `test_features.py`, `test_polish_regressions.py`; integration = `test_integration.py`, `test_single_instance.py`, `tests/test_serve_single_instance.py`. The other ~44 files (CRUD, search, graph, backup, doctor, cors, bookcase, TTL, hooks, CLI json, regressions) are **not executed by CI** ([risk], regressions in those areas ship unnoticed).
- No dedicated tests for REST auth bypass when `MEMORIUS_API_KEY` is set beyond `test_regression_bugs.py`'s 401/429 checks; no path-traversal, XSS, SQL-injection, SSRF, or command-injection tests (these are noted in the prior QA audit at `dev-notes/teammate-analysis/testing.md` findings T-01…T-09).
- LLM extraction mocking: not clearly present — `memorius.llm_extract` exists but no test file mocks an LLM provider ([gap]).

### 2. Strategies — unit vs integration vs e2e; pytest-asyncio; tmp_path; monkeypatching

- **Unit (majority):** in-process `VaultEngine` against `tempfile.mkdtemp()` storage with `MEMORIUS_STORAGE_PATH` env var. Examples: `tests/test_core.py`, `tests/test_feature_crud.py`, `tests/test_feature_search_filtering.py`, `tests/test_feature_doctor.py`, `tests/test_feature_ttl.py`, `tests/test_domain_modules.py`. Each is self-contained, no network, no subprocess.
- **Integration:** `tests/test_integration.py` runs the real `memorius` CLI subprocess against a fully sandboxed HOME/storage (`isolated_env` fixture) covering init → store → search → diary → status → ls, plus MCP stdio protocol (initialize + tools/list + tools/call) and HookEngine E2E ([observation], this is the heaviest test file).
- **E2E-ish over loopback:** `tests/test_bookcase.py::TestBookcaseServe` spawns `memorius bookcase` subprocess, polls `http://127.0.0.1:<port>/bookcase.html` and `/health`, asserts port release after terminate. `tests/test_serve_single_instance.py` spawns real `python -m memorius.cli.main serve` subprocesses and asserts the second refuses while the first runs (`rc == 1`, `<5s`, stderr names incumbent PID).
- **pytest-asyncio:** declared in dev deps but **unused** — zero async tests ([risk], dead dependency; or async code paths are untested).
- **`tmp_path` vs `tempfile`:** mixed — `test_cli_json_flag.py`, `test_single_instance.py`, `test_serve_single_instance.py`, `test_feature_ttl.py` use pytest's `tmp_path`/`TemporaryDirectory`; older files (`test_core.py`, `test_feature_crud.py`, `test_feature_search_filtering.py`, `test_feature_backup.py`) use `tempfile.mkdtemp()` ([observation], no single convention; both achieve isolation).
- **Monkeypatching:** used sparingly but effectively — `test_web_search.py` monkeypatches `urllib.request.urlopen` for Tavily and `memorius.web_search.get_web_provider` for CLI tests; `test_single_instance.py` monkeypatches `si.fcntl = None` for the no-fcntl no-op path; `test_delete.py`/`test_feature_graph_retrieval.py`/`test_repair_vector_meta_drift.py` use monkeypatch ([observation], targeted, not pervasive).

### 3. Fixtures — shared patterns; engine/vault setup; real Chroma vs mocked embeddings

- **Per-file `engine` fixture** (no shared conftest): creates `VaultEngine(load_config())` with `os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)` where `tmp = Path(tempfile.mkdtemp())`; teardown does `shutil.rmtree(tmp)` and defensively sets `eng._vector._client = None` ("ChromaDB's Rust backend holds file handles" — comment in `test_core.py:50-56`).
- `tests/test_domain_modules.py` goes further with composable fixtures: `engine` → `store` (`StoreModule(engine._vector, engine._meta)`) → `search` (`SearchModule(...)`), testing the extracted domain layer directly ([observation], the cleanest fixture pattern in the suite).
- **Real Chroma + real ONNX embeddings, NOT mocked:** `tests/test_core.py::test_embeddings_chroma_default` instantiates `ChromaDefaultProvider()` and asserts 384-dim unit-normalized vectors; `ChromaDefaultProvider._ensure_model_downloaded()` (`memorius/embeddings.py:66-84`) calls `model_download.setup_model()` which downloads `all-MiniLM-L6-v2` ONNX from S3 on first use if `~/.cache/memorius/onnx_models/model.onnx` is missing ([risk], tests are network-dependent on first run and slow/~80MB).
- `tests/test_integration.py::isolated_env` mitigates this by symlinking the developer's real `~/.cache/chroma/onnx_models` and `~/.cache/memorius/onnx_models` into a sandboxed `HOME`, so tests reuse a pre-downloaded model instead of re-downloading per test ([observation], clever but fragile — on CI without a populated cache, chromadb downloads as before).
- `tests/test_hooks_engine_mine_dir.py` uses a `_StubVaultEngine` stub (no real storage, records `mine()` calls) — the only test that fully mocks the vault engine ([observation], good pattern for hooks logic; not extended to LLM extraction).

### 4. Mocks — web_search, LLM extract, embeddings

- **web_search:** fully faked, no network. `MockProvider` returns canned results (`tests/test_web_search.py::test_mock_provider_returns_canned_results`); Tavily is covered by monkeypatching `urllib.request.urlopen` to return a fake response (`test_tavily_provider_parses_response`); CLI `cmd_search`/`cmd_web` tests monkeypatch `memorius.web_search.get_web_provider` to inject `MockProvider` ([observation], well done — web fallback is offline-safe).
- **LLM extract:** `memorius.llm_extract` exists (OpenAI-backed) but I found **no test mocking it** — no `monkeypatch` of the OpenAI client, no fake LLM responses in any test file ([gap], LLM-powered extraction/mine paths are untested against bad/empty model output).
- **Embeddings:** not mocked anywhere — `ChromaDefaultProvider` triggers a real ONNX model load/download; `SentenceTransformerProvider` lazily loads `sentence-transformers` ([risk], slow and network-dependent; consider a `FakeEmbeddingProvider` fixture for fast unit tests).
- Hooks: `_StubVaultEngine` stubs `engine.mine()` in `tests/test_hooks_engine_mine_dir.py` (no real storage) — a good lightweight mock pattern ([observation]).

### 5. Flakiness — regression guards, single-instance, network-dependent tests

- **`test_regression_bugs.py`** pins Bugs 1, 3, 4, 5 from the 0.4.5 hardening pass: SQLiteStore thread-local connection crosstalk, Chroma collection-name collision/length, REST auth returning 500 instead of 401/429, and fabricated search similarity ([observation], these are recurrence-prevention tests and should stay in CI).
- **`test_polish_regressions.py`** pins v0.1.3 polish bugs: `__version__` drift in MCP/REST/plugin-gen, `PiAdapter.can_parse` coverage, `interval_exchanges` template substitution, checkpoint `exchange_count` vs timestamp, WhatsApp international-format regex, LICENSE/package-data shipping ([observation], same recurrence-prevention role).
- **Single-instance port/lock conflicts:** `test_serve_single_instance.py` relies on kernel `flock` release on process death — if the incumbent subprocess isn't terminated cleanly, the lock lingers and the "new serve starts after first exits" test can hang (it uses a 90s timeout). `test_bookcase.py::TestBookcaseServe` uses `_free_port()` (bind port 0) to avoid fixed-port collisions and asserts `_port_released()` after terminate ([observation], port hygiene is handled but the flock test has a hard timeout dependency).
- **Network-dependent tests:** `memorius.model_download.is_model_downloaded()` checks `Path.home()/.cache/memorius/onnx_models/model.onnx` (`model_download.py:39-43`); `ChromaDefaultProvider.__init__` auto-downloads if missing (`embeddings.py:66-84`). Any test constructing a real `VaultEngine` (the default `engine` fixture) can trigger an ~80MB S3 download on a cold machine — flaky/slow in offline or rate-limited CI ([risk], `test_integration.py` works around it via cache symlinks, but the per-file `engine` fixtures do not).
- **Semantic search determinism:** `tests/test_regression_bugs.py::test_search_returns_relevant_result_first_and_no_distance_leak` and `test_search_does_not_use_synthetic_rank_position_similarity` depend on real Chroma distances being stable across model versions — if the ONNX model or Chroma version changes, ranking assertions could flip ([risk], ranking tests should pin the model version or tolerate re-ranking).

### 6. CI integration — test.yml; coverage thresholds

- `.github/workflows/test.yml`: `push` to `main` + `pull_request` + `workflow_dispatch`; matrix `python-version: ['3.11', '3.12', '3.13']`, `fail-fast: false`; installs `pip install -e ".[dev]"`; runs two steps:
  - "Run unit tests": `pytest tests/test_core.py tests/test_features.py tests/test_polish_regressions.py -q --tb=short`
  - "Run integration tests (CLI + MCP)": `pytest tests/test_integration.py tests/test_single_instance.py tests/test_serve_single_instance.py -q --tb=short`
- **Coverage: none** — no `--cov`, no `coverage` dependency, no threshold, no coverage report upload ([risk]).
- **CI test selection is narrow** — only 7 of ~50 files run ([risk], see Coverage section).
- `paths-ignore: ['docs/**', '**.md']` on push means doc-only changes skip CI ([observation], reasonable).

### 7. Test data — examples/quickstart.py; test vaults under tmp or ~/.memorius?

- `examples/quickstart.py` uses `tempfile.TemporaryDirectory()` and sets `config_data["storage"]["path"]` explicitly — it never touches `~/.memorius` ([observation], good example hygiene).
- All test vaults live under `tempfile.mkdtemp()` / `tmp_path` with `MEMORIUS_STORAGE_PATH` overridden — never `~/.memorius` directly ([observation], tests are hermetic w.r.t. the user's real vault).
- `tests/test_integration.py::isolated_env` additionally sandboxes `HOME` into a temp dir so memorius init writes `~/.memorius` inside the sandbox; it symlinks real ONNX/chroma caches in to avoid re-downloads ([observation], the one place `~` is touched, and deliberately sandboxed).
- `model_download.DEFAULT_CACHE_DIR = Path.home() / ".cache" / "memorius" / "onnx_models"` (`model_download.py:20`) is the real model cache location outside tests — tests can pollute the developer's `~/.cache` if they don't sandbox HOME.

### 8. Determinism — semantic search flakiness; model download in tests

- Semantic search uses real embeddings (`all-MiniLM-L6-v2`, 384-dim); results are deterministic for a fixed model/Chroma version but not version-pinned ([risk]).
- `model_download.is_model_downloaded()` is the gate: `True` if `model.onnx` exists at the cache dir; otherwise `ChromaDefaultProvider` downloads ~80MB from `https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz` and verifies SHA-256 (`model_download.py:28`, `MODEL_URL`, `MODEL_SHA256`) ([risk], first-run tests are network-bound; cold CI = slow or offline-failing).
- `test_core.py::test_embeddings_chroma_default` asserts `len(vectors[0]) == 384` and unit norm ≈ 1.0 — passes only if the model loads ([risk], flaky offline).
- No `pytest.mark.flaky`/`reruns` configuration visible; no `--tb=short` beyond the two CLI steps ([observation]).

---

## Highlights (short)

1. **Good feature coverage, weak CI execution:** ~50 test files cover CRUD, search, graph, consolidation, backup, doctor, cors, sqlite-vec, bookcase, single-instance, hooks, and CLI json flag — but CI only runs 7 of them, leaving most regression guards unexecuted.
2. **Embeddings are real, not mocked:** every `engine` fixture loads Chroma + ONNX `all-MiniLM-L6-v2`, potentially triggering an ~80MB S3 download (`model_download.is_model_downloaded()`); only `test_integration.py` mitigates via sandboxed-cache symlinks.
3. **`pytest-asyncio` is declared but unused:** zero async tests in the suite.
4. **No `conftest.py`, no coverage threshold:** the `engine` fixture is copy-pasted per file, and CI cannot enforce a coverage floor.

---

## Domain summary

Memorius's test suite is broad in feature area but shallow in CI execution: roughly fifty test files exercise the vault engine (CRUD, search filtering/tags, graph/temporal/retrieval, consolidation scaling, backup export/import, doctor health checks, CORS, sqlite-vec, TTL/prune, bookcase assets+serve+walkable, single-instance flock + subprocess E2E, hooks mine_dir with a stubbed engine, and the `--json` CLI flag with deterministic sorted output and README cross-checks), plus recurrence-prevention regression suites (`test_regression_bugs.py` for Bugs 1/3/4/5, `test_polish_regressions.py` for v0.1.3 polish). The dominant strategy is in-process unit tests against isolated `tempfile` vaults via `MEMORIUS_STORAGE_PATH`, with real ChromaDB and real ONNX `all-MiniLM-L6-v2` embeddings (not mocked), making tests network-dependent on first run; `pytest-asyncio` is a declared dev dependency but no async tests exist. There is no `conftest.py` (the `engine` fixture is duplicated per file), no coverage thresholds, and CI (`test.yml`) runs only `test_core.py`, `test_features.py`, `test_polish_regressions.py` (unit) and `test_integration.py`, `test_single_instance.py`, `test_serve_single_instance.py` (integration) across Python 3.11/3.12/3.13. Suggested tracking file: `dev-notes/teammate-analysis/testing.md` (this report) — keep it synced with `dev-notes/AUDIT.md` and `dev-notes/SPEC.md` as CI coverage and mocking strategy evolve.
