# SG-01 — Restore REST authentication (P0 hotfix)

## Evidence
- `memorius/rest_server.py` has no auth middleware and zero `401` responses.
- `pytest tests/test_regression_bugs.py -q` → 4 failed:
  - missing key + key configured → 200 (expected 401)
  - wrong key → 200 (expected 401)
  - no key configured + POST/PUT/PATCH/DELETE → 200 (expected 401)
- Regression introduced by `908f975` (PR #80, idempotency keys): the commit
  replaced `auth_middleware` with `idempotency_middleware`.
- PyPI `0.9.7` wheel verified affected (`auth_middleware present: False`,
  `401 count: 0`). `0.9.6` is also affected.

## Scope
- Restore the auth middleware from `908f975^` (per-request env read,
  `hmac.compare_digest`, 401 for bad/missing key when a key is set).
- When `MEMORIUS_API_KEY` is unset: allow read-only methods, return 401 for
  POST/PUT/PATCH/DELETE.
- Bypass auth for `/health` and `/health/*` probes.
- Keep idempotency middleware; auth must execute before it.
- Restore `import hmac`.
- Add `tests/test_regression_bugs.py` to CI unit selection.
- Bump patch version to `0.9.8` and add a CHANGELOG security entry.

## Out of scope
- RBAC/session auth (#65 H-04, deferred).
- Release tagging (SG-04).

## Definition of done
- [x] `pytest tests/test_regression_bugs.py -q` → all pass (11 passed).
- [x] `pytest tests/test_bookcase.py -q` still passes (bookcase sends no key
      when the server has none; read-only GETs must stay open).
- [x] A REST app with a key rejects missing/wrong keys with 401.
- [x] A REST app without a key rejects mutations with 401, allows GET.
- [x] CI runs `test_regression_bugs.py` on 3.11/3.12/3.13.
- [x] Version `0.9.8`, CHANGELOG updated.
- [x] `release.yml` no longer publishes on a `pyproject.toml` push, so this
      version cannot ship untagged.
- [ ] PR merged; PyPI publish verified by SG-04.

## Result
- Full suite: 528 passed, 3 failed, 1 skipped. The 3 failures are the
  pre-existing stale tests tracked by SG-02; no new failures.
- Added `_READ_ONLY_POSTS = {"/search"}` so the bookcase page can search a
  keyless local server while `/store` and friends still return 401.
