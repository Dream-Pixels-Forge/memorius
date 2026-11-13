# Pipeline Progress

## Current State
- Project: memorius
- Version: 0.9.8 (released 2026-11-13; tag, GitHub release and PyPI verified against the same version)
- Active branch: main
- Vault health: all doctor checks pass (meta=826, vectors=826 after repair --reindex)
- Status: CI green on Python 3.11 / 3.12 / 3.13 plus the full suite (570 tests). All subgoals SG-01–SG-10 are done; SG-08 added the production container image (#111) and SG-09 cleaned branches and the local vault.
- [2026-11-13] SG-09 hygiene: local branches reduced to `main`, 18 merged remote branches deleted, local CLI upgraded 0.9.5 → 0.9.8, `repair --reindex` re-embedded 894 missing vectors, `memorius doctor` all checks ok.
- [2026-11-13] Bookcase series landed: SG-05 strict CSP with vendored Three.js (#107), SG-07 library index / walk-to-shelf / surprise me (#108), and SG-10 bottom-left walk pad, walking hippo and centered reader (#109). Every bookcase asset stays under 500 lines; the page boots with zero console errors.
- [2026-11-13] Release integrity: v0.9.8 verified three-way (tag ↔ GitHub release ↔ PyPI); SG-04 removed `skip-existing` and pinned the release workflow to the tag (#105).
- [2026-10-17] Triage done: #31–#34 closed stale (verified 15/15 pass); #26–#30 wired to PR #37 (180s timeout); #23/#24 root-caused → PR #38 (Popen detach in _start_daemon); #22 → PR #35 (README CLI-ref anchor). PRs #37/#38/#35 merged to main with CI green (3.11+3.12). New convention: auto-merge only when all CI green + zero open issues/warnings + goal-met MET 10/10.
- [2026-10-18] Issue #43 closed: `memorius serve` single-instance guard — exclusive flock on `<storage.path>/serve.lock` stamped with the incumbent PID (dead-holder steal via kernel flock release, no-fcntl platforms no-op); second serve exits rc=1 in <5s naming the incumbent PID. PR #44 merged to main as 5776851 (CI 3.11+3.12 green; integration tests spawn real serve subprocesses). PR #45 merged as 3c61143: dropped sentence-transformers FutureWarning (task label API) + moved planning docs into `dev-notes/`. Repo-wide pyright cleanup LANDED (152 → 0 errors, repo-wide incl. tests): zero-behavior-change typing fixes only (annotations, narrowing intermediates, casts, rule-specific ignores); one unreachable duplicate `except Exception` removed in mcp_server.py; PR #46 merged to main as 49f6bd1 (CI 3.11+3.12 green on both commits, full suite 461 passed, independent verifier PASS after fixing its one flagged deviation — embeddings `or 384` → `cast(int, ...)` in 8ca4aae).
- [2026-10-18] Bookcase goal (GOAL-bookcase-3d-librarian.md) audit: NOT-MET (spec-only, zero execution). Execution now on branch `feature/bookcase-3d-librarian` (TDD): tests/test_bookcase.py RED→GREEN (3/3), `GET /vaults` + `VaultEngine.list_vaults()` added (only server-side change, CORS unchanged), `memorius bookcase` CLI (loopback static server + REST health-check, in-thread uvicorn when REST is down), packaged `memorius/bookcase/` assets (Three.js CDN r160 + Web Speech API librarian, all files ≤500 lines), docs + CHANGELOG updated. Headless-Chrome live check: page boots, "2 books" pill, librarian greeting rendered as text, zero JS console errors; `--help` exit 0; import from non-repo dir OK (editable install into pipx venv). → goal-met re-audit MET 10/10 (34 checks); squash commit eed8ecb; PR #40 merged to main as 6ae3ab5 (CI 3.11+3.12 green, zero review threads/issues); release pipeline completed: v0.9.0 bump (PR #41, main 650522d) + tag v0.9.0 + GitHub release + PyPI publish (wheel + sdist verified, bookcase assets ship in the wheel).

## Phase Completion
- [x] Phase 0: Bootstrap (DISCOVERY.md + AUDIT.md)
- [x] Phase 2: Governance (GOAL.md + SECURITY.md + SPEC.md)
- [ ] Phase 2: Design System (DESIGN.md) - Not applicable for this backend-focused enhancement
- [x] Phase 3: Engineer (implementation) - shipped through v0.9.8; ongoing subgoals tracked in `subgoals/README.md`

## Planning

- [Subgoal index](subgoals/README.md) — audited findings, owners and delivery status
- [GOAL.md](GOAL.md) — production-readiness goal and verification gates
- [SPEC.md](SPEC.md) — feature and API specification
- [AUDIT.md](AUDIT.md) — initial audit
- [Bookcase goal](GOAL-bookcase-3d-librarian.md) — 3D library with librarian
- [Walkable bookcase goal](GOAL-bookcase-walkable-shelves.md) — aisles, walking and shelf dressing

## Blockers
- None currently identified

## Decisions Made
- [2026-10-11] Chose Existing Application Realignment path (Mode B) for GOAL.md format
- [2026-10-11] Determined that agentic-design-systems track is not applicable for this backend-focused memory architecture enhancement
- [2026-10-11] Prioritized neuroscience-inspired consolidation, hybrid retrieval, and observability enhancements based on 2026 trends analysis

## Next Steps
1. All audited subgoals SG-01–SG-10 are complete; keep CI green across
   3.11/3.12/3.13 and the full suite on every change.
2. On the next version bump, re-run the three-way release verification
   (tag ↔ GitHub release ↔ version-specific PyPI endpoint).
3. Keep the local vault in sync (`memorius doctor`, `memorius repair --reindex`).