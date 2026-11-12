# SG-03 — Enforce full-suite CI + blocking dependency audit (P1)

## Evidence
`.github/workflows/test.yml` runs only 6 of 50 test files:
`test_core`, `test_features`, `test_polish_regressions`, `test_integration`,
`test_single_instance`, `test_serve_single_instance`.
The REST auth regression and the three SG-02 failures were invisible to CI.
`pip-audit` runs with `|| true` (non-blocking).

## Scope
- Add a `full-suite` job on Python 3.12 running `pytest tests/ -q`.
  Keep the existing fast subset on 3.11/3.12/3.13.
- Make `pip-audit` blocking (`python -m pip_audit --skip-editable`), with a
  documented ignore list only if a finding is genuinely unreachable.
- Keep `paths-ignore` for docs-only changes.
- Add a required-check note to CONTRIBUTING (which checks must be green).
- Pin both decisions with `tests/test_ci_contract.py` so a future edit
  cannot silently drop the full suite or reintroduce `|| true`.

## Definition of done
- [x] PR CI runs the full suite and fails on any failure.
- [x] `pip-audit` failure fails the job.
- [x] Docs-only pushes still skip tests.
- [ ] One green run on the PR and one on `main` after merge.

## Result
- `full-suite` job: Python 3.12, `pytest tests/ -q`, then a blocking
  `python -m pip_audit --skip-editable`. (The module is `pip_audit`; the
  first CI attempt used `python -m pip-audit` and died, so both the hyphen
  form and its absence are now pinned by a test.)
- Audit findings: 4 chromadb advisories with no fixed release —
  PYSEC-2026-311 (pre-auth `trust_remote_code` injection) and
  PYSEC-2026-3813/3814/3815 (tenant RBAC + `trust_remote_code`). All of
  them target the multi-tenant Chroma **HTTP server** `/api/v2/...` API.
  Memorius never starts a Chroma server, uses `chromadb.PersistentClient`
  only, is single-tenant, and never sets `trust_remote_code`, so they are
  unreachable. They are ignored with that justification inline in the
  workflow.
  `test_no_chroma_http_server_surface` fails if the package ever gains
  `chromadb.HttpClient` or `trust_remote_code`, which would invalidate the
  exception.
- `tests/test_ci_contract.py` pins the full-suite job, the absence of
  `|| true`, the documented ignore list, and the audit invocation.
- Clean-install mirror uncovered a second CI gap: `chromadb>=0.4.22,<1.0.0`
  resolves **0.6.3**, where `list_collections()` returns names and `None`
  metadata is rejected — 35 tests failed. The dev machine runs 1.5.9, which
  was outside the declared range, so local green was not representative.
  The requirement is now `chromadb>=1.0.0,<2.0.0` (the tested major), and
  `test_installed_chromadb_satisfies_declared_range` pins the invariant.
- `test_tests_do_not_hardcode_a_developer_path` rejects absolute
  `/home/<user>/…` paths in tests; the first CI run failed on exactly that.
- `CONTRIBUTING.md` documents the required checks and the ignore policy.
