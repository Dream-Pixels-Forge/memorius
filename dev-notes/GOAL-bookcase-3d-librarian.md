## Goal: Ship the "bookcase" feature — 3D library of the vault with a guiding librarian voice

### Objective
Deliver a browser-based 3D bookcase (`memorius bookcase`) where the user sees their memories as books organized by shelf (vault/shelf/folder hierarchy), and a "librarian" voice that audibly guides them to the book(s) they are looking for.

### Context
- Memorius stores memories in a vault → shelf → folder → note hierarchy (826 memories in `main` as of 2026-10-17). Users currently query via CLI/MCP/REST; there is no spatial way to *see* their corpus, and search results are text-only.
- The REST server (`memorius serve-rest`, default 127.0.0.1:8912) already exposes almost everything the bookcase needs — **no new search/list endpoints**:
  - `GET /vault?vault=main` → hierarchy dict (shelves → folders → notes)
  - `GET /memories?vault=&limit=≤100&cursor=` → `{count, next_cursor, memories[]}`
  - `POST /search` `{query, limit, vault, shelf, folder, note, tags, expand_graph, rerank}` → ranked results with paths
  - `GET /memory/{id}` → full record
- The one gap: no vault-name enumeration (`engine.status()` returns a *count*, not names). The bookcase adds one thin endpoint: `GET /vaults` → `{vaults: [{name, memories}]}` built from the existing per-store `list_vaults()` + vector counts. This is the **only** `rest_server.py` change in this goal.
- CORS is deliberately restrictive: allows `127.0.0.1|localhost(:port)` and `app://obsidian.md` only. The bookcase therefore runs **locally, on loopback** — it is not a GitHub-Pages target.
- Repo conventions: `docs/` static site is plain HTML (no build tooling); CI = pytest 3.11+3.12; no Node/JS test infra exists; the v0.8.6 goal mandated every CLI subcommand be documented on-site.

### Assumptions (locked — challenge these before executing, not during)
1. **3D stack:** Three.js loaded from CDN (ESM importmap). No build step, no npm, no asset pipeline. Books/shelves are procedural geometry (boxes + canvas-texture spine labels).
2. **Librarian = Web Speech API only** (browser `SpeechSynthesis` for output, optional `SpeechRecognition` for voice input). No TTS service, no API keys, no model downloads. Firefox/no-voice environments degrade to text-only guidance — the page stays fully usable.
3. **Multi-vault + spatial mapping:** vault selector (options from `GET /vaults`, default `main`; switching reloads + rebuilds the case). Layout: each *shelf* name = one shelf row; *folders* = slot groups; each *memory* = one book (spine label = truncated `shelf/folder/note` path; thickness ∝ content length, clamped; color = recency). Book arrangement within a row: selector with two modes — `by shelf` (path order, default) and `by recency` (newest left). Click book → side detail panel (full content, tags, date, path). Hover → tooltip.
4. **Search flow:** type (primary) or hold-to-talk (Chromium-only, optional) a query → `POST /search` (top 5, scoped to the selected vault) → librarian speaks the results *and their shelf locations* → camera flies to the top hit, which gets a pulsing highlight; all results are marked on the case. **Voice picker:** dropdown populated from `speechSynthesis.getVoices()`, default = librarian heuristic (calm, professional voice name); persisted in `localStorage`.
5. **Packaging:** page assets live in `memorius/bookcase/` (shipped as package data, so `pip install memorius` works outside a checkout). Deliberately **not** mirrored into `docs/`: CORS is loopback-only by design, so a GitHub-Pages origin could never call the local API — the CLI command is the single launch path.
### Deliverables
- [ ] `memorius/bookcase/bookcase.html` — page skeleton: scene canvas (`#bc-scene`), search input (`#bc-search`), detail panel (`#bc-detail`), librarian toggle + voice input + voice picker (`#bc-librarian`, `#bc-mic`, `#bc-voice`), vault selector (`#bc-vault`), layout selector (`#bc-layout`), status pill (`#bc-status`)
- [ ] `memorius/bookcase/bookcase.css` — styling consistent with the site's orange/cinematic design language
- [ ] `memorius/bookcase/bookcase.js` (+ split files `bookcase-scene.js`, `bookcase-librarian.js` if any file would exceed ~500 lines) — data load via the 5 REST endpoints above, 3D build, vault switch + rebuild, layout modes, interactions, search→speak→fly-to flow
- [ ] `memorius/rest_server.py` — **only** server change: `GET /vaults` → `{vaults: [{name, memories}]}`; `memorius/vault.py` gains thin `Engine.list_vaults()` (union of both meta stores + vector counts, mirroring `status()`'s vault-union logic)
- [ ] New CLI subcommand in `memorius/cli/main.py`: `memorius bookcase [--port 8912] [--static-port 8400] [--no-browser]` — health-checks the REST server (starts it via the existing serve path if down), serves `memorius/bookcase/` on the static port over loopback, prints the URL, opens the browser unless `--no-browser`
- [ ] `pyproject.toml` — package data includes `memorius/bookcase/*`; `memorius/bookcase/__init__.py` present so the package imports
- [ ] `tests/test_bookcase.py` — the tests listed in Verification
- [ ] Docs: `docs/cli-reference.html` gains the `bookcase` subcommand row; `docs/getting-started.html` gains a short "See your vault in 3D" section; `CHANGELOG.md` unreleased entry
- [ ] `dev-notes/PROGRESS.md` updated at completion

### Definition of Done
- [ ] `python3 -m pytest tests/test_bookcase.py -q` → all pass, exit 0
- [ ] `python3 -m memorius.cli.main bookcase --help` → exit 0, shows `--no-browser`
- [ ] Full suite `python3 -m pytest tests/ -q` green (3.12; CI will also run 3.11)
- [ ] Manual scenario (Verification 4) completes with **zero console errors**
- [ ] `grep -c 'allow_origins\|allow_origin_regex' memorius/rest_server.py` unchanged vs. pre-feature (no CORS widening)
- [ ] From a non-repo directory: `python3 -c "import memorius.bookcase"` succeeds after `pip install -e .`
- [ ] `docs/cli-reference.html` contains `bookcase`; the "every CLI subcommand documented on-site" invariant holds

### Verification Steps
1. **Assets ship + are well-formed** (`tests/test_bookcase.py::test_bookcase_assets`): files exist under `memorius/bookcase/`; HTML parses with `html.parser` (no malformed tags); required element ids present; JS text contains references to `/vault`, `/memories`, `/search`, `/memory/`; no file > 500 lines without a split.
2. **API contract the page depends on** (`tests/test_bookcase.py::test_bookcase_api_shapes`, run against the existing TestRestApi-style fixture engine): `GET /vaults` → `{vaults: [{name, memories}]}` including `{"name":"main"}`; `GET /vault?vault=main` → dict containing the shelves keys; `GET /memories?limit=5` → `{count, next_cursor, memories}` with ≤5 items; `POST /search {"query":"pytest"}` → HTTP 200 + list; `GET /memory/{first_id}` → record with `content`.
3. **CLI end-to-end** (`tests/test_bookcase.py::test_bookcase_serve`): subprocess `python3 -m memorius.cli.main bookcase --no-browser --port <unused> --static-port <unused>`; assert `GET http://127.0.0.1:<static>/bookcase.html` → 200 `text/html` containing `#bc-scene`; assert `GET http://127.0.0.1:<port>/health` → 200; terminate subprocess; assert port released.
4. **Manual scenario (final gate, no console errors):** start `memorius bookcase`; browser shows the 3D case populated from the real `main` vault; hover a book → tooltip; click → detail panel shows full content; toggle librarian on → greeting speech states total books/shelves; type a query (e.g. "pytest timeouts") → search results spoken *with shelf locations*, camera flies to top hit, hit highlighted; pick a different TTS voice in `#bc-voice` → the next utterance uses it and the choice survives a page reload (localStorage); switch vault in `#bc-vault` → case rebuilds from that vault (selector contents must match `GET /vaults`); switch layout to `by recency` → books within each row reorder newest-first; toggle librarian off → all guidance still visible as text and every interaction still works.
5. **Absence re-check:** `git diff memorius/rest_server.py` adds **only** the `GET /vaults` route — the CORS allowlist block is byte-identical; `git diff memorius/cli/main.py` adds only the `bookcase` subcommand; `gh issue list --state open` → 0 new failing checks on CI for this branch.

### Anti-Drift Rules
- The **only** server change is `GET /vaults` (+ `Engine.list_vaults()`). No other `rest_server.py` modifications; if anything else server-side is needed, report BLOCKED — don't extend the server.
- No build tooling, no npm/Node, no new Python dependencies beyond what CI already installs; Three.js only via `<script type="module">` CDN import.
- Web Speech API only for audio — no TTS/STT services, no keys, no downloads.
- No CORS allowlist changes; bind loopback only.
- In v1 scope: multi-vault switching, two layout modes, voice picker. **Out of scope (new goals):** book arrangement beyond by-shelf/by-recency (tags, custom groupings), case geometry/styling customization, TTS voice *training*/custom personas, layout persistence across sessions (only the voice picker persists, via localStorage).
- Every new behavior ships with its test (TDD: RED first). No skips/xfails to reach green.

### Estimated Effort
Large: ~1 focused session. Split: (A) assets + scene + librarian + tests (RED→GREEN), then (B) CLI + `GET /vaults` + packaging + docs + changelog + full-suite re-run. Subagents may build (A) scene and (A) librarian in parallel — they only meet at the documented DOM contract above.