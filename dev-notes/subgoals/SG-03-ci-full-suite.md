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
- Make `pip-audit` blocking (`python -m pip-audit`), with a documented
  ignore list only if a finding is genuinely unreachable.
- Keep `paths-ignore` for docs-only changes.
- Add a required-check note to CONTRIBUTING (which checks must be green).

## Definition of done
- [ ] PR CI runs the full suite and fails on any failure.
- [ ] `pip-audit` failure fails the job.
- [ ] Docs-only pushes still skip tests.
- [ ] One green run on the PR and one on `main` after merge.
