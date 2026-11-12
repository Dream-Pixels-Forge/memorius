# SG-02 — Make the full test suite green (P0)

## Evidence
Full run (`pytest -q`, 2026-11-12): **523 passed, 7 failed, 1 skipped**.
After SG-01 fixes the 4 auth failures, 3 remain:

1. `test_feature_prune.py::test_prune_hard_delete` — calls
   `prune(archive=False)` without `confirm=True`; #67 added the confirmation
   guard, so `archived_count` is 0.
2. `test_validation.py::test_validate_content_not_string` — code raises
   `TypeError` (ruff TRY004 change in `9d4e9ea`), test and docstring expect
   `ValueError`.
3. `test_cli_json_flag.py::test_readme_documents_json_flag` — regex expects
   the old README CLI layout; the redesigned README documents `--json` in a
   compact block.

## Scope
- Update the prune test to pass `confirm=True`; add a test that unconfirmed
  hard-delete returns the safety error and deletes nothing.
- Decide the `validate_content` contract: keep `TypeError` (correct Python
  semantics) and update the test + docstring.
- Update the README regex test to match the current documented format, or
  assert on the presence of `stats [--json]` / `status [--json]`.
- Run the full suite locally; no new failures.

## Definition of done
- [x] `pytest -q` → 0 failed (skip is acceptable if documented).
- [x] No production behavior changed except the validation contract docs.
- [ ] PR merged with CI green.

## Result
- `test_prune_hard_delete` now passes `confirm=True`; new
  `test_prune_hard_delete_requires_confirm` asserts the guard returns an
  error and leaves the memory intact.
- `validate_content` keeps `TypeError` for non-strings (correct Python
  semantics); the test and docstring now state that contract.
- README test targets `## CLI at a glance` and `memorius stats [--json]` /
  `memorius status [--json]`, matching the current cheat sheet.
