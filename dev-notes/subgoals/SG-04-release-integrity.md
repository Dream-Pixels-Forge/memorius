# SG-04 — Release integrity (P1)

## Evidence
Release gate on 2026-11-12:
`code=0.9.7 tag=v0.9.6 release=v0.9.6 pypi=0.9.7`.
- `0.9.7` is on PyPI but has no git tag or GitHub release.
- `v0.9.6` tag is 19 commits behind `main`.
- `.github/workflows/release.yml` publishes on **push to main touching
  `pyproject.toml`**, so version bumps publish before tagging/releasing.
  `skip-existing: true` hides the duplicate publish.

## Scope
- Change `release.yml` to publish only on `release: published` (and
  `workflow_dispatch` for manual recovery). Remove the `push` trigger.
- After SG-01/SG-02 merge and version `0.9.8` is on `main`:
  - tag `v0.9.8` at the release commit,
  - create the GitHub release with notes,
  - verify PyPI `0.9.8`, tag, and release all match.
- Do not reuse published versions; if 0.9.8 was already published by a
  `pyproject.toml` push, publish 0.9.9 instead.
- Add a release checklist entry to CONTRIBUTING.

## Release notes draft (v0.9.8)

```markdown
## Security
- REST authentication restored. 0.9.6 and 0.9.7 accepted unauthenticated
  mutations and any Bearer token after PR #80 replaced the auth middleware.
  Requests now require a valid token when MEMORIUS_API_KEY is set; with no
  key, read-only requests (including the bookcase's POST /search) are
  allowed and mutations return 401.

## Fixed
- `memorius prune --delete` remains confirmation-gated; the suite now proves
  the unconfirmed path deletes nothing.
- `validate_content` documents its TypeError contract for non-strings.
- README `--json` documentation test matches the current cheat sheet.

## CI
- CI runs the full test suite on Python 3.12 and a blocking pip-audit.
- Release publishing happens only when a GitHub release is published.
```

## Definition of done
- [x] Workflow has no `push` publish trigger (landed with SG-01 to stop
      0.9.8 shipping untagged).
- [ ] `git ls-remote --tags` shows `v0.9.8`.
- [ ] `gh release list` latest is `v0.9.8`.
- [ ] PyPI latest is `0.9.8`.
- [ ] `pip download memorius==0.9.8` wheel imports and contains the auth fix.
